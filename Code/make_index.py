# -*- coding: utf-8 -*-
"""
生成 GitHub Pages 导航首页（make_index.py）
============================================
把 README.md 内容转成导航页 index.html（GitHub Pages 首页）：
  - 扫描 PlateReport/、PortfolioReport/ 报告目录（YYYYMMDD.html，最新在前）
  - 扫描 Foundations/ 课程目录（6 部分 40 课，紧凑导航）
  - 持仓明细不展示（在持仓基金分析报告中查看），历史报告列表放页尾

用法：
  python make_index.py            # 生成根目录 index.html（报告/课程更新后重新运行）

说明：README.md 已精简为极简说明；index.html 是 Pages 导航首页。
"""
import os, sys, re, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, '..')
sys.path.insert(0, BASE)


# ---------- 数据扫描 ----------

def scan_reports(sub):
    """扫描报告目录，返回 [(日期8位, 文件名), ...] 按日期降序"""
    d = os.path.join(ROOT, sub)
    out = []
    if os.path.isdir(d):
        for f in os.listdir(d):
            if re.fullmatch(r'\d{8}\.html', f):
                out.append((f[:8], f))
    out.sort(reverse=True)
    return out


def fmt_date(d8):
    return f'{d8[:4]}-{d8[4:6]}-{d8[6:]}'


PARTS = [
    ('Part_I_Foundations', '基础概念（01–07）'),
    ('Part_II_Understanding_Financial_Markets', '金融市场（08–14）'),
    ('Part_III_Core_Investment_Principles', '核心投资原则（15–21）'),
    ('Part_IV_ETF_Investing', 'ETF 投资（22–28）'),
    ('Part_V_Understanding_the_Economy', '经济理解（29–34）'),
    ('Part_VI_Investment_Psychology', '投资心理（35–40）'),
]


def scan_lessons():
    """扫描 Foundations 课程，返回 [{dir, title, lessons:[(编号, 文件名)], zh_dir}]"""
    out = []
    for dirname, title in PARTS:
        d = os.path.join(ROOT, 'Foundations', dirname)
        lessons = []
        if os.path.isdir(d):
            for f in os.listdir(d):
                m = re.fullmatch(r'Lesson(\d{2})\.md', f)
                if m:
                    lessons.append((int(m.group(1)), f))
            lessons.sort()
        out.append({'dir': dirname, 'title': title, 'lessons': lessons})
    return out


# ---------- HTML 片段 ----------

def hist_tree(items, sub):
    """历史报告：年 > 月 > 日 三级折叠菜单（原生 details，年份默认展开）"""
    if not items:
        return '<p class="dim">暂无</p>'
    years = {}
    for d8, f in items:
        y, m = d8[:4], d8[4:6]
        years.setdefault(y, {}).setdefault(m, []).append((d8, f))
    out = []
    for y in sorted(years, reverse=True):
        months = years[y]
        n_y = sum(len(v) for v in months.values())
        ms = []
        for m in sorted(months, reverse=True):
            files = months[m]
            links = ''.join(
                f'<a class="hist-link" href="{sub}/{f}">{d8[6:]}日</a>' for d8, f in files)
            ms.append(f'<details class="m"><summary>{int(m)} 月（{len(files)} 份）</summary>'
                      f'<div class="d">{links}</div></details>')
        out.append(f'<details class="y" open><summary>{y} 年（{n_y} 份）</summary>'
                   f'{"".join(ms)}</details>')
    return ''.join(out)


def lessons_html(lessons):
    """课程导航：单卡片内紧凑列表（每部分一行，仅英文原文链接）"""
    lines = []
    for p in lessons:
        if not p['lessons']:
            continue
        base = f'Foundations/{p["dir"]}'
        links = ''.join(
            f'<a class="lesson" href="{base}/Lesson{n:02d}.md">第{n:02d}课</a>'
            for n, f in p['lessons'])
        lines.append(f'<p class="lrow">{p["title"]}：{links}</p>')
    return ''.join(lines)


# ---------- 主生成 ----------

def build_html():
    plate = scan_reports('PlateReport')
    pf = scan_reports('PortfolioReport')
    lessons = scan_lessons()
    gen = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    plate_latest = f'PlateReport/{plate[0][1]}' if plate else ''
    pf_latest = f'PortfolioReport/{pf[0][1]}' if pf else ''
    plate_date = fmt_date(plate[0][0]) if plate else '—'
    pf_date = fmt_date(pf[0][0]) if pf else '—'

    # 最新报告大卡片
    latest_cards = ''
    if pf_latest:
        latest_cards += f'''<a class="bigcard" href="{pf_latest}">
<div class="bc-emoji">📊</div><div><b>持仓基金分析报告</b>
<p>数据日期 {pf_date} · 指数定投倍数 / 红利买入区 / 行业持有关注</p></div>
<span class="arrow">→</span></a>'''
    if plate_latest:
        latest_cards += f'''<a class="bigcard" href="{plate_latest}">
<div class="bc-emoji">📈</div><div><b>板块分析报告</b>
<p>数据日期 {plate_date} · 行业 90 + 概念 375 · 热度榜/低估/强势</p></div>
<span class="arrow">→</span></a>'''

    return f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>投资方法与记录</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--line:#e3e6eb;--tx:#1c2333;--accent:#1f6feb}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:-apple-system,"Microsoft YaHei",sans-serif;font-size:14px;line-height:1.65}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
