# -*- coding: utf-8 -*-
"""
持仓基金分析报告（portfolio_report.py）
=======================================
分析 portfolio.db 中**全部持仓基金**，按三类（指数/红利/行业）分组，
用 fund_data 拉取的场外净值 + metrics 三套评分，输出每类的决策建议：
  - 指数：定投买入倍数（×1.5/×1.0/×0.5，基于 PE/价格分位）
  - 红利：买入区 / 卖出区（低吸高抛，均值回归）
  - 行业：持有 / 关注 / 减仓 / 离场（趋势波段，卖出为主；被动+主动已合并）

数据流：portfolio.db（持仓）→ fund_data 同步 + 拉净值 + 评分 → 本报告渲染

用法：
  python portfolio_report.py            # 同步持仓 + 增量拉净值 + 生成报告
  python run.py --index                 # 统一入口
输出：PortfolioReport/YYYYMMDD.html
"""
import os, sys, sqlite3, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))

import fund_data as fd

OUT_DIR = os.path.join(BASE, '..', 'PortfolioReport')
CATS = ['指数', '红利', '行业']
CAT_TITLES = {
    '指数': '📊 指数持仓（定投：分位 → 买入倍数）',
    '红利': '🧧 红利持仓（低吸高抛：分位 + 股息率安全垫）',
    '行业': '📈 行业持仓（被动+主动合并：趋势波段 · 卖出为主）',
}
CAT_NOTES = {
    '指数': '定投倍数 = PE 估值分位（<30% ×1.5 / 30-70% ×1.0 / >70% ×0.5），无 PE 时用价格分位兜底；分数高=现在适合多投。',
    '红利': '低分位（<30%）+ 止跌确认 = 买入区；高分位（>70%）+ 滞涨确认 = 卖出区；中间持有。股息率利差是安全垫（暂未接入，中性处理）。',
    '行业': '趋势驱动：20日动量 + MACD + 资金流（净值场景资金流中性）。信号转弱/死叉即提示离场，不恋战。',
}


def cash_implied():
    """余额宝可用余额（转入-已投基金），复用 portfolio_app 逻辑"""
    try:
        import portfolio_app as pa
        return pa.get_summary().get('cash_implied')
    except Exception:
        return None


def fmt_pct(v, suffix='%'):
    if isinstance(v, str) or v is None:
        return '—'
    return f'{v:+.1f}{suffix}'


def _score_style(sc):
    """综合分 → (文字色, 背景色)"""
    if sc is None:
        return '#adb5bd', '#f8f9fa'
    if sc >= 65:
        return '#c92a2a', '#fff0f0'
    if sc >= 40:
        return '#ba7517', '#fff9e6'
    return '#3b6d11', '#eaf3de'


def _rows_html(rows):
    """持仓行 HTML（fund_data.analyze_data 输出）：基金 | 金额 | 20日动量 | 分位 | 综合分 | 决策 | 预警"""
    html = ''
    for r in rows:
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in r['warnings'])
        pct_txt = f"{r['pct250']:.0%}" if r['pct250'] is not None else '—'
        sc = r['score']
        sp, sb = _score_style(sc)
        score_txt = f'{sc:.0f}' if sc is not None else '—'
        mom20 = r['mom20']
        mom20_txt = fmt_pct(mom20)
        mom20_cls = 'up' if isinstance(mom20, (int, float)) and mom20 > 0 else 'down'
        dec = r.get('decision') or '—'
        dec_cls = 'up' if '买入' in dec or '加倍' in dec else ('down' if '卖出' in dec or '离场' in dec else '')
        html += f'''<tr>
          <td style="text-align:left"><b>{r['fund']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td>¥{r['amt']:,.2f}</td>
          <td class="{mom20_cls}">{mom20_txt}</td>
          <td>{pct_txt}</td>
          <td><b>{score_txt}</b></td>
          <td><b class="{dec_cls}">{dec}</b></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''
    return html


def build_html(rows=None, cash=None):
    if rows is None:
        rows = fd.analyze_data()
    if cash is None:
        cash = cash_implied()
    cat_rows = {c: [r for r in rows if r['category'] == c] for c in CATS}
    cat_total = {c: sum(r['amt'] for r in cat_rows[c]) for c in CATS}
    total = sum(cat_total.values()) + (cash or 0)

    # 三类卡片
    cards = ''
    for c in CATS:
        tbl = _rows_html(cat_rows[c])
        cards += f'''<div class="card"><h2>{CAT_TITLES[c]}</h2>
