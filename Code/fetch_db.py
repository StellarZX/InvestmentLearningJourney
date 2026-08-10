# -*- coding: utf-8 -*-
"""
主库数据维护脚本（fetch_all_industry.py → 现为通用 fetch_db.py 逻辑）
======================================================================
用腾讯公开接口（前复权 qfq）维护统一主库 data/market.db：

表结构：
  etf_meta(code, name, type, is_ind)  全市场清单（1623 只，已含类型标注）
  kline(code, date, open, close, high, low, volume, amount)  前复权 K 线（含成交量和成交额）

用法:
  python fetch_db.py                      # 智能更新：无K线的拉全量，有K线的只增量（日常首选）
  python fetch_db.py --full               # 全量重拉所有标的（WAF 解封后补 OHLCV 用）
  python fetch_db.py --incremental        # 全部标的仅增量拉取（快）
  python fetch_db.py --types 宽基,跨境     # 指定拉取类型（后续扩展标的用；默认 industry）
  python fetch_db.py --types all          # 拉取全部类型（含宽基/跨境/债券/商品/货币）

注意：腾讯 fqkline 接口有 WAF 风控，脚本已限速（0.2s/请求 + 失败重试）。
全量拉取被 501 拦截时，请等待约 30-60 分钟再试。
"""
import os, sys, sqlite3, argparse, time, datetime
import concurrent.futures as cf
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))
from signal_lib import is_industry

DB = os.path.join(BASE, 'data', 'market_industry.db')
URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
PAGE = 640
MIN_WAIT = 0.2          # 请求间隔（秒），防 WAF
_session = None
_waf_hits = 0           # 连续 WAF/失败计数


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def fetch_seg(code, end, count=PAGE):
    """拉一段 K 线。返回 [ [date, open, close, high, low, volume, ...], ... ] 或 None(失败)"""
    global _waf_hits
    params = {'param': f'{code},day,2005-01-01,{end},{count},qfq'}
    for attempt in range(3):
        try:
            r = get_session().get(URL, params=params, timeout=20)
            if r.status_code != 200 or not r.text.strip().startswith('{'):
                _waf_hits += 1
                return None
            d = r.json()
            data = d.get('data', {})
            for v in data.values():
                if isinstance(v, dict):
                    return v.get('qfqday') or v.get('day') or []
            return []
        except Exception:
            _waf_hits += 1
            if attempt == 2:
                return None
            time.sleep(0.8)
    return []


def parse_row(r):
    """解析腾讯 K 线行为 (date, open, close, high, low, volume, amount)"""
    try:
        date = r[0]
        open_ = float(r[1])
        close = float(r[2])
        high = float(r[3])
        low = float(r[4])
        volume = float(r[5]) if len(r) > 5 and r[5] not in (None, '') else None
        amount = float(r[6]) if len(r) > 6 and r[6] not in (None, '') else None
        return (date, open_, close, high, low, volume, amount)
    except (ValueError, IndexError):
        return None


