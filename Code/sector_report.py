# -*- coding: utf-8 -*-
"""
行业数据分析报告（sector_report.py）
====================================
定位：不做短线量化操作指令，只输出「行业数据分析结果 + 操作建议参考」，
供用户自行判断。

报告内容：
  1. 当前行业持仓（从 Sector.log 推导：买入-赎回=当前持仓，含金额）
  2. 持仓预警：动量转弱 / MACD衰竭 / 历史分位过高 / 深度低估等
  3. 行业全景：全部行业型 ETF 按主题聚合的动量/分位/资金流/综合分排名
  4. 低估方向雷达：250日分位 < 0.3 的方向（均值回归参考）
  5. 强势方向雷达：综合分高 + 动量 + MACD 双多方向（趋势参考）

综合分（满分100，权重见 WEIGHTS）：
  动量（20日30 + 5日10 + 60日10）+ MACD多头/红柱15 + 站上MA60/偏离15
  + 历史分位低估10 + 资金流量能方向比10

数据源：
  - Sector.log（同目录，买卖记录）→ 当前持仓
  - data/market.db（统一主库：全市场清单 + 行业型 K 线，腾讯前复权）→ 行情分析
  - lib/otc_map.py（场外基金代码 → 主题）→ 持仓映射

用法：python sector_report.py
输出：sector_report.html（最新报告）
"""
import os, sys, json, sqlite3, datetime
import pandas as pd
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, 'lib'))
from signal_lib import theme_of, is_industry, classify_industry, macd_series
from otc_map import OTC_MAP

LOG_FILE = os.path.join(BASE, 'Sector.log')            # 旧持仓记录（已迁移到 portfolio.db，保留作历史）
PORTFOLIO_DB = os.path.join(BASE, 'data', 'portfolio.db')  # 统一持仓流水库（行业/指数/资金池）
DB = os.path.join(BASE, 'data', 'market_industry.db')   # 行业行情库：全市场清单 + 行业型K线（腾讯前复权）
OUT_HTML = os.path.join(BASE, '..', '03_SectorReport', 'sector_report.html')  # 报告输出到 03 行业报告目录
FEE = 0.005
BUY_PCT = 0.3          # 低估参考线
HIGH_PCT = 0.7         # 高估预警线

# ---- 综合评分权重（满分 100，可按偏好调整）----
# 设计逻辑：动量(涨势) + 趋势(MACD/MA60) + 资金流(量能方向) 是"进攻"，历史分位(低估) 是"防守/性价比"
WEIGHTS = {
    'mom20': 30,      # 20日动量（趋势核心）
    'mom5': 10,       # 5日动量（近期加速）
    'mom60': 10,      # 60日动量（中期趋势）
    'macd': 15,       # MACD 多头 + 红柱强度（红柱衰竭减半）
    'ma60': 15,       # 站上MA60 + 偏离度
    'pct': 10,        # 历史分位低估（分位越低分越高，性价比）
    'flow': 10,       # 20日资金流（量能方向比：上涨放量=流入）
}
# 各分项线性阈值（达到该值即拿满分）
THRESH = {'mom20': 0.10, 'mom5': 0.05, 'mom60': 0.15, 'hist': 0.04, 'ma_dev': 0.10, 'flow': 0.50}


# ================= 1. 持仓推导 =================
def load_positions():
    """从 portfolio.db（统一持仓流水库）读取行业基金流水，推导当前持仓。
    持仓 = 买入累计 - 赎回累计（金额<=0 视为已清仓）。
    返回 {基金代码: {name, code, amt, buys, sells, last_date, last_gain}}"""
    pos = {}
    if not os.path.exists(PORTFOLIO_DB):
        print(f'  [warn] 未找到 {PORTFOLIO_DB}，按空持仓处理')
        return pos
    conn = sqlite3.connect(PORTFOLIO_DB)
    rows = conn.execute(
        "SELECT date,fund,code,direction,amount,gain FROM trans WHERE category='行业' ORDER BY date").fetchall()
    conn.close()
    for d, name, code, direction, amt, gain in rows:
        if not code or not direction:
            continue
        if code == 'ZFB' or '余额宝' in name:          # 现金类，跳过
            continue
        p = pos.setdefault(code, {'name': name, 'code': code, 'amt': 0.0,
                                  'buys': 0, 'sells': 0, 'last_date': str(d),
                                  'last_gain': 0.0})
        if direction in ('买入', '申购', '加仓'):
            p['amt'] += amt
            p['buys'] += 1
        elif direction in ('卖出', '赎回', '减仓'):
            p['amt'] -= amt
            p['sells'] += 1
            try:
                p['last_gain'] = float(gain)
            except (TypeError, ValueError):
                pass
        if str(d) > p['last_date']:
            p['last_date'] = str(d)
    # 过滤：金额<=0 视为已清仓
    return {c: p for c, p in pos.items() if p['amt'] > 1}


