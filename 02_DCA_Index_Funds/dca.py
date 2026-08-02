"""
Monthly DCA allocation decision for the 02_DCA_Index_Funds dashboard.

Defines a fund universe available from the Bank of China app (CNY) and
Interactive Brokers (EUR), maps each fund to its tracking index, and computes
how to split a monthly budget (default: ¥2,000 + €50) using valuation
percentiles where available and price percentiles otherwise.

Usage:
    python dca.py --check            # print this month's allocation
    python dca.py --refresh          # fetch/refresh valuation and price data
    python dca.py --refresh --check

The fund list is a suggestion for learning. Verify availability and purchase
limits in your own apps, and edit FUNDS below to match your own plan.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INDEX_DIR = DATA_DIR / "indices"
VALUATION_DIR = DATA_DIR / "valuations"

CN_BUDGET = 2000.0
EUR_BUDGET = 50.0

# Percentile-to-monthly-multiplier rule
CHEAP_PCTILE = 30.0
EXPENSIVE_PCTILE = 70.0
CHEAP_MULTIPLIER = 1.5
EXPENSIVE_MULTIPLIER = 0.5

PRICE_WINDOW = 756  # Price-percentile lookback window (about 3 years of trading days)


@dataclass(frozen=True)
class Fund:
    market: str                 # "cn" | "ibkr"
    name: str                   # Fund name (kept in Chinese)
    code: str                   # Fund code / ETF ticker
    tracking: str               # Tracking index (English)
    index_slug: str             # Local index data folder name
    base_weight: float          # Quota weight (editable)
    valuation_symbol: str | None = None   # Akshare Legulegu symbol (Chinese, data-source key)
    price_source: str | None = None       # "local" | "sina:sz399006" | "yf:EUNL.DE" | "yf:515080.SS"
    proxy_note: str | None = None         # Price-proxy note
    currency: str = "CNY"


FUNDS: list[Fund] = [
    # ---- Bank of China App (CNY, monthly budget ¥2,000) ----
    # Quota weights: base_weight (targets 25/15/10/15/15/20)
    Fund("cn", "华泰柏瑞沪深300ETF联接A", "460300", "CSI 300", "csi_300",
         2.5, valuation_symbol="沪深300", price_source="local"),
    Fund("cn", "南方中证500ETF联接(LOF)A", "160119", "CSI 500", "csi_500",
         1.5, valuation_symbol="中证500"),
    Fund("cn", "易方达创业板ETF联接A", "110026", "ChiNext", "chi_next",
         1.0, price_source="sina:sz399006"),
    Fund("cn", "富国中证红利指数增强A", "100032", "CSI Dividend", "csi_dividend",
         1.5, price_source="yf:515080.SS", proxy_note="Price proxy: CSI Dividend ETF (515080)"),
    Fund("cn", "汇添富恒生指数(QDII-LOF)A", "164705", "Hang Seng Index", "hang_seng",
         1.5, price_source="local"),
    Fund("cn", "易方达恒生红利低波ETF联接A", "021457", "HS Dividend Low Vol", "hsi_dividend_lowvol",
         2.0, price_source="yf:159545.SZ", proxy_note="Price proxy: HS Dividend Low Vol ETF (159545)"),
    # ---- Interactive Brokers (EUR, monthly budget €50) ----
    Fund("ibkr", "iShares Core S&P 500 UCITS ETF (Acc)", "SXR8", "S&P 500", "sp500",
         1.0, price_source="local", currency="EUR"),
    Fund("ibkr", "Invesco EQQQ NASDAQ-100 UCITS ETF (Acc)", "EQQQ", "NASDAQ-100", "nasdaq_100",
         1.0, price_source="local", currency="EUR"),
]


# ---------------------------------------------------------------------------
# Local data reading
# ---------------------------------------------------------------------------

def read_index_csvs(slug: str) -> pd.DataFrame:
    frames = []
    index_dir = INDEX_DIR / slug
    if not index_dir.exists():
        return pd.DataFrame()
    for path in sorted(index_dir.glob("*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def read_valuation_csvs(slug: str) -> pd.DataFrame:
    frames = []
    valuation_dir = VALUATION_DIR / slug
    if not valuation_dir.exists():
        return pd.DataFrame()
    for path in sorted(valuation_dir.glob("*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def save_by_year(directory: Path, slug: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    target = directory / slug
    target.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, year_df in df.groupby("year"):
        out = target / f"{int(year)}.csv"
        year_df.drop(columns=["year"]).to_csv(out, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)


# ---------------------------------------------------------------------------
# Percentile calculations
# ---------------------------------------------------------------------------

def expanding_percentile(values: pd.Series) -> pd.Series:
    """Percentile of each value within all history up to that date (no look-ahead)."""
    return values.expanding().apply(lambda a: float((a <= a[-1]).mean() * 100), raw=True)


def trailing_percentile(values: pd.Series, window: int = PRICE_WINDOW) -> pd.Series:
    """Rolling percentile over the last `window` trading days (None if fewer than 60 samples)."""
    vals = values.tolist()
    out: list[float | None] = []
    for i, v in enumerate(vals):
        start = max(0, i - window + 1)
        sample = vals[start : i + 1]
        if len(sample) < 60:
            out.append(None)
        else:
            out.append(float(sum(1 for x in sample if x <= v)) / len(sample) * 100)
    return pd.Series(out, index=values.index)


def multiplier_for(pctile: float) -> float:
    if pctile < CHEAP_PCTILE:
        return CHEAP_MULTIPLIER
    if pctile > EXPENSIVE_PCTILE:
        return EXPENSIVE_MULTIPLIER
    return 1.0


def zone_info(pctile: float) -> tuple[str, str]:
    if pctile < CHEAP_PCTILE:
        return "cheap", "Cheap"
    if pctile > EXPENSIVE_PCTILE:
        return "expensive", "Expensive"
    return "neutral", "Neutral"


def percentile_info(fund: Fund) -> dict[str, Any]:
    """Valuation percentile first; fall back to price percentile, then to 1.0x."""
    if fund.valuation_symbol:
        vdf = read_valuation_csvs(fund.index_slug)
        if not vdf.empty and "pe_ttm" in vdf.columns:
            pe = pd.to_numeric(vdf["pe_ttm"], errors="coerce").dropna()
            if len(pe) >= 60:
                pctile = float(expanding_percentile(pe).iloc[-1])
                zone, zone_label = zone_info(pctile)
                return {
                    "percentile": round(pctile, 1),
                    "source": "Legulegu PE(TTM) history percentile",
                    "source_code": "legulegu_pe",
                    "data_date": str(pd.to_datetime(vdf["date"]).max().date()),
                    "multiplier": multiplier_for(pctile),
                    "zone": zone,
                    "zone_label": zone_label,
                }

    if fund.price_source:
        pdf = read_index_csvs(fund.index_slug)
        if not pdf.empty and "close" in pdf.columns:
            close = pd.to_numeric(pdf["close"], errors="coerce").dropna().reset_index(drop=True)
            if len(close) >= 60:
                pctile_series = trailing_percentile(close)
                pctile_value = pctile_series.iloc[-1]
                if pctile_value is not None:
                    pctile = float(pctile_value)
                    zone, zone_label = zone_info(pctile)
                    source = "3-year price percentile (ETF proxy)" if fund.proxy_note else "3-year price percentile"
                    source_code = "price_proxy" if fund.proxy_note else "price_3y"
                    return {
                        "percentile": round(pctile, 1),
                        "source": source,
                        "source_code": source_code,
                        "data_date": str(pd.to_datetime(pdf["date"]).max().date()),
                        "multiplier": multiplier_for(pctile),
                        "zone": zone,
                        "zone_label": zone_label,
                    }

    return {
        "percentile": None,
        "source": "No data, treated as 1.0x",
        "source_code": "no_data",
        "data_date": None,
        "multiplier": 1.0,
        "zone": "none",
        "zone_label": "No data",
    }


# ---------------------------------------------------------------------------
# Amount allocation (largest-remainder method; total always equals the budget)
# ---------------------------------------------------------------------------

def allocate(budget: float, weights: list[float], decimals: int) -> list[float]:
    total = sum(weights) or 1.0
    factor = 10**decimals
    raw = [budget * w / total for w in weights]
    floors = [int(a * factor) for a in raw]
    fracs = [a * factor - f for a, f in zip(raw, floors)]
    target = round(budget * factor)
    diff = target - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-fracs[i], i))
    for k in range(abs(diff)):
        i = order[k % len(order)]
        floors[i] += 1 if diff > 0 else -1
    return [f / factor for f in floors]


# ---------------------------------------------------------------------------
# Data fetching (--refresh)
# ---------------------------------------------------------------------------

def fetch_valuation(valuation_symbol: str, fund: Fund) -> pd.DataFrame:
    import akshare as ak

    # Column names below are the Chinese field names returned by Akshare/Legulegu
    pe_df = ak.stock_index_pe_lg(symbol=valuation_symbol)
    pb_df = ak.stock_index_pb_lg(symbol=valuation_symbol)
    pe_df = pe_df.rename(columns={
        "日期": "date",
        "指数": "index_close",
        "滚动市盈率": "pe_ttm",
        "等权滚动市盈率": "equal_weight_pe_ttm",
        "滚动市盈率中位数": "median_pe_ttm",
        "静态市盈率": "pe_static",
    })
    pb_df = pb_df.rename(columns={
        "日期": "date",
        "市净率": "pb",
        "等权市净率": "equal_weight_pb",
        "市净率中位数": "median_pb",
    })
    keep_pe = ["date", "index_close", "pe_ttm", "equal_weight_pe_ttm", "median_pe_ttm", "pe_static"]
    keep_pb = ["date", "pb", "equal_weight_pb", "median_pb"]
    df = pe_df[keep_pe].merge(pb_df[keep_pb], on="date", how="left")
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["earnings_yield"] = (100 / pd.to_numeric(df["pe_ttm"], errors="coerce")).round(6)
    df["slug"] = fund.index_slug
    df["name"] = fund.tracking
    df["source"] = "Legulegu via AkShare"
    return df.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def fetch_price_sina(symbol: str, fund: Fund) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_index_daily(symbol=symbol)
    # Column names below are the Chinese field names returned by Sina/AkShare
    rename = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }
    if "日期" in df.columns:
        df = df.rename(columns=rename)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(df.get("open"), errors="coerce"),
        "high": pd.to_numeric(df.get("high"), errors="coerce"),
        "low": pd.to_numeric(df.get("low"), errors="coerce"),
        "close": pd.to_numeric(df.get("close"), errors="coerce"),
        "adj_close": pd.to_numeric(df.get("close"), errors="coerce"),
        "volume": pd.to_numeric(df.get("volume"), errors="coerce").fillna(0),
        "symbol": symbol,
        "name": fund.tracking,
        "region": "China",
        "currency": "CNY",
        "source": "Sina via AkShare",
    })
    return out.dropna(subset=["close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")


def utc_timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def fetch_price_yahoo(symbol: str, fund: Fund) -> pd.DataFrame:
    from curl_cffi import requests

    today = date.today()
    start = date(today.year - 10, 1, 1)
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?period1={utc_timestamp(start)}&period2={utc_timestamp(today + timedelta(days=1))}"
        "&interval=1d&events=history"
    )
    response = requests.get(url, timeout=30, impersonate="chrome")
    response.raise_for_status()
    payload = response.json()
    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"{symbol}: {error}")
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    rows = []
    for i, ts in enumerate(timestamps):
        close = quote.get("close") or [None]
        close = close[i] if i < len(close) else None
        if close is None or math.isnan(close):
            continue
        rows.append({
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
            "open": (quote.get("open") or [None])[i],
            "high": (quote.get("high") or [None])[i],
            "low": (quote.get("low") or [None])[i],
            "close": float(close),
            "adj_close": float(adjclose[i]) if i < len(adjclose) and adjclose[i] is not None else float(close),
            "volume": (quote.get("volume") or [None])[i],
            "symbol": symbol,
            "name": fund.tracking,
            "region": fund.currency,
            "currency": fund.currency,
            "source": "Yahoo Finance chart API",
        })
    return pd.DataFrame(rows).sort_values("date").drop_duplicates(subset=["date"], keep="last")


def refresh_data(force: bool = False) -> dict[str, Any]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    VALUATION_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    touched: set[str] = set()

    for fund in FUNDS:
        key = (fund.index_slug, fund.valuation_symbol or "", fund.price_source or "")
        if key in seen:
            continue
        seen.add(key)
        status: list[str] = []

        if fund.valuation_symbol:
            existing = read_valuation_csvs(fund.index_slug)
            if force or existing.empty or pd.to_datetime(existing["date"]).max().date() < today:
                try:
                    fetched = fetch_valuation(fund.valuation_symbol, fund)
                    if not fetched.empty:
                        merged = (
                            pd.concat([existing, fetched], ignore_index=True)
                            .sort_values("date")
                            .drop_duplicates(subset=["date"], keep="last")
                        )
                        save_by_year(VALUATION_DIR, fund.index_slug, merged)
                        status.append("valuation refreshed")
                        touched.add(fund.index_slug)
                    else:
                        status.append("valuation empty")
                except Exception as exc:  # noqa: BLE001
                    status.append(f"valuation failed: {type(exc).__name__}")

        if fund.price_source and fund.price_source != "local":
            existing = read_index_csvs(fund.index_slug)
            if force or existing.empty or pd.to_datetime(existing["date"]).max().date() < today:
                try:
                    if fund.price_source.startswith("sina:"):
                        fetched = fetch_price_sina(fund.price_source[5:], fund)
                    elif fund.price_source.startswith("yf:"):
                        fetched = fetch_price_yahoo(fund.price_source[3:], fund)
                    else:
                        fetched = pd.DataFrame()
                    if not fetched.empty:
                        merged = (
                            pd.concat([existing, fetched], ignore_index=True)
                            .sort_values("date")
                            .drop_duplicates(subset=["date"], keep="last")
                        )
                        save_by_year(INDEX_DIR, fund.index_slug, merged)
                        status.append("price refreshed")
                        touched.add(fund.index_slug)
                    else:
                        status.append("price empty")
                except Exception as exc:  # noqa: BLE001
                    status.append(f"price failed: {type(exc).__name__}")

        results.append({"slug": fund.index_slug, "tracking": fund.tracking, "status": " / ".join(status) or "cached"})

    # Keep metadata.json in sync so the dashboard data status stays consistent
    metadata_file = DATA_DIR / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata.setdefault("indices", {})
    for slug in touched:
        vdf = read_valuation_csvs(slug)
        pdf = read_index_csvs(slug)
        entry = metadata["indices"].get(slug, {})
        if not vdf.empty:
            entry.update({
                "valuation_rows": int(len(vdf)),
                "valuation_metrics": ["earnings_yield", "pe_ttm", "pb"],
                "valuation_first_date": str(pd.to_datetime(vdf["date"]).min().date()),
                "valuation_last_date": str(pd.to_datetime(vdf["date"]).max().date()),
            })
        if not pdf.empty:
            entry.update({
                "rows": int(len(pdf)),
                "first_date": str(pd.to_datetime(pdf["date"]).min().date()),
                "last_date": str(pd.to_datetime(pdf["date"]).max().date()),
                "years": sorted(int(y) for y in pd.to_datetime(pdf["date"]).dt.year.unique()),
            })
        entry["refreshed_at"] = datetime.now().isoformat(timespec="seconds")
        entry["last_checked_on"] = today.isoformat()
        metadata["indices"][slug] = entry
    if touched:
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"results": results}


# ---------------------------------------------------------------------------
# Decision generation
# ---------------------------------------------------------------------------

def build_dca_decision(budget_cny: float = CN_BUDGET, budget_eur: float = EUR_BUDGET) -> dict[str, Any]:
    groups = []
    for market, budget, decimals, currency in (
        ("cn", budget_cny, 0, "CNY"),
        ("ibkr", budget_eur, 2, "EUR"),
    ):
        funds = [f for f in FUNDS if f.market == market]
        items = []
        for fund in funds:
            info = percentile_info(fund)
            items.append({
                "name": fund.name,
                "code": fund.code,
                "tracking": fund.tracking,
                "index_slug": fund.index_slug,
                "proxy_note": fund.proxy_note,
                "base_weight": fund.base_weight,
                **info,
            })
        weights = [float(item["base_weight"]) * float(item["multiplier"]) for item in items]
        sum_base = sum(float(item["base_weight"]) for item in items)
        for item in items:
            item["quota_pct"] = round(float(item["base_weight"]) / sum_base * 100, 1) if sum_base else 0.0
        amounts = allocate(budget, weights, decimals)
        for item, amount in zip(items, amounts):
            item["amount"] = amount
        groups.append({
            "market": market,
            "label": "Bank of China App (CNY)" if market == "cn" else "Interactive Brokers (EUR)",
            "currency": currency,
            "budget": budget,
            "decimals": decimals,
            "items": items,
            "total": round(sum(amounts), decimals),
        })

    all_dates = [item["data_date"] for group in groups for item in group["items"] if item.get("data_date")]
    as_of = max(all_dates) if all_dates else datetime.now().date().isoformat()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "rule": {
            "cheap_pctile": CHEAP_PCTILE,
            "expensive_pctile": EXPENSIVE_PCTILE,
            "cheap_multiplier": CHEAP_MULTIPLIER,
            "expensive_multiplier": EXPENSIVE_MULTIPLIER,
        },
        "groups": groups,
        "notes": [
            "Percentile <30% -> buy 1.5x, 30-70% -> 1.0x, >70% -> 0.5x; then weights are normalized to the monthly budget.",
            "Funds without valuation data (HK/US/dividend indices) use a 3-year price percentile instead; for reference only.",
            "Amounts are planned figures excluding fees and purchase limits; QDII funds may restrict purchases - check the app.",
        ],
    }


def print_dca(payload: dict[str, Any]) -> None:
    print("=" * 64)
    print("Monthly DCA allocation (example rules, for learning only)")
    print("=" * 64)
    for group in payload["groups"]:
        print(f"\n{group['label']}  ·  Monthly budget {group['budget']:g} {group['currency']}")
        print("-" * 64)
        for item in group["items"]:
            zone = item["zone_label"]
            pct = f"{item['percentile']:.1f}%" if item["percentile"] is not None else "n/a"
            print(f"  {item['code']:<8} {item['name']:<32} {item['amount']:>10,.2f} {group['currency']}  "
                  f"[{zone}] pct {pct} x{item['multiplier']:g}")
        print(f"  {'Total':<40} {group['total']:>10,.2f} {group['currency']}")
    print("\nNotes:")
    for note in payload["notes"]:
        print(f"  - {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description="02_DCA_Index_Funds monthly DCA allocation")
    parser.add_argument("--check", action="store_true", help="Print this month's allocation to the console")
    parser.add_argument("--refresh", action="store_true", help="Refresh valuation/price data first")
    parser.add_argument("--force", action="store_true", help="With --refresh: force a full refresh")
    parser.add_argument("--json", action="store_true", help="Output JSON (same as the web /api/dca)")
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing DCA data...")
        for item in refresh_data(force=args.force)["results"]:
            print(f"  {item['tracking']:<12} {item['status']}")

    payload = build_dca_decision()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_dca(payload)


if __name__ == "__main__":
    main()
