# -*- coding: utf-8 -*-
"""
板块数据层（plate_data.py）
===========================
数据源：**同花顺（akshare，脚本独立可用，无需 MCP/token，不限流）**
取代东财直连方案（东财高频必封 IP）：
  - 行业板块 90 个（stock_board_industry_name_ths）
  - 概念板块 375 个（stock_board_concept_name_ths）
  - 行业实时快照一次全量（stock_board_industry_summary_ths：涨跌幅/净流入/领涨股）
  - 板块指数 K 线（stock_board_industry_index_ths / stock_board_concept_index_ths，symbol=板块名称）

板块指数 K 线用于计算动量/分位/MACD/资金流信号（lib/metrics.py 的 _calc_index_metrics）。

用法：
  from plate_data import sync_ths_all, PlateStore
"""
import os, sqlite3, time, datetime, json, subprocess, sys, threading, re
import pandas as pd
import requests

os.environ.setdefault('TQDM_DISABLE', '1')   # 抑制 akshare 内部进度条输出

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'plate.db')
os.makedirs(os.path.dirname(DB), exist_ok=True)

H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
CLIST_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
KLINE_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'

# 板块类型
TYPE_INDUSTRY = 'industry'   # 行业板块
TYPE_CONCEPT = 'concept'     # 概念板块
FS_MAP = {TYPE_INDUSTRY: 'm:90+t:2', TYPE_CONCEPT: 'm:90+t:3'}

# K 线拉取长度（交易日数，约 1 年，够算 250 日分位）
THS_KLINE_DAYS = 320


def _get(url, params, retries=3, timeout=20):
    """带重试的 GET（东财接口偶发超时）"""
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=H)
            if r.status_code == 200 and r.text.strip().startswith('{'):
                return r.json()
        except Exception:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def fetch_plate_list(plate_type=TYPE_CONCEPT, max_pages=20):
    """拉某类板块全部清单。返回 [{code,name,zdf,mf}]（code=BKxxxx, zdf=涨跌幅%, mf=主力净流入）"""
    out = []
    for pn in range(1, max_pages + 1):
        j = _get(CLIST_URL, {
            'pn': pn, 'pz': 100, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': FS_MAP[plate_type], 'fields': 'f12,f14,f3,f62',
        })
        diff = ((j or {}).get('data') or {}).get('diff') or []
        if not diff:
            break
        for d in diff:
            out.append({
                'code': str(d.get('f12') or ''), 'name': str(d.get('f14') or ''),
                'zdf': d.get('f3'), 'mf': d.get('f62'),
            })
        if len(diff) < 100:
            break
        time.sleep(0.15)
    return out


def fetch_plate_kline(code, count=500):
    """拉板块指数日K（东财）。返回 DataFrame(date, open, close, high, low, volume, amount) 或空表。
    注意：东财高频请求会触发 502 封 IP，调用方必须限速（建议 0.3s+）。"""
    j = _get(KLINE_URL, {
        'secid': f'90.{code}',
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
        'klt': 101, 'fqt': 1, 'beg': '19900101', 'end': '20500101', 'lmt': count,
    })
    kl = ((j or {}).get('data') or {}).get('klines') or []
    if not kl:
        return pd.DataFrame()
    rows = []
    for line in kl:
        p = line.split(',')
        try:
            rows.append((p[0], float(p[1]), float(p[2]), float(p[3]),
                         float(p[4]), float(p[5]), float(p[6])))
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


QT_URL = 'https://qt.gtimg.cn/q='


# ================= 同花顺数据源（akshare，脚本独立可用）=================

def _ak():
    """延迟导入 akshare（仅清单/快照接口使用；K 线已改直连避免 MiniRacer 崩溃）"""
    import akshare as ak
    return ak


# ---------- 直连同花顺板块 K 线（替代 akshare，绕过 mini_racer/V8 崩溃） ----------

_THS_JS_CANDIDATES = [
    r'C:\Users\Zuoxin\.workbuddy\binaries\python\envs\default\Lib\site-packages\akshare\data\ths.js',
]