def otc_to_theme(code, name):
    """场外基金代码 → 主题（otc_map 反查，支持 tuple 与 list-of-tuple 两种值结构）"""
    def codes_of(v):
        """取出 v 里的所有基金代码"""
        out = []
        for item in (v if isinstance(v, list) else [v]):
            if isinstance(item, tuple) and len(item) >= 3:
                out.extend(item[1:])
        return out

    # 1) 代码反查（最可靠）
    for k, v in OTC_MAP.items():
        if code in codes_of(v):
            return k
    # 2) 名称关键词反查（v[0] 联接基金名包含主题词）
    for k, v in OTC_MAP.items():
        if isinstance(v, tuple) and v[0] and any(w in name for w in k.split('/')):
            return k
    # 3) 名称中包含的主题词
    for k in sorted(OTC_MAP.keys(), key=len, reverse=True):
        if k in name:
            return k
    return None


# ================= 2. 行情数据 =================
def latest_trading_day():
    """估算最近交易日（周一盘前=上周五；周末=周五）"""
    import datetime as _dt
    today = _dt.date.today()
    wd = today.weekday()          # 0=周一
    if wd == 0:                    # 周一：假设盘前，最近交易日=上周五
        return today - _dt.timedelta(days=3)
    if wd == 6:                    # 周日
        return today - _dt.timedelta(days=2)
    if wd == 5:                    # 周六
        return today - _dt.timedelta(days=1)
    return today                   # 周二~周五


def ensure_market_updated():
    """智能增量更新：仅当库内最新日期 < 最近交易日时才拉新K线（避免每次运行都请求接口）"""
    import subprocess
    fetch_script = os.path.join(BASE, 'fetch_db.py')
    if not os.path.exists(DB):
        print('  [首次] 全量重建数据库...')
        subprocess.run([sys.executable, fetch_script, '--types', 'all'], check=False)
        return
    try:
        conn = sqlite3.connect(DB)
        db_latest = conn.execute('SELECT MAX(date) FROM kline').fetchone()[0]
        conn.close()
    except Exception:
        db_latest = None
    need = latest_trading_day().strftime('%Y-%m-%d')
    if db_latest and db_latest >= need:
        print(f'  数据已最新（{db_latest}），跳过增量更新')
        return
    print(f'  库内 {db_latest} < 最近交易日 {need}，增量更新...')
    subprocess.run([sys.executable, fetch_script, '--incremental'], check=False)


