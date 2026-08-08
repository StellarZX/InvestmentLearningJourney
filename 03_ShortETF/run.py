# -*- coding: utf-8 -*-
"""
ETF 动量策略自动化管线（行业级决策版）
========================================
一次运行完成: 拉取数据 -> 更新本地 SQLite -> 计算信号 -> 生成行业级操作策略

设计说明:
    - 决策只基于场内 ETF 的动量/MACD 信号，直接给出「行业」维度的操作建议
    - 同一行业只保留动量最强的一只代表，避免行业内部重复持仓
    - 不再映射场外基金（场外标的代码与费率在入场时人工确认）

用法:
    python run.py                 # 全流程（拉数据+算信号+出策略）
    python run.py --update        # 仅更新数据
    python run.py --signal        # 仅用库内数据算信号+出策略（不联网）
    python run.py --universe 19   # 用小池(19只) / 默认100只
    python run.py --top 3         # TOP N 行业数量

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
LIB_DIR = os.path.join(BASE_DIR, 'lib')       # 依赖：top100_etf.json（otc_map.py 仅作入场核对参考）
DATA_DIR = os.path.join(BASE_DIR, 'data')     # 数据：etf_strategy.db
REPORT_DIR = os.path.join(BASE_DIR, 'reports')  # 历史报告（带日期）
DB_PATH = os.path.join(DATA_DIR, 'etf_strategy.db')

# 行业分类（与 rebuild_pool.py 的 INDUSTRY_CLASS 同口径，用于行业级去重与决策）
INDUSTRY_CLASS = [
    ('半导体', ['半导体','芯片','集成电路','功率半导体','存储','GPU','CPU','光刻','晶圆','封测','第三代半导体','科创芯片','科创半导体','IGBT','碳化硅','电子']),
    ('通信TMT', ['通信','5G','6G','光模块','CPO','光通信','电信','数据中心','IDC','算力','云计算','云','大数据','人工智能','AI','软件','信创','数据','数字','互联网','区块链','元宇宙','网络安全','量子']),
    ('传媒游戏', ['传媒','游戏','动漫','影视','视频','音乐','电竞','在线消费','直播','元宇宙']),
    ('医药医疗', ['医药','医疗','创新药','生物','中药','疫苗','血制品','医疗器械','医疗服务','CXO','制药','化学制药','医美','健康']),
    ('消费', ['消费','食品','饮料','白酒','酒','调味','乳业','家电','零售','免税','旅游','酒店','餐饮','农业','养殖','猪','粮食','种子','纺织','家居','教育']),
    ('汽车', ['汽车','智能驾驶','车联网','新能源车','整车','零部件','汽零']),
    ('新能源', ['新能源','光伏','风电','储能','电池','锂','氢能','燃料电池','充电桩','碳中和','绿色电力','清洁能源','太阳能','电力设备','特高压']),
    ('军工', ['军工','国防','航天','卫星','航空','船舶','无人机','低空']),
    ('金融地产', ['银行','证券','保险','券商','金融','地产','房地产','REITs','金融科技','互联网金融']),
    ('周期资源', ['有色','稀土','黄金','贵金属','化工','钢铁','煤炭','石油','油气','建材','水泥','稀有金属','小金属','锂矿','盐湖','工业金属','商品']),
    ('高端制造', ['机器人','机械','工业母机','高端装备','工程机械','自动化','机床','专用设备','智能制造','工业']),
    ('电力公用', ['电力','水电','火电','核电','燃气','环保','公用事业','水务']),
    ('港股科技', ['港股通科技','香港科技','港股科技','恒生科技','港股互联网','恒生互联网','港股通互联网','中概互联','中概互联网','港股新经济','港股通新经济']),
]

def classify_industry(name):
    """按名称关键词归入行业，无法归入返回'其他'"""
    for cls, kws in INDUSTRY_CLASS:
        if any(k in name for k in kws):
            return cls
    return '其他'
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
    # 动量 = 今日收盘 / N个交易日前收盘 - 1
    # 注意：iloc[-N] 是第 N-1 个交易日前，因此 5/20/60 日动量应分别用 iloc[-6]/[-21]/[-61]
    m5 = close.iloc[-1] / close.iloc[-6] - 1 if n > 6 else 0
    m20 = close.iloc[-1] / close.iloc[-min(21, n)] - 1
    m60 = close.iloc[-1] / close.iloc[-min(61, n)] - 1 if n > 60 else m20
    dif, dea = macd_series(close)
    macd_bull = bool(dif.iloc[-1] > dea.iloc[-1])
    macd_hist = 2.0 * (dif - dea)  # MACD 柱
    # 多头衰竭判断：仅当红柱（柱>0）且较近10日峰值明显回落（<60%）时提示动能衰减。
    # 修复：原逻辑用 abs() 比较，会把"绿柱收窄、刚翻红第一天"误判为衰竭。
    # 现在用带符号柱值 + 历史峰值比较——刚金叉（此前无红柱峰值）不再误报。
    macd_weakening = False
    if macd_bull and n >= 10:
        h0 = macd_hist.iloc[-1]                  # 今日柱（带符号，>0 为红柱）
        peak = macd_hist.iloc[-10:-1].max()      # 近10日（不含今日）红柱峰值
        if h0 > 0 and peak > 1e-6 and h0 < peak * 0.6:
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

# ================= 策略生成（行业级 TOP N 轮动） =================
def build_strategy(universe, top_n=3, db_path=DB_PATH, show_top=10):
    """从库内最新数据计算信号，生成行业级 TOP N 轮动策略并入库。
    决策只基于场内 ETF 信号，不映射场外基金（场外标的在入场时另行确认）。
    show_top: 报告候选池展示数量（<=0 表示全部）。"""
    conn = init_db(db_path)
    all_sig = []
    for code, name in universe.items():
        df = get_kline(conn, code)
        if len(df) < 65:
            continue
        sig = compute_signal(df)
        if not sig:
            continue
        sig['code'] = code; sig['name'] = name
        sig['industry'] = classify_industry(name)   # 行业标签
        # 写入 signals 表
        conn.execute("""INSERT OR REPLACE INTO signals
            (code,date,mom5,mom20,mom60,macd_bull,above_ma60,score,signal,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (code, sig['date'], sig['mom5'], sig['mom20'], sig['mom60'],
             int(sig['macd_bull']), int(sig['above_ma60']), sig['score'], sig['signal'], sig['reason']))
        all_sig.append(sig)
    conn.commit()

    # 过滤: 动量>0 且 MACD 多头；同一行业只保留动量最强的一只代表，避免行业重复持仓
    eligible = [s for s in all_sig if s['mom20'] > 0 and s['macd_bull']]
    eligible.sort(key=lambda x: -x['mom20'])
    dedup = {}
    for s in eligible:
        key = s['industry']
        if key not in dedup:
            dedup[key] = s
    unique = sorted(dedup.values(), key=lambda x: -x['mom20'])
    top = unique[:top_n]
    # 候选池：show_top<=0 表示展示全部行业代表
    candidates = unique if (show_top is None or show_top <= 0) else unique[:show_top]
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # 写入策略日志
    conn.execute("DELETE FROM strategy_log WHERE date=?", (today,))
    for i, s in enumerate(top):
        conn.execute("""INSERT OR REPLACE INTO strategy_log
            (date,rank,code,name,action,weight,score,mom20,otc_fund,otc_c)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (today, i+1, s['code'], s['name'], '持有', round(1.0/top_n, 4),
             s['score'], s['mom20'], None, None))
    conn.commit(); conn.close()

    result = {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'universe_size': len(all_sig),
        'eligible_count': len(eligible),
        'industry_count': len(unique),
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
    print(f'池内有效标的: {len(all_sig)} | 动量+MACD双多可买: {len(eligible)} | 双多行业: {len(unique)}')
    print(f'TOP{top_n} 行业持仓建议:')
    for s in top:
        macd_s = '多头' if s.get('macd_bull') else '空头'
        if s.get('macd_weakening'):
            macd_s = '多头⚠️衰竭'
        print(f'  [{s["industry"]}] {s["code"]} {s["name"]:12s} 评分{s["score"]:3d} 20D:{s["mom20"]:+6.1f}% MACD:{macd_s}')
    if len(top) < top_n:
        print(f'  [提示] 满足条件的行业仅 {len(top)} 个，不足 {top_n}；若为 0 应全部空仓')
    cand_label = f'全部 {len(candidates)} 个行业' if (show_top is None or show_top <= 0) else f'TOP{show_top}'
    print(f'\n双多行业候选池（{cand_label}，每行业只列动量最强代表）:')
    for i, s in enumerate(candidates):
        macd_s = '多头' if s.get('macd_bull') else '空头'
        if s.get('macd_weakening'):
            macd_s = '多头⚠️衰竭'
        mark = ' <-- 持仓' if i < top_n else ''
        print(f'  {i+1:2d}. [{s["industry"]}] {s["code"]} {s["name"]} 20D:{s["mom20"]:+6.1f}% MACD:{macd_s}{mark}')
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
        rows_html += f'''<tr>
          <td><span class="industry-pill">{s.get('industry', '—')}</span></td>
          <td><b>{s['name']}</b><br><span style="color:#868e96;font-size:12px">{s['code']}</span></td>
          <td><span class="score-pill" style="background:#fff0f0;color:#c92a2a">{s['score']}</span></td>
          <td class="up">+{s['mom20']:.1f}%</td>
          <td>{macd_tag(s)}</td>
          <td>{(1.0/len(top)*100) if top else 0:.0f}%</td>
        </tr>'''
    # 候选池（行业级代表，按动量排序）
    cand_rows_html = ''
    for i, s in enumerate(result.get('candidates', [])):
        in_top = '<span style="color:#2f5af5;font-weight:700">TOP' + str(result['top_n']) + '</span>' if i < result['top_n'] else '—'
        cand_rows_html += f'''<tr>
          <td>{i+1}</td>
          <td><span class="industry-pill">{s.get('industry', '—')}</span></td>
          <td><b>{s['name']}</b><br><span style="color:#868e96;font-size:12px">{s['code']}</span></td>
          <td class="up">+{s['mom20']:.1f}%</td>
          <td>{macd_tag(s)}</td>
          <td>{in_top}</td>
        </tr>'''
    # 全池信号一览：池内全部标的（含非双多），按评分降序
    all_rows_html = ''
    all_sorted = sorted(result.get('all_signals', []), key=lambda x: -x.get('score', 0))
    for i, s in enumerate(all_sorted):
        mom5 = s.get('mom5', 0); mom20 = s.get('mom20', 0); mom60 = s.get('mom60', 0)
        all_rows_html += f'''<tr>
          <td>{i+1}</td>
          <td><span class="industry-pill">{s.get('industry', '—')}</span></td>
          <td><b>{s['name']}</b><br><span style="color:#868e96;font-size:12px">{s['code']}</span></td>
          <td><span class="score-pill" style="background:#fff0f0;color:#c92a2a">{s['score']}</span></td>
          <td class="{'up' if mom5 > 0 else 'down'}">{mom5:+.1f}%</td>
          <td class="{'up' if mom20 > 0 else 'down'}">{mom20:+.1f}%</td>
          <td class="{'up' if mom60 > 0 else 'down'}">{mom60:+.1f}%</td>
          <td>{macd_tag(s)}</td>
          <td>{s.get('signal', '—')}</td>
        </tr>'''
    cand_title = f"行业候选池（全部 {len(result.get('candidates', []))} 个双多行业）" if result.get('show_top', 0) <= 0 else f"行业候选池 TOP{result.get('show_top')}"
    empty_note = '<div class="advice warn"><h4>空仓提示</h4><p>当前无行业同时满足动量&gt;0 与 MACD 多头，按策略应全部空仓等待。</p></div>' if not top else ''
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
.industry-pill{{display:inline-block;background:#eef2ff;color:#2f5af5;border-radius:6px;padding:2px 8px;font-weight:700;font-size:12px;white-space:nowrap}}
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
<table><thead><tr><th>行业</th><th>持仓标的</th><th>评分</th><th>20日动量</th><th>MACD</th><th>建议仓位</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<div class="note">规则：20日动量&gt;0 且 MACD 多头才持仓；每10个交易日收盘后重算；MACD死叉或浮亏-5~-8%立即离场；不足{result['top_n']}个行业按实际持有，0个空仓。行业决策基于场内 ETF 信号，场外基金代码在入场时另行确认。</div>
</div>
<div class="card"><h2>{cand_title}</h2>
<p style="font-size:13px;color:#5b6472;margin-bottom:10px">按 20 日动量排序（同一行业只保留动量最强的一只代表）。<b style="color:#2f5af5">TOP{result['top_n']}</b> 为当前建议持仓行业，其余为可替换候选。</p>
<table><thead><tr><th>#</th><th>行业</th><th>候选标的</th><th>20日动量</th><th>MACD</th><th>策略</th></tr></thead>
<tbody>{cand_rows_html}</tbody></table>
</div>
<div class="card"><h2>全池信号一览（{result['universe_size']} 只，按评分降序）</h2>
<p style="font-size:13px;color:#5b6472;margin-bottom:10px">当前股票池内全部标的的信号明细（含非双多标的）。<b style="color:#e03131">红色/正数</b>为上涨动量，<b style="color:#0ca678">绿色/负数</b>为下跌；「🟠多头·衰竭警告」表示红柱缩短、死叉在即，不要追高。</p>
<table><thead><tr><th>#</th><th>行业</th><th>标的</th><th>评分</th><th>5日动量</th><th>20日动量</th><th>60日动量</th><th>MACD</th><th>信号</th></tr></thead>
<tbody>{all_rows_html}</tbody></table>
</div>
<div class="card"><h2>评分计算说明</h2>
<p style="font-size:13.5px;margin-bottom:8px">每只标的按以下六项加分，总分上限 <b>100 分</b>：</p>
<table><thead><tr><th>加分项</th><th>条件</th><th>分值</th></tr></thead>
<tbody>
<tr><td>① 20日动量</td><td>最新收盘较 20 个交易日前上涨（m20 &gt; 0）</td><td>+25</td></tr>
<tr><td>② 5日动量</td><td>最新收盘较 5 个交易日前上涨（m5 &gt; 0）</td><td>+15</td></tr>
<tr><td>③ MACD 多头</td><td>DIF &gt; DEA（EMA12 − EMA26 快线在慢线上方）</td><td>+20</td></tr>
<tr><td>④ 站上 MA60</td><td>收盘价 &gt; 60 日均线</td><td>+20</td></tr>
<tr><td>⑤ 60日动量</td><td>最新收盘较 60 个交易日前上涨（m60 &gt; 0）</td><td>+10</td></tr>
<tr><td>⑥ 强趋势奖励</td><td>20 日动量超过 +5%</td><td>+10</td></tr>
</tbody></table>
<p style="font-size:13.5px;margin-top:10px">信号分级：<b>≥70 且 20日动量&gt;0 且 MACD多头</b> → 申购/加仓；<b>≥50 且 20日动量&gt;0</b> → 持有；<b>≥40</b> → 观察；<b>跌破 MA60</b> → 减持/赎回；其余 → 赎回/规避。</p>
</div>
<div class="card"><h2>风控纪律</h2>
<div class="advice">单行业 ≤ 总资金 20% · 持仓 ≤ {result['top_n']} 个行业（控制相关性）· 信号转空无条件离场，空仓等待也是策略 · 实际买入场外基金前核对代码与费率</div>
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
    parser.add_argument('--show-top', type=int, default=0, help='报告候选池展示数量（0=展示全部双多标的，默认全部）')
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
