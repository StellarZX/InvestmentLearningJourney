# -*- coding: utf-8 -*-
"""
行业数据分析报告（sector_report.py）
====================================
定位：不做短线量化操作指令，只输出「行业数据分析结果 + 操作建议参考」，
供用户自行判断。

报告内容：
  1. 当前行业持仓（从 Sector.log 推导：买入-赎回=当前持仓，含金额）
  2. 持仓预警：动量转弱 / MACD衰竭 / 历史分位过高 / 深度低估等
  3. 行业全景：全部行业指数（同主题ETF合成）按动量大类/分位/资金流/综合分排名
  4. 低估方向雷达：250日分位 < 0.3 的方向（均值回归参考）
  5. 强势方向雷达：综合分高 + 动量 + MACD 双多方向（趋势参考）

综合分（满分100，权重见 WEIGHTS）：
  动量（20日30 + 5日10 + 60日10）+ MACD多头/红柱15 + 站上MA60/偏离15
  + 历史分位低估10 + 资金流量能方向比10

数据源：
  - Sector.log（同目录，买卖记录）→ 当前持仓
  - data/market.db（统一主库：全市场清单 + 行业型 K 线，腾讯前复权）→ 行情分析
  - lib/otc_map.py（场外基金代码 → 主题）→ 持仓映射

用法：python sector_report.py
输出：03_SectorReport/YYYYMMDD.html（按数据日期命名的报告）
"""
import os, sys, json, sqlite3, datetime
import pandas as pd
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))
from signal_lib import theme_of, is_industry, classify_industry, macd_series, industry_of
from otc_map import OTC_MAP

LOG_FILE = os.path.join(BASE, 'Sector.log')            # 旧持仓记录（已迁移到 portfolio.db，保留作历史）
PORTFOLIO_DB = os.path.join(BASE, 'data', 'portfolio.db')  # 统一持仓流水库（行业/指数/资金池）
DB = os.path.join(BASE, 'data', 'market_industry.db')   # 行业行情库：全市场清单 + 行业型K线（腾讯前复权）
os.makedirs(os.path.dirname(DB), exist_ok=True)         # 首次运行自动创建 data/
OUT_DIR = os.path.join(BASE, '..', '03_SectorReport')    # 报告输出到 03 行业报告目录（按日期命名）
FEE = 0.005
BUY_PCT = 0.3          # 低估参考线
HIGH_PCT = 0.7         # 高估预警线

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


# ================= 1. 持仓推导 =================
def load_positions():
    """从 portfolio.db（统一持仓流水库）读取行业基金流水，推导当前持仓。
    持仓 = 买入累计 - 赎回累计（金额<=0 视为已清仓）。
    返回 {基金代码: {name, code, amt, buys, sells, last_date, last_gain}}"""
    pos = {}
    if not os.path.exists(PORTFOLIO_DB):
        print(f'  [warn] 未找到 {PORTFOLIO_DB}，按空持仓处理')
        return pos
    conn = sqlite3.connect(PORTFOLIO_DB)
    rows = conn.execute(
        "SELECT date,fund,code,direction,amount,gain FROM trans WHERE category='行业' ORDER BY date").fetchall()
    conn.close()
    for d, name, code, direction, amt, gain in rows:
        if not code or not direction:
            continue
        if code == 'ZFB' or '余额宝' in name:          # 现金类，跳过
            continue
        p = pos.setdefault(code, {'name': name, 'code': code, 'amt': 0.0,
                                  'buys': 0, 'sells': 0, 'last_date': str(d),
                                  'last_gain': 0.0})
        if direction in ('买入', '申购', '加仓'):
            p['amt'] += amt
            p['buys'] += 1
        elif direction in ('卖出', '赎回', '减仓'):
            p['amt'] -= amt
            p['sells'] += 1
            try:
                p['last_gain'] = float(gain)
            except (TypeError, ValueError):
                pass
        if str(d) > p['last_date']:
            p['last_date'] = str(d)
    # 过滤：金额<=0 视为已清仓
    return {c: p for c, p in pos.items() if p['amt'] > 1}


