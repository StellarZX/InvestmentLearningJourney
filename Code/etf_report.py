# -*- coding: utf-8 -*-
"""
ETF 联接入场机会报告（etf_report.py）
=====================================
基于底池（etf.db，成交额≥2亿 且 规模≥20亿的场内 ETF）计算指标引擎综合分，
发掘**场外 ETF 联接基金**的入场机会。

场外联接 T+1 特性约束（本报告的核心设计依据）：
  - 今日下单 → 明日确认，实际建仓成本是**明日收盘净值** → 无法抢日内反弹、无法止损当日生效
  - 因此只做中期趋势信号（5/20/60 日动量 + MACD + MA60），不追单日脉冲
  - 追高惩罚：条件满足但当日已涨 >3%（CHASE_PCT）的标的移入「等回踩」区，
    避免明日净值高位接盘

入场条件（稳健趋势型）：
  1. 综合分 ≥ 65（STRONG_SCORE）
  2. MACD 多头 且 站上 MA60（双确认）
  3. 非当日暴涨（当日涨幅 ≤ 3%）
  4. 近 5 日主力净流入 ≥ 0（资金不持续流出；数据不足时中性处理）

输出：EtfReport/YYYYMMDD.html
  1. 入场机会榜   —— 四条全满足，按综合分排序（联接可下单）
  2. 等回踩区     —— 唯独当日涨太猛（T+1 明天买就是接盘）
  3. 观察区       —— 综合分 ≥55 但缺确认/资金流出（趋势酝酿中）
  4. 低估方向     —— 250 日分位 <30%（逆向定投参考）
  5. 底池全景     —— 全部标的按综合分降序

用法：
  python etf_report.py              # 数据过旧自动增量更新后出报告
"""
import os, sys, datetime
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))

import etf_data as ed  # noqa: E402
from metrics import _calc_index_metrics  # noqa: E402 复用指标引擎

OUT_DIR = os.path.join(BASE, '..', 'EtfReport')

STRONG_SCORE = 65      # 入场综合分门槛（与板块报告一致）
WATCH_SCORE = 55       # 观察区门槛
CHASE_PCT = 3.0        # 当日涨幅超过此值 = 追高风险（T+1 场外特性）
LOW_PCT = 0.30         # 低估分位线


def load_pool_with_metrics():
    """读底池 + 每只 K 线/资金流算指标。返回 [metrics_dict,...] 按综合分降序。"""
    store = ed.EtfStore()
    out = []
    for e in store.list_pool():
        df = store.read_kline(e['code'])
        if len(df) < 65:
            continue    # K 线不足不算信号（新上市 ETF 自然沉淀后再进）
        s = df['close'].astype(float).reset_index(drop=True)
        o = df['open'].astype(float).reset_index(drop=True)
        v = df['volume'].astype(float).reset_index(drop=True)
        m = _calc_index_metrics(s, o, v, e['name'])
        m['code'] = e['code']
        m['date'] = df['date'].iloc[-1]
        m['zdf'] = e['zdf']
        m['amount'] = e['amount']
        m['mktcap'] = e['mktcap']
        # 主力资金流（本地逐日快照累积；不足 3 天不给 5 日值，中性处理）
        ff = store.read_fflow(e['code'])
        mfs = ff['mf'].astype(float).tolist() if not ff.empty else []
        m['mf_today'] = mfs[-1] if mfs else None
        m['mf5'] = sum(mfs[-5:]) if len(mfs) >= 3 else None
        m['mf20'] = sum(mfs[-20:]) if len(mfs) >= 10 else None
        out.append(m)
    out.sort(key=lambda x: -x['score'])
    return out


def classify(rows):
    """按稳健趋势策略分区：entry / chase / watch / rest
    资金流条件：近 5 日主力净流入 ≥0（缺数据中性）；当日价涨但主力净流出记背离提示。"""
    entry, chase, watch = [], [], []
    for r in rows:
        confirmed = r['macd_bull'] and r['above_ma60']
        hot_today = (r.get('zdf') is not None and r['zdf'] > CHASE_PCT)
        flow_bad = (r.get('mf5') is not None and r['mf5'] < 0)
        r['flow_bad'] = flow_bad
        r['diverge'] = bool((r.get('zdf') or 0) > 0 and (r.get('mf_today') is not None)
                            and r['mf_today'] < 0)
        if r['score'] >= STRONG_SCORE and confirmed:
            if hot_today:
                chase.append(r)
            elif flow_bad:
                watch.append(r)
            else:
                entry.append(r)
        elif r['score'] >= WATCH_SCORE:
            watch.append(r)
    return entry, chase, watch


