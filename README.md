# 投资方法与记录

这个仓库记录我的投资方法、执行记录与复盘。

## 投资体系

整个投资体系分为四个部分：**长期资产（核心）**、行业基金（增强）、量化基金（增强）、应急资金。

| 部分 | A股长期指数 | 美股长期指数 | 行业基金 | 量化基金 |
|---|---:|---:|---:|---:|
| 方式 | 每月定投 | 每月定投 | 一次性固定 | 一次性固定 |
| 金额 | ¥1,500 | ¥1,000 | ¥5,000 | ¥3,000 |

长期指数投资是核心，行业基金和量化基金只是增强收益。

### A股长期指数（每月 ¥1,500，比例永久不变）

| 指数 | 沪深300 | 中证500 | 创业板 | 中证红利 | 恒生指数 | 恒生红利低波 | **合计** |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 比例 | 25% | 15% | 10% | 15% | 15% | 20% | **100%** |
| 每月 | ¥375 | ¥225 | ¥150 | ¥225 | ¥225 | ¥300 | **¥1,500** |

- 沪深300：中国核心资产（银行、保险、消费、制造业龙头），负责稳定。
- 中证500：中盘成长，提高长期收益。
- 创业板：科技创新，成长性最高，比例不宜太高。
- 中证红利：降低组合波动，提高现金流质量。
- 恒生指数：配置香港上市的中国优质企业（腾讯、阿里、小米、网易等），很多优秀公司不在 A 股上市。
- 恒生红利低波：增强港股价值属性、降低波动，也是未来长期现金流的重要来源。

指数**不会更换**：以后收入提高只增加金额，比例永久不变。

### 美股指数（每月 ¥1,000）

| 指数 | 每月 | 执行方式 |
|---|---:|---|
| 标普500 | ¥400 | 每日 ¥10 定投：摩根标普500 A（019305）+ 摩根标普500 C（017641） |
| 纳斯达克100 | ¥600 | 每日 ¥10 定投：摩根纳斯达克100 A（019172）+ 招商纳斯达克100 A（019547）+ 华安纳斯达克100 A（040046） |

标普500代表美国整体经济，纳斯达克代表美国科技创新，覆盖苹果、微软、英伟达、亚马逊、Google、Meta，长期足够。美股通过国内平台每日定投执行，不再使用 IBKR。

### 估值调整机制

战略比例**永远不变**，只调整当月投入金额：

- 历史分位 <30%：买入 1.5 倍
- 30% ~ 70%：正常投入
- >70%：买入 0.5 倍

不是停止定投，只是便宜多买、贵时少买，避免择时。

## 1. 基础课程

40 课投资基础课程，分 6 个部分：基础概念（01–07）、金融市场（08–14）、核心投资原则（15–21）、ETF 投资（22–28）、经济理解（29–34）、投资心理（35–40），每课配有中文导读。课程在 [01_Foundations](01_Foundations/) 目录内按需阅读，不在首页展示。

## 2. 指数定投

- [定投指数基金看板](02_IndexETF/README.md)：8 个相关指数的行情数据、月度定投分配（A股 ¥1,500 + 美股 ¥1,000）与应急持仓评估。
- 页面：`/` 指数看板、`/dca.html` 定投决策、`/portfolio.html` 持仓记录、`/holdings.html` 持仓应急。
- 行情、估值与定投记录统一存放在本地数据库 `02_IndexETF/data/market.db`。

使用：

```powershell
.\.venv\Scripts\python.exe .\02_IndexETF\script.py              # 更新数据并启动看板
.\.venv\Scripts\python.exe .\02_IndexETF\script.py --fetch-only # 只更新数据，不启动
.\.venv\Scripts\python.exe .\02_IndexETF\script.py --refresh    # 强制全量刷新
.\.venv\Scripts\python.exe .\02_IndexETF\script.py --dca-check  # 控制台打印当月定投分配
.\.venv\Scripts\python.exe .\02_IndexETF\update_portfolio.py    # 重算持仓占比与收益率
```

启动后打开 `http://127.0.0.1:8050`。每月定投流程见下方「组合持仓」；更详细的说明见 [02_IndexETF/README.md](02_IndexETF/README.md)。


## 3. 短线 ETF

ETF 动量轮动策略：拉取场内 ETF 日 K，计算动量与 MACD 信号，生成 TOP N 持仓建议和可视化报告（用场外 C 类份额执行，并标注 7 天免赎回费标的）。