def otc_to_theme(code, name):
    """场外基金代码 → 主题（otc_map 反查，支持 tuple 与 list-of-tuple 两种值结构）"""
    def codes_of(v):
        """取出 v 里的所有基金代码"""
        out = []
        for item in (v if isinstance(v, list) else [v]):
            if isinstance(item, tuple) and len(item) >= 3:
                out.extend(item[1:])
        return out

    # 1) 代码反查（最可靠）
    for k, v in OTC_MAP.items():
        if code in codes_of(v):
            # 主题名过一遍 theme_of 归一，确保与场内主题口径一致（如 港股通科技→恒生科技）
            return theme_of(k)
    # 2) 名称关键词反查（v[0] 联接基金名包含主题词）
    for k, v in OTC_MAP.items():
        if isinstance(v, tuple) and v[0] and any(w in name for w in k.split('/')):
            return theme_of(k)
    # 3) 名称中包含的主题词
    for k in sorted(OTC_MAP.keys(), key=len, reverse=True):
        if k in name:
            return theme_of(k)
    return None


# ================= 2. 行情数据 =================
def latest_trading_day():
    """估算最近交易日（周一盘前=上周五；周末=周五）"""
    import datetime as _dt
    today = _dt.date.today()
    wd = today.weekday()          # 0=周一
    if wd == 0:                    # 周一：假设盘前，最近交易日=上周五
        return today - _dt.timedelta(days=3)
    if wd == 6:                    # 周日
        return today - _dt.timedelta(days=2)
    if wd == 5:                    # 周六
        return today - _dt.timedelta(days=1)
    return today                   # 周二~周五


def ensure_market_updated():
    """智能增量更新：仅当库内最新日期 < 最近交易日时才拉新K线（避免每次运行都请求接口）"""
    import subprocess
    fetch_script = os.path.join(BASE, 'fetch_db.py')
    if not os.path.exists(DB):
        print('  [首次] 全量重建数据库...')
        subprocess.run([sys.executable, fetch_script, '--types', 'all'], check=False)
        return
    try:
        conn = sqlite3.connect(DB)
        db_latest = conn.execute('SELECT MAX(date) FROM kline').fetchone()[0]
        conn.close()
    except Exception:
        db_latest = None
    need = latest_trading_day().strftime('%Y-%m-%d')
    if db_latest and db_latest >= need:
        print(f'  数据已最新（{db_latest}），跳过增量更新')
        return
    print(f'  库内 {db_latest} < 最近交易日 {need}，增量更新...')
    subprocess.run([sys.executable, fetch_script, '--incremental'], check=False)


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


def load_market():
    """加载行业指数数据（真实指数优先，ETF 合成为回退）：
    ① index_kline 有映射且 index_daily 有 K 线 → 用真实指数日线
    ② 否则 → 该主题多只 ETF 归一化合成指数曲线
    每主题返回 {指标dict}，theme≈指数方向。"""
    from collections import defaultdict
    conn = sqlite3.connect(DB)
    maps = conn.execute('SELECT theme, code, INDEXCODE, INDEXNAME FROM index_kline').fetchall()
    # 预计算每主题的 ETF 数
    metas_all = conn.execute("SELECT name FROM etf_meta WHERE is_ind=1").fetchall()
    theme_cnt = defaultdict(int)
    for (nm,) in metas_all:
        theme_cnt[theme_of(nm)] += 1
    # 1) 真实指数数据
    idx_data = {}
    for theme, etf_code, icode, iname in maps:
        df = pd.read_sql_query(
            "SELECT date,open,close,volume FROM index_daily WHERE indexcode=? ORDER BY date",
            conn, params=(icode,))
        if len(df) < 65:
            continue
        s = df['close'].astype(float).reset_index(drop=True)
        o = df['open'].astype(float).reset_index(drop=True)
        v = df['volume'].astype(float).reset_index(drop=True)
        d = _calc_index_metrics(s, o, v, theme)
        d['date'] = df['date'].iloc[-1]
        d['count'] = theme_cnt.get(theme, 1)
        d['rep_code'] = etf_code
        d['index_code'] = icode
        d['index_name'] = iname or theme
        idx_data[theme] = d
    # 2) 其余主题：ETF 合成回退
    meta = conn.execute("SELECT code,name FROM etf_meta WHERE is_ind=1").fetchall()
    groups = defaultdict(list)
    group_codes = defaultdict(list)
    for code, name in meta:
        th = theme_of(name)
        if th in idx_data:      # 已有真实指数，跳过
            continue
        df = pd.read_sql_query("SELECT date,open,close,volume FROM kline WHERE code=? ORDER BY date",
                               conn, params=(code,))
        if len(df) >= 65:
            groups[th].append(df)
            group_codes[th].append(code)
    conn.close()
    synth = {}
    for th, dfs in groups.items():
        norm_list = []
        for df in dfs:
            base = df['close'].astype(float).iloc[0]
            if base <= 0:
                continue
            norm = df[['date']].copy()
            norm['close'] = df['close'].astype(float) / base * 100.0
            norm['open'] = df['open'].astype(float) / base * 100.0
            norm['volume'] = df['volume'].astype(float)
            norm_list.append(norm)
        if len(norm_list) < 1:
            continue
        all_df = pd.concat(norm_list)
        idx_df = all_df.groupby('date', as_index=False).agg(
            open=('open', 'mean'), close=('close', 'mean'), volume=('volume', 'mean')) \
            .sort_values('date').reset_index(drop=True)
        if len(idx_df) < 65:
            continue
        s = idx_df['close'].astype(float).reset_index(drop=True)
        o = idx_df['open'].astype(float).reset_index(drop=True)
        v = idx_df['volume'].astype(float).reset_index(drop=True)
        d = _calc_index_metrics(s, o, v, th)
        d['date'] = idx_df['date'].iloc[-1]
        d['count'] = len(norm_list)
        d['rep_code'] = group_codes[th][0]
        d['index_code'] = ''
        d['index_name'] = th + '(ETF合成)'
        synth[th] = d
    data = {**synth, **idx_data}   # 真实指数优先
    n_idx = len(idx_data)
    n_syn = len(synth)
    if n_syn:
        print(f'  指数 {n_idx} 个真实 / {n_syn} 个ETF合成回退')
    return data