<p class="note">{CAT_NOTES[c]}</p>
<table><thead><tr><th>持仓基金</th><th>持仓金额</th><th>20日动量</th><th>历史分位</th><th>综合分</th><th>决策建议</th><th>预警</th></tr></thead>
<tbody>{tbl or '<tr><td colspan="7" style="color:#adb5bd">无该分类持仓</td></tr>'}</tbody></table>
</div>'''

    mkt_date = '—'
    try:
        conn = sqlite3.connect(fd.FUND_DB)
        mkt_date = conn.execute('SELECT MAX(date) FROM nav').fetchone()[0] or '—'
        conn.close()
    except Exception:
        pass
    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fname = datetime.datetime.now().strftime('%Y%m%d')
    out_html = os.path.join(OUT_DIR, f'{fname}.html')
    if os.path.exists(out_html):
        out_html = os.path.join(OUT_DIR, f"{fname}_{datetime.datetime.now().strftime('%H%M%S')}.html")

    kpi = ''
    for c in CATS:
        kpi += f'<div class="kpi"><div class="k">{c}</div><div class="v">¥{cat_total[c]:,.0f}</div><div class="note">{len(cat_rows[c])} 只</div></div>'
    kpi += f'<div class="kpi"><div class="k">余额宝</div><div class="v">¥{cash or 0:,.0f}</div><div class="note">可用现金</div></div>'
    kpi += f'<div class="kpi"><div class="k">持仓总资产</div><div class="v">¥{total:,.0f}</div><div class="note">含现金</div></div>'

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
<div class="sub">净值日期 {mkt_date} · 生成时间 {gen_time} · 三类持仓分组（指数/红利/行业）· 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
{kpi}
</div>

{cards}

<div class="card"><h2>💰 资金池</h2>
<table><thead><tr><th>账户</th><th>可用余额</th><th>说明</th></tr></thead>
<tbody><tr><td>余额宝（ZFB）</td><td class="up">¥{cash or 0:,.2f}</td><td style="text-align:left;color:#5b6472">转入累计 - 已投基金（推算口径，与持仓流水管理一致）</td></tr></tbody></table>
</div>

<div class="disclaimer">本报告由 Code/portfolio_report.py 生成：持仓来自 portfolio.db，行情为场外基金净值（天天基金），信号为纯价格统计（动量/分位/MACD）+ 指数 PE 估值分位。三类评分策略不同：指数=定投倍数、红利=低吸高抛、行业=趋势卖出为主（被动+主动已合并）。不构成投资建议。</div>
</div></body></html>'''
    return html, out_html


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-refresh', action='store_true', help='跳过净值拉取（只读缓存）')
    args = ap.parse_args()

    print('== 1/3 同步持仓 ==')
    try:
        pos = fd.sync_holdings()
        print(f'当前持仓 {len(pos)} 只')
    except Exception as e:
        print(f'  [warn] 持仓同步失败: {e}')

    print('== 2/3 增量拉取净值 ==')
    if args.no_refresh:
        print('  --no-refresh：跳过拉取')
    else:
        try:
            n = fd.ensure_updated()
            print(f'  新增 {n} 条净值')
        except Exception as e:
            print(f'  [warn] 净值更新失败: {e}')

    print('== 3/3 生成报告 ==')
    rows = fd.analyze_data()
    html, out_html = build_html(rows)
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    n_warn = sum(1 for r in rows if any('⚠️' in w or '🟠' in w for w in r['warnings']))
    n_insuff = sum(1 for r in rows if '数据不足' in ' '.join(r['warnings']))
    print(f'持仓基金分析报告已生成: {out_html} | 预警 {n_warn} | 数据不足 {n_insuff}')


if __name__ == '__main__':
    main()
