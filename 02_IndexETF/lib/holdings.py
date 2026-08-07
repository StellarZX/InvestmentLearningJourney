"""
Emergency position review for existing holdings.

Reads the actual holdings from the repository root README.md (the single source
of truth), attaches market metrics for each tracked index, and produces a
"sell first / keep" recommendation for a crash / urgent-cash scenario.

This is a decision-support framework, not investment advice.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

import dca

BASE_DIR = Path(__file__).resolve().parent.parent
SUMMARY_FILE = BASE_DIR.parent / "README.md"

# Holding code -> (index data folder, tracking index name)
HOLDING_INDEX_MAP: dict[str, tuple[str, str]] = {
    "460300": ("csi_300", "CSI 300"),
    "160119": ("csi_500", "CSI 500"),
    "110026": ("chi_next", "ChiNext"),
    "100032": ("csi_dividend", "CSI Dividend"),
    "021457": ("hsi_dividend_lowvol", "HS Dividend Low Vol"),
    "164705": ("hang_seng", "Hang Seng Index"),
    "SXR8": ("sp500", "S&P 500"),
}

CASH_CODES = {"EUR", "CNY", "USD", "HKD"}

# 赎回到账速度（应急用钱时的重要维度）
LIQUIDITY: dict[str, dict[str, str]] = {
    "460300": {"label": "快：赎回 T+1~T+3 到账", "level": "fast"},
    "160119": {"label": "快：赎回 T+1~T+3 到账", "level": "fast"},
    "110026": {"label": "快：赎回 T+1~T+3 到账", "level": "fast"},
    "100032": {"label": "快：赎回 T+1~T+3 到账", "level": "fast"},
    "021457": {"label": "慢：QDII 赎回约 T+7~T+10 到账", "level": "slow"},
    "164705": {"label": "慢：QDII 赎回约 T+7~T+10 到账", "level": "slow"},
    "SXR8": {"label": "中：卖出即时锁价，T+2 交割", "level": "medium"},
}

# 持仓角色标签
ROLE_LABEL = {
    "460300": "A股核心底仓",
    "160119": "A股中盘补充",
    "110026": "A股成长卫星",
    "100032": "A股红利防御",
    "021457": "港股红利低波卫星",
    "164705": "港股宽基卫星",
    "SXR8": "美股核心底仓",
}

# Position class codes for localization
POSITION_CLASS_CODE = {
    "460300": "core",
    "160119": "satellite",
    "110026": "satellite",
    "100032": "satellite",
    "021457": "satellite",
    "164705": "satellite",
    "SXR8": "core",
}

# Fallback holdings (used when the root README table cannot be parsed)
FALLBACK_HOLDINGS: list[dict[str, str]] = [
    {"market": "China A-share", "platform": "Domestic fund platform", "fund": "华泰柏瑞沪深300ETF联接A", "code": "460300", "target": "25%", "current_pct": "43.8%", "position": "¥2,625", "cost": "¥2,625", "return_pct": "0.0%"},
    {"market": "China A-share", "platform": "Domestic fund platform", "fund": "南方中证500ETF联接(LOF)A", "code": "160119", "target": "15%", "current_pct": "6.2%", "position": "¥371", "cost": "¥371", "return_pct": "0.0%"},
    {"market": "China A-share", "platform": "Domestic fund platform", "fund": "易方达创业板ETF联接A", "code": "110026", "target": "10%", "current_pct": "2.1%", "position": "¥125", "cost": "¥125", "return_pct": "0.0%"},
    {"market": "China A-share", "platform": "Domestic fund platform", "fund": "富国中证红利指数增强A", "code": "100032", "target": "15%", "current_pct": "3.1%", "position": "¥188", "cost": "¥188", "return_pct": "0.0%"},
    {"market": "Hong Kong", "platform": "Domestic fund platform", "fund": "汇添富恒生指数（QDII-LOF）", "code": "164705", "target": "15%", "current_pct": "19.8%", "position": "¥1,187", "cost": "¥1,187", "return_pct": "0.0%"},
    {"market": "Hong Kong", "platform": "Domestic fund platform", "fund": "易方达恒生红利低波ETF联接A", "code": "021457", "target": "20%", "current_pct": "25%", "position": "¥1,500", "cost": "¥1,500", "return_pct": "0.0%"},
    {"market": "美国", "platform": "IBKR", "fund": "安硕标普500 UCITS ETF（美元，累计）", "code": "SXR8", "target": "-", "current_pct": "-", "position": "0.6 份", "cost": "€425.918", "return_pct": "-"},
    {"market": "现金", "platform": "IBKR", "fund": "欧元现金", "code": "EUR", "target": "-", "current_pct": "-", "position": "€74.082", "cost": "€74.082", "return_pct": "-"},
]


def parse_summary_holdings() -> list[dict[str, str]]:
    if not SUMMARY_FILE.exists():
        return FALLBACK_HOLDINGS
    lines = SUMMARY_FILE.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^#{2,3}\s+(Current Holdings|当前持仓)", line)), None)
    if start is None:
        return FALLBACK_HOLDINGS
    table_start = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("|") and ("Market" in lines[i] or "市场" in lines[i])),
        None,
    )
    if table_start is None:
        return FALLBACK_HOLDINGS
    rows: list[dict[str, str]] = []
    for i in range(table_start + 1, len(lines)):
        line = lines[i]
        if not line.startswith("|"):
            break
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[3]:
            rows.append({
                "market": cells[0],
                "platform": cells[1],
                "fund": cells[2],
                "code": cells[3],
                "target": cells[4],
                "current_pct": cells[5],
                "position": cells[6],
                "cost": cells[7],
                "return_pct": cells[8],
            })
    return rows or FALLBACK_HOLDINGS


def extract_amount(raw: str) -> float | None:
    if not raw:
        return None
    match = re.search(r"\d+(?:\.\d+)?", raw.replace(",", ""))
    return float(match.group()) if match else None


def score_trend(distance_pct: float | None) -> int:
    if distance_pct is None:
        return 50
    if distance_pct >= 5:
        return 20
    if distance_pct >= 0:
        return 35
    if distance_pct >= -5:
        return 55
    if distance_pct >= -15:
        return 75
    return 90


def score_momentum(ret_6m_pct: float | None) -> int:
    if ret_6m_pct is None:
        return 50
    if ret_6m_pct >= 10:
        return 20
    if ret_6m_pct >= 0:
        return 40
    if ret_6m_pct >= -10:
        return 60
    if ret_6m_pct >= -20:
        return 75
    return 90


def tier_for(score: float) -> tuple[str, str]:
    if score >= 70:
        return "优先卖出", "high"
    if score >= 55:
        return "可考虑卖出", "medium"
    return "继续持有", "low"


def holding_metrics(slug: str) -> dict[str, Any] | None:
    df = dca.read_index_csvs(slug)
    if df.empty or "close" not in df.columns:
        return None
    close = pd.to_numeric(df["close"], errors="coerce").dropna().reset_index(drop=True)
    if len(close) < 60:
        return None
    latest = float(close.iloc[-1])
    last_date = str(pd.to_datetime(df["date"]).max().date())

    ma200 = close.rolling(200, min_periods=60).mean().iloc[-1]
    ma200_dist_pct = (latest / float(ma200) - 1) * 100 if pd.notna(ma200) and ma200 else None
    ret_6m_pct = (latest / float(close.iloc[-126]) - 1) * 100 if len(close) > 126 else None
    high_3y = float(close.iloc[-756:].max())
    drawdown_pct = (latest / high_3y - 1) * 100 if high_3y else None

    price_pctile = float(dca.trailing_percentile(close).iloc[-1]) if len(close) >= 60 else None

    val_pctile: float | None = None
    vdf = dca.read_valuation_csvs(slug)
    if not vdf.empty and "pe_ttm" in vdf.columns:
        pe = pd.to_numeric(vdf["pe_ttm"], errors="coerce").dropna()
        if len(pe) >= 60:
            val_pctile = float(dca.expanding_percentile(pe).iloc[-1])

    if val_pctile is not None:
        valuation_pct = val_pctile
        valuation_source = "PE(TTM) 历史分位"
        valuation_source_code = "pe_history"
    elif price_pctile is not None:
        valuation_pct = price_pctile
        valuation_source = "价格分位（近3年）"
        valuation_source_code = "price_3y"
    else:
        valuation_pct = None
        valuation_source = "暂无数据"
        valuation_source_code = "none"

    trend_score = score_trend(ma200_dist_pct)
    momentum_score = score_momentum(ret_6m_pct)
    valuation_score = valuation_pct if valuation_pct is not None else 50.0
    sell_score = round(0.4 * trend_score + 0.3 * momentum_score + 0.3 * valuation_score, 1)

    return {
        "slug": slug,
        "latest_close": round(latest, 2),
        "last_date": last_date,
        "ma200_distance_pct": round(ma200_dist_pct, 1) if ma200_dist_pct is not None else None,
        "trend": "above" if (ma200_dist_pct or 0) >= 0 else "below",
        "trend_label": "多头（站上200日线）" if (ma200_dist_pct or 0) >= 0 else "空头（跌破200日线）",
        "ret_6m_pct": round(ret_6m_pct, 1) if ret_6m_pct is not None else None,
        "drawdown_pct": round(drawdown_pct, 1) if drawdown_pct is not None else None,
        "price_pctile": round(price_pctile, 1) if price_pctile is not None else None,
        "valuation_pct": round(valuation_pct, 1) if valuation_pct is not None else None,
        "valuation_source": valuation_source,
        "valuation_source_code": valuation_source_code,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "sell_score": sell_score,
    }


def build_holdings_decision() -> dict[str, Any]:
    holdings = parse_summary_holdings()
    items: list[dict[str, Any]] = []
    cash_items: list[dict[str, Any]] = []

    for holding in holdings:
        code = holding["code"].strip()
        base = {
            "market": holding["market"],
            "platform": holding["platform"],
            "fund": holding["fund"],
            "code": code,
            "target": holding.get("target", "-"),
            "position_raw": holding["position"],
            "cost_raw": holding["cost"],
            "position_amount": extract_amount(holding["position"]),
            "cost_amount": extract_amount(holding["cost"]),
            "role": holding.get("role", ""),
        }
        if base["position_amount"] == 0:
            continue  # planned but not held yet (position 0 in the portfolio table)
        if code in CASH_CODES or "cash" in holding["fund"].lower():
            base.update({
                "position_class": "现金缓冲",
                "position_class_code": "cash",
                "sell_score": None,
                "tier": "保留现金",
                "tier_level": "cash",
                "recommendation": "现金是应急缓冲，优先使用它而不是卖基金",
                "liquidity": {"label": "已到账", "level": "cash"},
            })
            cash_items.append(base)
            continue

        mapped = HOLDING_INDEX_MAP.get(code)
        if not mapped:
            base.update({
                "position_class": "未知",
                "position_class_code": "unknown",
                "sell_score": None,
                "tier": "数据不足",
                "tier_level": "none",
                "recommendation": "未映射指数，请手动评估",
                "liquidity": LIQUIDITY.get(code, {"label": "未知", "level": "none"}),
                "note": "指数未映射",
            })
            items.append(base)
            continue

        slug, tracking = mapped
        metrics = holding_metrics(slug)
        if not metrics:
            base.update({
                "position_class": ROLE_LABEL.get(code, "持仓"),
                "position_class_code": POSITION_CLASS_CODE.get(code, "unknown"),
                "sell_score": None,
                "tier": "数据不足",
                "tier_level": "none",
                "recommendation": "指数数据不足，请手动评估",
                "liquidity": LIQUIDITY.get(code, {"label": "未知", "level": "none"}),
                "note": "无指数数据",
            })
            items.append(base)
            continue

        tier, tier_level = tier_for(metrics["sell_score"])
        is_core = code in {"460300", "SXR8"}
        recommendation = tier
        if tier_level == "low" and is_core:
            recommendation = "继续持有（核心底仓）"
        elif tier_level == "high" and is_core:
            recommendation = "优先卖出（虽是核心，但趋势与估值均弱）"
        elif tier_level == "medium" and is_core:
            recommendation = "可考虑卖出（核心底仓，谨慎权衡）"

        base.update({
            "position_class": ROLE_LABEL.get(code, "持仓"),
            "position_class_code": POSITION_CLASS_CODE.get(code, "unknown"),
            "is_core": is_core,
            "tracking": tracking,
            "slug": slug,
            "liquidity": LIQUIDITY.get(code, {"label": "未知", "level": "none"}),
            "tier": tier,
            "tier_level": tier_level,
            "recommendation": recommendation,
            **metrics,
        })
        items.append(base)

    items.sort(key=lambda item: (item.get("sell_score") is None, -(item.get("sell_score") or 0)))
    sell_order = [f"{i + 1}. {item['fund']}（优先级 {item['sell_score']:.0f}，{item['tier']}）"
                  for i, item in enumerate([it for it in items if it.get("sell_score") is not None])]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": max((item.get("last_date") for item in items if item.get("last_date")), default=date.today().isoformat()),
        "summary_source": str(SUMMARY_FILE.relative_to(BASE_DIR.parent)) if SUMMARY_FILE.exists() else "fallback list",
        "cash": cash_items,
        "items": items,
        "sell_order": sell_order,
        "notes": [
            "卖出优先级 = 40% 趋势（相对200日线）+ 30% 动量（近6个月）+ 30% 估值/价格分位；分数越高越建议先卖。",
            "急用现金时优先考虑到账速度：先用现金缓冲，再卖 A 股基金（T+1~T+3 到账），IBKR 卖出 T+2 交割，QDII 赎回最慢（T+7~T+10）。",
            "大跌中跌幅已深的持仓往往更接近阶段性底部，单纯因下跌而割肉需谨慎；本表反映的是趋势/动量/估值状态，不是买卖时点建议。",
            "本页面仅为决策参考框架，不构成投资建议；实际平仓请结合你的现金需求、持有成本与税务情况。",
        ],
        "disclaimer": "决策参考，非投资建议。",
    }


def print_holdings(payload: dict[str, Any]) -> None:
    print("=" * 68)
    print("持仓应急评估（决策参考，非投资建议）")
    print("=" * 68)
    for item in payload["items"]:
        score = f"{item['sell_score']:.0f}" if item.get("sell_score") is not None else "-"
        print(f"  {item['code']:<8} {item['fund']:<34} 优先级 {score:>3}  [{item['tier']}]")
        print(f"          趋势：{item.get('trend_label', '-')} | 近6月：{item.get('ret_6m_pct', '-')}% | "
              f"回撤：{item.get('drawdown_pct', '-')}% | 估值分位：{item.get('valuation_pct', '-')}%")
        print(f"          {item['recommendation']} | 到账速度：{item['liquidity']['label']}")
    if payload["cash"]:
        for c in payload["cash"]:
            print(f"  {c['code']:<8} {c['fund']:<34} 现金缓冲：{c['position_raw']}")
    print("-" * 68)
    print("建议卖出顺序（质地角度）：")
    for line in payload["sell_order"]:
        print(f"  {line}")
    print("=" * 68)


if __name__ == "__main__":
    print_holdings(build_holdings_decision())