def _find_ths_js():
    """定位 akshare 包内的 ths.js（v 签名算法），找不到时尝试按包路径扫描"""
    for p in _THS_JS_CANDIDATES:
        if os.path.exists(p):
            return p
    try:
        import akshare
        pkg = os.path.dirname(akshare.__file__)
        for root, _, files in os.walk(pkg):
            if 'ths.js' in files:
                return os.path.join(root, 'ths.js')
    except Exception:
        pass
    return None


_v_code_lock = threading.Lock()
_v_code_cache = None


def _ths_v_code(force=False):
    """计算同花顺 v 签名：用子进程跑 MiniRacer（主进程不碰 V8，避免退出崩溃）。
    子进程算完 os._exit(0) 跳过 V8 清理。结果缓存（进程内）。"""
    global _v_code_cache
    if _v_code_cache and not force:
        return _v_code_cache
    with _v_code_lock:
        if _v_code_cache and not force:
            return _v_code_cache
        js_path = _find_ths_js()
        if not js_path:
            raise RuntimeError('未找到 akshare 的 ths.js（v 签名算法），无法直连同花顺接口')
        script = (
            'import py_mini_racer, os\n'
            'js = py_mini_racer.MiniRacer()\n'
            f'js.eval(open({js_path!r}, encoding="utf-8").read())\n'
            'print(js.call("v"))\n'
            'os._exit(0)\n'
        )
        try:
            out = subprocess.run([sys.executable, '-c', script],
                                 capture_output=True, text=True, timeout=30)
            v = out.stdout.strip()
            if v:
                _v_code_cache = v
                return v
        except Exception:
            pass
        # 回退：当前进程算（接受进程退出时 V8 清理崩溃风险，数据已拿到）
        import py_mini_racer
        js = py_mini_racer.MiniRacer()
        js.eval(open(js_path, encoding='utf-8').read())
        _v_code_cache = js.call('v')
        return _v_code_cache


_THS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36',
    'Referer': 'http://q.10jqka.com.cn',
    'Host': 'd.10jqka.com.cn',
}


def _ths_fetch_year(code, year, v_code, retries=2):
    """拉某板块某年的指数数据，返回原始行列表 [(date,open,close,high,low,vol,amt), ...]"""
    url = f'https://d.10jqka.com.cn/v4/line/bk_{code}/01/{year}.js'
    headers = dict(_THS_HEADERS, Cookie=f'v={v_code}')
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            text = r.text
            i0 = text.find('{')
            if i0 < 0:
                return []
            j = json.loads(text[i0:-1])
            data = j.get('data', '')
            if not data:
                return []
            rows = []
            for line in data.split(';'):
                p = line.split(',')
                if len(p) < 7:
                    continue
                try:
                    rows.append((p[0], float(p[1]), float(p[4]),
                                 float(p[2]), float(p[3]),
                                 float(p[5]), float(p[6])))
                except (ValueError, IndexError):
                    continue
            return rows
        except Exception:
            if i < retries - 1:
                time.sleep(0.8)
    return []


def fetch_ths_kline_direct(code, start_date=None, end_date=None, count=THS_KLINE_DAYS, v_code=None):
    """直连同花顺板块指数日 K（不经过 akshare/MiniRacer，线程安全，可多线程并发）。
    code: 板块代码（plate_list.code，如 881121 / 308614）。
    start_date 缺省 = 最近 count 天；返回 DataFrame(date,open,close,high,low,volume,amount)。"""
    v_code = v_code or _ths_v_code()
    end = end_date or datetime.date.today().strftime('%Y%m%d')
    if start_date is None:
        start = (datetime.date.today() - datetime.timedelta(days=int(count * 1.7))).strftime('%Y%m%d')
    else:
        start = start_date
    rows = []
    begin_year = int(start[:4])
    cur_year = int(end[:4])
    for year in range(begin_year, cur_year + 1):
        rows.extend(_ths_fetch_year(code, year, v_code))
    if not rows:
        return pd.DataFrame()
    # 日期过滤（YYYYMMDD 字符串可比较）
    rows = [r for r in rows if start <= r[0] <= end]
    rows.sort(key=lambda x: x[0])
    return pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


