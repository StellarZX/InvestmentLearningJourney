"""
Portfolio page backend: current holdings and DCA records stored in a CSV file.

The CSV (data/dca_records.csv) is the source of truth for DCA records. Each row
stores the fund's position (持仓金额 / shares) and cost (累计成本) as of that
date; the latest row per fund is the current holding.

Adding a record also updates the Current Holdings table in the root README and
recomputes Current % / Return %.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

import dca
import update_portfolio

BASE_DIR = Path(__file__).resolve().parent
RECORDS_CSV = BASE_DIR / "data" / "dca_records.csv"
README = BASE_DIR.parent / "README.md"

CSV_COLUMNS = ["date", "code", "fund", "currency", "position", "cost", "note"]

FUND_NAMES = {f.code: f.name for f in dca.FUNDS}
FUND_NAMES["SXR8"] = "iShares Core S&P 500 UCITS ETF USD (Acc)"
TARGETS = {"460300": "25%", "160119": "15%", "110026": "10%", "100032": "15%", "164705": "15%", "021457": "20%", "SXR8": "-"}
CURRENCY = {f.code: f.currency for f in dca.FUNDS}
CURRENCY["SXR8"] = "EUR"


def read_records() -> pd.DataFrame:
    if not RECORDS_CSV.exists():
        return pd.DataFrame(columns=CSV_COLUMNS)
    df = pd.read_csv(RECORDS_CSV, dtype={"code": str})
    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


def records_list() -> list[dict[str, Any]]:
    df = read_records()
    if df.empty:
        return []
    df = df.sort_values("date", ascending=False)
    return df.to_dict(orient="records")


def current_holdings() -> list[dict[str, Any]]:
    df = read_records()
    if df.empty:
        return []
    df = df.sort_values("date")
    latest = df.groupby("code", as_index=False).tail(1)
    cny_total = sum(float(r["position"]) for _, r in latest.iterrows() if r["currency"] == "CNY")
    items = []
    for _, r in latest.iterrows():
        pos = float(r["position"]) if r["position"] not in (None, "") else 0.0
        cost = float(r["cost"]) if r["cost"] not in (None, "") else 0.0
        is_cny = r["currency"] == "CNY"
        current_pct = f"{pos / cny_total * 100:.1f}%" if is_cny and cny_total else "-"
        return_pct = f"{(pos - cost) / cost * 100:.1f}%" if is_cny and cost else "-"
        items.append({
            "code": r["code"],
            "fund": FUND_NAMES.get(r["code"], r["fund"]),
            "currency": r["currency"],
            "target": TARGETS.get(r["code"], "-"),
            "position": round(pos, 2),
            "cost": round(cost, 2),
            "current_pct": current_pct,
            "return_pct": return_pct,
            "last_date": str(r["date"]),
        })
    return items


def get_portfolio() -> dict[str, Any]:
    return {
        "holdings": current_holdings(),
        "records": records_list(),
        "funds": [{"code": c, "name": FUND_NAMES[c], "currency": CURRENCY.get(c, "CNY")} for c in FUND_NAMES],
    }


def _fmt_amount(value: float, currency: str) -> str:
    if currency == "EUR":
        text = f"€{value:,.3f}"
    else:
        text = f"¥{value:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def update_readme_holdings(code: str, position: float, cost: float) -> None:
    lines = README.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^#{2,3}\s+Current Holdings", line)), None)
    if start is None:
        return
    table_start = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("|") and "Market" in lines[i]),
        None,
    )
    if table_start is None:
        return
    currency = CURRENCY.get(code, "CNY")
    for i in range(table_start + 1, len(lines)):
        line = lines[i]
        if not line.startswith("|"):
            break
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[3] == code:
            pos_text = f"{position:g} shares" if currency == "EUR" else _fmt_amount(position, currency)
            cost_text = _fmt_amount(cost, currency)
            cells[6] = pos_text
            cells[7] = cost_text
            lines[i] = "| " + " | ".join(cells) + " |"
            break
    README.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_record(code: str, position: float, cost: float, note: str = "", rec_date: str = "") -> dict[str, Any]:
    code = str(code).strip()
    if code not in FUND_NAMES:
        raise ValueError(f"Unknown fund code: {code}")
    position = float(position)
    cost = float(cost)
    if position < 0 or cost < 0:
        raise ValueError("Position and cost must be >= 0")
    rec_date = rec_date.strip() or date.today().isoformat()

    row = {
        "date": rec_date,
        "code": code,
        "fund": FUND_NAMES[code],
        "currency": CURRENCY.get(code, "CNY"),
        "position": position,
        "cost": cost,
        "note": note.strip(),
    }
    df = read_records()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    RECORDS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RECORDS_CSV, index=False, encoding="utf-8")

    update_readme_holdings(code, position, cost)
    update_portfolio.recompute_readme(README)
    return row
