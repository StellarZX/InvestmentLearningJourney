# -*- coding: utf-8 -*-
"""
生成根 README 第 4 节「组合持仓」表格（export_positions.py）
============================================================
从统一持仓库 data/portfolio.db 汇总各基金当前持仓，
与「持仓流水管理」界面（portfolio_app）同口径：
  - 当前持仓 = 买入/转入 - 卖出/转出（+资金池收益）
  - 指数/行业按金额降序，余额宝固定放最后（显示推算余额=可用现金）
输出 markdown 表格。可打印或直接替换根 README 的「## 4. 组合持仓」段落。

用法：
  python export_positions.py           # 打印表格
  python export_positions.py --write    # 直接更新根 README.md
"""
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'portfolio.db')
os.makedirs(os.path.dirname(DB), exist_ok=True)   # 首次运行自动创建 data/
README = os.path.join(BASE, '..', 'README.md')   # 根 README


def positions():
    conn = sqlite3.connect(DB)
    rows = conn.execute('''
        SELECT category, fund, code,
          SUM(CASE WHEN direction IN ('买入','转入','收益') THEN amount
                   WHEN direction IN ('卖出','转出') THEN -amount ELSE 0 END) AS amt
        FROM trans GROUP BY code, category''').fetchall()
    conn.close()
    out = {'指数': [], '行业': [], '其他': []}
    for cat, fund, code, amt in rows:
        if amt <= 0:
            continue
        key = cat if cat in ('指数', '行业') else '其他'   # 资金池等归入「其他」
        out[key].append({'fund': fund, 'code': code, 'amt': round(amt, 2)})
    # 与持仓管理界面一致：指数/行业按当前持仓降序
    for k in ('指数', '行业'):
        out[k].sort(key=lambda x: -x['amt'])
    return out


def cash_implied():
    """余额宝推算余额（可用现金 = 转入-已投基金），复用 portfolio_app 逻辑"""
    try:
        import portfolio_app as app
        return app.get_summary().get('cash_implied')
    except Exception:
        return None


def fmt_money(v):
    return f'¥{v:,.2f}'


def build_md():
    md = ['## 4. 组合持仓', '',
          '|   类型   |   代码   |     当前持仓      |         基金          |',
          '|:------:|:------:|:-------------:|:-------------------:|']
    pos = positions()
    totals = {'指数': 0.0, '行业': 0.0}
    for cat in ('指数', '行业'):
        for it in pos[cat]:
            md.append(f"|   {cat}   | {it['code']:>6} | {fmt_money(it['amt']):>12} | {it['fund']:<16} |")
            totals[cat] += it['amt']
        md.append(f'| *{cat}合计* |  *-*   |  *{fmt_money(totals[cat])}*  |         *-*         |')
    # 其他（资金池等）——余额宝显示推算余额（可用现金）
    ci = cash_implied()
    cash_total = 0.0
    for it in pos['其他']:
        amt_show = ci if (it['code'] == 'ZFB' and ci is not None) else it['amt']
        cash_total += amt_show
        md.append(f"|   其他   | {it['code']:>6} | {fmt_money(amt_show):>12} | {it['fund']:<16} |")
    gt = totals['指数'] + totals['行业'] + cash_total
    md.append(f'|  总计   |  *-*   | *{fmt_money(gt)}*  |         *-*         |')
    md.append('')
    md.append('> 表格由 `Code/export_positions.py` 从 `Code/data/portfolio.db` 自动生成，与「持仓流水管理」当前持仓同口径；余额宝显示可用现金（转入-已投基金）。')
    return '\n'.join(md)


def write_readme(md):
    """把生成的表格写回根 README.md 第 4 节；返回是否成功"""
    if not os.path.exists(README):
        print(f'[err] 根 README.md 不存在: {README}')
        return False
    src = open(README, encoding='utf-8').read()
    m = re.search(r'## 4\. 组合持仓.*?(?=\n## )', src, re.S)
    if m:
        src = src[:m.start()] + md + '\n' + src[m.end():]
    else:
        src += '\n' + md + '\n'
    open(README, 'w', encoding='utf-8').write(src)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='直接更新根 README.md')
    args = ap.parse_args()

    md = build_md()
    if args.write:
        ok = write_readme(md)
        print('已更新根 README.md 第 4 节' if ok else '更新失败')
    else:
        print(md)


if __name__ == '__main__':
    main()
