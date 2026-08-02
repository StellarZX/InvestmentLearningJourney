# 03 Stock Quant (Pilot)

> Positioning: a small ¥1,000 (RMB) pilot for A-share single-stock quant trading, focused on learning. **No additional funding in the near term.**

## Background

- Budget: ¥1,000 - a loss would not affect daily life.
- Goal: go through the full pipeline of "data -> signal -> backtest -> paper trading -> small live account".
- Boundary: never add money after losses; only consider scaling up after the strategy proves stable in backtest and paper trading.

## Roadmap

1. **Data**: fetch A-share daily prices and fundamentals via AkShare; reuse the index data in `02_DCA_Index_Funds` as market context.
2. **Signals**: start with simple factors - momentum, valuation percentiles (P/E, P/B), moving-average trend, volume.
3. **Backtest**: run on local data with out-of-sample validation, fees and slippage included.
4. **Paper trading**: run 2-3 months to confirm live execution matches the backtest.
5. **Live**: start with ¥1,000, cap each position (e.g. 20%), follow stop-loss discipline.

## Rules

- ¥1,000 is tuition; do not add more.
- Backtest before live trading; retire any strategy that persistently underperforms its benchmark (e.g. CSI 300).
- Keep this completely separate from the long-term DCA plans (`02_DCA_Index_Funds`) and the holdings records (root README); never mix funds.
