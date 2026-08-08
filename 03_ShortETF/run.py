# -*- coding: utf-8 -*-
"""
ETF 动量策略自动化管线
========================
一次运行完成: 拉取数据 -> 更新本地 SQLite -> 计算信号 -> 生成操作策略

用法:
    python run.py                 # 全流程（拉数据+算信号+出策略）
    python run.py --update        # 仅更新数据
    python run.py --signal        # 仅用库内数据算信号+出策略（不联网）
    python run.py --universe 19   # 用小池(19只) / 默认100只
    python run.py --top 3         # TOP N 持仓数量

输出:
    - etf_strategy.db   本地数据库(kline/signals/strategy_log 表)
    - strategy_latest.json  最新操作策略
    - strategy_report.html  可视化策略报告
"""
import os, sys, glob, json, subprocess, sqlite3, argparse, datetime
import pandas as pd
import numpy as np

# ================= 配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(BASE_DIR, 'lib')       # 依赖：otc_map.py / top100_etf.json
DATA_DIR = os.path.join(BASE_DIR, 'data')     # 数据：etf_strategy.db / fee_db.json
REPORT_DIR = os.path.join(BASE_DIR, 'reports')  # 历史报告（带日期）
DB_PATH = os.path.join(DATA_DIR, 'etf_strategy.db')
NODE = r"C:\Users\Zuoxin\.workbuddy\binaries\node\versions\22.22.2\node.exe"
WESTOCK_CLI = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked\resources\builtin-skills\westock-data\scripts\index.js"
OUT_JSON = os.path.join(BASE_DIR, 'strategy_latest.json')
OUT_HTML = os.path.join(BASE_DIR, 'strategy_report.html')
TRADING_DAYS = 244
KLINE_LIMIT = 130  # 每次拉取根数（约半年+，够算60日均线）
for _d in (LIB_DIR, DATA_DIR, REPORT_DIR):
    os.makedirs(_d, exist_ok=True)

def find_dep(name):
    """在脚本目录与 lib/ 中定位依赖文件，找不到返回 None"""
    for d in (BASE_DIR, LIB_DIR):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None

def dated_out_paths():
    """带日期的输出文件名（存 reports/）：strategy_YYYYMMDD.json / strategy_YYYYMMDD.html"""
    d = datetime.datetime.now().strftime('%Y%m%d')
    return (os.path.join(REPORT_DIR, f'strategy_{d}.json'),
            os.path.join(REPORT_DIR, f'strategy_{d}.html'))

# 100 只池（从 lib/top100_etf.json 读取，若不存在回退小池）
def load_universe(use_small=False):
    if not use_small:
        pool_file = find_dep('top100_etf.json')
        if pool_file:
            d = json.load(open(pool_file, encoding='utf-8'))
            out = {}
            for c, v in d.items():
                # v 可能是字符串（名称）或字典（含 name 字段）
                out[c] = v if isinstance(v, str) else v.get('name', c)
            return out
    # 小池: data/ 目录里的 19 只
    names = {
        "sh510300": "沪深300", "sh510500": "中证500", "sz159915": "创业板",
        "sh588000": "科创50", "sh588200": "科创芯片", "sh518880": "黄金",
        "sh515880": "通信", "sh512880": "证券", "sz159516": "半导体设备",
        "sz159919": "沪深300嘉实", "sh513100": "纳指", "sh513180": "恒生科技",
        "sh512690": "酒", "sz159928": "消费", "sh512170": "医疗",
        "sh512010": "医药", "sh516160": "新能源", "sh512760": "芯片",
        "sh515030": "新能源车",
    }
    return names

