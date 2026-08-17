# -*- coding: utf-8 -*-
"""
持仓基金分析报告（portfolio_report.py）
=======================================
分析 portfolio.db 中**全部持仓基金**（指数 + 行业 + 资金池），逐只给出场外基金
或对应场内 ETF 的行情信号。数据拉取为**持仓驱动**：只拉当前持仓涉及的指数，
不维护预设的定投标的清单。

报告内容：
  1. 指数持仓分析：全部指数类持仓（A股宽基 + 红利 + 美股），映射到跟踪指数
     （market_index.db：健康度/分位/回撤/趋势/预警）
  2. 行业持仓分析：全部行业基金 → otc_map 映射主题 → market_industry.db 主题信号
     （综合分/分位/动量/MACD/预警）
  3. 资金池：余额宝可用余额

数据源：
  - data/portfolio.db：全部持仓流水（指数/行业/资金池）
  - data/market_index.db：指数行情与评估分（持仓驱动增量刷新，sina/yahoo）
  - data/market_industry.db：行业主题信号（自动增量更新）

用法：
  python portfolio_report.py            # 生成报告（数据过旧自动刷新）
  python run.py --index                 # 统一入口（--index 已指向本报告）
输出：PortfolioReport/YYYYMMDD.html（按数据日期命名，历史保留）
"""
import os, sys, sqlite3, datetime
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))

from dca import FUNDS, US_FUNDS, refresh_data
from signal_lib import theme_of
from otc_map import OTC_MAP
from metrics import _calc_index_metrics

PORTFOLIO_DB = os.path.join(BASE, 'data', 'portfolio.db')
IND_DB = os.path.join(BASE, 'data', 'market_industry.db')   # 行业行情库（腾讯前复权）
INDEX_DB = os.path.join(BASE, 'data', 'market_index.db')    # 指数行情库（新浪/Yahoo）
OUT_DIR = os.path.join(BASE, '..', 'PortfolioReport')
BUY_PCT = 0.3          # 低估参考线
HIGH_PCT = 0.7         # 高估预警线

# 健康度权重（满分100，自 index_report 合并）
W_PCT = 35      # 估值/价格分位：越低越健康（便宜=定投性价比高）
W_TREND = 25    # 趋势分
W_DD = 15       # 回撤分（深回撤=机会）
W_MOM = 15      # 20日动量（趋势确认）
W_FLOW = 10     # 20日量能方向比
CHEAP = 30.0    # 定投分位阈值（与 dca.py 一致）
EXPENSIVE = 70.0


# ================= 指数健康度引擎（自 index_report 合并，2026-08-17）=================
def idx_conn():
    return sqlite3.connect(INDEX_DB)


def load_indices(slug):
    """某指数的日线 DataFrame（date/close/volume）"""
    conn = idx_conn()
    df = pd.read_sql_query(
        'SELECT date, close, volume FROM indices WHERE slug=? ORDER BY date', conn, params=(slug,))
    conn.close()
    return df


def latest_assessment(slug):
    """assessments 最新一行 dict（分位/回撤/趋势分/加仓分）"""
    conn = idx_conn()
    row = conn.execute('''SELECT * FROM assessments a
        WHERE slug=? AND date=(SELECT MAX(date) FROM assessments a2 WHERE a2.slug=a.slug)''',
        (slug,)).fetchone()
    cols = [d[1] for d in conn.execute('PRAGMA table_info(assessments)').fetchall()]
    conn.close()
    return dict(zip(cols, row)) if row else None


def latest_valuation(slug):
    """valuations 最新一行（PE/PB），没有则 None"""
    conn = idx_conn()
    row = conn.execute('''SELECT * FROM valuations a
        WHERE slug=? AND date=(SELECT MAX(date) FROM valuations a2 WHERE a2.slug=a.slug)''',
        (slug,)).fetchone()
    cols = [d[1] for d in conn.execute('PRAGMA table_info(valuations)').fetchall()]
    conn.close()
    return dict(zip(cols, row)) if row else None


def flow_ratio(df, n=20):
    """量能方向比：近N日 (上涨量-下跌量)/总成交量，-100~+100%"""
    if len(df) < n + 1 or 'volume' not in df.columns:
        return None
    d = df.tail(n + 1).reset_index(drop=True)
    chg = d['close'].diff().dropna()
    vol = d['volume'].iloc[1:].astype(float)
    up = vol[chg > 0].sum()
    dn = vol[chg < 0].sum()
    tot = up + dn
    return round((up - dn) / tot * 100, 1) if tot > 0 else None


