# Investment Learning Journey

This repository records my journey of learning long-term investing from zero.

The goal is not to chase short-term profits, but to build a systematic understanding of investing, ETFs, market indices, portfolio management, and financial English.

## 1. Foundations

The Foundations section is a 40-lesson beginner path from basic investing ideas to a first long-term investment plan.


## 2. Index ETF

- [DCA Index Funds Dashboard](02_IndexETF/README.md) - data for the 8 fund-related indices, monthly DCA allocation (¥2,000 + €50), and an emergency position review.
- Run locally with `.\.venv\Scripts\python.exe .\02_IndexETF\script.py`, then open `http://127.0.0.1:8050`.
- Pages: `/` index dashboard, `/dca.html` monthly DCA decision, `/holdings.html` emergency review.


## 3. Short ETF


## 4. Sector ETF


## 5. Portfolio

The monthly workflow:
1. Refresh data — run .\\.venv\\Scripts\\python.exe .\\02_IndexETF\\script.py --fetch-only (market data updates automatically)
2. Buy — open the DCA decision page, read this month's allocation, place the orders manually
3. Record — add a DCA record on the portfolio page (`/portfolio.html`); it saves to `02_IndexETF/data/dca_records.csv` and updates the Current Holdings table in the root [README.md](D:/CodeX/InvestmentLearningJourney/README.md) automatically
4. Recalculate ratios — run the new .\\.venv\\Scripts\\python.exe .\\02_IndexETF\\update_portfolio.py, which automatically recomputes the Current % and Return % columns

### Current Holdings

| Market | Platform | Fund | Code | Target % | Current % | Current Position | Current Cost | Return % |
|---|---|---|---|---|---|---|---:|---:|
| China A-share | Domestic fund platform | 华泰柏瑞沪深300ETF联接A | 460300 | 25% | 42% | ¥2,536.48 | ¥2,625 | -3.4% |
| China A-share | Domestic fund platform | 南方中证500ETF联接(LOF)A | 160119 | 15% | 6.2% | ¥375 | ¥371 | 1.1% |
| China A-share | Domestic fund platform | 易方达创业板ETF联接A | 110026 | 10% | 2.1% | ¥125 | ¥125 | 0.0% |
| China A-share | Domestic fund platform | 富国中证红利指数增强A | 100032 | 15% | 3.1% | ¥188 | ¥188 | 0.0% |
| Hong Kong | Domestic fund platform | 汇添富恒生指数（QDII-LOF） | 164705 | 15% | 20.6% | ¥1,243.61 | ¥1,187 | 4.8% |
| Hong Kong | Domestic fund platform | 易方达恒生红利低波ETF联接A | 021457 | 20% | 26% | ¥1,572.82 | ¥1,500 | 4.9% |
| United States | IBKR | iShares Core S&P 500 UCITS ETF USD (Acc) | SXR8 | - | - | 0.6 shares | €425.918 | - |
| Cash | IBKR | EUR cash | EUR | - | - | €74.082 | €74.082 | - |

DCA records are managed on the portfolio page (`/portfolio.html`) and stored in [dca_records.csv](02_IndexETF/data/dca_records.csv).

## 4. Resources

- [Financial Glossary](Glossary/Vocabulary.md)
- [指数基金投资指南.epub](Glossary/指数基金投资指南.epub)
