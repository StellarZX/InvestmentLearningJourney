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
import os, sqlite3, time, datetime
import pandas as pd
import requests

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
    """延迟导入 akshare（首次使用才加载）"""
    import akshare as ak
    return ak


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


def fetch_ths_kline(name, plate_type, count=THS_KLINE_DAYS):
    """同花顺板块指数日 K（symbol=板块名称）。返回 DataFrame(date,open,close,high,low,volume,amount) 或空表"""
    ak = _ak()
    end = datetime.date.today().strftime('%Y%m%d')
    start = (datetime.date.today() - datetime.timedelta(days=int(count * 1.7))).strftime('%Y%m%d')
    try:
        if plate_type == TYPE_INDUSTRY:
            df = ak.stock_board_industry_index_ths(symbol=name, start_date=start, end_date=end)
        else:
            df = ak.stock_board_concept_index_ths(symbol=name, start_date=start, end_date=end)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        try:
            rows.append((str(r['日期']), float(r['开盘价']), float(r['收盘价']),
                         float(r['最高价']), float(r['最低价']),
                         float(r['成交量']), float(r['成交额'])))
        except (ValueError, KeyError):
            continue
    return pd.DataFrame(rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


def sync_ths_all(store=None, gap=0.35):
    """全量同步同花顺板块数据到 plate.db：清单 + 行业快照 + 全部板块 K 线。
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

    print('== 3/3 批量拉板块 K 线 ==', flush=True)
    stats = {'industry': 0, 'concept': 0, 'failed': []}
    plates = store.list_plates(TYPE_INDUSTRY) + store.list_plates(TYPE_CONCEPT)
    total = len(plates)
    for i, p in enumerate(plates, 1):
        # 增量：该板块 K 线已是最新交易日则跳过
        latest = store.kline_latest(p['code'])
        if latest and latest >= datetime.date.today().strftime('%Y-%m-%d'):
            stats[p['type']] += 1
            if i % 50 == 0 or i == total:
                print(f'  [{i}/{total}] (增量跳过) 行业{stats["industry"]} 概念{stats["concept"]}', flush=True)
            continue
        try:
            df = fetch_ths_kline(p['name'], p['type'])
            if len(df) < 60:
                # 重试一次（网络偶发断连）
                time.sleep(1.5)
                df = fetch_ths_kline(p['name'], p['type'])
            if len(df) >= 60:
                n = store.save_kline(p['code'], df)
                stats[p['type']] += 1
                # 概念当日涨跌幅从 K 线最后两根计算
                if p['type'] == TYPE_CONCEPT and n >= 2:
                    c = df['close'].astype(float)
                    zdf = round((c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
                    conn = sqlite3.connect(store.db)
                    conn.execute('UPDATE plate_list SET zdf=? WHERE code=?', (zdf, p['code']))
                    conn.commit(); conn.close()
            else:
                stats['failed'].append(p['name'])
        except Exception as e:
            stats['failed'].append(f"{p['name']}({type(e).__name__})")
        if i % 25 == 0 or i == total:
            print(f'  [{i}/{total}] 行业{stats["industry"]} 概念{stats["concept"]} 失败{len(stats["failed"])}', flush=True)
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