def load_market():
    """从 market.db 加载全部行业型 ETF 的 K 线，预计算动量/分位/MACD/资金流/综合评分"""
    conn = sqlite3.connect(DB)
    meta = conn.execute("SELECT code,name FROM etf_meta WHERE is_ind=1").fetchall()
    data = {}
    for code, name in meta:
        df = pd.read_sql_query("SELECT date,open,close,volume FROM kline WHERE code=? ORDER BY date",
                               conn, params=(code,))
        if len(df) < 65:
            continue
        s = df['close'].astype(float)
        n = len(s)
        m5 = s.iloc[-1] / s.iloc[-6] - 1 if n > 6 else 0
        m20 = s.iloc[-1] / s.iloc[-min(21, n)] - 1
        m60 = s.iloc[-1] / s.iloc[-min(61, n)] - 1 if n > 60 else m20
        dif, dea = macd_series(s)
        hist = 2.0 * (dif - dea)
        macd_bull = bool(dif.iloc[-1] > dea.iloc[-1])
        ma60 = s.rolling(60).mean().iloc[-1]
        above_ma60 = bool(s.iloc[-1] > ma60)
        # 250日分位（K线不足250根时 rolling 返回 NaN → None）
        mn = s.rolling(250).min().iloc[-1]
        mx = s.rolling(250).max().iloc[-1]
        try:
            pct250 = float((s.iloc[-1] - mn) / (mx - mn)) if (mx == mx and mn == mn and mx > mn) else None
        except Exception:
            pct250 = None
        # ---- 资金流：量能方向比（近N日 上涨成交量占比 - 下跌成交量占比，-1~1）----
        def _flow(window):
            o = df['open'].astype(float)
            v = df['volume'].astype(float)
            w_o, w_c, w_v = o.iloc[-window:], s.iloc[-window:], v.iloc[-window:]
            if w_v.sum() <= 0:
                return 0.0
            up = w_v[w_c > w_o].sum()
            dn = w_v[w_c < w_o].sum()
            return float((up - dn) / w_v.sum())
        flow5 = _flow(min(5, n))
        flow20 = _flow(min(20, n))
        # ---- 综合评分（多指标加权，满分100）----
        def _lin(x, th):
            return max(0.0, min(1.0, x / th)) if th else 0.0
        above_pct = s.iloc[-1] / ma60 - 1
        hist0 = hist.iloc[-1]
        W = WEIGHTS
        sc = 0.0
        sc += _lin(m20, THRESH['mom20']) * W['mom20']          # 20日动量
        sc += _lin(m5, THRESH['mom5']) * W['mom5']             # 5日动量
        sc += _lin(m60, THRESH['mom60']) * W['mom60']          # 60日动量
        # MACD：多头基础分 + 红柱强度；红柱衰竭减半
        if macd_bull:
            sc += W['macd'] * 0.5
            sc += _lin(hist0, THRESH['hist']) * W['macd'] * 0.5
        # MA60：站上基础分 + 偏离度
        if above_ma60:
            sc += W['ma60'] * 0.5
            sc += _lin(above_pct, THRESH['ma_dev']) * W['ma60'] * 0.5
        # 历史分位（低估加分：分位越低分越高；次新无分位给中值）
        if pct250 is not None:
            sc += (1 - pct250) * W['pct']
        else:
            sc += W['pct'] * 0.5
        # 资金流（流入加分，流出 0 分）
        sc += _lin(max(flow20, 0), THRESH['flow']) * W['flow']
        score = round(max(0.0, min(100.0, sc)), 1)
        # MACD 衰竭
        weakening = False
        if macd_bull and n >= 10:
            h0 = hist.iloc[-1]; peak = hist.iloc[-10:-1].max()
            if h0 > 0 and peak > 1e-6 and h0 < peak * 0.6:
                weakening = True
        data[code] = {
            'name': name, 'theme': theme_of(name),
            'date': str(df['date'].iloc[-1]), 'last': float(s.iloc[-1]),
            'mom5': round(float(m5)*100, 2), 'mom20': round(float(m20)*100, 2),
            'mom60': round(float(m60)*100, 2),
            'pct250': round(pct250, 3) if pct250 is not None else None,
            'macd_bull': macd_bull, 'macd_weakening': weakening,
            'above_ma60': above_ma60,
            'flow5': round(flow5*100, 1), 'flow20': round(flow20*100, 1),
            'score': score,
        }
    return data


def theme_aggregate(data):
    """按主题聚合：均值动量/分位/评分 + 代表（评分最高）标的"""
    from collections import defaultdict
    g = defaultdict(list)
    for code, x in data.items():
        g[x['theme']].append((code, x))
    themes = []
    for th, items in g.items():
        n = len(items)
        rep = max(items, key=lambda t: t[1]['score'])
        # 分位：仅用有效值（K线≥250根的标的）求均值；全部无效则为 None
        pcts = [x['pct250'] for _, x in items if x['pct250'] is not None]
        pct_avg = round(sum(pcts) / len(pcts), 3) if pcts else None
        themes.append({
            'theme': th, 'count': n,
            'mom5': round(sum(x['mom5'] for _, x in items) / n, 2),
            'mom20': round(sum(x['mom20'] for _, x in items) / n, 2),
            'mom60': round(sum(x['mom60'] for _, x in items) / n, 2),
            'pct250': pct_avg,
            'flow20': round(sum(x['flow20'] for _, x in items) / n, 1),
            'score': round(sum(x['score'] for _, x in items) / n, 1),
            'bull': sum(1 for _, x in items if x['macd_bull']),
            'weak': sum(1 for _, x in items if x['macd_weakening']),
            'rep_code': rep[0], 'rep_name': rep[1]['name'],
            'rep_score': rep[1]['score'], 'rep_last': rep[1]['last'],
        })
    themes.sort(key=lambda t: -t['score'])
    return themes


