# -*- coding: utf-8 -*-
"""
持仓基金汇总库（fund_data.py）
==============================
持仓驱动的数据层：从 portfolio.db 聚合当前持仓，**直接用场外基金代码拉净值**
（天天基金 f10/lsjz），指数/红利类按基金名自动关联指数估值源（PE/股息率，尽力而为）。
按持仓分类（指数/红利/行业）用 metrics 三套评分 + 决策翻译，供报告使用。

数据库：data/fund_data.db
  - holdings   持仓快照（portfolio.db 聚合，流水变更/报告运行时同步）
  - nav        场外基金净值日线（code + date + nav）
  - valuation  指数估值（symbol + date + pe_ttm [+ dividend_yield]）

分类（score_type）：
  - 指数（宽基）：定投估值驱动 → 买入倍数（×1.5/×1.0/×0.5）
  - 红利（高股息）：均值回归波段 → 买入区/持有/卖出区
  - 行业（被动+主动已合并）：趋势波段（20日动量）→ 持有/关注/减仓/离场

用法：
  python fund_data.py --sync --update --analyze
"""
import os, sys, sqlite3, datetime
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))

from metrics import _calc_index_metrics, calc_dd, calc_vol, score_index, score_dividend, score_trend

PORTFOLIO_DB = os.path.join(BASE, 'data', 'portfolio.db')
FUND_DB = os.path.join(BASE, 'data', 'fund_data.db')
MIN_BARS = 65          # 少于 65 根净值不计算指标
MAX_NAV = 300          # 每只基金保留的净值条数（约 1.2 年交易日，够 250 日分位；接口每页 20 条=15 页）

# 指数估值源：基金名关键词 → (指数代码, 乐咕中文名)。用于指数/红利拉 PE 估值分位。
INDEX_VAL = {
    '沪深300': ('000300', '沪深300'),
    '中证500': ('000905', '中证500'),
    '创业板':   ('399006', '创业板指'),
    '中证红利': ('000922', '中证红利'),
    '上证红利': ('000015', '上证红利'),
}


def conn():
    c = sqlite3.connect(FUND_DB)
    c.execute('''CREATE TABLE IF NOT EXISTS holdings(
        code TEXT PRIMARY KEY, name TEXT, amt REAL, category TEXT, updated_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nav(
        code TEXT, date TEXT, nav REAL, PRIMARY KEY(code, date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS valuation(
        symbol TEXT, date TEXT, pe_ttm REAL, dividend_yield REAL,
        PRIMARY KEY(symbol, date))''')
    c.commit()
    return c


# ================= 1. 分类判定 =================
def classify(name, cat='行业'):
    """按基金名判定三类：红利 / 指数 / 行业（被动与主动已合并为行业；category 为流水原始分类兜底）"""
    if '红利' in name:
        return '红利'
    if cat == '指数':
        return '指数'
    return '行业'


# ================= 2. 持仓同步 =================
def sync_holdings():
    """从 portfolio.db 聚合当前持仓 → holdings 表（分类归一），返回持仓 dict"""
    pos = {}
    if os.path.exists(PORTFOLIO_DB):
        c0 = sqlite3.connect(PORTFOLIO_DB)
        rows = c0.execute("SELECT category,fund,code,direction,amount FROM trans ORDER BY date").fetchall()
        c0.close()
        for cat, name, code, direction, amt in rows:
            if not code or not direction or code == 'ZFB' or '余额宝' in name:
                continue
            p = pos.setdefault(code, {'name': name, 'code': code, 'amt': 0.0, 'category': cat})
            if direction in ('买入', '转入', '申购', '加仓', '收益'):
                p['amt'] += amt
            elif direction in ('卖出', '赎回', '减仓', '转出'):
                p['amt'] -= amt
    pos = {c: p for c, p in pos.items() if p['amt'] > 1}
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    c = conn()
    c.execute('DELETE FROM holdings')
    c.executemany('INSERT OR REPLACE INTO holdings VALUES(?,?,?,?,?)',
                  [(p['code'], p['name'], p['amt'], classify(p['name'], p['category']), now)
                   for p in pos.values()])
    c.commit(); c.close()
    return pos


def list_holdings():
    """读持仓快照（表空则先同步）"""
    c = conn()
    n = c.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]
    c.close()
    if n == 0:
        sync_holdings()
    c = conn()
    rows = c.execute('SELECT code,name,amt,category FROM holdings ORDER BY amt DESC').fetchall()
    c.close()
    return [{'code': r[0], 'name': r[1], 'amt': r[2], 'category': r[3]} for r in rows]


