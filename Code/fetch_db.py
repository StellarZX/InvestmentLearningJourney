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
import os, sys, sqlite3, argparse, time, datetime, json
import concurrent.futures as cf
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))
from signal_lib import is_industry

DB = os.path.join(BASE, 'data', 'market_industry.db')
os.makedirs(os.path.dirname(DB), exist_ok=True)   # 首次运行自动创建 data/
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


def fetch_meta_list():
    """拉全市场 ETF 清单（首次运行 etf_meta 为空时自动重建）。
    双数据源：东方财富优先，失败自动切新浪。返回 (code, name) 列表。
    代码统一 6 位（如 159287 / 510010），不带市场前缀。"""
    import requests as _r
    H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'}
    # 源1：东财（f12 为 6 位代码）
    try:
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        out, pn = [], 1
        while True:
            params = {'pn': pn, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
                      'fid': 'f3', 'fs': 'b:MK0021,b:MK0022,b:MK0023,b:MK0024',
                      'fields': 'f12,f14'}
            j = None
            for _t in range(3):
                try:
                    j = _r.get(url, params=params, timeout=20, headers=H).json()
                    break
                except Exception:
                    time.sleep(1.0)
            diff = ((j or {}).get('data') or {}).get('diff') or []
            if not diff:
                break
            out += [(str(d.get('f12') or '').zfill(6), d.get('f14') or '') for d in diff]
            total = ((j or {}).get('data') or {}).get('total') or 0
            if len(out) >= total or len(diff) < 100:
                break
            pn += 1
            time.sleep(0.3)
        if len(out) > 500:
            return out
    except Exception:
        pass
    # 源2：新浪（symbol 带 sh/sz 前缀，与腾讯 K 线 code 格式一致）
    try:
        import re as _re
        url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
        out, page = [], 1
        while True:
            r = _r.get(url, params={'page': page, 'num': 100, 'sort': 'symbol', 'asc': 1,
                                    'node': 'etf_hq_fund'}, timeout=20, headers=H)
            txt = r.text.strip()
            if not txt or txt == 'null' or txt.startswith('<'):
                break
            d = json.loads(txt)
            if not d:
                break
            # 用 symbol（sh510010）→ 与腾讯 K 线 code（sh510150）格式一致，可直接匹配
            out += [(str(x.get('symbol') or ''), x.get('name') or '') for x in d if x.get('symbol')]
            if len(d) < 100:
                break
            page += 1
            time.sleep(0.3)
        if out:
            return out
    except Exception:
        pass
    return []


def enrich_names():
    """用腾讯批量行情接口给 etf_meta 补全称（新浪/东财清单的 name 可能是残缺简称，
    如 航空TH=航空航天ETF天弘、FG消费=港股通消费ETF富国，导致主题归一化失效）。
    全称只替换更长的（简称→全称），不覆盖已有的完整名称。"""
    import requests as _r
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT code, name FROM etf_meta').fetchall()
    # 疑似残缺简称：无中文或含孤立字母/过短
    todo = []
    for code, name in rows:
        if not name:
            todo.append(code)
        elif len(name) <= 5 and any(c.isalpha() for c in name):   # 如 航空TH/FG消费/HK消费
            todo.append(code)
    if not todo:
        conn.close()
        return 0
    print(f'  补全名称: {len(todo)} 只（残缺简称）...')
    n_fixed = 0
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        try:
            r = _r.get('https://qt.gtimg.cn/q=' + ','.join(batch), timeout=15,
                       headers={'User-Agent': 'Mozilla/5.0'})
            r.encoding = 'gbk'
            for line in r.text.strip().split(';'):
                if '=' not in line:
                    continue
                # 格式: v_sz159241="51~航空航天ETF天弘~159241~1.051~..."
                key, _, val = line.partition('=')
                code = key.replace('v_', '').strip()
                parts = val.strip('"').split('~')
                if len(parts) <= 3:
                    continue
                full = (parts[1] or '').strip()
                old = dict(rows).get(code, '')
                if full and len(full) > len(old):
                    conn.execute('UPDATE etf_meta SET name=? WHERE code=?', (full, code))
                    n_fixed += 1
        except Exception:
            pass
        time.sleep(0.3)
    conn.commit()
    conn.close()
    print(f'  已补全 {n_fixed} 只全称')
    return n_fixed


