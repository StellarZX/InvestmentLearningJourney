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

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR.parent / "README.md"

# Holding code -> (index data folder, tracking index name)
HOLDING_INDEX_MAP: dict[str, tuple[str, str]] = {
    "460300": ("csi_300", "CSI 300"),
    "021457": ("hsi_dividend_lowvol", "HS Dividend Low Vol"),
    "164705": ("hang_seng", "Hang Seng Index"),
    "SXR8": ("sp500", "S&P 500"),
}

CASH_CODES = {"EUR", "CNY", "USD", "HKD"}

# Redemption / settlement speed (key dimension for raising cash in an emergency)
LIQUIDITY: dict[str, dict[str, str]] = {
    "460300": {"label": "Fast: redemption T+1~T+3", "level": "fast"},
    "021457": {"label": "Slow: QDII redemption ~T+7~T+10", "level": "slow"},
    "164705": {"label": "Slow: QDII redemption ~T+7~T+10", "level": "slow"},
    "SXR8": {"label": "Medium: same-day sell, T+2 settlement", "level": "medium"},
}

# Position class labels (English)
ROLE_LABEL = {
    "460300": "A-share core holding",
    "021457": "HK dividend low-vol satellite",
    "164705": "HK broad-market satellite",
    "SXR8": "US core holding",
}

# Position class codes for localization
POSITION_CLASS_CODE = {
    "460300": "core",
    "021457": "satellite",
    "164705": "satellite",
    "SXR8": "core",
}

# Fallback holdings (used when the root README table cannot be parsed)
FALLBACK_HOLDINGS: list[dict[str, str]] = [
    {"market": "China A-share", "platform": "Domestic fund platform", "fund": "华泰柏瑞沪深300ETF联接A", "code": "460300", "position": "¥2,000", "cost": "¥2,000", "role": "China core broad-market exposure"},
    {"market": "Hong Kong", "platform": "Domestic fund platform", "fund": "易方达恒生红利低波ETF联接A", "code": "021457", "position": "¥1,000", "cost": "¥1,000", "role": "Hong Kong high-dividend low-volatility allocation"},
    {"market": "Hong Kong", "platform": "Domestic fund platform", "fund": "汇添富恒生指数（QDII-LOF）", "code": "164705", "position": "¥1,000", "cost": "¥1,000", "role": "Hang Seng broad-market exposure"},
    {"market": "United States", "platform": "IBKR", "fund": "iShares Core S&P 500 UCITS ETF USD (Acc)", "code": "SXR8", "position": "0.6 shares", "cost": "€425.918", "role": "US large-cap equity exposure"},
    {"market": "Cash", "platform": "IBKR", "fund": "EUR cash", "code": "EUR", "position": "€74.082", "cost": "€74.082", "role": "Cash buffer"},
]


