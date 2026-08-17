# -*- coding: utf-8 -*-
"""
板块分析报告（plate_report.py）
===============================
用东方财富官方板块体系取代自建关键词分组（signal_lib）：

  - 行业板块（约 496 个）：半导体/通信设备/医疗服务等，官方细分行业
  - 概念板块（约 504 个）：高带宽内存/CPO/AI算力/机器人等主题

每个板块的指数 K 线计算：5/20/60 日动量、250 日分位、MACD、MA60、资金流、综合分
（复用 lib/metrics._calc_index_metrics 指标引擎，数据源换成官方板块指数）。

报告内容：
  1. 行业板块全景：按综合分排序（含动量/分位/资金流/多头状态）
  2. 概念板块雷达：AI/半导体/新能源等主题，按动量+资金流排序
  3. 低估方向：250 日分位 < 30% 的板块（均值回归参考）
  4. 强势方向：综合分 ≥65 且动量 MACD 双多（趋势参考）
  5. 板块涨跌分布：当日涨跌幅排行（Top/Bottom）

数据源：
  - data/plate.db：板块清单 + 板块指数 K 线（东财官方，首次拉取后增量更新）

用法：
  python plate_report.py              # 生成报告（数据过旧自动增量更新）
输出：PlateReport/YYYYMMDD.html（按数据日期命名）
"""
import os, sys, sqlite3, datetime, time
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))

import plate_data as pd_  # noqa: E402
from metrics import _calc_index_metrics  # noqa: E402 复用指标引擎（lib/）

OUT_DIR = os.path.join(BASE, '..', 'PlateReport')
DB = os.path.join(BASE, 'data', 'plate.db')

BUY_PCT = 0.3
HIGH_PCT = 0.7
STRONG_SCORE = 65


def load_plates_with_kline(plate_type):
    """读某类板块清单 + 每板块 K 线，返回 [metrics_dict, ...]（复用指标引擎）。
    无 K 线时降级为实时行情模式（zdf 排序 + 基础字段）。"""
    store = pd_.PlateStore(DB)
    plates = store.list_plates(plate_type)
    out = []
    for p in plates:
        df = store.read_kline(p['code'])
        if len(df) < 65:
            # 降级：只有实时行情
            out.append({'theme': p['name'], 'code': p['code'], 'zdf': p['zdf'],
                        'mf': p['mf'], 'mom5': None, 'mom20': None, 'mom60': None,
                        'pct250': None, 'score': 0.0, 'macd_bull': False,
                        'macd_weakening': False, 'date': ''})
            continue
        s = df['close'].astype(float).reset_index(drop=True)
        o = df['open'].astype(float).reset_index(drop=True)
        v = df['volume'].astype(float).reset_index(drop=True)
        m = _calc_index_metrics(s, o, v, p['name'])
        m['code'] = p['code']
        m['date'] = df['date'].iloc[-1]
        m['zdf'] = p['zdf']          # 当日涨跌幅（实时快照）
        m['mf'] = p['mf']            # 主力净流入（实时快照）
        out.append(m)
    out.sort(key=lambda x: -x['score'])
    return out


def _mom_cell(v, fmt='{v:+.1f}%'):
    """动量单元格：None 显示 '—'，否则按格式"""
    if v is None:
        return '<td style="color:#adb5bd">—</td>'
    cls = 'up' if v > 0 else 'down'
    return f'<td class="{cls}">{fmt.format(v=v)}</td>'


def plate_rows_html(rows, cols=None, limit=40):
    """板块表格行 HTML（综合分降序已排）"""
    if not rows:
        return '<tr><td colspan="8" style="color:#adb5bd">无数据</td></tr>'
    html = ''
    for i, r in enumerate(rows[:limit], 1):
        sc = r['score']
        sp = ('#c92a2a' if sc >= 65 else ('#ba7517' if sc >= 35 else '#3b6d11'))
        sb = ('#fff0f0' if sc >= 65 else ('#fff9e6' if sc >= 35 else '#eaf3de'))
        pct_txt = f"{r['pct250']:.0%}" if r['pct250'] is not None else '—'
        mf_txt = f"{r['mf']/1e8:+.1f}亿" if r.get('mf') else '—'
        zdf_txt = f"{r['zdf']:+.1f}%" if r.get('zdf') is not None else '—'
        bull = '✅' if r['macd_bull'] else '❌'
        weak = '⚠️' if r['macd_weakening'] else ''
        html += f'''<tr>
          <td>{i}</td>
          <td style="text-align:left"><b>{r['theme']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td>{zdf_txt}</td>
          {_mom_cell(r.get('mom5'))}
          {_mom_cell(r.get('mom20'))}
          {_mom_cell(r.get('mom60'))}
          <td>{pct_txt}</td>
          <td>{mf_txt}</td>
          <td><span style="background:{sb};color:{sp};padding:2px 8px;border-radius:8px;font-weight:700">{sc:.0f}</span></td>
          <td>{bull}{weak}</td>
        </tr>'''
    return html


