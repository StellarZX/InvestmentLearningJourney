# -*- coding: utf-8 -*-
"""
板块/行业指标引擎（metrics.py）
==============================
纯函数指标计算，供 portfolio_report.py（行业持仓信号）与 plate_report.py（板块分析）共用。
2026-08-17 从 sector_report.py 抽取（该模块已废弃删除，函数合并进各调用方）。

综合分权重（满分 100）：
  动量（20日30 + 5日10 + 60日10）+ MACD多头/红柱15 + 站上MA60/偏离15
  + 历史分位低估10 + 资金流量能方向比10
"""
from signal_lib import macd_series

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
