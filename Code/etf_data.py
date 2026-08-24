# -*- coding: utf-8 -*-
"""
ETF 底池数据层（etf_data.py）
=============================
为「ETF 联接入场机会」子项目筛选底池：**流动性大、资金量大的场内 ETF**。

筛选标准（2026-08-22 定稿）：
  - 当日成交额 ≥ 2 亿（流动性门槛 AMOUNT_MIN）
  - 总市值 ≈ 基金规模 ≥ 20 亿（资金量门槛 CAP_MIN）

数据源：东方财富 push2 接口（与 plate_data 同模式，直连不限流但需限速防封 IP）
DB：data/etf.db
  - etf_pool(code,name,price,zdf,amount,mktcap,fetched_at)
  - etf_kline(code,date,open,close,high,low,volume,amount)

用法：
  python etf_data.py --sync       # 更新底池 + 增量拉 K 线（报告运行时自动触发）
"""
import os, sys, sqlite3, datetime, time
import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'etf.db')
os.makedirs(os.path.dirname(DB), exist_ok=True)

CLIST_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
FFLOW_URL = 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get'
H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

# 东财 ETF 板块全集（沪/深 ETF 四个市场块）
FS_ETF = 'b:MK0021,b:MK0022,b:MK0023,b:MK0024'

AMOUNT_MIN = 2e8      # 成交额 ≥ 2 亿（流动性）
CAP_MIN = 20e8        # 总市值 ≥ 20 亿（资金量/规模代理）
KLINE_DAYS = 320      # 拉取约 1.2 年，够算 250 日分位


def _get(url, params, retries=3, timeout=20):
    """带重试的 GET（东财接口偶发超时/502）"""
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=H)
            if r.status_code == 200 and r.text.strip().startswith('{'):
                return r.json()
        except Exception:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def _secid(code):
    """东财 secid：沪市 ETF(5 开头)=1.code，深市(1/0 开头，159 等)=0.code"""
    return ('1.' if code.startswith('5') else '0.') + code


def fetch_etf_spot():
    """拉全市场 ETF 实时快照。返回 [{code,name,price,zdf,amount,mktcap}]"""
    out = []
    pn = 1
    while True:
        j = _get(CLIST_URL, {
            'pn': pn, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f6',
            'fs': FS_ETF, 'fields': 'f12,f14,f2,f3,f6,f20',
        })
        diff = ((j or {}).get('data') or {}).get('diff') or []
        if not diff:
            break
        for d in diff:
            out.append({
                'code': str(d.get('f12') or ''), 'name': str(d.get('f14') or ''),
                'price': d.get('f2'), 'zdf': d.get('f3'),
                'amount': d.get('f6'), 'mktcap': d.get('f20'),
            })
        total = ((j or {}).get('data') or {}).get('total') or 0
        if len(out) >= total or len(diff) < 100:
            break
        pn += 1
        time.sleep(0.15)
    return out


def filter_pool(etfs):
    """按成交额+规模筛底池，剔除名称含『退』的异常标的"""
    pool = [e for e in etfs
            if e['amount'] and e['mktcap']
            and e['amount'] >= AMOUNT_MIN and e['mktcap'] >= CAP_MIN
            and '退' not in e['name']]
    pool.sort(key=lambda x: -x['amount'])
    return pool


def fetch_spot_flow():
    """拉全市场 ETF 当日主力净流入快照（clist f62，1-2 次分页请求即可全量）。
    返回 {code: {'mf': 元, 'pct': 主力净占比%}}（仅含有效值）。"""
    out = {}
    pn = 1
    while True:
        j = _get(CLIST_URL, {
            'pn': pn, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f6',
            'fs': FS_ETF, 'fields': 'f12,f62,f184',
        })
        diff = ((j or {}).get('data') or {}).get('diff') or []
        if not diff:
            break
        for d in diff:
            code = str(d.get('f12') or '')
            if code and isinstance(d.get('f62'), (int, float)):
                out[code] = {'mf': d['f62'], 'pct': d.get('f184')}
        total = ((j or {}).get('data') or {}).get('total') or 0
        if len(out) >= total or len(diff) < 100:
            break
        pn += 1
        time.sleep(0.3)
    return out


def latest_trade_date(store):
    """底池最新交易日（取全部 ETF K 线最大日期；快照资金流按此日入库）"""
    dates = [store.kline_latest(e['code']) for e in store.list_pool()]
    dates = [d for d in dates if d]
    return max(dates) if dates else datetime.date.today().strftime('%Y-%m-%d')