def _code_by_name(name, plate_type):
    """按板块名查库拿代码（直连需要 bk_code）"""
    conn = sqlite3.connect(DB)
    r = conn.execute('SELECT code FROM plate_list WHERE name=? AND type=?',
                     (name, plate_type)).fetchone()
    conn.close()
    return r[0] if r else None


def fetch_concept_inner_code(code, retries=2):
    """概念板块：访问详情页提取真正的指数代码（bk_{inner_code} 才有效；清单 code 只用于详情页）"""
    url = f'https://q.10jqka.com.cn/gn/detail/code/{code}'
    h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for i in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=15)
            if r.status_code == 200:
                m = re.search(r'id="clid"[^>]*value=[\'"](\d+)[\'"]', r.text)
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(0.8)
    return None


def fetch_ths_kline_direct(code, start_date=None, end_date=None, count=THS_KLINE_DAYS,
                           v_code=None, inner_code=None):
    """直连同花顺板块指数日 K（不经过 akshare/MiniRacer，线程安全，可多线程并发）。
    code: 板块清单代码（行业 881xxx 直接可用；概念需 inner_code，见下）。
    inner_code: 概念板块的真实指数代码（bk_{inner_code}），缺省时用 code。
    start_date 缺省 = 最近 count 天；返回 DataFrame(date,open,close,high,low,volume,amount)。"""
    v_code = v_code or _ths_v_code()
    bk = inner_code or code
    end = end_date or datetime.date.today().strftime('%Y%m%d')
    if start_date is None:
        start = (datetime.date.today() - datetime.timedelta(days=int(count * 1.7))).strftime('%Y%m%d')
    else:
        start = start_date
    rows = []
    begin_year = int(start[:4])
    cur_year = int(end[:4])
    for year in range(begin_year, cur_year + 1):
        rows.extend(_ths_fetch_year(bk, year, v_code))
    if not rows:
        return pd.DataFrame()
    # 日期过滤（YYYYMMDD 字符串可比较）
    rows = [r for r in rows if start <= r[0] <= end]
    rows.sort(key=lambda x: x[0])
    return pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


def fetch_ths_kline(name, plate_type, start_date=None, end_date=None, count=THS_KLINE_DAYS):
    """同花顺板块指数日 K（兼容旧接口：按名称转 code 后直连；概念板块自动解析 inner_code）。
    start_date 缺省 = 拉最近 count 天（约 1 年全量）；传入 %Y%m%d = 只拉该日起数据（增量补缺失 K 线）。"""
    code = _code_by_name(name, plate_type)
    if not code:
        return pd.DataFrame()
    inner = None
    if plate_type == TYPE_CONCEPT:
        st = PlateStore()
        inner = st.get_inner(code)
        if not inner:
            inner = fetch_concept_inner_code(code)
            if inner:
                st.set_inner(code, inner)
    return fetch_ths_kline_direct(code, start_date=start_date, end_date=end_date,
                                  count=count, inner_code=inner)


def fetch_ths_lists(retries=4):
    """同花顺板块清单：行业 90 + 概念 375。返回 (industry_list, concept_list)。
    网络偶发断连时重试（先成功才返回，调用方据此决定是否替换旧数据）。"""
    ak = _ak()
    last = None
    for i in range(retries):
        try:
            ind = ak.stock_board_industry_name_ths()
            con = ak.stock_board_concept_name_ths()
            ind_list = [{'code': str(r['code']), 'name': str(r['name'])} for _, r in ind.iterrows()]
            con_list = [{'code': str(r['code']), 'name': str(r['name'])} for _, r in con.iterrows()]
            if ind_list and con_list:
                return ind_list, con_list
            last = '空结果'
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
        print(f'  [retry] 清单拉取失败 {i+1}/{retries}: {last}', flush=True)
        time.sleep(2.5 * (i + 1))
    raise RuntimeError(f'同花顺板块清单拉取失败: {last}')