# ================= 3. 净值拉取（场外基金，天天基金）=================
def _fetch_nav(code, count=MAX_NAV):
    """天天基金历史净值（分页拉取）：返回 [(date, nav), ...] 升序；失败返回 []"""
    import requests
    url = 'https://api.fund.eastmoney.com/f10/lsjz'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://fundf10.eastmoney.com/'}
    rows = []
    page, page_size = 1, 20           # 接口固定每页最多 20 条（pageSize 参数无效），用 pageIndex 翻页
    while len(rows) < count and page <= 50:
        params = {'fundCode': code, 'pageIndex': page, 'pageSize': page_size}
        r = requests.get(url, params=params, timeout=20, headers=headers)
        if r.status_code != 200 or not r.text.strip().startswith('{'):
            break
        lst = (r.json().get('Data') or {}).get('LSJZList') or []
        if not lst:
            break
        for it in lst:
            try:
                rows.append((it['FSRQ'], float(it['DWJZ'])))
            except (ValueError, KeyError):
                continue
        if len(lst) < page_size:
            break
        page += 1
    rows.sort(key=lambda x: x[0])
    return rows


def fetch_nav(code, force=False):
    """拉净值入 nav 表（增量优化：先拉 1 页快速判断，库内最新 >= 接口最新则跳过；
    需要更新才全量分页拉）。返回写入条数。"""
    import requests
    url = 'https://api.fund.eastmoney.com/f10/lsjz'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://fundf10.eastmoney.com/'}
    # 快速检查最新日期（1 页 20 条）
    try:
        r = requests.get(url, params={'fundCode': code, 'pageIndex': 1, 'pageSize': 20},
                         timeout=15, headers=headers)
        lst = (r.json().get('Data') or {}).get('LSJZList') or [] if r.text.strip().startswith('{') else []
        latest_api = lst[0]['FSRQ'] if lst else None
    except Exception:
        latest_api = None
    if not latest_api:
        return 0
    c = conn()
    db_latest = c.execute('SELECT MAX(date) FROM nav WHERE code=?', (code,)).fetchone()[0]
    c.close()
    if not force and db_latest and db_latest >= latest_api:
        return 0
    rows = _fetch_nav(code)
    if not rows:
        return 0
    c = conn()
    for d, nav in rows:
        c.execute('INSERT OR REPLACE INTO nav VALUES(?,?,?)', (code, d, nav))
    c.commit(); c.close()
    return len(rows)


def ensure_updated(holdings=None):
    """对全部持仓拉取/增量更新净值，返回新增条数"""
    holdings = holdings or list_holdings()
    total = 0
    for h in holdings:
        try:
            n = fetch_nav(h['code'])
            if n:
                total += n
        except Exception as e:
            print(f'  [warn] {h["name"]} 净值拉取失败: {type(e).__name__}: {e}')
    return total


# ================= 4. 指数估值（PE 分位 / 股息率，尽力而为）=================
def _fetch_index_valuation(symbol, name):
    """拉指数 PE 历史（akshare 乐咕），返回 [(date, pe_ttm), ...]；失败返回 []"""
    try:
        import akshare as ak
        df = ak.stock_index_pe_lg(symbol=name)
        out = []
        for _, r in df.iterrows():
            try:
                out.append((str(r['日期'])[:10], float(r['滚动市盈率'])))
            except (ValueError, KeyError):
                continue
        return out
    except Exception:
        return []


def fetch_valuation(symbol, name):
    """拉指数估值存入 valuation 表，返回写入条数（失败 0）"""
    rows = _fetch_index_valuation(symbol, name)
    if not rows:
        return 0
    c = conn()
    n = 0
    for d, pe in rows:
        c.execute('INSERT OR REPLACE INTO valuation(symbol,date,pe_ttm) VALUES(?,?,?)',
                  (symbol, d, pe))
        n += 1
    c.commit(); c.close()
    return n


def get_pe_percentile(symbol):
    """当前 PE 的历史百分位(0-100)，数据不足返回 None"""
    c = conn()
    rows = c.execute('SELECT pe_ttm FROM valuation WHERE symbol=? AND pe_ttm IS NOT NULL '
                     'ORDER BY date', (symbol,)).fetchall()
    c.close()
    if len(rows) < 60:
        return None
    cur = rows[-1][0]
    hist = [r[0] for r in rows]
    return round(sum(1 for v in hist if v <= cur) / len(hist) * 100, 1)