def fetch_full(code):
    """分页拉全历史，返回 [(date, open, close, high, low, volume, amount), ...] 升序"""
    rows = []
    end = datetime.date.today().strftime('%Y-%m-%d')
    guard = 0
    while guard < 40:
        seg = fetch_seg(code, end)
        if seg is None:
            return None
        if not seg:
            break
        rows = seg + rows
        first = seg[0][0]
        if first <= '2005-01-01':
            break
        end = (datetime.datetime.strptime(first, '%Y-%m-%d') - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        guard += 1
    out = []
    for r in rows:
        p = parse_row(r)
        if p:
            out.append(p)
    out.sort(key=lambda x: x[0])
    return out


def fetch_incremental(code, last_date):
    """增量：拉 last_date 之后的新 K 线。失败返回 None"""
    end = datetime.date.today().strftime('%Y-%m-%d')
    seg = fetch_seg(code, end)
    if seg is None:
        return None
    if not seg:
        return []
    out = [p for p in (parse_row(r) for r in seg) if p]
    out.sort(key=lambda x: x[0])
    return [x for x in out if x[0] > last_date]


def get_codes(types):
    """从 market.db 的 etf_meta 取标的清单"""
    conn = sqlite3.connect(DB)
    if types == 'all':
        rows = conn.execute('SELECT code,name,type FROM etf_meta ORDER BY is_ind DESC, code').fetchall()
    else:
        tl = types.split(',')
        q = ','.join('?' * len(tl))
        rows = conn.execute(
            f'SELECT code,name,type FROM etf_meta WHERE type IN ({q}) ORDER BY code', tl).fetchall()
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true', help='全部标的仅增量拉取')
    ap.add_argument('--full', action='store_true', help='全部标的重拉全量（补OHLCV/修复数据）')
    ap.add_argument('--types', type=str, default='industry',
                    help='拉取类型: industry(默认) / all / 逗号分隔如 宽基,跨境')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    codes = get_codes(args.types)
    print(f'标的清单: {len(codes)} 只（类型={args.types}）→ {DB}')

    # 库内已有 K 线的标的及其最新日期
    have = {}
    for c, d in conn.execute('SELECT code, MAX(date) FROM kline GROUP BY code').fetchall():
        have[c] = d

    todo = []
    for code, name, typ in codes:
        last = have.get(code)
        if args.full:
            todo.append((code, name, typ, None, 'full'))            # 强制全量
        elif args.incremental:
            todo.append((code, name, typ, last, 'inc'))             # 全部增量
        else:
            todo.append((code, name, typ, last, 'full' if last is None else 'inc'))  # 智能

    t0 = time.time()
    ok = 0; fail = 0; new_rows = 0

    def work(item):
        code, name, typ, last, mode = item
        if mode == 'inc' and last:
            rows = fetch_incremental(code, last)
        else:
            rows = fetch_full(code)
        return code, name, rows, mode

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, it): it[0] for it in todo}
        for i, f in enumerate(cf.as_completed(futs), 1):
            code, name, rows, mode = f.result()
            if rows is None:
                fail += 1
                # 连续失败过多说明被 WAF 拦截，提前终止
                if _waf_hits >= 10:
                    print('\n[警告] 连续请求失败（疑似腾讯 WAF 风控），已提前终止。请等待 30-60 分钟后再试。')
                    conn.close()
                    return
                continue
            if rows:
                conn.executemany(
                    'INSERT OR REPLACE INTO kline(code,date,open,close,high,low,volume,amount) VALUES(?,?,?,?,?,?,?,?)',
                    [(code, d, o, c, h, l, v, a) for d, o, c, h, l, v, a in rows])
                new_rows += len(rows)
                conn.commit()
            ok += 1
            if i % 50 == 0 or i == len(todo):
                print(f'  [{i}/{len(todo)}] {name:<14} {mode} {len(rows) if rows else 0}根 用时{time.time()-t0:.0f}s', flush=True)
            time.sleep(MIN_WAIT)

    conn.close()
    print(f'\n完成: ok={ok} fail={fail} 新增K线={new_rows} 总耗时{time.time()-t0:.0f}s')

    # 统计
    conn = sqlite3.connect(DB)
    n_meta = conn.execute('SELECT COUNT(*) FROM etf_meta').fetchone()[0]
    n_k = conn.execute('SELECT COUNT(*) FROM kline').fetchone()[0]
    n_oh = conn.execute('SELECT COUNT(*) FROM kline WHERE volume IS NOT NULL').fetchone()[0]
    r = conn.execute('SELECT MIN(date), MAX(date) FROM kline').fetchone()
    conn.close()
    print(f'库内: 清单 {n_meta} 只 / K线 {n_k} 行（含成交量 {n_oh} 行）| 覆盖 {r[0]} ~ {r[1]}')


if __name__ == '__main__':
    main()
