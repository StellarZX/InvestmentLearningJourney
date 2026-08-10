# -*- coding: utf-8 -*-
"""
生成根 README 第 4 节「组合持仓」表格（export_positions.py）
============================================================
从统一持仓库 data/portfolio.db 汇总各基金当前持仓 / 累计成本，
输出 markdown 表格。可打印或直接替换根 README 的「## 4. 组合持仓」段落。

用法：
  python export_positions.py           # 打印表格
  python export_positions.py --write    # 直接更新根 README.md（保留收益率列原值）

说明：
  - 当前持仓 = 买入/转入 - 卖出/转出（+资金池收益）
  - 收益率列显示原 README 中已填写的值；新标的不填则显示 '—'（可手工补充现价估值）
"""
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'portfolio.db')
README = os.path.join(BASE, '..', 'README.md')   # 根 README


def positions():
    conn = sqlite3.connect(DB)
    rows = conn.execute('''
        SELECT category, fund, code,
          SUM(CASE WHEN direction IN ('买入','转入','收益') THEN amount
                   WHEN direction IN ('卖出','转出') THEN -amount ELSE 0 END) AS amt,
          SUM(CASE WHEN direction IN ('买入','转入') THEN amount ELSE 0 END) AS cost
        FROM trans GROUP BY code, category''').fetchall()
    conn.close()
    out = {'指数': [], '行业': [], '其他': []}
    for cat, fund, code, amt, cost in rows:
        if amt <= 0:
            continue
        key = cat if cat in ('指数', '行业') else '其他'   # 资金池等归入「其他」
        out[key].append({'fund': fund, 'code': code, 'amt': round(amt, 2), 'cost': round(cost, 2)})
    return out


def cash_implied():
    """余额宝推算余额（可用现金 = 转入-已投基金），复用 portfolio_app 逻辑"""
    try:
        import portfolio_app as app
        return app.get_summary().get('cash_implied')
    except Exception:
        return None


def old_returns():
    """从根 README 提取旧的 代码->收益率 映射（保留手工填的值）"""
    ret = {}
    if not os.path.exists(README):
        return ret
    src = open(README, encoding='utf-8').read()
    m = re.search(r'## 4\. 组合持仓.*?(?=\n## )', src, re.S)
    if not m:
        return ret
    for line in m.group(0).splitlines():
        mm = re.match(r'\|\s*(\S+)\s+\|\s*([0-9A-Za-z\-]+)\s+\|.*\|\s*(-?[\d.]+%|—|-|\s*)\s*\|', line)
        if mm:
            ret[mm.group(2)] = mm.group(3).strip()
    return ret


def fmt_money(v):
    return f'¥{v:,.2f}'


def build_md(returns):
    md = ['## 4. 组合持仓', '', '|   类型   |   代码   |         当前持仓 |        累计成本 | 收益率    | 基金             |',
          '|:------:|:------:|-------------:|------------:|--------|----------------|']
    pos = positions()
    totals = {'指数': 0.0, '行业': 0.0}
    costs = {'指数': 0.0, '行业': 0.0}
    for cat in ('指数', '行业'):
        items = sorted(pos[cat], key=lambda x: -x['amt'])
        for it in items:
            code = it['code']
            ret = returns.get(code, '—')
            md.append(f"|   {cat}   | {code:>6} | {fmt_money(it['amt']):>12} | {fmt_money(it['cost']):>11} | {ret:<7} | {it['fund']:<16} |")
            totals[cat] += it['amt']
            costs[cat] += it['cost']
        t, c = totals[cat], costs[cat]
        r = f'{(t/c-1)*100:+.1f}%' if c else '-'
        md.append(f'| *{cat}合计* |  *-*   |  *{fmt_money(t)}* |  *{fmt_money(c)}* | *{r}* | *-*            |')
    # 其他（资金池等）——余额宝显示推算余额（可用现金）
    cash_items = pos['其他']
    ci = cash_implied()
    cash_total = 0.0
    cash_cost = sum(x['cost'] for x in cash_items)
    for it in cash_items:
        code = it['code']
        ret = returns.get(code, '—')
        amt_show = ci if (code == 'ZFB' and ci is not None) else it['amt']
        cash_total += amt_show
        md.append(f"|   其他   | {code:>6} | {fmt_money(amt_show):>12} | {fmt_money(it['cost']):>11} | {ret:<7} | {it['fund']:<16} |")
    gt = totals['指数'] + totals['行业'] + cash_total
    gc = costs['指数'] + costs['行业'] + cash_cost
    md.append(f'|  总计   |  *-*   | *{fmt_money(gt)}* | *{fmt_money(gc)}* | *-*    | *-*            |')
    md.append('')
    md.append('> 表格由 `export_positions.py` 从 `data/portfolio.db` 自动生成；余额宝显示「可用现金」（转入-已投基金），收益率列为手工估值。')
    return '\n'.join(md)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='直接更新根 README.md')
    args = ap.parse_args()

    returns = old_returns()
    md = build_md(returns)
    if args.write:
        if not os.path.exists(README):
            print('[err] 根 README.md 不存在'); return
        src = open(README, encoding='utf-8').read()
        m = re.search(r'## 4\. 组合持仓.*?(?=\n## )', src, re.S)
        if m:
            src = src[:m.start()] + md + '\n' + src[m.end():]
        else:
            src += '\n' + md + '\n'
        open(README, 'w', encoding='utf-8').write(src)
        print('已更新根 README.md 第 4 节')
    else:
        print(md)


if __name__ == '__main__':
    main()
