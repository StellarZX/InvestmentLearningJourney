# DCA Monthly Records

> Current holdings are tracked in the Current Holdings table of the repository root README; this file records funding status and monthly DCA execution details.

## Funding Status

| Item | Status |
|---|---|
| Near-term extra funding | Paused |
| Manual monthly DCA | On the 10th each month; August 2026 completed |
| IBKR funding | €500 transferred and settled |
| Bookkeeping FX rate | 1 EUR = ¥7.80 |

## Monthly Records (July)
| Date       | Action | Fund                 |   Code |   Amount |
|------------|--------|----------------------|-------:|---------:|
| 2026-07-03 | Buy    | 华泰柏瑞沪深300ETF联接A      | 460300 |   ¥1,000 | 
| 2026-07-06 | Buy    | iShares Core S&P 500 |   SXR8 | €425.918 |
| 2026-07-10 | DCA    | 华泰柏瑞沪深300ETF联接A      | 460300 |   ¥1,000 |
| 2026-07-10 | DCA    | 易方达恒生红利低波ETF联接A      | 021457 |   ¥1,000 |

## Monthly Records (August)
| Date       | Action | Fund               |   Code | Amount |
|------------|--------|--------------------|-------:|-------:|
| 2026-08-03 | DCA    | 华泰柏瑞沪深300ETF联接A    | 460300 |   ¥625 |
| 2026-08-03 | DCA    | 南方中证500ETF联接(LOF)A | 160119 |   ¥375 |
| 2026-08-03 | DCA    | 易方达创业板ETF联接A       | 110026 |   ¥125 |
| 2026-08-03 | DCA    | 富国中证红利指数增强A        | 100032 |   ¥188 |
| 2026-08-03 | DCA    | 汇添富恒生指数(QDII-LOF)A | 164705 |   ¥187 |
| 2026-08-03 | DCA    | 易方达恒生红利低波ETF联接A    | 021457 |   ¥500 |

Rule: run the manual DCA on the 10th each month (amounts per the DCA decision page), append a row to Monthly Records, update Current Position / Current Cost in the root README holdings table, then run `..\\.venv\\Scripts\\python.exe .\\02_DCA_Index_Funds\\update_portfolio.py` to refresh the Current % / Return % columns automatically.