def fetch_ths_industry_snapshot():
    """行业板块实时快照（一次全量）。返回 {name: {zdf, net_in, lead}}"""
    ak = _ak()
    df = ak.stock_board_industry_summary_ths()
    out = {}
    for _, r in df.iterrows():
        try:
            out[str(r['板块'])] = {
                'zdf': float(r['涨跌幅']),
                'net_in': float(r['净流入']) if pd.notna(r['净流入']) else None,
                'lead': str(r['领涨股']) if pd.notna(r['领涨股']) else '',
            }
        except (ValueError, KeyError):
            continue
    return out


def _fetch_worker(args):
    """线程 worker：只做网络拉取（直连接口纯 requests，线程安全可并发）。
    增量 start_date = 库内最新 + 1 天；增量空 = 当天数据未出/停更，跳过（不回退全量）；
    首次（无历史）空结果重试一次全量。返回 (p, df, inc)。"""
    p, latest, inner = args
    inc = latest is not None
    start = None
    if inc:
        start = (datetime.date.fromisoformat(latest)
                 + datetime.timedelta(days=1)).strftime('%Y%m%d')
    try:
        df = fetch_ths_kline_direct(p['code'], start_date=start, inner_code=inner)
        if (df is None or df.empty) and not inc:
            df = fetch_ths_kline_direct(p['code'], inner_code=inner)   # 首次全量重试一次
        return p, df, inc
    except Exception as e:
        return p, None, inc


def sync_ths_all(store=None, gap=0.15, workers=8):
    """全量同步同花顺板块数据到 plate.db：清单 + 行业快照 + 全部板块 K 线。
    增量优化：只拉每个板块缺失区间的 K 线（start_date=库内最新+1 天，不再全量 545 天）。
    并发：K 线改用**直连接口**（绕过 akshare 的 mini_racer/V8，纯 requests 线程安全），
    多线程并发拉取，主线程串行写库避免 SQLite 锁。
    返回 {industry, concept, failed} 统计。脚本独立运行，无会话依赖。"""
    store = store or PlateStore()
    ak = _ak()
    print('== 1/3 拉取同花顺板块清单 ==', flush=True)
    ind_list, con_list = fetch_ths_lists()
    print(f'  行业 {len(ind_list)} / 概念 {len(con_list)}', flush=True)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    # 先清理旧清单（同花顺体系替换旧数据源），再写入新清单
    conn = sqlite3.connect(store.db)
    conn.execute("DELETE FROM plate_list WHERE type IN ('industry','concept')")
    conn.commit(); conn.close()
    for p in ind_list:
        store.save_list([{**p, 'zdf': None, 'mf': None}], TYPE_INDUSTRY)
    for p in con_list:
        store.save_list([{**p, 'zdf': None, 'mf': None}], TYPE_CONCEPT)

    print('== 2/3 行业实时快照 ==', flush=True)
    snap = fetch_ths_industry_snapshot()
    conn = sqlite3.connect(store.db)
    for name, s in snap.items():
        conn.execute('UPDATE plate_list SET zdf=?, mf=? WHERE name=? AND type=?',
                     (s['zdf'], s['net_in'], name, TYPE_INDUSTRY))
    conn.commit(); conn.close()
    print(f'  行业快照 {len(snap)} 个', flush=True)

    print('== 3/3 批量拉板块 K 线（增量 + 多线程并发，直连接口）==', flush=True)
    stats = {'industry': 0, 'concept': 0, 'failed': []}
    plates = store.list_plates(TYPE_INDUSTRY) + store.list_plates(TYPE_CONCEPT)
    total = len(plates)
    today = datetime.date.today().strftime('%Y-%m-%d')
    # 一次查出所有板块最新日期（避免逐板块查询）
    conn = sqlite3.connect(store.db)
    latest_map = dict(conn.execute(
        'SELECT code, MAX(date) FROM plate_kline GROUP BY code').fetchall())
    conn.close()
    todo = []
    for p in plates:
        if latest_map.get(p['code']) and latest_map[p['code']] >= today:
            stats[p['type']] += 1
        else:
            todo.append(p)
    print(f'  待更新 {len(todo)}/{total} 个板块（已最新跳过）', flush=True)
    if not todo:
        print(f'完成：行业 {stats["industry"]} 概念 {stats["concept"]} 失败 0', flush=True)
        return stats

    def apply_one(p, df, inc):
        """主线程：写库 + 概念当日涨跌幅。增量空 = 无新数据跳过（不算失败）；首次全量空才算失败"""
        if df is None:
            stats['failed'].append(p['name'])
            return
        if len(df) == 0:
            if not inc:
                stats['failed'].append(p['name'])
            return
        if not inc and len(df) < 60:
            stats['failed'].append(p['name'])
            return
        store.save_kline(p['code'], df)
        stats[p['type']] += 1
        if p['type'] == TYPE_CONCEPT:
            conn = sqlite3.connect(store.db)
            rows = conn.execute(
                'SELECT close FROM plate_kline WHERE code=? ORDER BY date DESC LIMIT 2',
                (p['code'],)).fetchall()
            if len(rows) >= 2 and rows[0][0] and rows[1][0]:
                zdf = round((rows[0][0] / rows[1][0] - 1) * 100, 2)
                conn.execute('UPDATE plate_list SET zdf=? WHERE code=?', (zdf, p['code']))
            conn.commit(); conn.close()

    _ths_v_code()   # 预热 v 签名（子进程计算，主进程不碰 V8）
    # 概念板块预取 inner_code（缓存缺失才抓详情页，一次请求/板块；后续同步零开销）
    need_inner = [p for p in todo if p['type'] == TYPE_CONCEPT and not store.get_inner(p['code'])]
    if need_inner:
        print(f'  解析 {len(need_inner)} 个概念板块指数代码（首次，约 2 分钟）...', flush=True)
        for i, p in enumerate(need_inner, 1):
            ic = fetch_concept_inner_code(p['code'])
            if ic:
                store.set_inner(p['code'], ic)
            if i % 50 == 0 or i == len(need_inner):
                print(f'    [{i}/{len(need_inner)}]', flush=True)
            time.sleep(0.1)
    inner_map = {p['code']: store.get_inner(p['code']) for p in todo}
    args = [(p, latest_map.get(p['code']), inner_map.get(p['code'])) for p in todo]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (p, df, inc) in enumerate(ex.map(_fetch_worker, args), 1):
            apply_one(p, df, inc)
            if i % 50 == 0 or i == len(todo):
                print(f'  [{i}/{len(todo)}] 行业{stats["industry"]} 概念{stats["concept"]} '
                      f'失败{len(stats["failed"])}', flush=True)
            time.sleep(gap)
    print(f'完成：行业 {stats["industry"]} 概念 {stats["concept"]} 失败 {len(stats["failed"])}', flush=True)
    if stats['failed']:
        print('  失败:', stats['failed'][:20], flush=True)
    return stats