def sync_flow_snapshot(store=None):
    """把当日主力净流入快照写入 etf_fflow（按最新交易日入库）。
    每天跑一次即可本地累积出历史，不依赖东财历史接口（该接口限流严重）。"""
    store = store or EtfStore()
    td = latest_trade_date(store)
    flow = fetch_spot_flow()
    if not flow:
        print('[warn] 资金流快照拉取失败（东财限流），本次跳过')
        return 0
    n = 0
    conn = sqlite3.connect(store.db)
    for e in store.list_pool():
        f = flow.get(e['code'])
        if f and f.get('mf') is not None:
            conn.execute('INSERT OR REPLACE INTO etf_fflow(code,date,mf) VALUES(?,?,?)',
                         (e['code'], td, float(f['mf'])))
            n += 1
    conn.commit()
    conn.close()
    print(f"资金流快照已入库存 {n} 只（交易日 {td}）")
    return n


def _tx_symbol(code):
    """腾讯代码前缀：沪市 ETF(5 开头)=sh，深市=sz"""
    return ('sh' if code.startswith('5') else 'sz') + code


def fetch_kline(code, count=KLINE_DAYS):
    """拉 ETF 日K（前复权，腾讯 ifzq）。返回 DataFrame(date,open,close,high,low,volume,amount) 或空表。
    注：东财历史行情接口在当前网络被拒（2026-08-22 实测），改用腾讯；
    腾讯无成交额字段，amount 为估算值（手×100×收盘价）。"""
    sym = _tx_symbol(code)
    j = _get(KLINE_URL, {'param': f'{sym},day,,,{count},qfq'})
    d = ((j or {}).get('data') or {}).get(sym) or {}
    rows = []
    for p in (d.get('qfqday') or d.get('day') or []):
        try:
            o, c, h, l, v = float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
            rows.append((p[0], o, c, h, l, v, round(v * 100 * c)))
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


def fetch_fflow(code, count=KLINE_DAYS):
    """拉 ETF 每日主力净流入历史（东财 fflow 历史接口，限流严重、间歇可用）。
    仅作历史回补（--fflow），日常增量走 sync_flow_snapshot 快照累积。
    单位：元。返回 DataFrame(date, mf) 或空表。"""
    j = _get(FFLOW_URL, {
        'lmt': count, 'klt': 101, 'secid': _secid(code),
        'fields1': 'f1,f2,f3,f7', 'fields2': 'f51,f52',
    })
    kl = ((j or {}).get('data') or {}).get('klines') or []
    rows = []
    for line in kl:
        p = line.split(',')
        try:
            rows.append((p[0], float(p[1])))
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows, columns=['date', 'mf'])