def index_health(slug):
    """计算某指数的健康度指标（分位/回撤/趋势/动量/资金流综合分）"""
    df = load_indices(slug)
    if len(df) < 65:
        return None
    s = df['close'].astype(float)
    n = len(s)
    mom5 = float(s.iloc[-1] / s.iloc[-6] - 1) * 100 if n > 6 else 0.0
    mom20 = float(s.iloc[-1] / s.iloc[-21] - 1) * 100 if n > 21 else 0.0
    mom60 = float(s.iloc[-1] / s.iloc[-61] - 1) * 100 if n > 61 else mom20
    flow = flow_ratio(df)
    a = latest_assessment(slug)
    v = latest_valuation(slug)
    # 分位：优先估值分位（有 PE 数据时用价格分位兜底）
    pct = None
    pct_src = '—'
    if a and a.get('price_percentile') is not None:
        pct = float(a['price_percentile'])
        pct_src = '价格分位'
    dd = float(a['drawdown_pct']) if a and a.get('drawdown_pct') is not None else 0.0
    trend = float(a['trend_score']) if a and a.get('trend_score') is not None else 50.0
    dd_score = float(a['drawdown_score']) if a and a.get('drawdown_score') is not None else 50.0
    pe = float(v['pe_ttm']) if v and v.get('pe_ttm') is not None else None
    # 健康度分
    def _pct_score(p):
        if p is None:
            return W_PCT * 0.5
        if p <= CHEAP:
            return W_PCT
        if p >= EXPENSIVE:
            return 0.0
        return W_PCT * (EXPENSIVE - p) / (EXPENSIVE - CHEAP)
    health = (_pct_score(pct) + W_TREND * min(trend, 100) / 100.0
              + W_DD * min(dd_score, 100) / 100.0
              + (W_MOM * 0.8 if mom20 > 0 else W_MOM * 0.2)
              + (W_FLOW if (flow or 0) > 0 else 0.0))
    health = max(0.0, min(100.0, health))
    return {
        'slug': slug, 'date': str(df['date'].iloc[-1]), 'last': float(s.iloc[-1]),
        'mom5': round(mom5, 2), 'mom20': round(mom20, 2), 'mom60': round(mom60, 2),
        'flow': flow, 'pct': round(pct, 1) if pct is not None else None,
        'pct_src': pct_src, 'dd': round(dd, 1), 'trend': round(trend, 1),
        'pe': pe, 'health': round(health, 1),
    }


def latest_trading_day():
    """估算最近交易日（与 plate 同口径）：
    A股北京时间 15:00 收盘——未收盘(北京<15:00)返回上一交易日，已收盘返回当天。"""
    import datetime as _dt
    bj = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=8)  # 北京时间
    today = bj.date()
    wd = today.weekday()
    if bj.hour < 15:                     # 尚未收盘：取上一交易日
        if wd == 0:                      # 周一盘前=上周五
            return today - _dt.timedelta(days=3)
        if wd == 6:                      # 周日
            return today - _dt.timedelta(days=2)
        if wd == 5:                      # 周六
            return today - _dt.timedelta(days=1)
        return today - _dt.timedelta(days=1)   # 周二~周五盘前=前一天
    if wd == 6:                          # 周日(北京15点后=北京时间周日晚, 实际少见)
        return today - _dt.timedelta(days=2)
    if wd == 5:                          # 周六
        return today - _dt.timedelta(days=1)
    return today                         # 周一~周五已收盘=当天


def load_all_positions():
    """从 portfolio.db 读全部持仓，返回 {code: {name, code, amt, category}}（amt>0）"""
    pos = {}
    if not os.path.exists(PORTFOLIO_DB):
        return pos
    conn = sqlite3.connect(PORTFOLIO_DB)
    rows = conn.execute(
        "SELECT category,fund,code,direction,amount FROM trans ORDER BY date").fetchall()
    conn.close()
    for cat, name, code, direction, amt in rows:
        if not code or not direction:
            continue
        if code == 'ZFB' or '余额宝' in name:
            continue
        p = pos.setdefault(code, {'name': name, 'code': code, 'amt': 0.0, 'category': cat})
        if direction in ('买入', '转入', '申购', '加仓', '收益'):
            p['amt'] += amt
        elif direction in ('卖出', '赎回', '减仓', '转出'):
            p['amt'] -= amt
    return {c: p for c, p in pos.items() if p['amt'] > 1}


