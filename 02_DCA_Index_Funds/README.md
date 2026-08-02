# DCA Index Funds Dashboard

This folder contains a local market index data system.

It can:

- fetch major index data from Yahoo Finance chart API;
- store each index as yearly CSV files under `data/indices`;
- store available valuation metrics under `data/valuations`;
- store composite assessment scores under `data/assessments`;
- run a local dashboard at `http://127.0.0.1:8050`;
- show latest index values, daily changes, long-term change, a close-price chart, valuation curves, and recent OHLC records.
- switch the dashboard between English and Chinese with one button.

The current valuation module supports CSI 300 data from Legulegu through AkShare, including earnings yield, P/E TTM, and P/B.

The dashboard also calculates a `Composite Assessment Score` for every index.

For indices with valuation data, the score uses:

- 45% valuation score;
- 25% price percentile score;
- 20% drawdown score;
- 10% trend score.

For indices without valuation data, the score uses:

- 45% price percentile score;
- 35% drawdown score;
- 20% trend score.

A higher score means the index has a more attractive combination of valuation, price position, drawdown, and trend. This is only a preliminary reference for long-term investors, not investment advice.

## Monthly DCA Decision

The dashboard also includes a monthly dollar-cost-averaging (DCA) allocation panel (`/api/dca`). It splits a monthly budget of ¥2,000 (Bank of China app funds, CNY) and €50 (IBKR ETFs, EUR) across a configurable fund universe.

How it works:

- each fund maps to its tracking index;
- each fund has a quota weight (base_weight): the CNY side currently targets CSI 300 / CSI 500 / ChiNext / CSI Dividend / Hang Seng / Hang Seng Dividend Low Volatility at 25/15/10/15/15/20 (weights 2.5/1.5/1.0/1.5/1.5/2.0);
- when valuation data exists (CSI 300, CSI 500 via Legulegu/AkShare), the decision uses the PE(TTM) history percentile;
- otherwise it uses a 3-year price percentile (Hang Seng, S&P 500, NASDAQ-100, MSCI World, ChiNext, CSI Dividend);
- percentile < 30% → 1.5× the normal weight, 30-70% → 1.0×, >70% → 0.5×;
- weights are normalized to the exact monthly budget.

NASDAQ-100 and S&P 500 are bought on IBKR only (EQQQ and SXR8); the CNY list focuses on China/HK indices.

Monthly flow (run on the 10th):

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py --fetch-only
```

Then open `http://127.0.0.1:8050` to read the allocation. To print the allocation in the console instead:

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py --dca-check
```

The fund universe and base weights are defined in `02_DCA_Index_Funds/dca.py` (FUNDS list) and can be edited to match your own plan. Verify fund availability and purchase limits in your apps before buying.

Monthly execution records are kept in `records/monthly_records.md`; current holdings live in the repository root README (single source of truth).

## Emergency Position Review

The dashboard also has an emergency review page (`/holdings.html`, data from `/api/holdings`). It reads the actual holdings from the repository root `README.md` (the single source of truth), attaches market metrics for each tracked index (trend vs. the 200-day average, 6-month momentum, drawdown, valuation/price percentile), and ranks them by a transparent sell-priority score:

- 40% trend (distance from the 200-day average)
- 30% momentum (6-month return)
- 30% valuation/price percentile

Each holding gets a tier (sell first / may sell / keep) plus a redemption-liquidity note (A-share funds T+1~T+3, IBKR T+2 settlement, QDII T+7~T+10). This is a decision-support framework, not investment advice.

## Run

From the project root:

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py
```

Then open:

```text
http://127.0.0.1:8050
```

## Refresh Data

By default, the script uses incremental updates. It checks whether today's data already exists locally. If it does, the local CSV files are used directly. If it does not, the script fetches only the recent missing window, merges it with local CSV files, and saves the updated yearly files.

Force a full data refresh only when you want to rebuild the local data files:

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py --refresh
```

Fetch data without starting the server:

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py --fetch-only
```

Change history length:

```powershell
.\.venv\Scripts\python.exe .\02_DCA_Index_Funds\script.py --years 15
```