def theme_aggregate(data):
    """data 已是主题（指数）级：直接把指数指标转成主题列表。
    主题 ≈ ETF 追踪的指数（同主题多只 ETF 已合成一条指数曲线）。"""
    themes = []
    for th, x in data.items():
        themes.append({
            'theme': th, 'count': x.get('count', 1),
            'mom5': x['mom5'], 'mom20': x['mom20'], 'mom60': x['mom60'],
            'pct250': x['pct250'],
            'flow20': x['flow20'],
            'score': x['score'],
            'bull': 1 if x['macd_bull'] else 0,
            'weak': 1 if x['macd_weakening'] else 0,
            'rep_code': x.get('rep_code', ''), 'rep_name': th,
            'rep_score': x['score'], 'rep_last': x.get('last'),
            'index_code': x.get('index_code', ''), 'index_name': x.get('index_name', ''),
        })
    themes.sort(key=lambda t: -t['score'])
    return themes


def industry_aggregate(themes):
    """按行业大类聚合（固定索引 INDUSTRY_INDEX）：大类 = 下属主题加权汇总"""
    from signal_lib import industry_of
    from collections import defaultdict
    g = defaultdict(list)
    for t in themes:
        g[industry_of(t['theme'])].append(t)
    cats = []
    for cat, ts in g.items():
        n = sum(t['count'] for t in ts)
        # 大类分位：下属主题有效分位按标的数加权平均（全部无效则为 None）
        pcts = [(t['pct250'], t['count']) for t in ts if t['pct250'] is not None]
        pct_avg = round(sum(p * c for p, c in pcts) / sum(c for _, c in pcts), 3) if pcts else None
        cats.append({
            'cat': cat, 'themes': len(ts), 'count': n,
            'pct250': pct_avg,
            'mom5': round(sum(t['mom5'] * t['count'] for t in ts) / n, 2),
            'mom20': round(sum(t['mom20'] * t['count'] for t in ts) / n, 2),
            'mom60': round(sum(t['mom60'] * t['count'] for t in ts) / n, 2),
            'flow20': round(sum((t['flow20'] or 0) * t['count'] for t in ts) / n, 1),
            'score': round(sum(t['score'] * t['count'] for t in ts) / n, 1),
            'bull': sum(t['bull'] for t in ts),
            'weak': sum(t['weak'] for t in ts),
            # 大类代表 = 下属主题中综合分最高者
            'rep': max(ts, key=lambda t: t['score']),
        })
    cats.sort(key=lambda c: -c['score'])
    return cats


