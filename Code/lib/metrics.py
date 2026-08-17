# -*- coding: utf-8 -*-
"""
指标评估引擎（metrics.py）
==========================
纯函数指标计算，供 portfolio_report.py（持仓基金信号）与 plate_report.py（板块分析）共用。
2026-08-17 从 sector_report.py 抽取，并吸收 signal_lib.macd_series（signal_lib 已废弃）。

综合分权重（满分 100）：
  动量（20日30 + 5日10 + 60日10）+ MACD多头/红柱15 + 站上MA60/偏离15
  + 历史分位低估10 + 资金流量能方向比10
"""


def macd_series(close):
    """计算 MACD 的 DIF/DEA 序列（EWM 12/26/9）"""
    ema_f = close.ewm(span=12, adjust=False).mean()
    ema_s = close.ewm(span=26, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea

# ---- 综合评分权重（满分 100，可按偏好调整）----
# 设计逻辑：动量(涨势) + 趋势(MACD/MA60) + 资金流(量能方向) 是"进攻"，历史分位(低估) 是"防守/性价比"
WEIGHTS = {
    'mom20': 30,      # 20日动量（趋势核心）
    'mom5': 10,       # 5日动量（近期加速）
    'mom60': 10,      # 60日动量（中期趋势）
    'macd': 15,       # MACD 多头 + 红柱强度（红柱衰竭减半）
    'ma60': 15,       # 站上MA60 + 偏离度
    'pct': 10,        # 历史分位低估（分位越低分越高，性价比）
    'flow': 10,       # 20日资金流（量能方向比：上涨放量=流入）
}
# 各分项线性阈值（达到该值即拿满分）
THRESH = {'mom20': 0.10, 'mom5': 0.05, 'mom60': 0.15, 'hist': 0.04, 'ma_dev': 0.10, 'flow': 0.50}


def _calc_index_metrics(s, o, v, theme):
    """在合成指数序列上计算全部指标（s=收盘/指数点, o=开盘, v=成交量）"""
    n = len(s)
    m5 = s.iloc[-1] / s.iloc[-6] - 1 if n > 6 else 0
    m20 = s.iloc[-1] / s.iloc[-min(21, n)] - 1
    m60 = s.iloc[-1] / s.iloc[-min(61, n)] - 1 if n > 60 else m20
    dif, dea = macd_series(s)
    hist = 2.0 * (dif - dea)
    macd_bull = bool(dif.iloc[-1] > dea.iloc[-1])
    ma60 = s.rolling(60).mean().iloc[-1]
    above_ma60 = bool(s.iloc[-1] > ma60)
    mn = s.rolling(250).min().iloc[-1]
    mx = s.rolling(250).max().iloc[-1]
    try:
        pct250 = float((s.iloc[-1] - mn) / (mx - mn)) if (mx == mx and mn == mn and mx > mn) else None
    except Exception:
        pct250 = None

    def _flow(window):
        w_o, w_c, w_v = o.iloc[-window:], s.iloc[-window:], v.iloc[-window:]
        if w_v.sum() <= 0:
            return 0.0
        up = w_v[w_c > w_o].sum()
        dn = w_v[w_c < w_o].sum()
        return float((up - dn) / w_v.sum())
    flow5 = _flow(min(5, n))
    flow20 = _flow(min(20, n))

    def _lin(x, th):
        return max(0.0, min(1.0, x / th)) if th else 0.0
    above_pct = s.iloc[-1] / ma60 - 1
    hist0 = hist.iloc[-1]
    W = WEIGHTS
    sc = 0.0
    sc += _lin(m20, THRESH['mom20']) * W['mom20']
    sc += _lin(m5, THRESH['mom5']) * W['mom5']
    sc += _lin(m60, THRESH['mom60']) * W['mom60']
    if macd_bull:
        sc += W['macd'] * 0.5
        sc += _lin(hist0, THRESH['hist']) * W['macd'] * 0.5
    if above_ma60:
        sc += W['ma60'] * 0.5
        sc += _lin(above_pct, THRESH['ma_dev']) * W['ma60'] * 0.5
    if pct250 is not None:
        sc += (1 - pct250) * W['pct']
    else:
        sc += W['pct'] * 0.5
    sc += _lin(max(flow20, 0), THRESH['flow']) * W['flow']
    score = round(max(0.0, min(100.0, sc)), 1)
    weakening = False
    if macd_bull and n >= 10:
        h0 = hist.iloc[-1]; peak = hist.iloc[-10:-1].max()
        if h0 > 0 and peak > 1e-6 and h0 < peak * 0.6:
            weakening = True
    return {
        'theme': theme, 'date': str(s.index[-1]) if hasattr(s.index[-1], 'strftime') else '',
        'mom5': round(float(m5)*100, 2), 'mom20': round(float(m20)*100, 2),
        'mom60': round(float(m60)*100, 2),
        'pct250': round(pct250, 3) if pct250 is not None else None,
        'macd_bull': macd_bull, 'macd_weakening': weakening,
        'above_ma60': above_ma60,
        'flow5': round(flow5*100, 1), 'flow20': round(flow20*100, 1),
        'score': score,
    }


# ================= 三套评分 + 决策翻译（2026-08-18）=================
# 持仓分三类评分策略：
#   index    指数（宽基）：定投估值驱动 → 输出「买入倍数」（×1.5/×1.0/×0.5）
#   dividend 红利（高股息）：均值回归波段 → 输出「买入区/持有/卖出区」
#   trend    趋势类（被动行业 + 主动混合，共用一套策略）：→ 输出「持有/关注/减仓/离场」（卖出为主）
# 被动/主动差异仅为时间尺度：passive 看 20 日动量，active 看 60 日动量（申赎成本高、调仓更钝）

def calc_dd(close):
    """距 250 日高点回撤 %（负值）"""
    n = min(250, len(close))
    if n < 20:
        return 0.0
    peak = close.iloc[-n:].max()
    return float(close.iloc[-1] / peak - 1) * 100


def calc_vol(close, window=60):
    """年化波动率 %（净值日收益 std × sqrt(252)）"""
    r = close.pct_change().dropna()
    if len(r) < 20:
        return 0.0
    return float(r.tail(window).std() * (252 ** 0.5)) * 100


def _lin(x, th):
    return max(0.0, min(1.0, x / th)) if th else 0.0


def _pct_score(pct, weight, cheap=30, exp=70):
    """分位便宜度分：分位越低分越高（pct 为 0-100 的百分数，None 给一半）"""
    if pct is None:
        return weight * 0.5
    if pct <= cheap:
        return weight
    if pct >= exp:
        return 0.0
    return weight * (exp - pct) / (exp - cheap)


def score_index(m, pe_pct=None):
    """指数评分（定投估值驱动）。m 为指标 dict（含 mom5/20/60, pct250, macd_bull,
    macd_weakening, above_ma60, flow20, dd）；pe_pct 为 PE 估值分位(0-100)，None 用价格分位。
    返回 {score, pct_used, mult, decision}"""
    pct = pe_pct if pe_pct is not None else (m['pct250'] * 100 if m.get('pct250') is not None else None)
    s = 0.0
    s += _pct_score(pct, 35)                                # PE/价格分位 35（便宜度）
    s += 20 * (1.0 if m.get('above_ma60') else 0.3)         # MA60 长期趋势 20
    s += _lin(max(m.get('mom60') or 0, 0) / 100, 0.15) * 15  # 60日动量 15（中期动能）
    dd = m.get('dd')
    s += (min(15, max(0, -dd / 25 * 15)) if dd is not None else 7.5)  # 回撤 15：深回撤=机会
    s += (_lin(max(m.get('flow20') or 0, 0) / 100, 0.5) * 10
          if m.get('flow20') is not None else 5)            # 资金流 10（净值缺失中性）
    s += _lin(max(m.get('mom20') or 0, 0) / 100, 0.05) * 5  # 短动量 5（噪音忽略）
    score = round(max(0.0, min(100.0, s)), 1)
    base = pct if pct is not None else 50
    mult = 1.5 if base < 30 else (0.5 if base > 70 else 1.0)
    zone = '低估（加倍定投）' if base < 30 else ('高估（减半定投）' if base > 70 else '正常（标准定投）')
    return {'score': score, 'pct_used': round(pct, 1) if pct is not None else None,
            'mult': mult, 'decision': f'定投 ×{mult} · {zone}'}


def score_dividend(m, yield_spread=None):
    """红利评分（均值回归波段）。yield_spread 为股息率-国债利差 %（None 缺失）。
    返回 {score, decision}，决策为 买入区/观察区/持有/卖出观察区/卖出区"""
    pct = m['pct250'] * 100 if m.get('pct250') is not None else None
    s = 0.0
    s += _pct_score(pct, 35)                                # 价格分位 35（低买高卖核心）
    if yield_spread is None:
        s += 10                                             # 利差缺失中性
    else:
        s += min(20, yield_spread / 3.0 * 20)               # 股息率利差 20（安全垫，3%+满分）
    dd = m.get('dd')
    s += (min(15, max(0, -dd / 25 * 15)) if dd is not None else 7.5)  # 回撤 15：深=接近买点
    mom20 = m.get('mom20') or 0
    if pct is not None and pct < 40 and mom20 > 0:
        s += 15                                             # 低位 + 止跌确认
    elif pct is not None and pct < 40:
        s += 6                                              # 低位未企稳（观察）
    elif pct is not None and pct > 60 and mom20 > 0:
        s += 8                                              # 高位仍涨（等滞涨）
    else:
        s += 11                                             # 中位
    s += 10 if m.get('macd_bull') else 3                     # MACD 10
    vol = m.get('vol')
    s += 5 * (0.5 if vol is None else (1.0 if vol < 20 else max(0.0, 1 - (vol - 20) / 30)))  # 波动 5
    score = round(max(0.0, min(100.0, s)), 1)
    # 决策：双向
    if pct is not None and pct < 30 and mom20 > 0 and m.get('macd_bull'):
        decision = '买入区（低吸）'
    elif pct is not None and pct < 30:
        decision = '观察区（等止跌确认再买）'
    elif pct is not None and pct > 70 and mom20 < 0:
        decision = '卖出区（高抛）'
    elif pct is not None and pct > 70:
        decision = '卖出观察区（等滞涨确认再卖）'
    else:
        decision = '持有'
    return {'score': score, 'decision': decision}


def score_trend(m, scale='passive'):
    """趋势类评分（被动行业 + 主动混合共用；卖出为主）。
    scale='passive' 看 20 日动量（短线波段）/ 'active' 看 60 日动量（中线持有）。
    返回 {score, decision}，决策为 持有/关注/建议减仓/建议离场"""
    s = 0.0
    s += _lin(max(m.get('mom20') or 0, 0) / 100, 0.10) * 30  # 20日动量 30
    s += (12 if m.get('macd_bull') else 0) + (0 if not m.get('macd_weakening') else -4)  # MACD 20（多头12/衰竭-4）
    s += (_lin(max(m.get('flow20') or 0, 0) / 100, 0.5) * 15
          if m.get('flow20') is not None else 7.5)          # 资金流 15（净值缺失中性）
    s += _lin(max(m.get('mom5') or 0, 0) / 100, 0.05) * 10   # 5日动量 10（加速）
    s += 10 if m.get('above_ma60') else 2                    # MA60 10（中期过滤）
    s += _pct_score(m['pct250'] * 100 if m.get('pct250') is not None else None, 10)  # 分位 10
    score = round(max(0.0, min(100.0, s)), 1)
    mom20 = m.get('mom20') or 0
    mom60 = m.get('mom60') or 0
    if m.get('macd_weakening') and mom20 < 0:
        decision = '建议离场（MACD衰竭+动量转负）'
    elif (mom20 < -8 if scale == 'passive' else mom60 < -8):
        decision = '建议离场（中期趋势走坏）'
    elif (mom20 < 0 if scale == 'passive' else mom60 < 0) or not m.get('above_ma60'):
        decision = '关注（动能转弱，准备卖出）'
    elif m.get('macd_bull') and mom20 > 0 and score >= 65:
        decision = '持有（趋势强）'
    else:
        decision = '持有'
    return {'score': score, 'decision': decision}

