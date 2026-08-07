"""
重算根 README 持仓表中的当前占比与收益率两列。

在根 README 更新持仓金额/累计成本后运行：
    python update_portfolio.py

当前占比 = 持仓 / 人民币持仓合计（欧元行不参与）
收益率   = (当前持仓 - 累计成本) / 累计成本
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def extract_amount(raw: str) -> float | None:
    if not raw or "share" in raw.lower() or "份" in raw:
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


def recompute_readme(path: Path = README) -> dict[str, Any]:
    """重算 README 持仓表中的当前占比/收益率列，返回汇总。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^#{2,3}\s+(Current Holdings|当前持仓)", line)), None)
    if start is None:
        return {"error": "未找到当前持仓标题"}

    table_start = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("|") and ("Market" in lines[i] or "市场" in lines[i])),
        None,
    )
    if table_start is None:
        return {"error": "未找到持仓表"}

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
        is_eur = "€" in cells[6] or "份" in cells[6] or "share" in cells[6].lower()

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

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"total": rmb_total, "changed": changed}


def main() -> None:
    parser = argparse.ArgumentParser(description="重算根 README 持仓表中的当前占比与收益率")
    parser.add_argument("--path", type=Path, default=README, help="目标 README 路径（用于测试）")
    args = parser.parse_args()
    result = recompute_readme(args.path)
    if "error" in result:
        print(result["error"])
        return
    rmb_total, changed = result["total"], result["changed"]
    print(f"人民币持仓合计：¥{rmb_total:,.0f}")
    if changed:
        for code, oc, nc, or_, nr in changed:
            print(f"  {code}：当前占比 {oc} -> {nc} | 收益率 {or_} -> {nr}")
    else:
        print("无需修改（当前占比/收益率已是最新）。")


if __name__ == "__main__":
    main()