# ================= 3. 持仓预警 =================
def analyze_holdings(pos, data, themes):
    """对每笔持仓（场外基金）生成预警。用主题下代表 ETF 的信号代理。"""
    theme_map = {t['theme']: t for t in themes}
    # 模糊匹配：主题名互为子串也视为匹配（如 otc_map 的'消费' ↔ 场内'消费ETF'）
    def resolve(theme):
        if theme in theme_map:
            return theme_map[theme]
        for k, t in theme_map.items():
            if theme and (theme in k or k in theme):
                return t
        return None
    rows = []
    for code, p in pos.items():
        theme = otc_to_theme(code, p['name'])
        t = resolve(theme) if theme else None
        row = {
            'fund': p['name'], 'code': code, 'theme': theme or '未知',
            'amt': p['amt'], 'buys': p['buys'], 'sells': p['sells'],
            'last_date': p['last_date'],
            'mom5': '—', 'mom20': '—', 'mom60': '—', 'pct': '—',
            'score': '—', 'bull': '—', 'weak': '—', 'warnings': [],
        }
        if t is None:
            row['warnings'].append('未找到对应行业主题')
        else:
            row['mom5'] = t['mom5']; row['mom20'] = t['mom20']; row['mom60'] = t['mom60']
            row['pct'] = t['pct250']; row['score'] = t['score']
            row['bull'] = t['bull']; row['weak'] = t['weak']
            row['rep'] = f"{t['rep_name']}（{t['rep_code']}）"
            row['rep_score'] = t['rep_score']
            # 预警规则
            if t['mom20'] < 0 and not t['bull']:
                row['warnings'].append('⚠️ 动量转负且MACD空头——趋势走弱，关注回调')
            elif t['mom20'] < 0:
                row['warnings'].append('⚠️ 20日动量为负——短线动能不足')
            if t['weak']:
                row['warnings'].append('🟠 MACD红柱衰竭——涨势减速，勿追高')
            if t['pct250'] is not None and t['pct250'] > HIGH_PCT:
                row['warnings'].append(f"📈 历史分位 {t['pct250']:.0%} 偏高——估值已修复，谨慎加仓")
            if t['pct250'] is not None and t['pct250'] < BUY_PCT:
                row['warnings'].append(f"📉 历史分位 {t['pct250']:.0%} 低位——深度低估区间（参考）")
            if t['score'] >= 65 and t['mom20'] > 0 and t['bull']:
                row['warnings'].append('✅ 动量MACD双多——趋势强劲（参考持有）')
            if not row['warnings']:
                row['warnings'].append('➖ 中性区间，无特别预警')
        rows.append(row)
    # 按金额降序
    rows.sort(key=lambda r: -r['amt'])
    return rows


# ================= 4. 报告 =================
def fmt_pct(v, suffix='%'):
    if isinstance(v, str):
        return v
    return f'{v:+.1f}{suffix}'