# ================= 3. 持仓预警 =================
def analyze_holdings(pos, data, themes):
    """对每笔持仓（场外基金）生成预警。用主题下代表 ETF 的信号代理。"""
    theme_map = {t['theme']: t for t in themes}
    # 模糊匹配：主题名互为子串也视为匹配（如 otc_map 的'消费' ↔ 场内'消费ETF'）
    def resolve(theme):
        if theme in theme_map:
            return theme_map[theme]
        for k, t in theme_map.items():
            if theme and (theme in k or k in theme):
                return t
        return None
    rows = []
    for code, p in pos.items():
        theme = otc_to_theme(code, p['name'])
        t = resolve(theme) if theme else None
        row = {
            'fund': p['name'], 'code': code, 'theme': theme or '未知',
            'amt': p['amt'], 'buys': p['buys'], 'sells': p['sells'],
            'last_date': p['last_date'],
            'mom5': '—', 'mom20': '—', 'mom60': '—', 'pct': '—',
            'score': '—', 'bull': '—', 'weak': '—', 'warnings': [],
        }
        if t is None:
            row['warnings'].append('未找到对应行业主题')
        else:
            row['mom5'] = t['mom5']; row['mom20'] = t['mom20']; row['mom60'] = t['mom60']
            row['pct'] = t['pct250']; row['score'] = t['score']
            row['bull'] = t['bull']; row['weak'] = t['weak']
            row['rep'] = f"{t['rep_name']}（{t['rep_code']}）"
            row['rep_score'] = t['rep_score']
            # 预警规则
            if t['mom20'] < 0 and not t['bull']:
                row['warnings'].append('⚠️ 动量转负且MACD空头——趋势走弱，关注回调')
            elif t['mom20'] < 0:
                row['warnings'].append('⚠️ 20日动量为负——短线动能不足')
            if t['weak']:
                row['warnings'].append('🟠 MACD红柱衰竭——涨势减速，勿追高')
            if t['pct250'] is not None and t['pct250'] > HIGH_PCT:
                row['warnings'].append(f"📈 历史分位 {t['pct250']:.0%} 偏高——估值已修复，谨慎加仓")
            if t['pct250'] is not None and t['pct250'] < BUY_PCT:
                row['warnings'].append(f"📉 历史分位 {t['pct250']:.0%} 低位——深度低估区间（参考）")
            if t['score'] >= 65 and t['mom20'] > 0 and t['bull']:
                row['warnings'].append('✅ 动量MACD双多——趋势强劲（参考持有）')
            if not row['warnings']:
                row['warnings'].append('➖ 中性区间，无特别预警')
        rows.append(row)
    # 按金额降序
    rows.sort(key=lambda r: -r['amt'])
    return rows


# ================= 4. 报告 =================
def fmt_pct(v, suffix='%'):
    if isinstance(v, str):
        return v
    return f'{v:+.1f}{suffix}'