def cash_implied():
    """余额宝可用余额（转入-已投基金），复用 portfolio_app 逻辑"""
    try:
        import portfolio_app as pa
        return pa.get_summary().get('cash_implied')
    except Exception:
        return None


def holding_index_slugs(pos):
    """从当前持仓中推导需要分析的指数 slug 集合（持仓驱动：只拉持仓涉及的指数）"""
    fmap = {f.code: f for f in FUNDS + US_FUNDS}
    slugs = set()
    for code, p in pos.items():
        if p['category'] != '指数':
            continue
        f = fmap.get(code)
        if f:
            slugs.add(f.index_slug)
    return slugs


def analyze_index_holdings(pos):
    """指数持仓 → 每只基金映射到跟踪指数，取 index_health 信号。覆盖全部（含红利/美股）"""
    fmap = {f.code: f for f in FUNDS + US_FUNDS}
    rows = []
    for code, p in pos.items():
        if p['category'] != '指数':
            continue
        f = fmap.get(code)
        if not f:
            continue
        hh = index_health(f.index_slug)
        if not hh:
            continue
        warns = []
        if hh['pct'] is not None:
            if hh['pct'] > 70:
                warns.append(f"⚠️ 分位{hh['pct']:.0f}% 高估，建议减半定投")
            elif hh['pct'] < 30:
                warns.append(f"✅ 分位{hh['pct']:.0f}% 低估，可加倍定投")
        if hh['trend'] < 50:
            warns.append('📉 趋势分偏低')
        if hh['mom20'] < -5:
            warns.append('📉 20日动量转弱')
        if hh['dd'] < -20:
            warns.append('⚠️ 深度回撤')
        if not warns:
            warns.append('✅ 状态正常')
        rows.append({
            'fund': p['name'], 'code': code, 'amt': p['amt'],
            'idx': f.index_slug, 'slug': f.tracking,
            'market': f.market,  # cn / us
            'mom20': hh['mom20'], 'pct': hh['pct'], 'dd': hh['dd'],
            'trend': hh['trend'], 'pe': hh['pe'], 'health': hh['health'],
            'warnings': warns,
        })
    rows.sort(key=lambda r: -r['amt'])
    return rows


# ================= 行业持仓信号引擎（自 sector_report 合并，2026-08-17）=================
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


def ensure_market_updated():
    """智能增量更新行业行情：仅当库内最新日期 < 最近交易日时才拉新K线（避免每次运行都请求接口）"""
    import subprocess
    fetch_script = os.path.join(BASE, 'fetch_db.py')
    if not os.path.exists(IND_DB):
        print('  [首次] 全量重建行业数据库...')
        subprocess.run([sys.executable, fetch_script, '--types', 'all'], check=False)
        return
    try:
        conn = sqlite3.connect(IND_DB)
        db_latest = conn.execute('SELECT MAX(date) FROM kline').fetchone()[0]
        conn.close()
    except Exception:
        db_latest = None
    need = latest_trading_day().strftime('%Y-%m-%d')
    if db_latest and db_latest >= need:
        print(f'  行业数据已最新（{db_latest}），跳过增量更新')
        return
    print(f'  行业库内 {db_latest} < 最近交易日 {need}，增量更新...')
    subprocess.run([sys.executable, fetch_script, '--incremental'], check=False)


def load_market():
    """加载行业指数数据（真实指数优先，ETF 合成为回退）：
    ① index_kline 有映射且 index_daily 有 K 线 → 用真实指数日线
    ② 否则 → 该主题多只 ETF 归一化合成指数曲线
    每主题返回 {指标dict}，theme≈指数方向。"""
    from collections import defaultdict
    conn = sqlite3.connect(IND_DB)
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
        print(f'  行业指数 {n_idx} 个真实 / {n_syn} 个ETF合成回退')
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


def fmt_pct(v, suffix='%'):
    if isinstance(v, str):
        return v
    return f'{v:+.1f}{suffix}'


def analyze_industry_holdings(pos):
    """行业持仓 → otc_map 映射主题 + 主题信号 + 预警（引擎已合并进本模块）"""
    ind_pos = {c: {'name': p['name'], 'code': c, 'amt': p['amt'],
                   'buys': 0, 'sells': 0, 'last_date': '', 'last_gain': 0.0}
               for c, p in pos.items() if p['category'] == '行业'}
    if not ind_pos:
        return [], 0
    data = load_market()
    themes = theme_aggregate(data)
    rows = analyze_holdings(ind_pos, data, themes)
    return rows, len(themes)