# ---------- HTML 小件 ----------

def _mom_cell(v, fmt='{v:+.1f}%'):
    if v is None:
        return '<td style="color:#adb5bd">—</td>'
    cls = 'up' if v > 0 else 'down'
    return f'<td class="{cls}">{fmt.format(v=v)}</td>'


def _amt_txt(v):
    if v is None or v <= 0:
        return '<td style="color:#adb5bd">—</td>'
    return f'<td>{v / 1e8:.1f}亿</td>'


def _flow_cell(v):
    """主力净流入单元格：亿元，流入红/流出绿（东财配色习惯：红涨绿跌）"""
    if v is None:
        return '<td style="color:#adb5bd">—</td>'
    cls = 'up' if v > 0 else 'down'
    sign = '+' if v > 0 else ''
    return f'<td class="{cls}">{sign}{v / 1e8:.2f}亿</td>'


def _score_cell(sc):
    sp = '#c92a2a' if sc >= STRONG_SCORE else ('#ba7517' if sc >= WATCH_SCORE else '#3b6d11')
    sb = '#fff0f0' if sc >= STRONG_SCORE else ('#fff9e6' if sc >= WATCH_SCORE else '#eaf3de')
    return (f'<td><span style="background:{sb};color:{sp};'
            f'padding:2px 8px;border-radius:8px;font-weight:700">{sc:.0f}</span></td>')


def _rows_html(rows, limit=50, tip_col=None):
    """通用底池表格行：# / 名称代码 / 综合 / 当日 / 成交额 / 当日资金 / 5日资金 /
    5日 / 20日 / 60日 / 分位 / MACD / MA60 [/ 提示]"""
    span = 13 + (1 if tip_col else 0)
    if not rows:
        return f'<tr><td colspan="{span}" style="color:#adb5bd">当前无符合条件的标的</td></tr>'
    html = ''
    for i, r in enumerate(rows[:limit], 1):
        pct_txt = f"{r['pct250']:.0%}" if r.get('pct250') is not None else '—'
        zdf_txt = f"{r['zdf']:+.1f}%" if r.get('zdf') is not None else '—'
        bull = '✅' if r['macd_bull'] else '❌'
        weak = '⚠️' if r.get('macd_weakening') else ''
        ma60 = '✅' if r['above_ma60'] else '❌'
        tip = f'<td>{tip_col(r)}</td>' if tip_col else ''
        html += f'''<tr>
          <td>{i}</td>
          <td style="text-align:left"><b>{r['theme']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          {_score_cell(r['score'])}
          <td class="{'up' if (r.get('zdf') or 0) > 0 else 'down'}">{zdf_txt}</td>
          {_amt_txt(r.get('amount'))}
          {_flow_cell(r.get('mf_today'))}
          {_flow_cell(r.get('mf5'))}
          {_mom_cell(r.get('mom5'))}
          {_mom_cell(r.get('mom20'))}
          {_mom_cell(r.get('mom60'))}
          <td>{pct_txt}</td>
          <td>{bull}{weak}</td>
          <td>{ma60}</td>
          {tip}
        </tr>'''
    return html


_COLS_BASE = ('<th>#</th><th>ETF</th><th>综合分</th><th>当日</th><th>成交额</th>'
              '<th>当日资金</th><th>5日资金</th>'
              '<th>5日</th><th>20日</th><th>60日</th><th>250日分位</th><th>MACD</th><th>MA60</th>')
_COLS_TIP = _COLS_BASE + '<th>T+1 提示</th>'


