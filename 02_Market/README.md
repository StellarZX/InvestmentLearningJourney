# Market Index Dashboard

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

## Run

From the project root:

```powershell
.\.venv\Scripts\python.exe .\02_Market\script.py
```

Then open:

```text
http://127.0.0.1:8050
```

## Refresh Data

Force a full data refresh:

```powershell
.\.venv\Scripts\python.exe .\02_Market\script.py --refresh
```

Fetch data without starting the server:

```powershell
.\.venv\Scripts\python.exe .\02_Market\script.py --fetch-only
```

Change history length:

```powershell
.\.venv\Scripts\python.exe .\02_Market\script.py --years 15
```