class EtfStore:
    """本地缓存：etf_pool + etf_kline"""

    def __init__(self, db=DB):
        self.db = db
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db)
        conn.execute('''CREATE TABLE IF NOT EXISTS etf_pool(
            code TEXT PRIMARY KEY, name TEXT, price REAL, zdf REAL,
            amount REAL, mktcap REAL, fetched_at TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS etf_kline(
            code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
            volume REAL, amount REAL, PRIMARY KEY(code, date))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS etf_fflow(
            code TEXT, date TEXT, mf REAL, PRIMARY KEY(code, date))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ek_code ON etf_kline(code)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ef_code ON etf_fflow(code)')
        conn.commit()
        conn.close()

    def save_pool(self, pool):
        conn = sqlite3.connect(self.db)
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        conn.execute('DELETE FROM etf_pool')
        conn.executemany(
            'INSERT INTO etf_pool(code,name,price,zdf,amount,mktcap,fetched_at) VALUES(?,?,?,?,?,?,?)',
            [(e['code'], e['name'], e['price'], e['zdf'], e['amount'], e['mktcap'], now)
             for e in pool])
        conn.commit()
        conn.close()

    def list_pool(self):
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            'SELECT code,name,price,zdf,amount,mktcap FROM etf_pool ORDER BY amount DESC').fetchall()
        conn.close()
        return [{'code': r[0], 'name': r[1], 'price': r[2], 'zdf': r[3],
                 'amount': r[4], 'mktcap': r[5]} for r in rows]

    def kline_latest(self, code):
        conn = sqlite3.connect(self.db)
        r = conn.execute('SELECT MAX(date) FROM etf_kline WHERE code=?', (code,)).fetchone()
        conn.close()
        return r[0] if r else None

    def save_kline(self, code, df):
        if df.empty:
            return 0
        conn = sqlite3.connect(self.db)
        rows = [(code, d, o, c, h, l, v, a) for d, o, c, h, l, v, a in
                zip(df['date'], df['open'], df['close'], df['high'], df['low'],
                    df['volume'], df['amount'])]
        conn.executemany(
            'INSERT OR REPLACE INTO etf_kline(code,date,open,close,high,low,volume,amount) '
            'VALUES(?,?,?,?,?,?,?,?)', rows)
        conn.commit()
        conn.close()
        return len(rows)

    def read_kline(self, code):
        conn = sqlite3.connect(self.db)
        df = pd.read_sql_query(
            'SELECT date,open,close,high,low,volume,amount FROM etf_kline '
            'WHERE code=? ORDER BY date', conn, params=(code,))
        conn.close()
        return df

    def save_fflow(self, code, df):
        if df.empty:
            return 0
        conn = sqlite3.connect(self.db)
        conn.executemany(
            'INSERT OR REPLACE INTO etf_fflow(code,date,mf) VALUES(?,?,?)',
            [(code, d, m) for d, m in zip(df['date'], df['mf'])])
        conn.commit()
        conn.close()
        return len(df)

    def fflow_latest(self, code):
        conn = sqlite3.connect(self.db)
        r = conn.execute('SELECT MAX(date) FROM etf_fflow WHERE code=?', (code,)).fetchone()
        conn.close()
        return r[0] if r else None

    def read_fflow(self, code):
        conn = sqlite3.connect(self.db)
        df = pd.read_sql_query(
            'SELECT date,mf FROM etf_fflow WHERE code=? ORDER BY date', conn, params=(code,))
        conn.close()
        return df


def sync_klines(store=None, quiet=False):
    """给底池内所有 ETF 增量更新 K 线（最新则跳过；落后 1-5 天拉增量，更久全量重拉）。"""
    store = store or EtfStore()
    codes = [e['code'] for e in store.list_pool()]
    today = datetime.date.today()
    done = skip = 0
    for i, code in enumerate(codes):
        latest = store.kline_latest(code)
        count = KLINE_DAYS
        if latest:
            try:
                gap = (today - datetime.datetime.strptime(latest, '%Y-%m-%d').date()).days
            except ValueError:
                gap = 99
            if gap == 0:
                skip += 1
                continue
            if gap <= 5:
                count = 10
        df = fetch_kline(code, count)
        if not df.empty:
            store.save_kline(code, df)
            done += 1
        if (i + 1) % 20 == 0 and not quiet:
            print(f'  K线 {i+1}/{len(codes)} ...')
        time.sleep(0.3)
    if not quiet:
        print(f'K线更新完成：新增/更新 {done}，已最新跳过 {skip}，共 {len(codes)}')


def sync_fflows(store=None, quiet=False):
    """历史回补（尽力而为）：逐只拉东财 fflow 历史。限流时部分失败属正常，
    失败的标的下次运行会重试；日常增量请走 sync_flow_snapshot。"""
    store = store or EtfStore()
    codes = [e['code'] for e in store.list_pool()]
    today = datetime.date.today()
    done = skip = fail = 0
    for i, code in enumerate(codes):
        latest = store.fflow_latest(code)
        count = KLINE_DAYS
        if latest:
            try:
                gap = (today - datetime.datetime.strptime(latest, '%Y-%m-%d').date()).days
            except ValueError:
                gap = 99
            if gap == 0:
                skip += 1
                continue
            if gap <= 5:
                count = 10
        df = fetch_fflow(code, count)
        if not df.empty:
            store.save_fflow(code, df)
            done += 1
        else:
            fail += 1
        time.sleep(0.5)
    print(f'资金流回补完成：成功 {done}，已最新 {skip}，失败 {fail}（失败的下次自动重试）')


def sync_all():
    """完整同步：底池快照 → K 线增量 → 资金流快照累积"""
    spot = fetch_etf_spot()
    if not spot:
        print('[err] ETF 快照拉取失败')
        return
    pool = filter_pool(spot)
    print(f'全市场 ETF {len(spot)} 只，达到底池标准（额≥{AMOUNT_MIN/1e8:.0f}亿 且 规模≥{CAP_MIN/1e8:.0f}亿）{len(pool)} 只')
    store = EtfStore()
    store.save_pool(pool)
    sync_klines(store=store)
    sync_flow_snapshot(store=store)


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--pool' in args:
        s = fetch_etf_spot()
        p = filter_pool(s)
        print(f'底池 {len(p)} 只')
        EtfStore().save_pool(p)
    elif '--kline' in args:
        sync_klines()
    elif '--fflow' in args:
        sync_fflows()          # 历史回补（尽力而为）
    elif '--flow' in args:
        sync_flow_snapshot()   # 当日资金流快照
    else:
        sync_all()
