"""
Recompute the Current % and Return % columns in the root README holdings table.

Run after updating Current Position / Current Cost in the root README:
    python update_portfolio.py

Current %  = position / total RMB positions (EUR rows excluded)
Return %   = (Current Position - Current Cost) / Current Cost
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def extract_amount(raw: str) -> float | None:
    if not raw or "share" in raw.lower():
        return None
    match = re.search(r"\d+(?:\.\d+)?", raw.replace(",", ""))
    return float(match.group()) if match else None


def fmt_current(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(value, 1):g}%"


def fmt_return(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute Current % / Return % in the root README holdings table")
    parser.add_argument("--path", type=Path, default=README, help="Target README path (for testing)")
    args = parser.parse_args()
    lines = args.path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^#{2,3}\s+Current Holdings", line)), None)
    if start is None:
        print("Current Holdings heading not found.")
        return

    table_start = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("|") and "Market" in lines[i]),
        None,
    )
    if table_start is None:
        print("Holdings table not found.")
        return

    rows: list[tuple[int, list[str]]] = []
    for i in range(table_start + 1, len(lines)):
        line = lines[i]
        if not line.startswith("|"):
            break
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[3]:
            rows.append((i, cells))

    rmb_total = sum(
        pos for _, cells in rows
        if (pos := extract_amount(cells[6])) is not None and "€" not in cells[6]
    )

    changed = []
    for i, cells in rows:
        position = extract_amount(cells[6])
        cost = extract_amount(cells[7])
        is_eur = "€" in cells[6] or "share" in cells[6].lower()

        if is_eur or position is None:
            new_current, new_return = "-", "-"
        else:
            new_current = fmt_current(position / rmb_total * 100) if rmb_total else "0%"
            new_return = fmt_return((position - cost) / cost * 100) if cost and position else "-"

        if cells[5] != new_current or cells[8] != new_return:
            old_current, old_return = cells[5], cells[8]
            cells[5], cells[8] = new_current, new_return
            lines[i] = "| " + " | ".join(cells) + " |"
            changed.append((cells[3], old_current, new_current, old_return, new_return))

    for i in range(start + 1, len(lines)):
        if "Current % = position" in lines[i]:
            lines[i] = re.sub(r"\(¥[\d,]+\)", f"(¥{rmb_total:,.0f})", lines[i])
            break

    args.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"RMB total position: ¥{rmb_total:,.0f}")
    if changed:
        for code, oc, nc, or_, nr in changed:
            print(f"  {code}: Current % {oc} -> {nc} | Return % {or_} -> {nr}")
    else:
        print("No changes needed (Current % / Return % already up to date).")


if __name__ == "__main__":
    main()
