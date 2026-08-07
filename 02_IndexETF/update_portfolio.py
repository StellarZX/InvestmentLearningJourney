"""
重算根 README 持仓表中的当前占比与收益率，并同步每组小计与总计。

在根 README 更新持仓金额/累计成本后运行：
    python update_portfolio.py

当前占比 = 持仓 / 人民币持仓合计（欧元/份额行不参与）
收益率   = (当前持仓 - 累计成本) / 累计成本
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LIB_DIR = BASE_DIR / "lib"
sys.path.insert(0, str(LIB_DIR))

import readme_table

ROOT = BASE_DIR.parent
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
    """重算 README 持仓表中的当前占比/收益率列，并刷新小计/总计，返回汇总。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    block = readme_table.find_table_block(lines)
    if block is None:
        return {"error": "未找到持仓表"}

    rows = readme_table.parse_rows(lines)
    data_rows = [r for r in rows if r["kind"] == "data"]

    rmb_total = 0.0
    for r in data_rows:
        pos = extract_amount(r["position"])
        is_eur = "€" in r["position"] or "份" in r["position"] or "share" in r["position"].lower()
        if pos is not None and not is_eur:
            rmb_total += pos

    changed = []
    for r in data_rows:
        position = extract_amount(r["position"])
        cost = extract_amount(r["cost"])
        is_eur = "€" in r["position"] or "份" in r["position"] or "share" in r["position"].lower()
        if is_eur or position is None:
            new_current, new_return = "-", "-"
        else:
            new_current = fmt_current(position / rmb_total * 100) if rmb_total else "0%"
            new_return = fmt_return((position - cost) / cost * 100) if cost and position else "-"
        if r["current_pct"] != new_current or r["return_pct"] != new_return:
            changed.append((r["code"], r["current_pct"], new_current, r["return_pct"], new_return))
            r["current_pct"], r["return_pct"] = new_current, new_return

    start, end = block
    lines[start : end + 1] = readme_table.render_table(data_rows).splitlines()
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
