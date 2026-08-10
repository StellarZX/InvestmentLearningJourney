# -*- coding: utf-8 -*-
"""
宽基指数报告（index_report.py）
================================
替代原「指数看板」：输出静态 HTML 报告到 02_IndexReport/index_report.html。
内容：
  1. 当前持仓指数基金健康度分析（综合分 + 预警，基于估值/价格分位 + 趋势 + 动量 + 资金流）
  2. 宽基指数全景表（8 个定投指数：分位/回撤/趋势/健康度）
  3. 当月定投分配建议（复用 lib/dca.py 的分位×倍数规则）
  4. 低估 / 高估方向

数据源：
  - data/market_index.db：indices（日线）/ valuations（PE）/ assessments（评估分）
  - data/portfolio.db：指数持仓（category='指数'）
  - lib/dca.py：定投标的映射与定投分配

用法：
  python index_report.py            # 生成报告（数据已有则秒级）
  python index_report.py --refresh  # 先生成报告；数据过旧时自动刷新（联网）
"""
import os
import sys
import sqlite3
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'lib'))

import pandas as pd
import numpy as np
from dca import FUNDS, US_FUNDS, build_dca_decision

INDEX_DB = os.path.join(BASE, 'data', 'market_index.db')
PORTFOLIO_DB = os.path.join(BASE, 'data', 'portfolio.db')
OUT_DIR = os.path.join(BASE, '..', '02_IndexReport')    # 报告输出到 02 指数报告目录（按日期命名）

# 健康度权重（满分100）
W_PCT = 35      # 估值/价格分位：越低越健康（便宜=定投性价比高）
W_TREND = 25    # 趋势分
W_DD = 15       # 回撤分（深回撤=机会）
W_MOM = 15      # 20日动量（趋势确认）
W_FLOW = 10     # 20日量能方向比

# 定投分位阈值（与 dca.py 一致）
CHEAP = 30.0
EXPENSIVE = 70.0


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
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


def index_meta():
    """slug -> 中文名（优先固定映射，其次库内中文名，最后英文名）"""
    FIXED = {
        'csi_300': '沪深300', 'csi_500': '中证500', 'chi_next': '创业板指',
        'csi_dividend': '中证红利', 'hang_seng': '恒生指数',
        'hsi_dividend_lowvol': '恒生红利低波', 'nasdaq_100': '纳斯达克100',
        'sp500': '标普500',
    }
    conn = idx_conn()
    rows = conn.execute('SELECT DISTINCT slug, name FROM indices').fetchall()
    conn.close()
    meta = {sl: FIXED.get(sl, sl) for sl in FIXED}
    for slug, name in rows:
        if slug in meta:
            continue
        if name and not any(c.isascii() for c in name):   # 中文名
            meta[slug] = name
        elif slug not in meta:
            meta[slug] = name or slug
    return meta


def load_portfolio_holdings():
    """指数持仓：code -> {fund, code, amt}（与 portfolio_app 同口径）"""
    conn = sqlite3.connect(PORTFOLIO_DB)
    rows = conn.execute('''
        SELECT fund, code,
          SUM(CASE WHEN direction IN ('买入','转入','收益') THEN amount
                   WHEN direction IN ('卖出','转出') THEN -amount ELSE 0 END) AS amt
        FROM trans WHERE category='指数' GROUP BY code''').fetchall()
    conn.close()
    return {r[1]: {'fund': r[0], 'code': r[1], 'amt': round(r[2], 2)} for r in rows if r[2] > 0}