def fetch_tencent_quotes(codes):
    """批量拉板块实时行情（腾讯 qt.gtimg.cn，稳定）。
    codes: 板块代码列表（pt02GNxxxx / pt018xxxx / pt02xxxxxx）。
    返回 {code: {name, price, zdf, zd, high, low, vol, hsl, time}}"""
    if not codes:
        return {}
    import requests as _r
    out = {}
    for i in range(0, len(codes), 50):   # 每批 50 个
        batch = codes[i:i + 50]
        try:
            r = _r.get(QT_URL + ','.join(batch), timeout=15,
                       headers={'User-Agent': 'Mozilla/5.0'})
            r.encoding = 'gbk'
            for line in r.text.strip().split(';'):
                if '=' not in line:
                    continue
                key, _, val = line.partition('=')
                code = key.replace('v_', '').strip().strip('\n')
                parts = val.strip('"').split('~')
                if len(parts) < 35:
                    continue
                try:
                    out[code] = {
                        'name': parts[1], 'price': float(parts[3]),
                        'zdf': float(parts[32]), 'zd': float(parts[31]),
                        'high': float(parts[33]), 'low': float(parts[34]),
                        'vol': float(parts[36] or 0), 'hsl': float(parts[38] or 0),
                        'lb': float(parts[39] or 0), 'time': parts[30],
                    }
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass
        import time as _t
        _t.sleep(0.2)
    return out


