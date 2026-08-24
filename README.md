# 投资方法与记录

个人投资方法、执行记录与复盘（数据仅供参考，不构成投资建议）。

- **导航首页**（报告 / 课程 / 持仓）：[index.html](https://stellarzx.github.io/InvestmentLearningJourney/)，由 `Code/make_index.py` 自动生成
- **本地使用**（双击根目录批处理）：
  1. `update_portfolio.bat` → 记录当日持仓流水（浏览器 http://127.0.0.1:8051）
  2. `daily_report.bat` → 一次生成三份报告（持仓基金分析 + 板块分析 + ETF 联接入场机会），自动刷新导航页并提交推送
- **ETF 联接子项目**：`Code/etf_data.py` 筛选底池（成交额≥2亿 且 规模≥20亿），`Code/etf_report.py` 输出稳健趋势入场信号（综合分≥65 + MACD/MA60 双确认 + T+1 追高惩罚）
