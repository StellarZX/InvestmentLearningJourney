# -*- coding: utf-8 -*-
"""
westock 板块数据导入器（westock_import.py）
==========================================
腾讯自选股（westock MCP）在会话内拉取板块数据后，通过本脚本导入本地 plate.db：
  - K 线：会话内用 data_kline 拉取，保存为 JSON 文件后导入 plate_kline 表
  - 清单/快照：可选，同步 name 等

JSON 文件格式（每文件一个板块）：
{
  "code": "pt02GN2222",
  "name": "AI算力芯片",
  "type": "concept",            # concept / industry
  "nodes": [
    {"date": "2026-08-18", "open": 1951.81, "close": 1936.68, "high": 1957.67,
     "low": 1905.9, "volume": 14475919, "amount": 129956510000}, ...
  ]
}

用法：
  python westock_import.py <json文件> [<json文件>...]
  python westock_import.py data/westock/*.json    # 批量导入
"""
import os, sys, json, sqlite3, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'plate.db')


def import_file(path, db=DB):
    """导入单个 JSON 文件，返回 (code, name, kline_rows)"""
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    code = d.get('code', '')
    name = d.get('name', '')
    nodes = d.get('nodes') or []
    if not code or not nodes:
        print(f'  [skip] {path}: 缺少 code 或 nodes')
        return None
    conn = sqlite3.connect(db)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    # 同步清单名称（新增板块）
    ptype = d.get('type', 'concept')
    conn.execute('INSERT OR IGNORE INTO plate_list(code,name,type,zdf,mf,fetched_at) VALUES(?,?,?,?,?,?)',
                 (code, name, ptype, None, None, now))
    # 导入 K 线（覆盖式）
    rows = [(code, n['date'], float(n['open']), float(n['close']), float(n['high']),
             float(n['low']), float(n.get('volume') or 0), float(n.get('amount') or 0))
            for n in nodes if n.get('date')]
    conn.executemany(
        'INSERT OR REPLACE INTO plate_kline(code,date,open,close,high,low,volume,amount) '
        'VALUES(?,?,?,?,?,?,?,?)', rows)
    conn.commit()
    conn.close()
    return (code, name, len(rows))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    total = 0
    for p in args:
        if not os.path.exists(p):
            print(f'  [missing] {p}')
            continue
        r = import_file(p)
        if r:
            print(f'  [ok] {r[0]} {r[1]} -> {r[2]} 根 K 线')
            total += r[2]
    print(f'完成：共导入 {total} 根 K 线到 {DB}')


if __name__ == '__main__':
    main()