class PlateStore:
    """本地缓存：plate_list(code,name,type,zdf,mf) + plate_kline(code,date,o,c,h,l,v,a)"""

    def __init__(self, db=DB):
        self.db = db
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db)
        conn.execute('''CREATE TABLE IF NOT EXISTS plate_list(
            code TEXT PRIMARY KEY, name TEXT, type TEXT,
            zdf REAL, mf REAL, fetched_at TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS plate_kline(
            code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
            volume REAL, amount REAL, PRIMARY KEY(code, date))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS plate_inner(
            code TEXT PRIMARY KEY, inner_code TEXT, fetched_at TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_pk_code ON plate_kline(code)')
        conn.commit()
        conn.close()

    def save_list(self, plates, plate_type):
        conn = sqlite3.connect(self.db)
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        conn.executemany(
            'INSERT OR REPLACE INTO plate_list(code,name,type,zdf,mf,fetched_at) VALUES(?,?,?,?,?,?)',
            [(p['code'], p['name'], plate_type, p['zdf'], p['mf'], now) for p in plates])
        conn.commit()
        conn.close()

    def list_plates(self, plate_type):
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            'SELECT code,name,type,zdf,mf,fetched_at FROM plate_list WHERE type=? ORDER BY name',
            (plate_type,)).fetchall()
        conn.close()
        return [{'code': r[0], 'name': r[1], 'type': r[2], 'zdf': r[3],
                 'mf': r[4], 'fetched_at': r[5]} for r in rows]

    def kline_latest(self, code):
        conn = sqlite3.connect(self.db)
        r = conn.execute('SELECT MAX(date) FROM plate_kline WHERE code=?', (code,)).fetchone()
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
            'INSERT OR REPLACE INTO plate_kline(code,date,open,close,high,low,volume,amount) '
            'VALUES(?,?,?,?,?,?,?,?)', rows)
        conn.commit()
        conn.close()
        return len(rows)

    def read_kline(self, code):
        conn = sqlite3.connect(self.db)
        df = pd.read_sql_query(
            'SELECT date,open,close,high,low,volume,amount FROM plate_kline '
            'WHERE code=? ORDER BY date', conn, params=(code,))
        conn.close()
        return df

    def get_inner(self, code):
        conn = sqlite3.connect(self.db)
        r = conn.execute('SELECT inner_code FROM plate_inner WHERE code=?', (code,)).fetchone()
        conn.close()
        return r[0] if r else None

    def set_inner(self, code, inner_code):
        conn = sqlite3.connect(self.db)
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        conn.execute('INSERT OR REPLACE INTO plate_inner(code,inner_code,fetched_at) VALUES(?,?,?)',
                     (code, inner_code, now))
        conn.commit()
        conn.close()


def refresh_all(plate_type=TYPE_CONCEPT, limit=None, store=None, only_codes=None):
    """全量/增量拉某类板块的 K 线。返回 (updated_codes, failed_codes)"""
    store = store or PlateStore()
    plates = store.list_plates(plate_type)
    if only_codes:
        plates = [p for p in plates if p['code'] in only_codes]
    if limit:
        plates = plates[:limit]
    updated, failed = [], []
    for i, p in enumerate(plates, 1):
        latest = store.kline_latest(p['code'])
        if latest and latest >= datetime.date.today().strftime('%Y-%m-%d'):
            continue
        df = fetch_plate_kline(p['code'])
        if df.empty:
            failed.append(p['code'])
            continue
        store.save_kline(p['code'], df)
        updated.append(p['code'])
        if i % 50 == 0 or i == len(plates):
            print(f'  [{i}/{len(plates)}] {p["name"]:<14} {len(df)}根', flush=True)
        time.sleep(0.12)
    return updated, failed


if __name__ == '__main__':
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else TYPE_CONCEPT
    print(f'拉取板块清单（{t}）...')
    store = PlateStore()
    plates = fetch_plate_list(t)
    store.save_list(plates, t)
    print(f'板块清单: {len(plates)} 个，已缓存到 {DB}')
    print('增量拉取 K 线...')
    upd, fail = refresh_all(t, store=store)
    print(f'完成: 更新 {len(upd)} 个，失败 {len(fail)} 个')