def build_html():
    print('读取 ETF 底池数据...')
    rows = load_pool_with_metrics()
    print(f'  有效标的: {len(rows)} 只（K线≥65日）')
    if not rows:
        raise SystemExit('[err] 底池无有效数据，先运行 python Code/etf_data.py --sync')

    entry, chase, watch = classify(rows)
    low_list = [r for r in rows if r['pct250'] is not None and r['pct250'] < LOW_PCT]
    low_list.sort(key=lambda x: x['pct250'])

    # 底池合计当日主力净流入（市场情绪温度计）
    mf_sum = sum(r['mf_today'] for r in rows if r.get('mf_today') is not None)
    n_flow = sum(1 for r in rows if r.get('mf_today') is not None)
    flow_kpi = ''
    if n_flow:
        cls = 'up' if mf_sum > 0 else 'down'
        flow_kpi = (f'<div class="kpi"><div class="k">底池合计当日资金</div>'
                    f'<div class="v {cls}">{mf_sum/1e8:+.0f}亿</div>'
                    f'<div class="note">主力净流入，{n_flow} 只有数据</div></div>')

    def _tip_entry(r):
        if r.get('diverge'):
            return '<span style="color:#e8590c">资金背离（价涨主力流出），轻仓</span>'
        flow = '，5日资金流入' if (r.get('mf5') or 0) > 0 else ''
        return f'<span style="color:#0ca678">可下单{flow}</span>'

    def _tip_chase(r):
        base = f'当日 {r["zdf"]:+.1f}%，明日净值或高位，等回踩'
        if r.get('mf_today') is not None and r['mf_today'] < 0:
            base += '；且当日主力净流出'
        return f'<span style="color:#e8590c">{base}</span>'

    def _tip_watch(r):
        miss = []
        if not r['macd_bull']:
            miss.append('MACD 未多头')
        if not r['above_ma60']:
            miss.append('未站上MA60')
        if r['score'] < STRONG_SCORE:
            miss.append(f"评分{r['score']:.0f}<65")
        if r.get('flow_bad'):
            miss.append(f"5日主力净流出{(r['mf5'] or 0)/1e8:.1f}亿")
        return f'<span style="color:#868e96">{"；".join(miss)}</span>'

    entry_html = _rows_html(entry, limit=30, tip_col=_tip_entry)
    chase_html = _rows_html(chase, limit=20, tip_col=_tip_chase)
    watch_html = _rows_html(watch, limit=20, tip_col=_tip_watch)
    low_html = ''.join(
        f'''<tr><td style="text-align:left"><b>{r['theme']}</b></td><td>{r['code']}</td>
        <td class="down">{(str(round(r['pct250']*100))+'%') if r.get('pct250') is not None else '—'}</td>
        <td class="{'up' if (r.get('mom20') or 0) > 0 else 'down'}">{(r.get('mom20') or 0):+.1f}%</td>
        <td>{r['score']:.0f}</td></tr>'''
        for r in low_list[:10])
    all_html = _rows_html(rows, limit=200)

    mkt_date = rows[0]['date'] if rows else '—'
    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fname = datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>ETF 联接入场机会报告</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--line:#e3e6eb;--tx:#1c2333}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:-apple-system,"Microsoft YaHei",sans-serif;font-size:14px}}
