"""
Local market index dashboard.

Run with:
    ..\\.venv\\Scripts\\python.exe script.py

Then open:
    http://127.0.0.1:8050
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from curl_cffi import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "indices"
VALUATION_DIR = BASE_DIR / "data" / "valuations"
ASSESSMENT_DIR = BASE_DIR / "data" / "assessments"
STATIC_DIR = BASE_DIR / "static"
METADATA_FILE = BASE_DIR / "data" / "metadata.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8050


@dataclass(frozen=True)
class IndexConfig:
    slug: str
    name: str
    symbol: str
    region: str
    currency: str
    source: str = "Yahoo Finance chart API"
    valuation_symbol: str | None = None


INDICES: list[IndexConfig] = [
    IndexConfig("sp500", "S&P 500", "^GSPC", "United States", "USD"),
    IndexConfig("nasdaq_composite", "NASDAQ Composite", "^IXIC", "United States", "USD"),
    IndexConfig("dow_jones", "Dow Jones Industrial Average", "^DJI", "United States", "USD"),
    IndexConfig("nasdaq_100", "NASDAQ-100", "^NDX", "United States", "USD"),
    IndexConfig("hang_seng", "Hang Seng Index", "^HSI", "Hong Kong", "HKD"),
    IndexConfig("csi_300", "CSI 300", "000300.SS", "China", "CNY", valuation_symbol="沪深300"),
    IndexConfig("shanghai_composite", "Shanghai Composite", "000001.SS", "China", "CNY"),
    IndexConfig("shenzhen_component", "Shenzhen Component", "399001.SZ", "China", "CNY"),
    IndexConfig("nikkei_225", "Nikkei 225", "^N225", "Japan", "JPY"),
    IndexConfig("ftse_100", "FTSE 100", "^FTSE", "United Kingdom", "GBP"),
    IndexConfig("dax", "DAX", "^GDAXI", "Germany", "EUR"),
]


def utc_timestamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def clean_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except TypeError:
        pass
    return round(float(value), 6)


def fetch_index(config: IndexConfig, start: date, end: date) -> pd.DataFrame:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{config.symbol}?period1={utc_timestamp(start)}&period2={utc_timestamp(end)}"
        "&interval=1d&events=history"
    )
    response = requests.get(url, timeout=30, impersonate="chrome")
    response.raise_for_status()
    payload = response.json()
    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"{config.name}: {error}")

    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []

    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        close = clean_number((quote.get("close") or [None])[i])
        if close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                "open": clean_number((quote.get("open") or [None])[i]),
                "high": clean_number((quote.get("high") or [None])[i]),
                "low": clean_number((quote.get("low") or [None])[i]),
                "close": close,
                "adj_close": clean_number(adjclose[i]) if i < len(adjclose) else close,
                "volume": clean_number((quote.get("volume") or [None])[i]),
                "symbol": config.symbol,
                "name": config.name,
                "region": config.region,
                "currency": config.currency,
                "source": config.source,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"{config.name}: no data returned")
    return df.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def save_index_by_year(config: IndexConfig, df: pd.DataFrame) -> None:
    index_dir = DATA_DIR / config.slug
    index_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, year_df in df.groupby("year"):
        out = index_dir / f"{int(year)}.csv"
        year_df = year_df.drop(columns=["year"])
        year_df.to_csv(out, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)


def fetch_valuation(config: IndexConfig) -> pd.DataFrame:
    if not config.valuation_symbol:
        return pd.DataFrame()

    import akshare as ak

    pe_df = ak.stock_index_pe_lg(symbol=config.valuation_symbol)
    pb_df = ak.stock_index_pb_lg(symbol=config.valuation_symbol)
    pe_df = pe_df.rename(
        columns={
            "日期": "date",
            "指数": "index_close",
            "滚动市盈率": "pe_ttm",
            "等权滚动市盈率": "equal_weight_pe_ttm",
            "滚动市盈率中位数": "median_pe_ttm",
            "静态市盈率": "pe_static",
        }
    )
    pb_df = pb_df.rename(
        columns={
            "日期": "date",
            "市净率": "pb",
            "等权市净率": "equal_weight_pb",
            "市净率中位数": "median_pb",
        }
    )
    keep_pe = ["date", "index_close", "pe_ttm", "equal_weight_pe_ttm", "median_pe_ttm", "pe_static"]
    keep_pb = ["date", "pb", "equal_weight_pb", "median_pb"]
    df = pe_df[keep_pe].merge(pb_df[keep_pb], on="date", how="left")
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["earnings_yield"] = (100 / pd.to_numeric(df["pe_ttm"], errors="coerce")).round(6)
    df["slug"] = config.slug
    df["name"] = config.name
    df["source"] = "Legulegu via AkShare"
    return df.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def save_valuation_by_year(config: IndexConfig, df: pd.DataFrame) -> None:
    if df.empty:
        return
    index_dir = VALUATION_DIR / config.slug
    index_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, year_df in df.groupby("year"):
        out = index_dir / f"{int(year)}.csv"
        year_df.drop(columns=["year"]).to_csv(out, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)


def save_assessment_by_year(config: IndexConfig, df: pd.DataFrame) -> None:
    if df.empty:
        return
    index_dir = ASSESSMENT_DIR / config.slug
    index_dir.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, year_df in df.groupby("year"):
        out = index_dir / f"{int(year)}.csv"
        year_df.drop(columns=["year"]).to_csv(out, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL)


def read_index_csvs(slug: str) -> pd.DataFrame:
    index_dir = DATA_DIR / slug
    frames = []
    for path in sorted(index_dir.glob("*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date")


def read_valuation_csvs(slug: str) -> pd.DataFrame:
    index_dir = VALUATION_DIR / slug
    frames = []
    for path in sorted(index_dir.glob("*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date")


def read_assessment_csvs(slug: str) -> pd.DataFrame:
    index_dir = ASSESSMENT_DIR / slug
    frames = []
    for path in sorted(index_dir.glob("*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date")


def dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


def latest_date(df: pd.DataFrame) -> date | None:
    if df.empty or "date" not in df.columns:
        return None
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    latest = dates.max().date()
    return latest


def has_today(df: pd.DataFrame) -> bool:
    latest = latest_date(df)
    return latest == date.today()


def append_index_data(config: IndexConfig, years: int, force: bool = False) -> tuple[pd.DataFrame, str, int]:
    today = date.today()
    full_start = date(today.year - years, 1, 1)
    existing = read_index_csvs(config.slug)

    if force or existing.empty:
        fetched = fetch_index(config, full_start, today + timedelta(days=1))
        save_index_by_year(config, fetched)
        status = "refreshed" if force and not existing.empty else "created"
        return fetched, status, int(len(fetched))

    if has_today(existing):
        return existing, "cached_today", 0

    previous_latest = latest_date(existing)
    start = max((previous_latest or full_start) - timedelta(days=7), full_start)
    fetched = fetch_index(config, start, today + timedelta(days=1))
    merged = (
        pd.concat([existing, fetched], ignore_index=True)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
    )
    save_index_by_year(config, merged)
    if previous_latest:
        new_rows = int((pd.to_datetime(merged["date"]).dt.date > previous_latest).sum())
    else:
        new_rows = int(len(merged))
    return merged, "appended" if new_rows else "checked", new_rows


def update_valuation_data(config: IndexConfig, start: date, force: bool = False) -> tuple[pd.DataFrame, int]:
    if not config.valuation_symbol:
        return pd.DataFrame(), 0

    existing = read_valuation_csvs(config.slug)
    if not force and not existing.empty and has_today(existing):
        return existing, 0

    previous_latest = latest_date(existing)
    valuation_df = fetch_valuation(config)
    if valuation_df.empty:
        return existing, 0

    valuation_df = valuation_df[valuation_df["date"] >= start.isoformat()]
    merged = (
        pd.concat([existing, valuation_df], ignore_index=True)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
    )
    save_valuation_by_year(config, merged)
    if previous_latest:
        new_rows = int((pd.to_datetime(merged["date"]).dt.date > previous_latest).sum())
    else:
        new_rows = int(len(merged))
    return merged, new_rows


def load_metadata() -> dict[str, Any]:
    if not METADATA_FILE.exists():
        return {}
    return json.loads(METADATA_FILE.read_text(encoding="utf-8"))


def save_metadata(metadata: dict[str, Any]) -> None:
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_data(years: int = 10, force: bool = False) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VALUATION_DIR.mkdir(parents=True, exist_ok=True)
    ASSESSMENT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    start = date(today.year - years, 1, 1)
    metadata = load_metadata()
    metadata.setdefault("indices", {})

    results = []
    for config in INDICES:
        existing_before = read_index_csvs(config.slug)
        index_metadata = metadata.get("indices", {}).get(config.slug, {})
        already_checked_today = index_metadata.get("last_checked_on") == today.isoformat()
        can_use_daily_cache = (
            not force
            and not existing_before.empty
            and already_checked_today
            and not has_today(existing_before)
        )

        if can_use_daily_cache:
            df, status, new_rows = existing_before, "cached_checked", 0
        else:
            df, status, new_rows = append_index_data(config, years=years, force=force)

        existing_valuation = read_valuation_csvs(config.slug)
        if can_use_daily_cache and (not config.valuation_symbol or not existing_valuation.empty):
            valuation_df, valuation_new_rows = existing_valuation, 0
        else:
            valuation_df, valuation_new_rows = update_valuation_data(config, start=start, force=force)
        assessment_df = ensure_assessment_csv(config, force=force or new_rows > 0 or valuation_new_rows > 0)
        metadata["indices"][config.slug] = {
            **asdict(config),
            "rows": int(len(df)),
            "first_date": str(df["date"].min()),
            "last_date": str(df["date"].max()),
            "refreshed_at": datetime.now().isoformat(timespec="seconds"),
            "years": sorted(int(y) for y in pd.to_datetime(df["date"]).dt.year.unique()),
            "valuation_rows": int(len(valuation_df)) if not valuation_df.empty else 0,
            "valuation_metrics": ["earnings_yield", "pe_ttm", "pb"] if not valuation_df.empty else [],
            "assessment_rows": int(len(assessment_df)) if not assessment_df.empty else 0,
            "last_update_status": status,
            "new_rows": new_rows,
            "valuation_new_rows": valuation_new_rows,
            "last_checked_on": today.isoformat(),
        }
        save_metadata(metadata)
        results.append({"slug": config.slug, "name": config.name, "status": status, "rows": len(df), "new_rows": new_rows})
    return {"results": results, "metadata": load_metadata()}


def index_summary(config: IndexConfig) -> dict[str, Any]:
    df = read_index_csvs(config.slug)
    if df.empty:
        return {**asdict(config), "rows": 0}
    df = df.sort_values("date")
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest
    first = df.iloc[0]
    latest_close = float(latest["close"])
    previous_close = float(previous["close"])
    first_close = float(first["close"])
    daily_change = latest_close - previous_close
    daily_change_pct = daily_change / previous_close * 100 if previous_close else 0
    total_change_pct = (latest_close / first_close - 1) * 100 if first_close else 0
    return {
        **asdict(config),
        "rows": int(len(df)),
        "has_valuation": not read_valuation_csvs(config.slug).empty,
        "first_date": str(first["date"]),
        "last_date": str(latest["date"]),
        "latest_close": round(latest_close, 4),
        "daily_change": round(daily_change, 4),
        "daily_change_pct": round(daily_change_pct, 2),
        "total_change_pct": round(total_change_pct, 2),
    }


def records_for_slug(slug: str) -> list[dict[str, Any]]:
    df = read_index_csvs(slug)
    if df.empty:
        return []
    return dataframe_records(df)


def valuation_for_slug(slug: str) -> list[dict[str, Any]]:
    df = read_valuation_csvs(slug)
    if df.empty:
        return []
    return dataframe_records(df)


def compute_assessment_df(slug: str) -> pd.DataFrame:
    df = read_index_csvs(slug)
    if df.empty:
        return pd.DataFrame()
    df = df[["date", "close"]].copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    window = min(756, len(df))
    rolling_high = df["close"].rolling(window=window, min_periods=60).max()
    moving_average_200 = df["close"].rolling(window=200, min_periods=60).mean()

    percentiles = []
    drawdown_scores = []
    trend_scores = []
    for idx, close in enumerate(df["close"]):
        start = max(0, idx - window + 1)
        sample = df.loc[start:idx, "close"]
        if len(sample) < 60:
            percentiles.append(None)
            drawdown_scores.append(None)
            trend_scores.append(None)
            continue
        percentile = float((sample <= close).mean() * 100)
        percentiles.append(round(percentile, 4))

        high = rolling_high.iloc[idx]
        drawdown = float(close / high - 1) if high else 0
        drawdown_scores.append(round(min(abs(drawdown) / 0.30 * 100, 100), 4))

        ma200 = moving_average_200.iloc[idx]
        if pd.isna(ma200) or ma200 == 0:
            trend_scores.append(None)
        else:
            distance = float(close / ma200 - 1)
            if distance >= 0:
                trend_scores.append(70.0)
            elif distance >= -0.10:
                trend_scores.append(50.0)
            else:
                trend_scores.append(30.0)

    df["price_percentile"] = percentiles
    df["drawdown_pct"] = ((df["close"] / rolling_high - 1) * 100).round(4)
    df["price_score"] = (100 - pd.to_numeric(df["price_percentile"], errors="coerce")).clip(0, 100).round(4)
    df["drawdown_score"] = drawdown_scores
    df["trend_score"] = trend_scores

    valuation_df = read_valuation_csvs(slug)
    if not valuation_df.empty:
        valuation_df = valuation_df[["date", "earnings_yield", "pe_ttm", "pb"]].copy()
        valuation_df["earnings_yield"] = pd.to_numeric(valuation_df["earnings_yield"], errors="coerce")
        valuation_df["pe_ttm"] = pd.to_numeric(valuation_df["pe_ttm"], errors="coerce")
        valuation_df["pb"] = pd.to_numeric(valuation_df["pb"], errors="coerce")

        valuation_scores = []
        for idx, row in valuation_df.reset_index(drop=True).iterrows():
            start = max(0, idx - window + 1)
            sample = valuation_df.iloc[start : idx + 1]
            if len(sample) < 60:
                valuation_scores.append(None)
                continue
            ey_score = float((sample["earnings_yield"] <= row["earnings_yield"]).mean() * 100)
            pe_score = 100 - float((sample["pe_ttm"] <= row["pe_ttm"]).mean() * 100)
            pb_score = 100 - float((sample["pb"] <= row["pb"]).mean() * 100)
            valuation_scores.append(round((ey_score + pe_score + pb_score) / 3, 4))
        valuation_df["valuation_score"] = valuation_scores
        df = df.merge(valuation_df[["date", "valuation_score"]], on="date", how="left")
        df["extra_investment_score"] = (
            pd.to_numeric(df["valuation_score"], errors="coerce") * 0.45
            + pd.to_numeric(df["price_score"], errors="coerce") * 0.25
            + pd.to_numeric(df["drawdown_score"], errors="coerce") * 0.20
            + pd.to_numeric(df["trend_score"], errors="coerce") * 0.10
        ).round(4)
        df["method"] = "Composite: 45% valuation, 25% price percentile, 20% drawdown, 10% trend"
        df["confidence"] = "valuation_supported"
    else:
        df["valuation_score"] = None
        df["extra_investment_score"] = (
            pd.to_numeric(df["price_score"], errors="coerce") * 0.45
            + pd.to_numeric(df["drawdown_score"], errors="coerce") * 0.35
            + pd.to_numeric(df["trend_score"], errors="coerce") * 0.20
        ).round(4)
        df["method"] = "Composite: 45% price percentile, 35% drawdown, 20% trend"
        df["confidence"] = "price_only"
    return df


def ensure_assessment_csv(config: IndexConfig, force: bool = False) -> pd.DataFrame:
    cached = read_assessment_csvs(config.slug)
    index_df = read_index_csvs(config.slug)
    if not force and not cached.empty and latest_date(cached) == latest_date(index_df):
        return cached
    df = compute_assessment_df(config.slug)
    save_assessment_by_year(config, df)
    return df


def assessment_for_slug(slug: str) -> list[dict[str, Any]]:
    df = read_assessment_csvs(slug)
    if df.empty:
        config = next((item for item in INDICES if item.slug == slug), None)
        if not config:
            return []
        df = ensure_assessment_csv(config, force=True)
    if df.empty:
        return []
    return dataframe_records(df)


class MarketHandler(BaseHTTPRequestHandler):
    server_version = "MarketDashboard/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[market] {self.address_string()} - {fmt % args}")

    def send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path in {"/", "/index.html"}:
            self.send_file(STATIC_DIR / "index.html")
            return
        if path == "/api/indices":
            self.send_json({"indices": [index_summary(config) for config in INDICES], "metadata": load_metadata()})
            return
        if path.startswith("/api/index/"):
            slug = path.removeprefix("/api/index/").strip("/")
            config = next((item for item in INDICES if item.slug == slug), None)
            if not config:
                self.send_json({"error": "Unknown index"}, HTTPStatus.NOT_FOUND)
                return
            records = records_for_slug(slug)
            limit = int(query.get("limit", [0])[0] or 0)
            if limit > 0:
                records = records[-limit:]
            self.send_json({"index": index_summary(config), "records": records})
            return
        if path.startswith("/api/valuation/"):
            slug = path.removeprefix("/api/valuation/").strip("/")
            config = next((item for item in INDICES if item.slug == slug), None)
            if not config:
                self.send_json({"error": "Unknown index"}, HTTPStatus.NOT_FOUND)
                return
            records = valuation_for_slug(slug)
            limit = int(query.get("limit", [0])[0] or 0)
            if limit > 0:
                records = records[-limit:]
            self.send_json({"index": index_summary(config), "records": records})
            return
        if path.startswith("/api/assessment/"):
            slug = path.removeprefix("/api/assessment/").strip("/")
            config = next((item for item in INDICES if item.slug == slug), None)
            if not config:
                self.send_json({"error": "Unknown index"}, HTTPStatus.NOT_FOUND)
                return
            records = assessment_for_slug(slug)
            limit = int(query.get("limit", [0])[0] or 0)
            if limit > 0:
                records = records[-limit:]
            self.send_json({"index": index_summary(config), "records": records})
            return
        if path.startswith("/data/"):
            self.send_file(BASE_DIR / path.lstrip("/"))
            return
        self.send_file(STATIC_DIR / path.lstrip("/"))


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), MarketHandler)
    url = f"http://{host}:{port}"
    print(f"Market dashboard is running: {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch major index data and run the local market dashboard.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--years", default=10, type=int, help="How many years of daily data to fetch.")
    parser.add_argument("--refresh", action="store_true", help="Force a full data refresh before starting.")
    parser.add_argument("--fetch-only", action="store_true", help="Fetch data and exit without starting the server.")
    args = parser.parse_args()

    print("Preparing market index data...")
    result = refresh_data(years=args.years, force=args.refresh)
    for item in result["results"]:
        suffix = f", +{item['new_rows']} new" if item.get("new_rows") else ""
        print(f"  {item['name']}: {item['status']} ({item['rows']} rows{suffix})")
    if args.fetch_only:
        return
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