def build_html():
    print('读取板块数据...')
    store = pd_.PlateStore(DB)
    n_concept = len(store.list_plates('concept'))
    n_industry = len(store.list_plates('industry'))
    print(f'  板块清单: 概念 {n_concept} / 行业 {n_industry}')

    ind_rows = load_plates_with_kline('industry')
    con_rows = load_plates_with_kline('concept')
    print(f'  有效K线: 行业 {len(ind_rows)} / 概念 {len(con_rows)}')

    # 低估 / 强势（概念板块视角）
    low_list = [r for r in con_rows if r['pct250'] is not None and r['pct250'] < BUY_PCT]
    low_list.sort(key=lambda x: x['pct250'])
    strong_list = [r for r in con_rows if r['score'] >= STRONG_SCORE
                   and (r['mom20'] or 0) > 0 and r['macd_bull']]
    strong_list.sort(key=lambda x: -x['score'])

    ind_html = plate_rows_html(ind_rows, limit=60)
    con_html = plate_rows_html(con_rows, limit=60)
    low_html = ''
    for r in low_list[:20]:
        pct_txt = f"{r['pct250']:.0%}" if r['pct250'] is not None else '—'
        low_html += f'''<tr><td style="text-align:left"><b>{r['theme']}</b></td>
          <td>{r['code']}</td><td class="down">{pct_txt}</td>
          <td class="{'up' if (r['mom20'] or 0)>0 else 'down'}">{r['mom20']:+.1f}%</td>
          <td>{r['score']:.0f}</td></tr>'''
    strong_html = ''
    for r in strong_list[:20]:
        strong_html += f'''<tr><td style="text-align:left"><b>{r['theme']}</b></td>
          <td>{r['code']}</td><td class="up">{r['score']:.0f}</td>
          <td class="up">{r['mom20']:+.1f}%</td>
          <td class="up">{r['mom60']:+.1f}%</td></tr>'''

    # 当日涨跌排行（概念板块实时快照）
    by_zdf = sorted(con_rows, key=lambda x: -(x.get('zdf') or -999))
    top_zdf = ''.join(
        f'<tr><td style="text-align:left">{r["theme"]}</td>'
        f'<td class="up">{r["zdf"]:+.1f}%</td>'
        f'{_mom_cell(r.get("mom20"))}</tr>'
        for r in by_zdf[:10] if r.get('zdf') is not None)
    bot_zdf = ''.join(
        f'<tr><td style="text-align:left">{r["theme"]}</td>'
        f'<td class="down">{r["zdf"]:+.1f}%</td>'
        f'{_mom_cell(r.get("mom20"))}</tr>'
        for r in by_zdf[-10:] if r.get('zdf') is not None)

    mkt_date = con_rows[0]['date'] if con_rows else '—'
    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fname = datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')
    if os.path.exists(out_html):
        out_html = os.path.join(OUT_DIR, f"{fname}_{datetime.datetime.now().strftime('%H%M%S')}.html")

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>板块分析报告</title>
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
<h1>板块分析报告</h1>
<div class="sub">数据日期 {mkt_date} · 生成时间 {gen_time} · 东方财富官方板块体系（行业+概念）· 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">行业板块</div><div class="v">{len(ind_rows)}</div><div class="note">官方细分行业</div></div>
  <div class="kpi"><div class="k">概念板块</div><div class="v">{len(con_rows)}</div><div class="note">主题热点</div></div>
  <div class="kpi"><div class="k">低估方向</div><div class="v">{len(low_list)}</div><div class="note">分位&lt;30%</div></div>
  <div class="kpi"><div class="k">强势方向</div><div class="v">{len(strong_list)}</div><div class="note">综合分≥65 双多</div></div>