# ================= 数据库 =================
def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS etf_list(
        code TEXT PRIMARY KEY, name TEXT, updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS kline(
        code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL,
        volume REAL, PRIMARY KEY(code, date))""")
    c.execute("""CREATE TABLE IF NOT EXISTS signals(
        code TEXT, date TEXT, mom5 REAL, mom20 REAL, mom60 REAL,
        macd_bull INTEGER, above_ma60 INTEGER, score INTEGER, signal TEXT,
        reason TEXT, PRIMARY KEY(code, date))""")
    c.execute("""CREATE TABLE IF NOT EXISTS strategy_log(
        date TEXT, rank INTEGER, code TEXT, name TEXT, action TEXT,
        weight REAL, score INTEGER, mom20 REAL, otc_fund TEXT, otc_c TEXT,
        PRIMARY KEY(date, rank))""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_kline ON kline(code, date)""")
    conn.commit()
    return conn

def upsert_kline(conn, code, rows):
    """rows: list of dict(date/open/close/high/low/volume)，增量写入"""
    c = conn.cursor()
    c.executemany("""INSERT OR REPLACE INTO kline(code,date,open,close,high,low,volume)
        VALUES(?,?,?,?,?,?,?)""",
        [(code, r['date'], r['open'], r['close'], r['high'], r['low'], r['volume']) for r in rows])
    conn.commit()

def get_kline(conn, code, limit=None):
    q = "SELECT date,open,close,high,low,volume FROM kline WHERE code=? ORDER BY date"
    if limit:
        q = f"SELECT date,open,close,high,low,volume FROM (SELECT * FROM kline WHERE code=? ORDER BY date DESC LIMIT {int(limit)}) ORDER BY date"
    df = pd.read_sql_query(q, conn, params=(code,))
    return df

# ================= 数据拉取 =================
def fetch_kline(code, limit=KLINE_LIMIT):
    """调用 westock-data CLI 拉取单只 ETF 日K，返回 [{date,open,close,high,low,volume}]（时间升序）"""
    cmd = [NODE, WESTOCK_CLI, 'kline', code, '--period', 'day', '--limit', str(limit)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=60)
        out = r.stdout
    except Exception as e:
        print(f'  [warn] {code} 拉取失败: {e}')
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        # 跳过表头行和分隔行（以 | date 开头 或 含 ---），数据行以 | 数字开头
        if not line or line.startswith('| date') or '| ---' in line:
            continue
        if not line.startswith('|'):
            continue
        parts = [p.strip() for p in line.split('|')]
        parts = [p for p in parts if p]
        if len(parts) < 7:
            continue
        try:
            rows.append({'date': parts[0], 'open': float(parts[1]), 'close': float(parts[2]),
                         'high': float(parts[3]), 'low': float(parts[4]), 'volume': float(parts[5])})
        except (ValueError, IndexError):
            continue
    rows.sort(key=lambda r: r['date'])
    return rows

def update_all(universe, db_path=DB_PATH, limit=KLINE_LIMIT):
    """拉取全部标的日K并增量入库"""
    conn = init_db(db_path)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    ok = 0; fail = []
    for i, (code, name) in enumerate(universe.items()):
        rows = fetch_kline(code, limit)
        if rows:
            upsert_kline(conn, code, rows)
            conn.execute("INSERT OR REPLACE INTO etf_list(code,name,updated_at) VALUES(?,?,?)",
                         (code, name, now))
            ok += 1
        else:
            fail.append(code)
        if (i + 1) % 20 == 0:
            print(f'  进度 {i+1}/{len(universe)}')
    conn.commit(); conn.close()
    print(f'更新完成: {ok} 只成功, {len(fail)} 只失败')
    if fail:
        print(f'  失败: {fail}')
    return ok

# ================= 信号计算 =================
def macd_series(close):
    ema_f = close.ewm(span=12, adjust=False).mean()
    ema_s = close.ewm(span=26, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea

def compute_signal(df):
    """对单只 ETF 的日K计算最新信号，返回 dict（与之前 signals100 同口径）"""
    close = df['close']
    n = len(df)
    if n < 65:
        return None
    m5 = close.iloc[-1] / close.iloc[-6] - 1 if n > 6 else 0
    m20 = close.iloc[-1] / close.iloc[-min(20, n)] - 1
    m60 = close.iloc[-1] / close.iloc[-min(60, n)] - 1 if n > 60 else m20
    dif, dea = macd_series(close)
    macd_bull = bool(dif.iloc[-1] > dea.iloc[-1])
    macd_hist = 2.0 * (dif - dea)  # MACD 柱
    # 多头衰竭判断：柱为正（多头）但较 3 天前明显缩短 → 动能衰减警告
    macd_weakening = False
    if macd_bull and n >= 4:
        h0 = abs(macd_hist.iloc[-1])
        h3 = abs(macd_hist.iloc[-4])
        if h3 > 1e-6 and h0 < h3 * 0.6:
            macd_weakening = True
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if n >= 60 else ma20
    above_ma60 = bool(close.iloc[-1] > ma60)

    s = 0
    s += 25 if m20 > 0 else 0
    s += 15 if m5 > 0 else 0
    s += 20 if macd_bull else 0
    s += 20 if above_ma60 else 0
    s += 10 if m60 > 0 else 0
    if m20 > 0.05: s += 10
    s = max(0, min(100, int(round(s))))

    if s >= 70 and m20 > 0 and macd_bull:
        signal, reason = '申购/加仓', '动量与MACD双多，趋势强劲'
    elif s >= 50 and m20 > 0:
        signal, reason = '持有', '动量转正，趋势修复中'
    elif s >= 40:
        signal, reason = '观察', '中性震荡，等待方向'
    elif above_ma60:
        signal, reason = '减持/赎回', '跌破趋势线，动量转弱'
    else:
        signal, reason = '赎回/规避', '空头趋势，不宜持有'
    return {
        'date': str(df['date'].iloc[-1]), 'mom5': round(float(m5)*100, 2),
        'mom20': round(float(m20)*100, 2), 'mom60': round(float(m60)*100, 2),
        'macd_bull': macd_bull, 'macd_weakening': macd_weakening,
        'above_ma60': above_ma60, 'score': s,
        'signal': signal, 'reason': reason, 'last': round(float(close.iloc[-1]), 4),
    }

# ================= 场外映射 =================
def load_otc_map():
    sys.path.insert(0, LIB_DIR)
    sys.path.insert(0, BASE_DIR)
    try:
        from otc_map import map_fund
        return map_fund
    except Exception:
        return lambda name: None

# ================= 策略生成（TOP N 轮动） =================
def build_strategy(universe, top_n=3, db_path=DB_PATH, show_top=10):
    """从库内最新数据计算信号，生成 TOP N 轮动策略并入库。
    show_top: 报告候选池展示数量（默认 TOP10），供人工挑选 7 天免赎标的。"""
    conn = init_db(db_path)
    map_fund = load_otc_map()
    all_sig = []
    for code, name in universe.items():
        df = get_kline(conn, code)
        if len(df) < 65:
            continue
        sig = compute_signal(df)
        if not sig:
            continue
        sig['code'] = code; sig['name'] = name
        otc = map_fund(name)
        sig['otc_fund'] = otc[0] if otc else None
        sig['otc_c'] = otc[2] if otc else None
        # 查询C类赎回费率，标注"7天免费"标签
        sig['fee_free7'] = False
        sig['fee_desc'] = '费率未核实'
        if sig['otc_c']:
            try:
                import otc_map as _om
                fr = _om.get_fee(sig['otc_c'])
                if fr:
                    sig['fee_free7'] = fr[1]
                    sig['fee_desc'] = fr[2]
            except Exception:
                pass
        # 写入 signals 表
        conn.execute("""INSERT OR REPLACE INTO signals
            (code,date,mom5,mom20,mom60,macd_bull,above_ma60,score,signal,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (code, sig['date'], sig['mom5'], sig['mom20'], sig['mom60'],
             int(sig['macd_bull']), int(sig['above_ma60']), sig['score'], sig['signal'], sig['reason']))
        all_sig.append(sig)
    conn.commit()

    # 过滤: 动量>0 且 MACD 多头；同一场外基金（同主题）只保留动量最强的一只，避免重复持仓
    eligible = [s for s in all_sig if s['mom20'] > 0 and s['macd_bull']]
    eligible.sort(key=lambda x: -x['mom20'])
    dedup = {}
    for s in eligible:
        key = s['otc_c'] or s['otc_fund'] or s['name'][:4]
        if key not in dedup:
            dedup[key] = s
    unique = sorted(dedup.values(), key=lambda x: -x['mom20'])
    top = unique[:top_n]
    candidates = unique[:show_top]  # 候选池（供挑选 7 天免赎标的）
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # 写入策略日志
    conn.execute("DELETE FROM strategy_log WHERE date=?", (today,))
    for i, s in enumerate(top):
        conn.execute("""INSERT OR REPLACE INTO strategy_log
            (date,rank,code,name,action,weight,score,mom20,otc_fund,otc_c)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (today, i+1, s['code'], s['name'], '持有', round(1.0/top_n, 4),
             s['score'], s['mom20'], s['otc_fund'], s['otc_c']))
    conn.commit(); conn.close()

    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'universe_size': len(all_sig),
        'eligible_count': len(eligible),
        'top_n': top_n,
        'show_top': show_top,
        'strategy': top,
        'candidates': candidates,
        'all_signals': all_sig,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    json_path, _ = dated_out_paths()
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f'策略已保存: {json_path}')
    print(f'\n=== 策略信号（{today}）===')
    print(f'池内有效标的: {len(all_sig)} | 动量+MACD双多可买: {len(eligible)}')
    print(f'TOP{top_n} 持仓建议:')
    for s in top:
        fee = '✅7天免赎' if s.get('fee_free7') else '⚠️' + (s.get('fee_desc') or '未核实')
        macd_s = '多头' if s.get('macd_bull') else '空头'
        if s.get('macd_weakening'):
            macd_s = '多头⚠️衰竭'
        print(f'  {s["code"]} {s["name"]:12s} 评分{s["score"]:3d} 20D:{s["mom20"]:+6.1f}% MACD:{macd_s} -> {s["otc_fund"] or "无映射"} C:{s["otc_c"] or "-"} [{fee}]')
    if len(top) < top_n:
        print(f'  [提示] 满足条件的仅 {len(top)} 只，不足 {top_n}；若为 0 应全部空仓')
    print(f'\n候选池 TOP{show_top}（挑选 7 天免赎标的执行，[]内为费率标签）:')
    for i, s in enumerate(candidates):
        fee = '✅7天免赎' if s.get('fee_free7') else '⚠️' + (s.get('fee_desc') or '未核实')
        macd_s = '多头' if s.get('macd_bull') else '空头'
        if s.get('macd_weakening'):
            macd_s = '多头⚠️衰竭'
        mark = ' <-- 持仓' if i < top_n else ''
        print(f'  {i+1:2d}. {s["otc_fund"] or s["name"]} C:{s["otc_c"] or "-"} 20D:{s["mom20"]:+6.1f}% MACD:{macd_s} [{fee}]{mark}')
    return result

# ================= 报告输出 =================
def macd_tag(s):
    """MACD 状态彩色标签：红=多头 / 橙=多头衰竭警告 / 绿=空头"""
    if s.get('macd_bull'):
        if s.get('macd_weakening'):
            return '<span style="color:#e8590c;font-weight:700">🟠多头·衰竭警告</span>'
        return '<span style="color:#e03131;font-weight:700">🟥多头</span>'
    return '<span style="color:#0ca678;font-weight:700">🟩空头</span>'

def write_report(result):
    top = result['strategy']
    rows_html = ''
    for i, s in enumerate(top):
        fee_tag = '<span style="color:#0ca678;font-weight:700">✅7天免赎</span>' if s.get('fee_free7') else '<span style="color:#f59f00">⚠️' + (s.get('fee_desc') or '未核实') + '</span>'
        rows_html += f'''<tr>
          <td><b>{s['name']}</b><br><span style="color:#868e96;font-size:12px">{s['code']}</span></td>
          <td><span class="score-pill" style="background:#fff0f0;color:#c92a2a">{s['score']}</span></td>
          <td class="up">+{s['mom20']:.1f}%</td>
          <td>{macd_tag(s)}</td>
          <td>{s['otc_fund'] or '—'}<br>{fee_tag}</td>
          <td>{s['otc_c'] or '—'}</td>
          <td>{(1.0/len(top)*100) if top else 0:.0f}%</td>
        </tr>'''
    # 候选池 TOP{show_top}（按动量排序，7天免赎优先高亮）
    cand_rows_html = ''
    for i, s in enumerate(result.get('candidates', [])):
        free7 = s.get('fee_free7')
        fee_tag = '<span style="color:#0ca678;font-weight:700">✅7天免赎</span>' if free7 else '<span style="color:#f59f00">⚠️' + (s.get('fee_desc') or '未核实') + '</span>'
        pick = '<span style="color:#0ca678;font-weight:700">✔ 优先选</span>' if free7 else '<span style="color:#adb5bd">可选</span>'
        in_top = '<span style="color:#2f5af5;font-weight:700">TOP' + str(result['top_n']) + '</span>' if i < result['top_n'] else '—'
        cand_rows_html += f'''<tr>
          <td>{i+1}</td>
          <td><b>{s['name']}</b><br><span style="color:#868e96;font-size:12px">{s['code']}</span></td>
          <td class="up">+{s['mom20']:.1f}%</td>
          <td>{macd_tag(s)}</td>
          <td>{s['otc_fund'] or '—'}<br>{fee_tag}</td>
          <td>{s['otc_c'] or '—'}</td>
          <td>{pick}</td>
          <td>{in_top}</td>
        </tr>'''
    empty_note = '<div class="advice warn"><h4>空仓提示</h4><p>当前无标的同时满足动量&gt;0 与 MACD 多头，按策略应全部空仓等待。</p></div>' if not top else ''
    html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>ETF 动量策略日报</title><style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#1a2233;--sub:#5b6472;--line:#e4e7ee;--up:#e03131;--down:#0ca678;--accent:#2f5af5}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65;padding-bottom:40px}}
.wrap{{max-width:980px;margin:0 auto;padding:0 20px}}
header{{background:linear-gradient(135deg,#1a2233,#2f5af5);color:#fff;padding:36px 0 28px;margin-bottom:22px}}
header h1{{font-size:22px;font-weight:700}}
header .sub{{opacity:.85;font-size:13px;margin-top:6px}}
.card{{background:var(--card);border-radius:14px;padding:20px 22px;margin-bottom:18px;border:1px solid var(--line)}}
.card h2{{font-size:17px;margin-bottom:10px}}
.kpi{{display:inline-block;background:#fbfcfe;border:1px solid var(--line);border-radius:10px;padding:12px 18px;margin-right:12px}}
.kpi .k{{font-size:12px;color:var(--sub)}} .kpi .v{{font-size:20px;font-weight:700;margin-top:2px}}
.up{{color:var(--up)}} .down{{color:var(--down)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{background:#f3f5f9;color:var(--sub);text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}}
td{{padding:9px 10px;border-bottom:1px solid #eef0f5}}
.score-pill{{display:inline-block;min-width:36px;text-align:center;border-radius:8px;padding:2px 6px;font-weight:700;font-size:12.5px}}
.advice{{border-left:4px solid var(--accent);background:#eef2ff;border-radius:0 10px 10px 0;padding:13px 16px;font-size:13.5px}}
.advice.warn{{border-color:#f59f00;background:#fff9e6}}
.note{{font-size:12px;color:var(--sub);margin-top:10px;border-top:1px dashed var(--line);padding-top:8px}}
footer{{text-align:center;color:var(--sub);font-size:12px;margin-top:20px}}
</style></head><body>
<header><div class="wrap">
<h1>ETF 动量策略日报</h1>
<div class="sub">生成时间 {result['generated_at']} · 池内 {result['universe_size']} 只 · 双多可买 {result['eligible_count']} 只 · 持仓 TOP{result['top_n']}</div>
</div></header>
<div class="wrap">
<div class="card"><h2>今日操作策略（每10个交易日调仓）</h2>
{empty_note}
<table><thead><tr><th>持仓标的</th><th>评分</th><th>20日动量</th><th>MACD</th><th>场外基金</th><th>C类代码</th><th>建议仓位</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<div class="note">规则：20日动量&gt;0 且 MACD 多头才持仓；每10个交易日收盘后重算；MACD死叉或浮亏-5~-8%立即离场；不足{result['top_n']}只按实际持有，0只空仓。</div>
</div>
<div class="card"><h2>候选池 TOP{result.get('show_top', 10)}（从中挑选 7 天免赎标的执行）</h2>
<p style="font-size:13px;color:#5b6472;margin-bottom:10px">按 20 日动量排序（已按场外基金去重）。<b style="color:#0ca678">✔ 优先选 7 天免赎</b>的标的——每 10 交易日调仓约 14 自然日，若落在 7-30 天区间、收费基金每次调仓多付 0.5% 赎回费。</p>
<table><thead><tr><th>#</th><th>候选标的</th><th>20日动量</th><th>MACD</th><th>场外基金</th><th>C类代码</th><th>挑选</th><th>策略</th></tr></thead>
<tbody>{cand_rows_html}</tbody></table>
</div>
<div class="card"><h2>风控纪律</h2>
<div class="advice">单标的 ≤ 总资金 20% · 持仓 ≤ {result['top_n']} 只（控制相关性）· 场外C类份额执行（成本0.25%/年）· 信号转空无条件离场，空仓等待也是策略</div>
</div>
<div class="card" style="border-color:#ffc9c9"><div style="font-size:13px;color:#a61e1e"><b>免责声明</b>：本报告基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。过往表现不预示未来收益。</div></div>
<footer>数据来源：腾讯自选股 · 本地库 {DB_PATH} · 本页面为量化研究工具</footer>
</div></body></html>'''
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    _, html_path = dated_out_paths()
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'报告已生成: {html_path}')

# ================= 主入口 =================
def main():
    parser = argparse.ArgumentParser(description='ETF 动量策略自动化管线')
    parser.add_argument('--update', action='store_true', help='仅更新数据')
    parser.add_argument('--signal', action='store_true', help='仅算信号+出策略（不联网）')
    parser.add_argument('--universe', type=int, default=100, help='标的池大小: 100(默认) 或 19(小池)')
    parser.add_argument('--top', type=int, default=3, help='TOP N 持仓数量')
    parser.add_argument('--show-top', type=int, default=10, help='报告候选池展示数量（默认10，供挑选7天免赎标的）')
    parser.add_argument('--limit', type=int, default=130, help='每只拉取K线根数')
    args = parser.parse_args()

    universe = load_universe(use_small=(args.universe == 19))
    print(f'标的池: {len(universe)} 只 | TOP {args.top} | 拉取 {args.limit} 根/只')

    if not args.signal:
        update_all(universe, limit=args.limit)
    if not args.update:
        result = build_strategy(universe, top_n=args.top, show_top=args.show_top)
        write_report(result)
    print('\n完成。')

if __name__ == '__main__':
    main()