def main():
    print('== 0/4 增量更新行情数据 ==')
    ensure_market_updated()

    print('== 1/4 读取持仓 ==')
    pos = load_positions()
    print(f'当前持仓: {len(pos)} 笔')
    for c, p in pos.items():
        print(f'  {p["name"]} ({c}) ¥{p["amt"]:,.0f}')

    print('== 2/4 加载行情 ==')
    data = load_market()
    themes = theme_aggregate(data)
    print(f'行业型 ETF {len(data)} 只 / {len(themes)} 个主题')

    print('== 3/4 分析持仓并生成报告 ==')
    rows = analyze_holdings(pos, data, themes)

    # --- 主题排名表（全部）---
    theme_rows = ''
    # 全部主题（不截断，便于看资金流向：排名=强弱，资金流列=净流入/流出）
    for i, t in enumerate(themes, 1):
        score_pill = f'<span style="background:{"#fff0f0" if t["score"]>=65 else ("#fff9e6" if t["score"]>=35 else "#eaf3de")};color:{"#c92a2a" if t["score"]>=65 else ("#ba7517" if t["score"]>=35 else "#3b6d11")};padding:2px 8px;border-radius:8px;font-weight:700">{t["score"]:.0f}</span>'
        pct_c = 'up' if (t['pct250'] or 0) > 0.5 else ('down' if (t['pct250'] if t['pct250'] is not None else 1) < 0.3 else '')
        pct_txt = f"{t['pct250']:.0%}" if t['pct250'] is not None else '—'
        theme_rows += f'''<tr>
          <td>{i}</td><td><b>{t['theme']}</b></td><td>{t['count']}</td>
          <td>{t['rep_name']}<br><span style="color:#868e96;font-size:11px">{t['rep_code']} · 综合分{t['rep_score']:.0f}</span></td>
          <td class="{'up' if t['mom5']>0 else 'down'}">{t['mom5']:+.1f}%</td>
          <td class="{'up' if t['mom20']>0 else 'down'}">{t['mom20']:+.1f}%</td>
          <td class="{'up' if t['mom60']>0 else 'down'}">{t['mom60']:+.1f}%</td>
          <td class="{pct_c}">{pct_txt}</td>
          <td class="{'up' if t['flow20']>0 else 'down'}">{t['flow20']:+.0f}%</td>
          <td>{score_pill}</td>
          <td>{t['bull']}/{t['count']}</td>
          <td>{'<span style="color:#e8590c;font-weight:700">' + str(t['weak']) + '</span>' if t['weak'] else '0'}</td>
        </tr>'''

    # --- 低估方向（分位<0.3）---
    low_list = [t for t in themes if t['pct250'] is not None and t['pct250'] < BUY_PCT]
    low_rows = ''
    for t in sorted(low_list, key=lambda x: x['pct250'])[:15]:
        low_rows += f'''<tr><td>{t['theme']}</td><td>{t['count']}只</td>
          <td class="down">{t['pct250']:.0%}</td>
          <td>{t['rep_name']}</td>
          <td class="{'up' if t['mom20']>0 else 'down'}">{t['mom20']:+.1f}%</td></tr>'''
    low_note = f'当前 {len(low_list)} 个方向处于历史低位（250日分位&lt;{BUY_PCT:.0%}）——均值回归参考' if low_list else '当前无深度低估方向'

    # --- 强势方向（双多）---
    strong_list = [t for t in themes if t['score'] >= 65 and t['mom20'] > 0 and t['bull']]
    strong_rows = ''
    for t in sorted(strong_list, key=lambda x: -x['score'])[:15]:
        strong_rows += f'''<tr><td>{t['theme']}</td><td>{t['count']}只</td>
          <td class="up">{t['score']:.0f}</td>
          <td>{t['rep_name']}</td>
          <td class="up">{t['mom20']:+.1f}%</td>
          <td class="up">{t['mom60']:+.1f}%</td></tr>'''
    strong_note = f'当前 {len(strong_list)} 个方向动量+MACD双多——趋势参考' if strong_list else '当前无双多方向（市场偏弱）'

    # --- 持仓表 ---
    hold_rows = ''
    for r in rows:
        warn_txt = '<br>'.join(f'<span style="font-size:12px">{w}</span>' for w in r['warnings'])
        amt_txt = f"¥{r['amt']:,.0f}"
        score_txt = r['score'] if isinstance(r['score'], (int, float)) else '—'
        # 历史分位：0~1 小数按百分比显示（0.2 → 20%）
        pct_txt = f"{r['pct']:.0%}" if isinstance(r['pct'], (int, float)) else '—'
        hold_rows += f'''<tr>
          <td><b>{r['fund']}</b><br><span style="color:#868e96;font-size:11px">{r['code']}</span></td>
          <td><span style="background:#edf2ff;color:#364fc7;padding:2px 8px;border-radius:8px;font-weight:700">{r['theme']}</span></td>
          <td>{amt_txt}</td>
          <td class="{'up' if isinstance(r['mom20'], (int,float)) and r['mom20']>0 else 'down'}">{fmt_pct(r['mom20'])}</td>
          <td>{pct_txt}</td>
          <td><b>{score_txt}</b></td>
          <td style="text-align:left">{warn_txt}</td>
        </tr>'''

    gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    market_date = data[next(iter(data))]['date'] if data else '—'

    html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>行业数据分析日报</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--line:#e3e6eb;--tx:#1c2333}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:-apple-system,"Microsoft YaHei",sans-serif;font-size:14px}}
