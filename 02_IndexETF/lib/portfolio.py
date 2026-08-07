"""
持仓页后端：当前持仓与定投记录，存放在 SQLite（data/market.db）。

每行记录某只基金在当日的持仓（持仓金额/份额）与成本（累计成本）；
每只基金的最新一条记录即当前持仓。

新增记录时会同步更新根 README 的当前持仓表，并重算当前占比与收益率。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

import dca
import db
import readme_table
import update_portfolio

BASE_DIR = Path(__file__).resolve().parent.parent
README = BASE_DIR.parent / "README.md"

CSV_COLUMNS = ["date", "code", "fund", "currency", "position", "cost", "note"]

FUND_NAMES = {f.code: f.name for f in dca.FUNDS}
FUND_NAMES["SXR8"] = "安硕标普500 UCITS ETF（美元，累计）"
TARGETS = {"460300": "25%", "160119": "15%", "110026": "10%", "100032": "15%", "164705": "15%", "021457": "20%", "SXR8": "-"}
CURRENCY = {f.code: f.currency for f in dca.FUNDS}
CURRENCY["SXR8"] = "EUR"


def read_records() -> pd.DataFrame:
    df = pd.DataFrame(db.read_dca_records())
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
    block = readme_table.find_table_block(lines)
    if block is None:
        return
    rows = readme_table.parse_rows(lines)
    currency = CURRENCY.get(code, "CNY")
    pos_text = f"{position:g} 份" if currency == "EUR" else _fmt_amount(position, currency)
    cost_text = _fmt_amount(cost, currency)
    found = False
    for r in rows:
        if r["kind"] == "data" and r["code"] == code:
            r["position"] = pos_text
            r["cost"] = cost_text
            found = True
            break
    if not found:
        return
    data_rows = [r for r in rows if r["kind"] == "data"]
    start, end = block
    lines[start : end + 1] = readme_table.render_table(data_rows).splitlines()
    README.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_record(code: str, position: float, cost: float, note: str = "", rec_date: str = "") -> dict[str, Any]:
    code = str(code).strip()
    if code not in FUND_NAMES:
        raise ValueError(f"未知基金代码：{code}")
    position = float(position)
    cost = float(cost)
    if position < 0 or cost < 0:
        raise ValueError("持仓与成本必须 >= 0")
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
    db.insert_dca_record(row)

    update_readme_holdings(code, position, cost)
    update_portfolio.recompute_readme(README)
    return row