def build_html():
    pos = load_all_positions()
    idx_rows = analyze_index_holdings(pos)
    ind_rows, n_themes = analyze_industry_holdings(pos)
    cash = cash_implied()

    idx_total = sum(r['amt'] for r in idx_rows)
    ind_total = sum(r['amt'] for r in ind_rows)
    total = idx_total + ind_total + (cash or 0)

    # ---- 指数持仓表 ----
    idx_tbl = ''
    for r in idx_rows:
        hc = r['health']
        hp = ('#c92a2a' if hc >= 65 else ('#ba7517' if hc >= 40 else '#3b6d11'))
        hb = ('#fff0f0' if hc >= 65 else ('#fff9e6' if hc >= 40 else '#eaf3de'))
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in r['warnings'])
        pct_txt = f"{r['pct']:.0f}%" if r['pct'] is not None else '—'
        pe_txt = f"{r['pe']:.1f}" if r['pe'] else '—'
        mkt_tag = '美股' if r['market'] == 'us' else 'A股/港股'
        idx_tbl += f'''<tr>
          <td style="text-align:left"><b>{r['fund']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td><span style="background:#edf2ff;color:#364fc7;padding:2px 8px;border-radius:8px;font-weight:700">{r['slug']}</span></td>
          <td><span style="color:#868e96;font-size:11px">{mkt_tag}</span></td>
          <td>¥{r['amt']:,.2f}</td>
          <td class="{'up' if r['mom20'] > 0 else 'down'}">{r['mom20']:+.1f}%</td>
          <td>{pct_txt}</td>
          <td>{pe_txt}</td>
          <td>{r['dd']:+.1f}%</td>
          <td><span style="background:{hb};color:{hp};padding:2px 8px;border-radius:8px;font-weight:700">{hc:.0f}</span></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''

    # ---- 行业持仓表 ----
    ind_tbl = ''
    for r in ind_rows:
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in r['warnings'])
        pct_txt = f"{r['pct']:.0%}" if isinstance(r['pct'], (int, float)) else '—'
        score_txt = r['score'] if isinstance(r['score'], (int, float)) else '—'
        ind_tbl += f'''<tr>
          <td style="text-align:left"><b>{r['fund']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td><span style="background:#ebfbee;color:#0f6e56;padding:2px 8px;border-radius:8px;font-weight:700">{r['theme']}</span></td>
          <td>¥{r['amt']:,.2f}</td>
          <td class="{'up' if isinstance(r['mom20'], (int, float)) and r['mom20']>0 else 'down'}">{fmt_pct(r['mom20'])}</td>
          <td>{pct_txt}</td>
          <td><b>{score_txt}</b></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''

    # ---- 数据日期 ----
    mkt_date = '—'
    try:
        conn = sqlite3.connect(INDEX_DB)
        mkt_date = conn.execute('SELECT MAX(date) FROM indices').fetchone()[0] or '—'
        conn.close()
    except Exception:
        pass
    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fname = datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')
    if os.path.exists(out_html):
        out_html = os.path.join(OUT_DIR, f"{fname}_{datetime.datetime.now().strftime('%H%M%S')}.html")

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>持仓基金分析报告</title>
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
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f1f3f5;padding:9px 8px;text-align:center;font-weight:600;border-bottom:2px solid var(--line)}}
td{{padding:8px;text-align:center;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9fa}}
.up{{color:#e03131;font-weight:600}}
.down{{color:#0ca678;font-weight:600}}
.note{{font-size:13px;color:#5b6472;line-height:1.7;margin-top:10px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
.kpi{{flex:1;min-width:150px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi .k{{color:#5b6472;font-size:12px}}
.kpi .v{{font-size:22px;font-weight:700;margin-top:4px}}
.disclaimer{{font-size:12px;color:#868e96;line-height:1.7;margin-top:16px;padding:12px;background:#f8f9fa;border-radius:10px}}
</style></head><body>
<header><div class="wrap">
<h1>持仓基金分析报告</h1>
<div class="sub">数据日期 {mkt_date} · 生成时间 {gen_time} · 分析全部持仓基金（指数/行业/资金池）· 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">指数持仓</div><div class="v">¥{idx_total:,.0f}</div><div class="note">{len(idx_rows)} 只（含红利/美股）</div></div>
  <div class="kpi"><div class="k">行业持仓</div><div class="v">¥{ind_total:,.0f}</div><div class="note">{len(ind_rows)} 只（主题信号）</div></div>
  <div class="kpi"><div class="k">余额宝</div><div class="v">¥{cash:,.0f}</div><div class="note">可用现金</div></div>
  <div class="kpi"><div class="k">持仓总资产</div><div class="v">¥{total:,.0f}</div><div class="note">含现金</div></div>
</div>

<div class="card"><h2>📋 指数持仓分析（全部，含红利/美股）</h2>
<p class="note">健康度分 = 分位便宜度(35) + 趋势(25) + 回撤(15) + 20日动量(15) + 资金流(10)，满分 100。
分位越低越健康；≥65 健康 / 40-65 关注 / &lt;40 谨慎。数据按当前持仓涉及的指数拉取（持仓驱动）。</p>
<table><thead><tr><th>持仓基金</th><th>指数</th><th>市场</th><th>持仓金额</th><th>20日动量</th><th>价格分位</th><th>PE(TTM)</th><th>距高点回撤</th><th>健康度</th><th>预警</th></tr></thead>
<tbody>{idx_tbl or '<tr><td colspan="10" style="color:#adb5bd">无指数持仓</td></tr>'}</tbody></table>
</div>

<div class="card"><h2>📋 行业持仓分析（主题信号）</h2>
<p class="note">持仓映射到场内代表 ETF（otc_map），综合分 = 动量(50) + MACD(15) + MA60(15) + 历史分位(10) + 资金流(10)。</p>
<table><thead><tr><th>持仓基金</th><th>主题</th><th>持仓金额</th><th>20日动量</th><th>历史分位</th><th>综合分</th><th>预警</th></tr></thead>
<tbody>{ind_tbl or '<tr><td colspan="7" style="color:#adb5bd">无行业持仓</td></tr>'}</tbody></table>
</div>

<div class="card"><h2>💰 资金池</h2>
<table><thead><tr><th>账户</th><th>可用余额</th><th>说明</th></tr></thead>
<tbody><tr><td>余额宝（ZFB）</td><td class="up">¥{cash:,.2f}</td><td style="text-align:left;color:#5b6472">转入累计 - 已投基金（推算口径，与持仓流水管理一致）</td></tr></tbody></table>
</div>

<div class="disclaimer">宽基指数为长期定投资产：战略比例不变，便宜多买、贵时少买（分位&lt;30% ×1.5、30-70% ×1.0、&gt;70% ×0.5），不择时。本报告由 Code/portfolio_report.py 生成，指数数据来自新浪/腾讯/Yahoo（持仓驱动），行业数据来自腾讯前复权行情，持仓来自 portfolio.db。</div>
</div></body></html>'''
    return html, out_html


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='强制刷新指数数据（联网）')
    ap.add_argument('--no-refresh', action='store_true', help='跳过指数数据新鲜度检查')
    args = ap.parse_args()

    # 指数数据：持仓驱动刷新——只拉当前持仓涉及的指数 slug
    pos = load_all_positions()
    slugs = holding_index_slugs(pos)
    try:
        if args.refresh:
            print('强制刷新指数数据...')
            refresh_data(force=True, only_slugs=slugs or None)
        elif not args.no_refresh and slugs:
            # 数据过旧才刷新（复用 index_report 的 ensure_fresh，按持仓涉及的指数判断）
            conn = sqlite3.connect(INDEX_DB)
            latest = conn.execute('SELECT MAX(date) FROM indices').fetchone()[0]
            conn.close()
            need = latest_trading_day().strftime('%Y-%m-%d')
            if latest and latest >= need:
                print(f'  指数数据已最新（{latest}），跳过刷新')
            else:
                print(f'  指数数据 {latest} < 最近交易日 {need}，按持仓驱动刷新...')
                refresh_data(only_slugs=slugs)
    except Exception as e:
        print(f'  [warn] 指数数据刷新失败: {e}')

    # 行业数据：增量更新（引擎已合并进本模块）
    try:
        ensure_market_updated()
    except Exception as e:
        print(f'  [warn] 行业数据更新失败: {e}')

    html, out_html = build_html()
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'持仓基金分析报告已生成: {out_html}')


if __name__ == '__main__':
    main()