header{{background:#fff;border-bottom:1px solid var(--line);padding:22px 0}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 20px}}
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
<h1>ETF 联接入场机会报告</h1>
<div class="sub">数据日期 {mkt_date} · 生成时间 {gen_time} · 底池 {len(rows)} 只（成交额≥2亿 且 规模≥20亿）· 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">入场机会</div><div class="v">{len(entry)}</div><div class="note">分≥65 双确认 非追高 资金不流出</div></div>
  <div class="kpi"><div class="k">等回踩</div><div class="v">{len(chase)}</div><div class="note">信号好但当日&gt;3%</div></div>
  <div class="kpi"><div class="k">观察区</div><div class="k">&nbsp;</div><div class="v">{len(watch)}</div><div class="note">分≥55 缺确认/资金流出</div></div>
  <div class="kpi"><div class="k">低估方向</div><div class="v">{len(low_list)}</div><div class="note">250日分位&lt;30%</div></div>
  {flow_kpi}
</div>

<div class="card"><h2>🎯 入场机会榜（稳健趋势：四条全满足，按综合分排序）</h2>
<p class="note"><b>场外联接 T+1 规则</b>：今日收盘价下单 → 明日确认份额，实际成本≈明日净值。因此只认中期趋势信号（动量+MACD+MA60），不做日内博弈；当日已大涨的标的自动移入「等回踩」区，避免明日高位接盘。<b>资金流条件</b>：近 5 日主力净流入合计 ≥0 才可入场——价格在涨但主力持续流出的标的进观察区（趋势缺乏资金支撑）。<b>操作建议</b>：榜单标的可在收盘前（14:45 后）确认信号仍在再下单；单一行业主题建议分批建仓。</p>
<table><thead><tr>{_COLS_TIP}</tr></thead><tbody>{entry_html}</tbody></table>
</div>

<div class="card"><h2>⏳ 等回踩区（信号成立但当日暴涨 &gt;{CHASE_PCT:.0f}%，T+1 追入风险大）</h2>
<p class="note">这些标的基本面/趋势信号都好，但今天涨幅过大——明天确认的净值大概率在短期高点。等 1-3 天缩量回踩（如回落至 5 日线附近）再入场更安全。</p>
<table><thead><tr>{_COLS_TIP}</tr></thead><tbody>{chase_html}</tbody></table>
</div>

<div class="card"><h2>👀 观察区（综合分 ≥{WATCH_SCORE:.0f} 但尚缺确认，趋势酝酿中）</h2>
<table><thead><tr>{_COLS_TIP}</tr></thead><tbody>{watch_html}</tbody></table>
</div>

<div class="card"><h2>📉 低估方向 Top 10（250 日分位 &lt;30%，逆向定投参考）</h2>
<table><thead><tr><th>ETF</th><th>代码</th><th>历史分位</th><th>20日动量</th><th>综合分</th></tr></thead>
<tbody>{low_html or '<tr><td colspan="5" style="color:#adb5bd">无</td></tr>'}</tbody></table>
</div>

<div class="card"><h2>🗂️ 底池全景（全部 {len(rows)} 只，按综合分降序）</h2>
<p class="note">底池 = 全市场 ETF 中最新成交额 ≥2 亿且总市值 ≥20 亿的标的（东财口径），覆盖宽基/行业/跨境/商品；综合分与板块报告同引擎（动量50 + MACD15 + MA60 15 + 低估10 + 资金流10）。K 线为腾讯前复权日线，成交额来自实时快照。<b>资金流说明</b>：当日/5日资金 = 东财主力净流入（超大单+大单），每日快照入本地库累积成历史；数据不足 3 天时显示 —（策略中性处理，不误伤新标的）。</p>
<table><thead><tr>{_COLS_BASE}</tr></thead><tbody>{all_html}</tbody></table>
</div>

<div class="disclaimer">底池筛选与评分为历史统计模型，不预示未来表现；场外联接基金存在 T+1 确认、申赎费率与跟踪偏差。本报告仅做数据分析与参考，不构成任何投资建议。</div>
</div></body></html>'''
    return html, out_html


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-refresh', action='store_true', help='跳过数据更新（直接用缓存）')
    args = ap.parse_args()

    if not args.no_refresh:
        try:
            store = ed.EtfStore()
            if not store.list_pool():
                print('首次同步 ETF 底池（快照 + 全部 K 线，约 2 分钟）...', flush=True)
                ed.sync_all()
            else:
                latest = max((store.kline_latest(e['code']) or '') for e in store.list_pool())
                today = datetime.date.today()
                try:
                    stale = (today - datetime.datetime.strptime(latest, '%Y-%m-%d').date()).days >= 1
                except ValueError:
                    stale = True
                if stale:
                    print('增量同步 ETF 底池数据...', flush=True)
                    spot = ed.fetch_etf_spot()
                    if spot:
                        store.save_pool(ed.filter_pool(spot))
                    ed.sync_klines(store=store)
                    ed.sync_flow_snapshot(store=store)
                else:
                    print('ETF 数据已是最新，补一次资金流快照后出报告', flush=True)
                    ed.sync_flow_snapshot(store=store)
        except Exception as e:
            print(f'  [warn] ETF 数据更新失败: {e}', flush=True)

    html, out_html = build_html()
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'ETF 报告已生成: {out_html}', flush=True)


if __name__ == '__main__':
    main()