</div>

<div class="card"><h2>📈 当日概念板块涨跌 Top / Bottom（实时快照）</h2>
<table><thead><tr><th style="width:50%">涨幅领先</th><th style="width:50%">跌幅居前</th></tr></thead>
<tbody><tr><td style="vertical-align:top"><table style="border:none"><tr><th>板块</th><th>当日</th><th>20日</th></tr>{top_zdf}</table></td>
<td style="vertical-align:top"><table style="border:none"><tr><th>板块</th><th>当日</th><th>20日</th></tr>{bot_zdf}</table></td></tr></tbody></table>
</div>

<div class="card"><h2>📉 低估概念方向（250日分位 &lt;30%，均值回归参考）</h2>
<table><thead><tr><th>概念板块</th><th>代码</th><th>历史分位</th><th>20日动量</th><th>综合分</th></tr></thead>
<tbody>{low_html or '<tr><td colspan="5" style="color:#adb5bd">无</td></tr>'}</tbody></table>
</div>

<div class="card"><h2>📈 强势概念方向（综合分≥65 且动量MACD双多）</h2>
<table><thead><tr><th>概念板块</th><th>代码</th><th>评分</th><th>20日动量</th><th>60日动量</th></tr></thead>
<tbody>{strong_html or '<tr><td colspan="5" style="color:#adb5bd">当前无双多概念板块（市场偏弱）</td></tr>'}</tbody></table>
</div>

<div class="card"><h2>🗂️ 行业板块全景（{len(ind_rows)} 个，按综合分降序）</h2>
<p class="note">综合分 = 动量(5/20/60日) + MACD + MA60 + 历史分位 + 资金流，满分 100。数据来自东财官方行业板块指数。</p>
<table><thead><tr><th>#</th><th>行业板块</th><th>当日</th><th>5日</th><th>20日</th><th>60日</th><th>分位</th><th>主力资金</th><th>综合分</th><th>MACD</th></tr></thead>
<tbody>{ind_html}</tbody></table>
</div>

<div class="card"><h2>🗂️ 概念板块全景（{len(con_rows)} 个，按综合分降序）</h2>
<p class="note">概念板块聚焦主题热点（AI/半导体/新能源/机器人等），综合分口径同上。</p>
<table><thead><tr><th>#</th><th>概念板块</th><th>当日</th><th>5日</th><th>20日</th><th>60日</th><th>分位</th><th>主力资金</th><th>综合分</th><th>MACD</th></tr></thead>
<tbody>{con_html}</tbody></table>
</div>

<div class="disclaimer">板块分类来自东方财富官方（行业板块/概念板块），板块指数为等权指数；综合分基于历史统计，不预示未来。本报告仅做数据分析与参考，不构成买卖指令。</div>
</div></body></html>'''
    return html, out_html


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-refresh', action='store_true', help='跳过数据更新（直接用缓存）')
    ap.add_argument('--only-concept', action='store_true', help='只处理概念板块（跳过行业，快速出报告）')
    args = ap.parse_args()

    # 增量更新板块数据（失败不阻塞报告；东财可能限流，超时后跳过）
    if not args.no_refresh:
        try:
            store = pd_.PlateStore(DB)
            types = ['concept'] if args.only_concept else ['concept', 'industry']
            for t in types:
                if not store.list_plates(t):
                    print(f'首次拉取 {t} 板块清单...', flush=True)
                    plates = pd_.fetch_plate_list(t, max_pages=10)
                    if plates:
                        store.save_list(plates, t)
                        print(f'  {t}: {len(plates)} 个', flush=True)
                    else:
                        print(f'  {t}: 清单拉取失败（跳过）', flush=True)
                    time.sleep(3)
            print('增量更新板块 K 线（限速）...', flush=True)
            for t in types:
                upd, fail = pd_.refresh_all(t, store=store)
                print(f'  {t}: 更新 {len(upd)} 失败 {len(fail)}', flush=True)
                time.sleep(3)
        except Exception as e:
            print(f'  [warn] 板块数据更新失败: {e}', flush=True)

    html, out_html = build_html()
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'板块分析报告已生成: {out_html}', flush=True)


if __name__ == '__main__':
    main()
