# 05 Quantitative Investing Learning Path

> Quant is not a shortcut to guaranteed profits. It is a method of making investment decisions with data, rules, and systems: every buy and sell has a rationale, can be backtested, and can be reviewed.
> This folder starts from zero and helps you build quant skills on top of the market data already stored in this repository.

## 0. Decide which kind of "making money with quant" you want

| Type | Characteristics | Suitable for individuals? |
|---|---|---|
| Quant investing (low frequency) | Rebalancing weekly/monthly; index enhancement, valuation-based DCA, asset allocation | Yes, compatible with long-term investing |
| Quant trading (medium frequency) | Daily-level strategies; grids, momentum rotation, trend following | Possible, but requires more time |
| High-frequency trading | Millisecond-level execution; competes on speed and infrastructure | Not suitable; extremely costly |

**Realistic expectation:** Quant cannot guarantee profits. Its real value is discipline (no gut-feel trades), verifiability (historical backtests), and accountability (you can review what went wrong).

## 1. Phase 1: Tool basics (about 2-4 weeks)

- Python basics: variables, lists, dicts, functions, loops, conditionals.
- pandas / numpy: reading, filtering, computing, and merging DataFrames.
- Visualization: matplotlib or plotly for price and indicator charts.
- Practice data: use the CSV files under `02_Market/data/indices/` in this repository, e.g. load the S&P 500 and compute daily returns.

Spend 30-60 minutes a day, and keep notes in this folder as you learn.

## 2. Phase 2: The raw materials of quant strategies (about 2-3 weeks)

- Data: OHLCV, indices, valuations (P/E, P/B, dividend yield).
- Metrics: returns, annualized volatility, maximum drawdown, Sharpe ratio, win rate.
- Classic ideas:
  - Momentum: winners keep winning; buy what performed best recently.
  - Mean reversion: what goes up too far tends to pull back; what falls too far tends to recover.
  - Grid trading: buying and selling in batches within a set range.
  - Valuation-based DCA: invest more when cheap (low P/E or P/B percentile), less or pause when expensive.
- Build financial English vocabulary in parallel (see `04_Glossary/Vocabulary.md`).

## 3. Phase 3: Write your first strategy and backtest it (about 4-6 weeks)

Pick one of these three simple strategies to start:

1. **DCA vs. lump sum**: compare monthly fixed-amount investing against one initial purchase using historical data.
2. **Dual moving average**: hold when price is above the 50/200-day average, sit out when below; measure long-term performance.
3. **Monthly momentum rotation**: at the start of each month, compare trailing 6-month returns across indices, hold the strongest, re-rank next month.

Backtest tool choices:

- Hand-written simple backtest: most transparent, best for learning.
- vectorbt: fast, great for parameter sweeps.
- backtrader: full-featured, well documented.

**Costs you must include:** commissions, slippage, fund subscription/redemption fees, and taxes. Ignoring them makes backtest returns seriously overstated.

## 4. Phase 4: Spot the "backtest traps" (about 2 weeks)

- Overfitting: the more parameters you tune, the prettier the results and the more likely you are fitting noise. Fewer parameters and simpler logic are more robust.
- Out-of-sample validation: hold out the most recent 20-30% of data, never use it for tuning, and test it only once.
- Look-ahead bias: use only information available at the time (using next month's data to "predict" this month is cheating).
- Survivorship bias: backtesting only indices or stocks that still exist today overstates returns.
- Sanity check: if a backtest shows 50% annual returns with no drawdowns, assume something is wrong.

## 5. Phase 5: Validation and live trading (ongoing)

- Run the strategy in a paper account for 2-3 months first to confirm live execution matches the backtest.
- Start live with a small amount (e.g. ¥1,000) that you could lose without affecting your life.
- Keep a trade journal: why you bought, what you expected, what actually happened, what to change next time.
- Combine with your long-term investing: treat quant signals as a reference for adding or reducing positions, not an excuse for frequent trading.

## 6. Connecting with the rest of this repository

- `02_Market`: already contains daily data for 11 indices since 2016, plus CSI 300 valuation data - ready to use for backtests.
- `03_Portfolio`: your current DCA plans can be upgraded to "valuation-based DCA" by scaling the monthly amount with the CSI 300 P/E or P/B percentile.
- `04_Glossary`: record quant-related financial English vocabulary here.

## Risk warnings

- Past strategy performance does not guarantee future returns.
- Never invest money you need to live on; do not borrow money or use leverage.
- If your strategy underperforms simple DCA for 3-6 months, it probably is not better than blind DCA - that is also a useful conclusion.