def rebuild_meta():
    """重建 etf_meta 全市场清单（含类型标注 + 全称补全）"""
    from signal_lib import classify_industry, is_industry
    lst = fetch_meta_list()
    if not lst:
        print('  [warn] 清单接口无数据，跳过重建')
        return 0
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS etf_meta(
        code TEXT PRIMARY KEY, name TEXT, type TEXT, is_ind INTEGER DEFAULT 0)''')
    conn.execute('DELETE FROM etf_meta')
    rows = []
    for code, name in lst:
        if is_industry(name):
            t = 'industry'
        else:
            t = classify_industry(name)
        rows.append((code, name, t, 1 if t == 'industry' else 0))
    conn.executemany('INSERT OR REPLACE INTO etf_meta(code,name,type,is_ind) VALUES(?,?,?,?)', rows)
    conn.commit()
    conn.close()
    n = len(rows)
    n_ind = sum(1 for r in rows if r[3])
    # 用腾讯接口补全称（简称→全称）
    enrich_names()
    print(f'  已重建清单: {n} 只（行业型 {n_ind}）')
    return n


def fetch_index_data(force=False):
    """拉取每只行业 ETF 跟踪的真实指数日线：
    ① fundmobapi 查 ETF 跟踪指数(INDEXCODE/INDEXNAME) → index_kline 映射表
    ② 东财 kline 接口拉指数日线 → index_daily 表
    幂等可续跑：已有映射跳过查询，已有K线跳过拉取（东财限流后重跑即可续）"""
    import requests as _r
    H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS index_kline(
        code TEXT PRIMARY KEY, name TEXT, theme TEXT,
        INDEXCODE TEXT, INDEXNAME TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS index_daily(
        indexcode TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, amount REAL, PRIMARY KEY(indexcode, date))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_index_daily ON index_daily(indexcode)')
    conn.commit()
    # 已有映射
    known = {r[0] for r in conn.execute('SELECT theme FROM index_kline').fetchall()}
    metas = conn.execute(
        "SELECT code, name FROM etf_meta WHERE is_ind=1 ORDER BY code").fetchall()
    conn.close()
    # 主题 → 代表ETF
    from signal_lib import theme_of
    rep_by_theme = {}
    for code, name in metas:
        th = theme_of(name)
        rep_by_theme.setdefault(th, (code, name))

    # ① 查缺失的映射
    todo = [(th, c, n) for th, (c, n) in rep_by_theme.items() if th not in known]
    if todo:
        print(f'指数映射: 已有 {len(known)} 个, 待查 {len(todo)} 个')
        conn = sqlite3.connect(DB)
        for i, (th, code, name) in enumerate(todo, 1):
            for _t in range(2):
                try:
                    r = _r.get('https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation',
                               params={'FCODE': code[-6:], 'deviceid': 'x', 'plat': 'Android',
                                       'product': 'EFund', 'version': '6.3.8'}, timeout=10, headers=H)
                    d = (r.json().get('Datas') or {})
                    ic, inm = d.get('INDEXCODE') or '', d.get('INDEXNAME') or ''
                    if ic:
                        conn.execute('INSERT OR REPLACE INTO index_kline(code,name,theme,INDEXCODE,INDEXNAME) '
                                     'VALUES(?,?,?,?,?)', (code, name, th, ic, inm))
                        conn.commit()
                    break
                except Exception:
                    time.sleep(1.0)
            if i % 40 == 0:
                print(f'  [{i}/{len(todo)}] 映射中...', flush=True)
            time.sleep(0.12)
        conn.close()
        print('  映射阶段完成')

    # ② 拉缺失的指数K线
    conn = sqlite3.connect(DB)
    maps = conn.execute('SELECT theme, code, INDEXCODE, INDEXNAME FROM index_kline').fetchall()
    have = {r[0] for r in conn.execute('SELECT DISTINCT indexcode FROM index_daily').fetchall()}
    conn.close()
    todo_kl = [m for m in maps if m[2] not in have]
    print(f'指数K线: 已有 {len(maps)-len(todo_kl)} 个, 待拉 {len(todo_kl)} 个')
    ok_cnt = 0
    conn = sqlite3.connect(DB)
    for i, (th, code, ic, inm) in enumerate(todo_kl, 1):
        kl = None
        for _try in range(3):
            try:
                r = _r.get('https://push2his.eastmoney.com/api/qt/stock/kline/get',
                           params={'secid': f'2.{ic}',
                                   'fields1': 'f1,f2,f3,f4,f5,f6',
                                   'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
                                   'klt': 101, 'fqt': 1, 'beg': '19900101', 'end': '20500101',
                                   'lmt': 2000}, timeout=20, headers=H)
                kl = ((r.json().get('data') or {}).get('klines')) or []
                if kl:
                    break
            except Exception:
                time.sleep(2.0)
        if kl:
            rows = []
            for line in kl:
                p = line.split(',')
                rows.append((ic, p[0], float(p[1]), float(p[2]), float(p[3]),
                             float(p[4]), float(p[5]), float(p[6])))
            conn.executemany(
                'INSERT OR REPLACE INTO index_daily(indexcode,date,open,close,high,low,volume,amount) '
                'VALUES(?,?,?,?,?,?,?,?)', rows)
            conn.commit()
            ok_cnt += 1
        if i % 30 == 0:
            print(f'  K线 [{i}/{len(todo_kl)}] 完成 {ok_cnt}', flush=True)
        time.sleep(0.6)
    conn.close()
    print(f'完成: 本次拉取K线 {ok_cnt} 个指数')
    return ok_cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true', help='全部标的仅增量拉取')
    ap.add_argument('--full', action='store_true', help='全部标的重拉全量（补OHLCV/修复数据）')
    ap.add_argument('--types', type=str, default='industry',
                    help='拉取类型: industry(默认) / all / 逗号分隔如 宽基,跨境')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--indexes', action='store_true', help='拉取行业ETF跟踪的真实指数日线（替代ETF合成）')
    args = ap.parse_args()

    if args.indexes:
        fetch_index_data()
        return

    conn = sqlite3.connect(DB)
    # 首次运行自动建表（幂等）：全市场清单 + K线
    conn.execute('''CREATE TABLE IF NOT EXISTS etf_meta(
        code TEXT PRIMARY KEY, name TEXT, type TEXT, is_ind INTEGER DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS kline(
        code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, amount REAL, PRIMARY KEY(code, date))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_kline_code ON kline(code)')
    conn.execute('''CREATE TABLE IF NOT EXISTS index_kline(
        code TEXT PRIMARY KEY, name TEXT, theme TEXT,
        INDEXCODE TEXT, INDEXNAME TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS index_daily(
        indexcode TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, amount REAL, PRIMARY KEY(indexcode, date))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_index_daily ON index_daily(indexcode)')
    conn.commit()
    # 清单为空（如克隆仓库后首次运行）→ 自动从接口重建全市场清单
    n_meta0 = conn.execute('SELECT COUNT(*) FROM etf_meta').fetchone()[0]
    if n_meta0 == 0:
        print('  etf_meta 为空，自动重建全市场清单...')
        rebuild_meta()
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