def parse_summary_holdings() -> list[dict[str, str]]:
    if not SUMMARY_FILE.exists():
        return FALLBACK_HOLDINGS
    lines = SUMMARY_FILE.read_text(encoding="utf-8").splitlines()
    in_table = False
    rows: list[dict[str, str]] = []
    for line in lines:
        if re.match(r"^#{2,3}\s+Current Holdings", line):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 7 and cells[3]:
                rows.append({
                    "market": cells[0],
                    "platform": cells[1],
                    "fund": cells[2],
                    "code": cells[3],
                    "position": cells[4],
                    "cost": cells[5],
                    "role": cells[-1],
                })
        elif line.strip() == "":
            in_table = False
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
        return "Sell first", "high"
    if score >= 55:
        return "May sell", "medium"
    return "Keep", "low"


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
        valuation_source = "PE(TTM) history percentile"
        valuation_source_code = "pe_history"
    elif price_pctile is not None:
        valuation_pct = price_pctile
        valuation_source = "3-year price percentile"
        valuation_source_code = "price_3y"
    else:
        valuation_pct = None
        valuation_source = "No data"
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
        "trend_label": "Above 200-day MA" if (ma200_dist_pct or 0) >= 0 else "Below 200-day MA",
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
            "position_raw": holding["position"],
            "cost_raw": holding["cost"],
            "position_amount": extract_amount(holding["position"]),
            "cost_amount": extract_amount(holding["cost"]),
            "role": holding["role"],
        }
        if code in CASH_CODES or "cash" in holding["fund"].lower():
            base.update({
                "position_class": "Cash buffer",
                "position_class_code": "cash",
                "sell_score": None,
                "tier": "Keep cash",
                "tier_level": "cash",
                "recommendation": "Cash is the emergency buffer; use it before selling funds",
                "liquidity": {"label": "Settled", "level": "cash"},
            })
            cash_items.append(base)
            continue

        mapped = HOLDING_INDEX_MAP.get(code)
        if not mapped:
            base.update({
                "position_class": "Unknown",
                "position_class_code": "unknown",
                "sell_score": None,
                "tier": "Insufficient data",
                "tier_level": "none",
                "recommendation": "No index mapping - evaluate manually",
                "liquidity": LIQUIDITY.get(code, {"label": "Unknown", "level": "none"}),
                "note": "Index not mapped",
            })
            items.append(base)
            continue

        slug, tracking = mapped
        metrics = holding_metrics(slug)
        if not metrics:
            base.update({
                "position_class": ROLE_LABEL.get(code, "Holding"),
                "position_class_code": POSITION_CLASS_CODE.get(code, "unknown"),
                "sell_score": None,
                "tier": "Insufficient data",
                "tier_level": "none",
                "recommendation": "Insufficient index data - evaluate manually",
                "liquidity": LIQUIDITY.get(code, {"label": "Unknown", "level": "none"}),
                "note": "No index data",
            })
            items.append(base)
            continue

        tier, tier_level = tier_for(metrics["sell_score"])
        is_core = code in {"460300", "SXR8"}
        recommendation = tier
        if tier_level == "low" and is_core:
            recommendation = "Keep (core holding)"
        elif tier_level == "high" and is_core:
            recommendation = "Sell first (core, but trend and valuation are both weak)"
        elif tier_level == "medium" and is_core:
            recommendation = "May sell (core holding - weigh carefully)"

        base.update({
            "position_class": ROLE_LABEL.get(code, "Holding"),
            "position_class_code": POSITION_CLASS_CODE.get(code, "unknown"),
            "is_core": is_core,
            "tracking": tracking,
            "slug": slug,
            "liquidity": LIQUIDITY.get(code, {"label": "Unknown", "level": "none"}),
            "tier": tier,
            "tier_level": tier_level,
            "recommendation": recommendation,
            **metrics,
        })
        items.append(base)

    items.sort(key=lambda item: (item.get("sell_score") is None, -(item.get("sell_score") or 0)))
    sell_order = [f"{i + 1}. {item['fund']} (score {item['sell_score']:.0f}, {item['tier']})"
                  for i, item in enumerate([it for it in items if it.get("sell_score") is not None])]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": max((item.get("last_date") for item in items if item.get("last_date")), default=date.today().isoformat()),
        "summary_source": str(SUMMARY_FILE.relative_to(BASE_DIR.parent)) if SUMMARY_FILE.exists() else "fallback list",
        "cash": cash_items,
        "items": items,
        "sell_order": sell_order,
        "notes": [
            "Sell priority = 40% trend (vs 200-day MA) + 30% momentum (6-month) + 30% valuation/price percentile; higher score suggests selling first.",
            "For urgent cash, prioritize settlement speed: use the cash buffer first, then A-share funds (T+1~T+3), IBKR (T+2), QDII last (T+7~T+10).",
            "Positions already deep in a drawdown are often closer to a bottom; selling just because of a drop needs care. This table reflects trend/momentum/valuation state, not timing advice.",
            "This page is a decision-support framework, not investment advice; consider your cash needs, cost basis and tax situation.",
        ],
        "disclaimer": "Decision reference only; not investment advice.",
    }


def print_holdings(payload: dict[str, Any]) -> None:
    print("=" * 68)
    print("Emergency position review (decision reference, not investment advice)")
    print("=" * 68)
    for item in payload["items"]:
        score = f"{item['sell_score']:.0f}" if item.get("sell_score") is not None else "-"
        print(f"  {item['code']:<8} {item['fund']:<34} score {score:>3}  [{item['tier']}]")
        print(f"          trend: {item.get('trend_label', '-')} | 6M: {item.get('ret_6m_pct', '-')}% | "
              f"drawdown: {item.get('drawdown_pct', '-')}% | valuation pct: {item.get('valuation_pct', '-')}%")
        print(f"          {item['recommendation']} | settlement: {item['liquidity']['label']}")
    if payload["cash"]:
        for c in payload["cash"]:
            print(f"  {c['code']:<8} {c['fund']:<34} cash buffer: {c['position_raw']}")
    print("-" * 68)
    print("Suggested sell order (quality perspective):")
    for line in payload["sell_order"]:
        print(f"  {line}")
    print("=" * 68)


if __name__ == "__main__":
    print_holdings(build_holdings_decision())