def fund_to_slug():
    """基金代码 -> (基金对象, index_slug)"""
    m = {}
    for f in FUNDS + US_FUNDS:
        m[f.code] = f
    return m


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
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
    """计算某指数的健康度指标"""
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


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------
def build_html():
    meta = index_meta()
    slug_names = {}
    for f in FUNDS + US_FUNDS:
        slug_names[f.index_slug] = meta.get(f.index_slug, f.index_slug)

    # 全部定投标的的健康度
    all_slugs = []
    for f in FUNDS + US_FUNDS:
        if f.index_slug not in all_slugs:
            all_slugs.append(f.index_slug)
    health_map = {sl: index_health(sl) for sl in all_slugs}

    # 持仓
    holdings = load_portfolio_holdings()
    f2s = fund_to_slug()
    hold_rows = ''
    hold_amt = 0.0
    for code, h in holdings.items():
        f = f2s.get(code)
        if not f:
            continue
        hh = health_map.get(f.index_slug)
        if not hh:
            continue
        hold_amt += h['amt']
        # 预警
        warns = []
        if hh['pct'] is not None:
            if hh['pct'] > EXPENSIVE:
                warns.append(f"⚠️ 分位{hh['pct']:.0f}% 高估，建议减半定投")
            elif hh['pct'] < CHEAP:
                warns.append(f"✅ 分位{hh['pct']:.0f}% 低估，可加倍定投")
        if hh['trend'] < 50:
            warns.append('📉 趋势分偏低')
        if hh['mom20'] < -5:
            warns.append('📉 20日动量转弱')
        if hh['dd'] < -20:
            warns.append('⚠️ 深度回撤')
        if not warns:
            warns.append('✅ 状态正常')
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in warns)
        # 健康度徽章
        hc = hh['health']
        hp = ('#c92a2a' if hc >= 65 else ('#ba7517' if hc >= 40 else '#3b6d11'))
        hb = ('#fff0f0' if hc >= 65 else ('#fff9e6' if hc >= 40 else '#eaf3de'))
        pe_txt = f"{hh['pe']:.1f}" if hh['pe'] else '—'
        hold_rows += f'''<tr>
          <td style="text-align:left"><b>{h['fund']}</b><br><span style="color:#868e96;font-size:11px">{h['code']}</span></td>
          <td><span style="background:#edf2ff;color:#364fc7;padding:2px 8px;border-radius:8px;font-weight:700">{f.index_slug}</span></td>
          <td>¥{h['amt']:,.2f}</td>
          <td class="{'up' if hh['mom20'] > 0 else 'down'}">{hh['mom20']:+.1f}%</td>
          <td>{f"{hh['pct']:.0f}%" if hh['pct'] is not None else '—'}</td>
          <td>{pe_txt}</td>
          <td><span style="background:{hb};color:{hp};padding:2px 8px;border-radius:8px;font-weight:700">{hc:.0f}</span></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''

    # 全景表（8 指数，健康度降序）
    panorama = []
    for sl in all_slugs:
        hh = health_map.get(sl)
        if not hh:
            continue
        panorama.append(hh)
    panorama.sort(key=lambda x: -x['health'])
    pano_rows = ''
    for i, hh in enumerate(panorama, 1):
        hc = hh['health']
        hp = ('#c92a2a' if hc >= 65 else ('#ba7517' if hc >= 40 else '#3b6d11'))
        hb = ('#fff0f0' if hc >= 65 else ('#fff9e6' if hc >= 40 else '#eaf3de'))
        flow_txt = f"{hh['flow']:+.0f}%" if hh['flow'] is not None else '—'
        pano_rows += f'''<tr>
          <td>{i}</td>
          <td style="text-align:left"><b>{slug_names.get(hh['slug'], hh['slug'])}</b></td>
          <td>{hh['date']}</td>
          <td class="{'up' if hh['mom20'] > 0 else 'down'}">{hh['mom20']:+.1f}%</td>
          <td>{f"{hh['pct']:.0f}%" if hh['pct'] is not None else '—'}</td>
          <td>{hh['dd']:+.1f}%</td>
          <td>{flow_txt}</td>
          <td><span style="background:{hb};color:{hp};padding:2px 8px;border-radius:8px;font-weight:700">{hc:.0f}</span></td>
        </tr>'''

    # 低估 / 高估方向
    low_list = [hh for hh in panorama if hh['pct'] is not None and hh['pct'] < CHEAP]
    high_list = [hh for hh in panorama if hh['pct'] is not None and hh['pct'] > EXPENSIVE]
    low_rows = ''.join(
        f'<tr><td><b>{slug_names.get(hh["slug"], hh["slug"])}</b></td><td class="down">{hh["pct"]:.0f}%</td>'
        f'<td>{hh["dd"]:+.1f}%</td><td class="{"up" if hh["mom20"]>0 else "down"}">{hh["mom20"]:+.1f}%</td></tr>'
        for hh in low_list)
    high_rows = ''.join(
        f'<tr><td><b>{slug_names.get(hh["slug"], hh["slug"])}</b></td><td class="up">{hh["pct"]:.0f}%</td>'
        f'<td>{hh["dd"]:+.1f}%</td><td class="{"up" if hh["mom20"]>0 else "down"}">{hh["mom20"]:+.1f}%</td></tr>'
        for hh in high_list)

    # 定投分配（复用 dca）
    try:
        dec = build_dca_decision()
        dca_rows = ''
        for g in dec['groups']:
            for it in g['items']:
                zone = it.get('zone_label', '—')
                dca_rows += f'''<tr>
                  <td style="text-align:left">{it['name']}</td><td>{it['code']}</td>
                  <td>{it['tracking']}</td><td>¥{it['amount']:.0f}</td>
                  <td>{it.get('percentile', '—') if it.get('percentile') is not None else '—'}%</td>
                  <td>{zone}</td></tr>'''
        dca_note = '定投金额 = 预算 × 分位倍数（<30% 1.5倍 / 30-70% 1.0倍 / >70% 0.5倍）；美股固定金额。'
    except Exception:
        dca_rows = '<tr><td colspan="6">定投分配计算失败</td></tr>'
        dca_note = ''

    market_date = max((hh['date'] for hh in panorama), default='—')
    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    n_low = len(low_list)
    n_high = len(high_list)
    # 报告文件名按数据日期命名（20260810.html），目录本身已区分指数/行业
    fname = market_date.replace('-', '') if market_date and market_date != '—' \
        else datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>宽基指数报告</title>
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
<h1>宽基指数报告</h1>
<div class="sub">数据日期 {market_date} · 生成时间 {gen_time} · 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">持仓指数基金</div><div class="v">{len(holdings)} 只</div><div class="note">portfolio.db 推导</div></div>
  <div class="kpi"><div class="k">持仓总金额</div><div class="v">¥{hold_amt:,.0f}</div><div class="note">买入-卖出累计</div></div>
  <div class="kpi"><div class="k">低估方向</div><div class="v">{n_low} 个</div><div class="note">分位&lt;30%</div></div>
  <div class="kpi"><div class="k">高估方向</div><div class="v">{n_high} 个</div><div class="note">分位&gt;70%</div></div>
  <div class="kpi"><div class="k">覆盖指数</div><div class="v">{len(panorama)} 个</div><div class="note">A股6 + 美股2</div></div>
</div>

<div class="card"><h2>📋 当前持仓指数基金健康度分析</h2>
<p class="note">健康度分 = 分位便宜度(35) + 趋势(25) + 回撤(15) + 20日动量(15) + 资金流(10)，满分 100。
分位越低越健康（定投性价比高）；≥65 健康 / 40-65 关注 / &lt;40 谨慎。分位 &gt;70% 高估减投、&lt;30% 低估加投。</p>
<table><thead><tr><th>持仓基金</th><th>指数</th><th>持仓金额</th><th>20日动量</th><th>价格分位</th><th>PE(TTM)</th><th>健康度</th><th>预警</th></tr></thead>
<tbody>{hold_rows}</tbody></table>
</div>

<div class="card"><h2>🗂️ 宽基指数全景（{len(panorama)} 个，按健康度降序）</h2>
<table><thead><tr><th>#</th><th>指数</th><th>数据日期</th><th>20日动量</th><th>价格分位</th><th>距高点回撤</th><th>资金流</th><th>健康度</th></tr></thead>
<tbody>{pano_rows}</tbody></table>
</div>

<div class="card"><h2>📉 低估方向（{n_low}）· 📈 高估方向（{n_high}）</h2>
<table><thead><tr><th style="width:50%">📉 低估（分位&lt;30%，可加倍定投）</th><th style="width:50%">📈 高估（分位&gt;70%，减半定投）</th></tr></thead>
<tbody><tr><td style="vertical-align:top">
<table style="border:none"><tr><th>指数</th><th>分位</th><th>回撤</th><th>20日动量</th></tr>{low_rows or '<tr><td colspan="4">无</td></tr>'}</table>
</td><td style="vertical-align:top">
<table style="border:none"><tr><th>指数</th><th>分位</th><th>回撤</th><th>20日动量</th></tr>{high_rows or '<tr><td colspan="4">无</td></tr>'}</table>
</td></tr></tbody></table>
</div>

<div class="card"><h2>💰 当月定投分配建议</h2>
<p class="note">{dca_note}</p>
<table><thead><tr><th>基金</th><th>代码</th><th>跟踪指数</th><th>本月定投</th><th>分位</th><th>区间</th></tr></thead>
<tbody>{dca_rows}</tbody></table>
</div>

<div class="disclaimer">宽基指数为长期定投资产：战略比例不变，便宜多买、贵时少买（分位&lt;30% ×1.5、30-70% ×1.0、&gt;70% ×0.5），不择时。本报告由 Code/index_report.py 生成，数据来自腾讯/乐咕乐股行情。</div>
</div></body></html>'''
    return html, out_html


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='数据过旧时自动刷新（联网）')
    args = ap.parse_args()
    if args.refresh:
        try:
            from dca import refresh_data
            print('检查/刷新指数数据...')
            refresh_data()
        except Exception as e:
            print(f'  [warn] 数据刷新失败: {e}')
    html = build_html()
    out_html = html[1] if isinstance(html, tuple) else None
    html = html[0] if isinstance(html, tuple) else html
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'宽基指数报告已生成: {out_html}')


if __name__ == '__main__':
    main()