def main():
    print('== 0/4 增量更新行情数据 ==')
    ensure_market_updated()

    print('== 1/4 读取持仓 ==')
    pos = load_positions()
    print(f'当前持仓: {len(pos)} 笔')
    for c, p in pos.items():
        print(f'  {p["name"]} ({c}) ¥{p["amt"]:,.0f}')

    print('== 2/4 加载行情 ==')
    data = load_market()
    themes = theme_aggregate(data)
    print(f'行业指数 {len(data)} 个（同主题ETF合成） / 主题 {len(themes)} 个')

    print('== 3/4 分析持仓并生成报告 ==')
    rows = analyze_holdings(pos, data, themes)

    # --- 行业大类全景（固定索引，按大类聚合；每大类可展开看细分方向）---
    cats = industry_aggregate(themes)
    cat_rows = ''
    for i, c in enumerate(cats, 1):
        sc = c['score']
        sp = ('#c92a2a' if sc >= 65 else ('#ba7517' if sc >= 35 else '#3b6d11'))
        sb = ('#fff0f0' if sc >= 65 else ('#fff9e6' if sc >= 35 else '#eaf3de'))
        rep = c['rep']
        # 该大类下的细分方向（主题）：按综合分降序取前 8 个（主题≈指数，同指数多基金已归一）
        sub_themes = sorted([t for t in themes if industry_of(t['theme']) == c['cat']],
                            key=lambda t: -t['score'])[:8]
        sub_rows = ''
        for t in sub_themes:
            pct_txt = f"{t['pct250']:.0%}" if t['pct250'] is not None else '—'
            sub_rows += f'''<div class="sub-row">
              <span class="etf" style="text-align:left"><b>{t['theme']}</b> <span style="color:#868e96;font-size:11px">{t.get('index_code') or t['rep_code']}</span></span>
              <span class="mom {'up' if t['mom5']>0 else 'down'}">{t['mom5']:+.1f}%</span>
              <span class="mom {'up' if t['mom20']>0 else 'down'}">{t['mom20']:+.1f}%</span>
              <span class="mom {'up' if t['mom60']>0 else 'down'}">{t['mom60']:+.1f}%</span>
              <span class="pct">{pct_txt}</span>
              <span class="flow {'up' if t['flow20']>0 else 'down'}">{t['flow20']:+.0f}%</span>
              <span class="score"><b>{t['score']:.0f}</b></span>
              <span class="bull">{t['bull']}/{t['count']}</span>
              <span class="weak">{t['weak']}</span>
            </div>'''
        cat_rows += f'''<details class="cat-detail">
<summary>
  <span class="rank">{i}</span>
  <span class="cat-name"><b>{c['cat']}</b></span>
  <span class="mom {'up' if c['mom5']>0 else 'down'}">{c['mom5']:+.1f}%</span>
  <span class="mom {'up' if c['mom20']>0 else 'down'}">{c['mom20']:+.1f}%</span>
  <span class="mom {'up' if c['mom60']>0 else 'down'}">{c['mom60']:+.1f}%</span>
  <span class="pct">{f"{c['pct250']:.0%}" if c['pct250'] is not None else '—'}</span>
  <span class="flow {'up' if c['flow20']>0 else 'down'}">{c['flow20']:+.0f}%</span>
  <span class="score" style="background:{sb};color:{sp}">{sc:.0f}</span>
  <span class="bull">{c['bull']}/{c['count']}</span>
  <span class="weak">{c['weak']}</span>
</summary>
<div class="sub-table">
{sub_rows}
</div>
</details>'''

    # --- 低估方向（分位<0.3，按行业大类聚合）---
    # 大类分位 = 下属主题按标的数加权平均
    low_list = []
    for c in cats:
        pcts = [t['pct250'] * t['count'] for t in themes if industry_of(t['theme']) == c['cat'] and t['pct250'] is not None]
        cnts = [t['count'] for t in themes if industry_of(t['theme']) == c['cat'] and t['pct250'] is not None]
        if pcts:
            c['pct250'] = round(sum(pcts) / sum(cnts), 3)
            if c['pct250'] < BUY_PCT:
                low_list.append(c)
    low_list.sort(key=lambda x: x['pct250'])
    low_rows = ''
    for c in low_list[:15]:
        low_rows += f'''<tr><td style="text-align:left"><b>{c['cat']}</b></td>
          <td>{c['themes']}个/{c['count']}只</td>
          <td class="down">{c['pct250']:.0%}</td>
          <td>{c['rep']['theme']}</td>
          <td class="{'up' if c['mom20']>0 else 'down'}">{c['mom20']:+.1f}%</td></tr>'''
    low_note = f'当前 {len(low_list)} 个行业大类处于历史低位（250日分位&lt;{BUY_PCT:.0%}）——均值回归参考' if low_list else '当前无深度低估行业大类'

    # --- 强势方向（双多，按行业大类聚合）---
    strong_list = [c for c in cats if c['score'] >= 65 and c['mom20'] > 0 and c['bull'] >= c['count'] * 0.5]
    strong_list.sort(key=lambda x: -x['score'])
    strong_rows = ''
    for c in strong_list[:15]:
        strong_rows += f'''<tr><td style="text-align:left"><b>{c['cat']}</b></td>
          <td>{c['themes']}个/{c['count']}只</td>
          <td class="up">{c['score']:.0f}</td>
          <td>{c['rep']['theme']}</td>
          <td class="up">{c['mom20']:+.1f}%</td>
          <td class="up">{c['mom60']:+.1f}%</td></tr>'''
    strong_note = f'当前 {len(strong_list)} 个行业大类动量+MACD双多——趋势参考' if strong_list else '当前无双多行业大类（市场偏弱）'

    # --- 持仓表 ---
    hold_rows = ''
    for r in rows:
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in r['warnings'])
        amt_txt = f"¥{r['amt']:,.0f}"
        score_txt = r['score'] if isinstance(r['score'], (int, float)) else '—'
        # 历史分位：0~1 小数按百分比显示（0.2 → 20%）
        pct_txt = f"{r['pct']:.0%}" if isinstance(r['pct'], (int, float)) else '—'
        hold_rows += f'''<tr>
          <td><b>{r['fund']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td><span style="background:#edf2ff;color:#364fc7;padding:2px 8px;border-radius:8px;font-weight:700">{r['theme']}</span></td>
          <td>{amt_txt}</td>
          <td class="{'up' if isinstance(r['mom20'], (int,float)) and r['mom20']>0 else 'down'}">{fmt_pct(r['mom20'])}</td>
          <td>{pct_txt}</td>
          <td><b>{score_txt}</b></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''

    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    market_date = data[next(iter(data))]['date'] if data else '—'
    # 报告统一命名：YYYYMMDD.html（按数据日期），目录本身已区分指数/行业；
    # 同一天多次生成覆盖同名文件，历史日期的报告保留不删
    fname = market_date.replace('-', '') if market_date and market_date != '—' \
        else datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>行业数据分析日报</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--line:#e3e6eb;--tx:#1c2333}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:-apple-system,"Microsoft YaHei",sans-serif;font-size:14px}}
header{{background:#fff;border-bottom:1px solid var(--line);padding:22px 0}}
.wrap{{max-width:1150px;margin:0 auto;padding:0 20px}}
header h1{{font-size:22px}}
header .sub{{opacity:.85;font-size:13px;margin-top:6px}}
.card{{background:var(--card);border-radius:14px;padding:20px 22px;margin:18px 0;border:1px solid var(--line)}}
.card h2{{font-size:17px;margin-bottom:12px}}
.card h3{{font-size:14px;color:#364fc7;margin:6px 0 10px}}
/* 行业大类折叠列表 */
.cat-list{{border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.cat-head,.cat-detail summary{{display:flex;align-items:center;gap:10px;padding:9px 12px;font-size:13px;white-space:nowrap}}
.cat-head{{background:#f1f3f5;font-weight:600;color:#5b6472}}
.cat-detail{{border-top:1px solid #f1f3f5}}
.cat-detail summary{{cursor:pointer;list-style:none}}
.cat-detail summary::-webkit-details-marker{{display:none}}
.cat-detail summary:hover{{background:#f8f9fa}}
.cat-detail summary .rank,.cat-head .rank{{width:20px;flex:none;color:#868e96}}
.cat-detail summary .cat-name,.cat-head .cat-name{{flex:1;min-width:80px;overflow:hidden;text-overflow:ellipsis}}
.cat-detail summary .mom,.cat-head .mom{{width:58px;flex:none;text-align:right;font-size:12px}}
.cat-detail summary .pct,.cat-head .pct{{width:48px;flex:none;text-align:right;font-size:12px;color:#5b6472}}
.cat-detail summary .flow,.cat-head .flow{{width:56px;flex:none;text-align:right;font-size:12px}}
.cat-detail summary .score,.cat-head .score{{width:40px;flex:none;text-align:center;font-weight:700;padding:2px 4px;border-radius:8px}}
.cat-detail summary .bull,.cat-head .bull{{width:42px;flex:none;text-align:right;color:#5b6472;font-size:12px}}
.cat-detail summary .weak,.cat-head .weak{{width:24px;flex:none;text-align:right;font-size:12px}}
.cat-detail .sub-table{{padding:6px 14px;background:#fafbfc;border-top:1px solid #f1f3f5}}
.cat-detail .sub-row{{display:flex;align-items:center;gap:10px;padding:6px 0;font-size:12px;border-bottom:1px solid #f1f3f5}}
.cat-detail .sub-row:last-child{{border-bottom:none}}
.cat-detail .sub-row .etf{{flex:1;min-width:90px;overflow:hidden;text-overflow:ellipsis}}
.cat-detail .sub-row .mom{{width:58px;flex:none;text-align:right}}
.cat-detail .sub-row .pct{{width:48px;flex:none;text-align:right;color:#5b6472}}
.cat-detail .sub-row .flow{{width:56px;flex:none;text-align:right}}
.cat-detail .sub-row .score{{width:40px;flex:none;text-align:center}}
.cat-detail .sub-row .bull{{width:44px;flex:none;text-align:right}}
.cat-detail .sub-row .weak{{width:24px;flex:none;text-align:center}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f1f3f5;padding:9px 8px;text-align:center;font-weight:600;border-bottom:2px solid var(--line)}}
td{{padding:8px;text-align:center;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9fa}}
.up{{color:#e03131;font-weight:600}}
.down{{color:#0ca678;font-weight:600}}
.note{{font-size:13px;color:#5b6472;line-height:1.7;margin-top:10px}}
.warn-box{{border-left:4px solid #f59f00;background:#fff9db;padding:12px 14px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;margin:10px 0}}
.ok-box{{border-left:4px solid #0ca678;background:#ebfbee;padding:12px 14px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;margin:10px 0}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
.kpi{{flex:1;min-width:150px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi .k{{color:#5b6472;font-size:12px}}
.kpi .v{{font-size:22px;font-weight:700;margin-top:4px}}
.disclaimer{{font-size:12px;color:#868e96;line-height:1.7;margin-top:16px;padding:12px;background:#f8f9fa;border-radius:10px}}
</style></head><body>
<header><div class="wrap">
<h1>行业数据分析日报</h1>
<div class="sub">数据日期 {market_date} · 生成时间 {gen_time} · 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">当前持仓</div><div class="v">{len(rows)} 笔</div><div class="note">Sector.log 推导</div></div>
  <div class="kpi"><div class="k">持仓总金额</div><div class="v">¥{sum(r['amt'] for r in rows):,.0f}</div><div class="note">买入-赎回累计</div></div>
  <div class="kpi"><div class="k">行业主题</div><div class="v">{len(themes)} 个</div><div class="note">细分主题聚合</div></div>
  <div class="kpi"><div class="k">行业大类</div><div class="v">{len(cats)} 个</div><div class="note">固定行业索引</div></div>
  <div class="kpi"><div class="k">低估方向</div><div class="v">{len(low_list)} 个</div><div class="note">分位&lt;30%</div></div>
  <div class="kpi"><div class="k">强势方向</div><div class="v">{len(strong_list)} 个</div><div class="note">综合分≥65 双多</div></div>
</div>

<div class="card"><h2>📋 当前行业持仓与预警</h2>
<p class="note">持仓来自 Sector.log（买入-赎回推导）。预警用对应主题的代表 ETF 信号代理（场内 ETF 与场外联接基金跟踪同一指数，趋势一致）。</p>
<table><thead><tr><th>持仓基金</th><th>主题</th><th>持仓金额</th><th>20日动量</th><th>历史分位</th><th>综合分</th><th>预警</th></tr></thead>
<tbody>{hold_rows}</tbody></table>
</div>

<div class="card"><h2>📉 低估行业大类雷达（参考）</h2>
<p class="note">{low_note}</p>
<table><thead><tr><th>行业大类</th><th>主题/标的</th><th>历史分位</th><th>代表主题</th><th>20日动量</th></tr></thead>
<tbody>{low_rows}</tbody></table>
</div>

<div class="card"><h2>📈 强势行业大类雷达（参考）</h2>
<p class="note">{strong_note}</p>
<table><thead><tr><th>行业大类</th><th>主题/标的</th><th>评分</th><th>代表主题</th><th>20日动量</th><th>60日动量</th></tr></thead>
<tbody>{strong_rows}</tbody></table>
</div>

<div class="card"><h2>🗂️ 行业大类全景（{len(cats)} 个，按综合分降序，点击展开看 Top5 ETF）</h2>
<p class="note">按 A 股通用行业分类固定索引（有色金属/医药生物/半导体电子/计算机软件/通信传媒/国防军工/新能源/汽车/机械设备/食品饮料/家用电器/房地产基建/金融/能源化工/公用事业/社会服务/综合），下属细分主题加权汇总。新增 ETF 自动归入对应大类。</p>
<div class="cat-list">
<div class="cat-head"><span class="rank">#</span><span class="cat-name">行业大类</span><span class="mom">5日</span><span class="mom">20日</span><span class="mom">60日</span><span class="pct">分位</span><span class="flow">资金流</span><span class="score">综合分</span><span class="bull">多头</span><span class="weak">衰竭</span></div>
{cat_rows}
</div>
</div>

<div class="disclaimer">⚠️ 免责声明：本报告基于公开行情数据的量化分析，仅供参考，不构成投资建议。动量/分位/评分均为历史统计，不预示未来。任何操作请结合个人风险承受能力独立判断。场外基金费率与赎回到账时间以基金公司公告为准。</div>

</div></body></html>'''
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n报告已生成: {out_html}')
    print(f'持仓预警 {sum(1 for r in rows if any("⚠️" in w or "🟠" in w for w in r["warnings"]))} 笔 | 低估方向 {len(low_list)} | 强势方向 {len(strong_list)}')


if __name__ == '__main__':
    main()