def valuation_symbol(name):
    """按基金名找估值源 (symbol, 中文名)；找不到返回 None"""
    for kw, val in INDEX_VAL.items():
        if kw in name:
            return val
    return None


# ================= 5. 分析 =================
def analyze_data(holdings=None):
    """读持仓+净值+估值 → 按分类算信号与决策。
    返回 [{fund, code, amt, category, score, decision, 指标..., warnings}]"""
    holdings = holdings or list_holdings()
    out = []
    for h in holdings:
        cat = h['category']
        row = {
            'fund': h['name'], 'code': h['code'], 'amt': h['amt'], 'category': cat,
            'date': '', 'score': None, 'decision': '—',
            'mom5': None, 'mom20': None, 'mom60': None, 'pct250': None,
            'macd_bull': False, 'macd_weak': False, 'dd': None, 'warnings': [],
        }
        # 净值
        c = conn()
        df = pd.read_sql_query('SELECT date,nav FROM nav WHERE code=? ORDER BY date',
                               c, params=(h['code'],))
        c.close()
        if len(df) < MIN_BARS:
            row['warnings'].append(f'净值数据不足（{len(df)} 根 < {MIN_BARS}），等待拉取')
            out.append(row)
            continue
        s = df['nav'].astype(float).reset_index(drop=True)
        o = s.copy()                       # 净值无开盘价，用自身
        v = pd.Series([0.0] * len(s))      # 净值无成交量
        met = _calc_index_metrics(s, o, v, cat)
        met['flow20'] = None               # 净值无成交量 → 资金流缺失
        met['flow5'] = None
        met['dd'] = round(calc_dd(s), 1)
        met['vol'] = round(calc_vol(s), 1)
        row.update({
            'date': met['date'], 'mom5': met['mom5'], 'mom20': met['mom20'], 'mom60': met['mom60'],
            'pct250': met['pct250'], 'macd_bull': met['macd_bull'], 'macd_weak': met['macd_weakening'],
            'dd': met['dd'],
        })
        # 分类评分 + 决策
        if cat == '指数':
            pe_pct = None
            vs = valuation_symbol(h['name'])
            if vs:
                pe_pct = get_pe_percentile(vs[0])
            r = score_index(met, pe_pct)
            row['score'] = r['score']; row['decision'] = r['decision']
            row['pct_used'] = r['pct_used']
            row['src'] = 'PE分位' if pe_pct is not None else '价格分位'
            if pe_pct is None:
                row['warnings'].append('未取到 PE 估值，用价格分位兜底')
        elif cat == '红利':
            r = score_dividend(met)         # 股息率利差暂缺失（中性处理），后续补估值
            row['score'] = r['score']; row['decision'] = r['decision']
        elif cat == '行业':
            r = score_trend(met)            # 趋势类（被动+主动已合并，统一 20 日动量尺度）
            row['score'] = r['score']; row['decision'] = r['decision']
        # 预警
        if met['mom20'] < 0 and not met['macd_bull']:
            row['warnings'].append('⚠️ 动量转负且MACD空头——趋势走弱')
        if met['macd_weakening']:
            row['warnings'].append('🟠 MACD红柱衰竭——涨势减速')
        if row['pct250'] is not None and row['pct250'] > 0.7:
            row['warnings'].append(f"📈 历史分位 {row['pct250']:.0%} 偏高")
        if row['pct250'] is not None and row['pct250'] < 0.3:
            row['warnings'].append(f"📉 历史分位 {row['pct250']:.0%} 低位")
        if not row['warnings']:
            row['warnings'].append('➖ 中性区间，无特别预警')
        out.append(row)
    out.sort(key=lambda r: -r['amt'])
    return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--sync', action='store_true', help='同步持仓快照')
    ap.add_argument('--update', action='store_true', help='拉取/增量更新净值')
    ap.add_argument('--analyze', action='store_true', help='输出分析表')
    args = ap.parse_args()
    if args.sync or (not args.update and not args.analyze):
        pos = sync_holdings()
        print(f'持仓同步: {len(pos)} 只')
    if args.update:
        n = ensure_updated()
        print(f'净值更新: 新增 {n} 条')
    if args.analyze:
        for r in analyze_data():
            sc = f"{r['score']:.0f}" if r['score'] is not None else '—'
            print(f"{r['category']:<4} {r['fund']:<24} ¥{r['amt']:>8,.0f} | 分{r['score'] if False else sc:>3} | {r['decision']}")