header{{background:#fff;border-bottom:1px solid var(--line);padding:26px 0}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 20px}}
header h1{{font-size:24px}}
header .sub{{opacity:.8;font-size:13px;margin-top:6px}}
.card{{background:var(--card);border-radius:14px;padding:20px 22px;margin:18px 0;border:1px solid var(--line)}}
.card h2{{font-size:17px;margin-bottom:12px}}
.note{{font-size:13px;color:#5b6472;line-height:1.7;margin-top:10px}}
.dim{{color:#adb5bd}}
.bigcards{{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0}}
.bigcard{{flex:1;min-width:280px;background:#fff;border:1px solid var(--line);border-radius:14px;
  padding:18px 20px;display:flex;align-items:center;gap:14px;color:var(--tx)}}
.bigcard:hover{{border-color:var(--accent);text-decoration:none;transform:translateY(-1px)}}
.bigcard .bc-emoji{{font-size:34px}}
.bigcard b{{font-size:16px}}
.bigcard p{{font-size:12px;color:#5b6472;margin-top:4px}}
.bigcard .arrow{{margin-left:auto;font-size:20px;color:#adb5bd}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f1f3f5;padding:8px;text-align:left;border-bottom:2px solid var(--line)}}
td{{padding:7px 8px;text-align:left;border-bottom:1px solid #f1f3f5}}
ul.hist{{list-style:none;display:flex;flex-wrap:wrap;gap:6px 18px}}
ul.hist li a{{font-size:13px}}
details.y{{margin:2px 0}}
details.y > summary{{font-weight:700;cursor:pointer;padding:5px 0;font-size:13.5px}}
details.m{{margin:2px 0 2px 14px}}
details.m > summary{{cursor:pointer;font-size:13px;color:#5b6472;padding:4px 0;font-weight:600}}
.d{{display:flex;flex-wrap:wrap;gap:6px 14px;margin:2px 0 8px 14px}}
.hist-link{{font-size:13px}}
.lrow{{margin:9px 0;font-size:13px;color:#5b6472;line-height:2.1}}
a.lesson{{border:1px solid var(--line);border-radius:7px;padding:2px 8px;font-size:12px;color:var(--tx);background:#f8f9fa;margin-left:4px;white-space:nowrap}}
a.lesson:hover{{border-color:var(--accent);text-decoration:none}}
code{{background:#f1f3f5;border-radius:5px;padding:1px 6px;font-size:12px}}
.disclaimer{{font-size:12px;color:#868e96;margin:16px 0 30px;padding:12px;background:#f8f9fa;border-radius:10px}}
.dup{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:760px){{.dup{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div class="wrap">
<h1>💰 投资方法与记录</h1>
<div class="sub">个人投资方法、执行记录与复盘 · 导航首页自动生成于 {gen} · 数据仅供参考，不构成投资建议</div>
</div></header>
<div class="wrap">

<div class="bigcards">{latest_cards or '<div class="card" style="flex:1">暂无报告</div>'}</div>

<div class="card"><h2>🧭 投资体系</h2>
<table><thead><tr><th>部分</th><th>方式</th><th>约束</th><th>决策</th></tr></thead>
<tbody>
<tr><td>指数（长期资产）</td><td>每月定投</td><td>战略比例不变</td><td>定投倍数 ×1.5 / ×1.0 / ×0.5</td></tr>
<tr><td>红利（防守资产）</td><td>定投 + 波段</td><td>单只 ≤¥5,000</td><td>买入区 / 持有 / 卖出区</td></tr>
<tr><td>行业基金（增强）</td><td>不固定投入</td><td>单只 ≤¥5,000</td><td>持有 / 关注 / 减仓 / 离场</td></tr>
<tr><td>现金池（余额宝）</td><td>闲钱暂存</td><td>可用现金</td><td>—</td></tr>
</tbody></table>
<p class="note">指数 = 逆向定投（分位低多买）；红利 = 均值回归波段（低吸高抛）；行业 = 趋势波段（卖出为主，动量转负/死叉离场）。</p>
</div>

<div class="card"><h2>📚 基础课程（40 课）</h2>{lessons_html(lessons)}</div>

<div class="card"><h2>🚀 使用（本地）</h2>
<p class="note">统一入口 <code>run.py</code>（根目录）：<br>
· <code>python run.py --index</code> → 持仓基金分析报告（PortfolioReport/YYYYMMDD.html）<br>
· <code>python run.py --plate</code> → 板块分析报告（PlateReport/YYYYMMDD.html，同花顺官方行业 90 + 概念 375）<br>
· <code>python run.py --portfolio</code> → 持仓流水管理（浏览器 http://127.0.0.1:8051）<br>
· 报告/课程更新后 <code>python run.py --nav</code> 刷新本导航页（--index/--plate 已自动刷新）</p>
</div>

<div class="card"><h2>📖 资料</h2>
<p class="note">· <a href="Glossary/指数基金投资指南.epub">指数基金投资指南.epub</a><br>
· 旧版本备份在 backup_old/（废弃模块，不入库）。</p>
</div>

<div class="dup">
  <div class="card"><h2>📊 持仓基金分析报告（历史）</h2>{hist_tree(pf, 'PortfolioReport')}</div>
  <div class="card"><h2>📈 板块分析报告（历史）</h2>{hist_tree(plate, 'PlateReport')}</div>
</div>

<div class="disclaimer">本仓库内容为个人投资记录与学习笔记，全部为数据分析与参考，不构成任何投资建议。基金有风险，投资需谨慎。</div>
</div></body></html>'''


def main():
    html = build_html()
    out = os.path.join(ROOT, 'index.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'导航首页已生成: {out}')


if __name__ == '__main__':
    main()
