"""
根 README 当前持仓表的解析与渲染工具。

持仓表为 HTML 表格（类型列用 rowspan 合并单元格、每组带合计行、末尾有总计行），
同时兼容解析旧的 Markdown 表格。
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

HEADING_RE = re.compile(r"^#{2,3}\s+(当前持仓|Current Holdings)")
GROUP_TYPES = ("指数", "量化", "行业", "其他")


# ---------------------------------------------------------------------------
# 数值工具
# ---------------------------------------------------------------------------

def pct_value(raw: str) -> float | None:
    if not raw or raw == "-":
        return None
    match = re.search(r"[\d.]+", raw)
    return float(match.group()) if match else None


def amount_value(raw: str) -> float | None:
    """提取金额数字；份额/空值返回 None。"""
    if not raw or raw == "-":
        return None
    if "份" in raw or "share" in raw.lower():
        return None
    match = re.search(r"\d+(?:\.\d+)?", raw.replace(",", ""))
    return float(match.group()) if match else None


def fmt_money(value: float, symbol: str) -> str:
    text = f"{symbol}{value:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_pct(value: float) -> str:
    return f"{round(value, 1):g}%"


def fmt_return(value: float) -> str:
    return f"{value:.1f}%"


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: str | None = None
        self._attrs: dict[str, str] = {}
        self._pending: list[list[Any]] = []  # [剩余行数, 文本]，用于 rowspan 延续
        self._pending_start = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
            self._pending_start = len(self._pending)
        elif tag in ("td", "th"):
            self._cell = ""
            self._attrs = dict(attrs)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell += data

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            text = " ".join((self._cell or "").split())
            colspan = int(self._attrs.get("colspan", "1") or 1)
            rowspan = int(self._attrs.get("rowspan", "1") or 1)
            for _ in range(colspan):
                self._row.append(text)
            if rowspan > 1:
                self._pending.append([rowspan - 1, text])
            self._cell = None
        elif tag == "tr":
            # 只把本行之前产生的 rowspan 延续插到该行最前面（合并列是第一列）
            for item in self._pending[: self._pending_start]:
                self._row.insert(0, item[1])
                item[0] -= 1
            self._pending = [p for p in self._pending if p[0] > 0]
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _parse_html_rows(lines: list[str]) -> list[list[str]]:
    parser = _HtmlTableParser()
    parser.feed("\n".join(lines))
    return parser.rows


def _parse_markdown_rows(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "---" in line or "Market" in line or "市场" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 9:
            rows.append(cells[:9])
    return rows


def find_table_block(lines: list[str]) -> tuple[int, int] | None:
    """返回持仓表在 README 行列表中的 [起始, 结束] 行号。"""
    start = next((i for i, line in enumerate(lines) if HEADING_RE.match(line)), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        if "<table" in lines[i]:
            end = next((j for j in range(i + 1, len(lines)) if "</table>" in lines[j]), None)
            return (i, end) if end is not None else None
    table_start = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith("|") and ("市场" in lines[i] or "Market" in lines[i])),
        None,
    )
    if table_start is None:
        return None
    end = table_start
    while end + 1 < len(lines) and lines[end + 1].startswith("|"):
        end += 1
    return table_start, end


def _classify(cells: list[str]) -> tuple[str, str]:
    first = cells[0]
    if first in GROUP_TYPES:
        return "data", first
    if first == "总计":
        return "total", "总计"
    if first.endswith("合计"):
        return "subtotal", first.removesuffix("合计").strip()
    return "data", first


def parse_rows(lines: list[str]) -> list[dict[str, Any]]:
    """解析持仓表，返回 {kind, type, market, fund, code, target,
    current_pct, position, cost, return_pct} 列表。"""
    block = find_table_block(lines)
    if block is None:
        return []
    start, end = block
    segment = lines[start : end + 1]
    if any("<table" in line for line in segment):
        raw_rows = _parse_html_rows(segment)
    else:
        raw_rows = _parse_markdown_rows(segment)
    result: list[dict[str, Any]] = []
    for cells in raw_rows:
        if len(cells) < 9 or cells[0] in ("类型", "Market"):
            continue
        kind, type_label = _classify(cells)
        result.append({
            "kind": kind,
            "type": type_label,
            "market": cells[1],
            "fund": cells[2],
            "code": cells[3],
            "target": cells[4],
            "current_pct": cells[5],
            "position": cells[6],
            "cost": cells[7],
            "return_pct": cells[8],
        })
    return result


# ---------------------------------------------------------------------------
# 渲染（按类型合并第一列，自动生成每组合计行与总计行）
# ---------------------------------------------------------------------------

def _subtotal_values(data_rows: list[dict[str, Any]], type_label: str) -> dict[str, str]:
    members = [r for r in data_rows if r["type"] == type_label]
    target_sum = 0.0
    current_sum = 0.0
    has_target = False
    has_current = False
    positions: list[float] = []
    costs: list[float] = []
    share_position: str | None = None
    eur_cost: float | None = None
    for r in members:
        t = pct_value(r["target"])
        if t is not None:
            target_sum += t
            has_target = True
        c = pct_value(r["current_pct"])
        if c is not None:
            current_sum += c
            has_current = True
        pos = amount_value(r["position"])
        cost = amount_value(r["cost"])
        is_share = "份" in r["position"] or "share" in r["position"].lower()
        if is_share:
            share_position = r["position"]
        elif pos is not None:
            positions.append(pos)
            costs.append(cost if cost is not None else 0.0)
        if "€" in r["cost"] and cost is not None:
            eur_cost = cost

    pos_sum = sum(positions)
    cost_sum = sum(costs)
    target = fmt_pct(target_sum) if has_target else "-"
    current = fmt_pct(current_sum) if has_current else "-"
    if pos_sum:
        position_text = fmt_money(pos_sum, "¥")
        if share_position:
            position_text += " + " + share_position
    elif share_position:
        position_text = share_position
    else:
        position_text = "-"
    if cost_sum:
        cost_text = fmt_money(cost_sum, "¥")
        if eur_cost:
            cost_text += " + " + fmt_money(eur_cost, "€")
    elif eur_cost:
        cost_text = fmt_money(eur_cost, "€")
    else:
        cost_text = "-"
    ret = fmt_return((pos_sum - cost_sum) / cost_sum * 100) if pos_sum and cost_sum else "-"
    return {"target": target, "current": current, "position": position_text,
            "cost": cost_text, "return": ret}


def _total_values(data_rows: list[dict[str, Any]]) -> dict[str, str]:
    all_pos = 0.0
    all_cost = 0.0
    shares: list[str] = []
    eur_costs: list[float] = []
    for r in data_rows:
        pos = amount_value(r["position"])
        cost = amount_value(r["cost"])
        is_share = "份" in r["position"] or "share" in r["position"].lower()
        if is_share:
            if r["position"] not in shares:
                shares.append(r["position"])
        elif pos is not None:
            all_pos += pos
            all_cost += cost or 0.0
        if "€" in r["cost"] and cost is not None:
            eur_costs.append(cost)
    position_text = fmt_money(all_pos, "¥")
    if shares:
        position_text += " + " + " + ".join(shares)
    cost_text = fmt_money(all_cost, "¥")
    if eur_costs:
        cost_text += " + " + " + ".join(fmt_money(v, "€") for v in eur_costs)
    return {"position": position_text, "cost": cost_text}


def render_table(data_rows: list[dict[str, Any]]) -> str:
    """根据数据行渲染 HTML 持仓表（含合并单元格、每组合计行、总计行）。"""
    groups: list[str] = []
    for r in data_rows:
        if r["type"] not in groups:
            groups.append(r["type"])
    lines = [
        "<table>",
        "  <thead>",
        "    <tr>",
        "      <th>类型</th><th>市场</th><th>基金</th><th>代码</th><th>目标占比</th><th>当前占比</th><th>当前持仓</th><th>累计成本</th><th>收益率</th>",
        "    </tr>",
        "  </thead>",
        "  <tbody>",
    ]
    for type_label in groups:
        members = [r for r in data_rows if r["type"] == type_label]
        for idx, r in enumerate(members):
            cells: list[str] = []
            if idx == 0:
                cells.append(f'<td rowspan="{len(members)}">{html.escape(r["type"])}</td>')
            cells.extend([
                f"<td>{html.escape(r['market'])}</td>",
                f"<td>{html.escape(r['fund'])}</td>",
                f"<td>{html.escape(r['code'])}</td>",
                f"<td>{html.escape(r['target'])}</td>",
                f"<td>{html.escape(r['current_pct'])}</td>",
                f"<td>{html.escape(r['position'])}</td>",
                f"<td>{html.escape(r['cost'])}</td>",
                f"<td>{html.escape(r['return_pct'])}</td>",
            ])
            lines.append("    <tr>" + "".join(cells) + "</tr>")
        s = _subtotal_values(data_rows, type_label)
        lines.append(
            f'    <tr class="subtotal"><td colspan="2">{html.escape(type_label)} 合计</td>'
            f"<td>-</td><td>-</td>"
            f'<td>{s["target"]}</td><td>{s["current"]}</td>'
            f'<td>{s["position"]}</td><td>{s["cost"]}</td><td>{s["return"]}</td></tr>'
        )
    total = _total_values(data_rows)
    lines.append(
        '    <tr class="total"><td colspan="2">总计</td>'
        "<td>-</td><td>-</td><td>-</td><td>-</td>"
        f'<td>{total["position"]}</td><td>{total["cost"]}</td><td>-</td></tr>'
    )
    lines.extend(["  </tbody>", "</table>"])
    return "\n".join(lines)