使用：

```powershell
.\.venv\Scripts\python.exe .\03_ShortETF\run.py               # 全流程：拉数据 + 算信号 + 出策略
.\.venv\Scripts\python.exe .\03_ShortETF\run.py --update      # 仅更新数据
.\.venv\Scripts\python.exe .\03_ShortETF\run.py --signal      # 仅用本地数据算信号（不联网）
.\.venv\Scripts\python.exe .\03_ShortETF\run.py --universe 19 # 使用 19 只小池（默认 100 只）
.\.venv\Scripts\python.exe .\03_ShortETF\run.py --top 3       # TOP N 持仓数量
```

输出：`strategy_latest.json` 最新策略、`strategy_report.html` 可视化报告、`data/etf_strategy.db` 本地数据库；历史报告保存在 `reports/`。


## 4. 行业 ETF


## 5. 组合持仓

每月流程：
1. 更新数据 — 运行 `.\.venv\Scripts\python.exe .\02_IndexETF\script.py --fetch-only`（行情自动增量更新）
2. 买入 — 打开定投决策页查看当月分配，在 App 中手动下单
3. 记录 — 在持仓记录页（`/portfolio.html`）添加定投记录；保存到本地数据库并自动更新根 [README.md](D:/CodeX/InvestmentLearningJourney/README.md) 的当前持仓表
4. 重算比例 — 运行 `.\.venv\Scripts\python.exe .\02_IndexETF\update_portfolio.py`，自动重算当前占比与收益率

### 当前持仓

<table>
  <thead>
    <tr>
      <th>类型</th><th>市场</th><th>基金</th><th>代码</th><th>目标占比</th><th>当前占比</th><th>当前持仓</th><th>累计成本</th><th>收益率</th>
    </tr>
  </thead>
  <tbody>
    <tr><td rowspan="8">指数</td><td>沪深</td><td>华泰柏瑞沪深300</td><td>460300</td><td>25%</td><td>42%</td><td>¥2,536.48</td><td>¥2,625</td><td>-3.4%</td></tr>
    <tr><td>沪深</td><td>南方中证500</td><td>160119</td><td>15%</td><td>6.2%</td><td>¥375</td><td>¥371</td><td>1.1%</td></tr>
    <tr><td>沪深</td><td>易方达创业板</td><td>110026</td><td>10%</td><td>2.1%</td><td>¥125</td><td>¥125</td><td>0.0%</td></tr>
    <tr><td>沪深</td><td>富国中证红利指数增强</td><td>100032</td><td>15%</td><td>3.1%</td><td>¥188</td><td>¥188</td><td>0.0%</td></tr>
    <tr><td>港股</td><td>汇添富恒生指数</td><td>164705</td><td>15%</td><td>20.6%</td><td>¥1,243.61</td><td>¥1,187</td><td>4.8%</td></tr>
    <tr><td>港股</td><td>易方达恒生红利低波</td><td>021457</td><td>20%</td><td>26%</td><td>¥1,572.82</td><td>¥1,500</td><td>4.9%</td></tr>
    <tr><td>美股</td><td>标普500</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>美股</td><td>纳斯达克100</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr class="subtotal"><td colspan="2">指数 合计</td><td>-</td><td>-</td><td>100%</td><td>100%</td><td>¥6,040.91</td><td>¥5,996</td><td>0.7%</td></tr>
    <tr><td rowspan="3">量化</td><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr class="subtotal"><td colspan="2">量化 合计</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td rowspan="3">行业</td><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>沪深</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr class="subtotal"><td colspan="2">行业 合计</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td rowspan="1">其他</td><td>美股</td><td>安硕标普500</td><td>SXR8</td><td>-</td><td>-</td><td>0.6 份</td><td>€500</td><td>-</td></tr>
    <tr class="subtotal"><td colspan="2">其他 合计</td><td>-</td><td>-</td><td>-</td><td>-</td><td>0.6 份</td><td>€500</td><td>-</td></tr>
    <tr class="total"><td colspan="2">总计</td><td>-</td><td>-</td><td>-</td><td>-</td><td>¥6,040.91 + 0.6 份</td><td>¥5,996 + €500</td><td>-</td></tr>
  </tbody>
</table>

定投记录在持仓记录页（`/portfolio.html`）管理，存放于本地数据库 `02_IndexETF/data/market.db`。

## 6. 资料

- [指数基金投资指南.epub](Glossary/指数基金投资指南.epub)