header{{background:#fff;border-bottom:1px solid var(--line);padding:22px 0}}
.wrap{{max-width:1150px;margin:0 auto;padding:0 20px}}
header h1{{font-size:22px}}
header .sub{{opacity:.85;font-size:13px;margin-top:6px}}
.card{{background:var(--card);border-radius:14px;padding:20px 22px;margin:18px 0;border:1px solid var(--line)}}
.card h2{{font-size:17px;margin-bottom:12px}}
.card h3{{font-size:14px;color:#364fc7;margin:6px 0 10px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f1f3f5;padding:9px 8px;text-align:center;font-weight:600;border-bottom:2px solid var(--line)}}
td{{padding:8px;text-align:center;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9fa}}
.up{{color:#e03131;font-weight:600}}
.down{{color:#0ca678;font-weight:600}}
.note{{font-size:13px;color:#5b6472;line-height:1.7;margin-top:10px}}
.warn-box{{border-left:4px solid #f59f00;background:#fff9db;padding:12px 14px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;margin:10px 0}}
.ok-box{{border-left:4px solid #0ca678;background:#ebfbee;padding:12px 14px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;margin:10px 0}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
.kpi{{flex:1;min-width:150px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi .k{{color:#5b6472;font-size:12px}}
.kpi .v{{font-size:22px;font-weight:700;margin-top:4px}}
.disclaimer{{font-size:12px;color:#868e96;line-height:1.7;margin-top:16px;padding:12px;background:#f8f9fa;border-radius:10px}}
</style></head><body>
<header><div class="wrap">
<h1>行业数据分析日报</h1>
<div class="sub">数据日期 {market_date} · 生成时间 {gen_time} · 本报告仅做数据分析与参考，不构成买卖指令</div>
</div></header>
<div class="wrap">

<div class="kpis">
  <div class="kpi"><div class="k">当前持仓</div><div class="v">{len(rows)} 笔</div><div class="note">Sector.log 推导</div></div>
  <div class="kpi"><div class="k">持仓总金额</div><div class="v">¥{sum(r['amt'] for r in rows):,.0f}</div><div class="note">买入-赎回累计</div></div>
  <div class="kpi"><div class="k">行业主题</div><div class="v">{len(themes)} 个</div><div class="note">行业型 ETF 聚合</div></div>
  <div class="kpi"><div class="k">低估方向</div><div class="v">{len(low_list)} 个</div><div class="note">分位&lt;30%</div></div>
  <div class="kpi"><div class="k">强势方向</div><div class="v">{len(strong_list)} 个</div><div class="note">综合分≥65 双多</div></div>
</div>

<div class="card"><h2>📋 当前行业持仓与预警</h2>
<p class="note">持仓来自 Sector.log（买入-赎回推导）。预警用对应主题的代表 ETF 信号代理（场内 ETF 与场外联接基金跟踪同一指数，趋势一致）。</p>
<table><thead><tr><th>持仓基金</th><th>主题</th><th>持仓金额</th><th>20日动量</th><th>历史分位</th><th>综合分</th><th>预警</th></tr></thead>
<tbody>{hold_rows}</tbody></table>
</div>

<div class="card"><h2>📉 低估方向雷达（参考）</h2>
<p class="note">{low_note}</p>
<table><thead><tr><th>方向</th><th>标的数</th><th>历史分位</th><th>代表ETF</th><th>20日动量</th></tr></thead>
<tbody>{low_rows}</tbody></table>
</div>

<div class="card"><h2>📈 强势方向雷达（参考）</h2>
<p class="note">{strong_note}</p>
<table><thead><tr><th>方向</th><th>标的数</th><th>评分</th><th>代表ETF</th><th>20日动量</th><th>60日动量</th></tr></thead>
<tbody>{strong_rows}</tbody></table>
</div>

<div class="card"><h2>🗂️ 全部行业主题排名（{len(themes)} 个，按综合分均值降序）</h2>
<p class="note">综合分 = 20日动量30 + 5日动量10 + 60日动量10 + MACD多头/红柱15 + 站上MA60/偏离15 + 历史分位低估10 + 资金流10（满分100，权重可调）。「多头」= MACD多头标的数/总数；「衰竭」= MACD红柱缩短警告数；「资金流」= 近20日量能方向比（上涨放量-下跌放量，正=净流入）。历史分位 = 250日价格分位，&lt;30%低估、&gt;70%高估。</p>
<table><thead><tr><th>#</th><th>方向</th><th>标的数</th><th>代表ETF</th><th>5日动量</th><th>20日动量</th><th>60日动量</th><th>历史分位</th><th>资金流</th><th>综合分</th><th>多头</th><th>衰竭</th></tr></thead>
<tbody>{theme_rows}</tbody></table>
</div>

<div class="disclaimer">⚠️ 免责声明：本报告基于公开行情数据的量化分析，仅供参考，不构成投资建议。动量/分位/评分均为历史统计，不预示未来。任何操作请结合个人风险承受能力独立判断。场外基金费率与赎回到账时间以基金公司公告为准。</div>

</div></body></html>'''
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n报告已生成: {OUT_HTML}')
    print(f'持仓预警 {sum(1 for r in rows if any("⚠️" in w or "🟠" in w for w in r["warnings"]))} 笔 | 低估方向 {len(low_list)} | 强势方向 {len(strong_list)}')


if __name__ == '__main__':
    main()
