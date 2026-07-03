import akshare as ak
import pandas as pd
from datetime import datetime
from tabulate import tabulate


def get_index_valuation(index_name: str):
    """
    从 AkShare 获取指数估值数据
    数据来源通常为基金数据中心 / 指数估值数据
    """
    df = ak.index_value_hist_funddb(symbol=index_name)

    if df.empty:
        raise ValueError(f"无法获取 {index_name} 的估值数据")

    latest = df.iloc[-1]

    # 不同版本 AkShare 字段名可能略有差异
    pe_col = None
    for col in df.columns:
        if "PE" in col.upper() or "市盈率" in col:
            pe_col = col
            break

    if pe_col is None:
        raise ValueError(f"{index_name} 找不到 PE 字段，当前字段为: {df.columns.tolist()}")

    pe = float(latest[pe_col])
    earnings_yield = 1 / pe * 100

    return {
        "指数": index_name,
        "日期": latest[df.columns[0]],
        "PE": round(pe, 2),
        "盈利收益率": round(earnings_yield, 2),
        "建议": make_advice(earnings_yield),
    }


def make_advice(ey: float):
    if ey >= 10:
        return "低估：加倍定投"
    elif ey >= 7:
        return "正常：正常定投"
    elif ey >= 6:
        return "偏贵：少量定投"
    else:
        return "高估：暂停加仓 / 持有"


def main(WATCH_LIST):
    results = []

    for name in WATCH_LIST:
        try:
            data = get_index_valuation(name)
            results.append(data)
        except Exception as e:
            results.append({
                "指数": name,
                "日期": "-",
                "PE": "-",
                "盈利收益率": "-",
                "建议": f"获取失败：{e}",
            })

    df = pd.DataFrame(results)

    print("\n指数基金投资建议")
    print("生成时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    print(tabulate(df, headers="keys", tablefmt="github", showindex=False))

    df.to_csv("index_advice.csv", index=False, encoding="utf-8-sig")
    print("\n已保存到 index_advice.csv")


if __name__ == "__main__":
    WATCH_LIST = {
        "沪深300": "000300",
        "中证500": "000905",
        "中证红利": "000922",
        "上证50": "000016",
        "创业板指": "399006",
    }

    main(WATCH_LIST)