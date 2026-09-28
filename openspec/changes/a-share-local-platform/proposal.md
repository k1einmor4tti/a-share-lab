## Why

A-share research needs a local platform that can retain long daily histories, refresh only missing dates, and run reproducible strategy backtests. The existing command-line turtle experiment does not provide a market browser, durable incremental data store, or a modular strategy interface.

## What Changes

- Build a local single-user web application backed by the open-source AKQuant engine.
- Collect about 20 years of Shanghai, Shenzhen, and Beijing A-share daily bars from Eastmoney through AKShare, including identifiable delisted stocks; record source and coverage and use a named public fallback where needed.
- Start an initial full-market download in the background. Provide progress, errors, retry, search, historical charts, and a full-market update button that fetches date gaps and corrects adjusted history when corporate actions change it.
- Display the latest completed daily bars for the Shanghai Composite, Shenzhen Component, ChiNext, CSI 300, and CSI 500 indexes.
- Provide selectable single-stock turtle, moving-average crossover, RSI, Bollinger Bands, and buy-and-hold strategy modules with A-share execution settings and downloadable results.
- Import local or public GitHub `SKILL.md` content for a local DSH assistant that answers strategy questions and suggests parameters without executing imported scripts.

## Capabilities

### New Capabilities

- `market-data`: Stock and index catalog, historical bars, full-market background download, incremental refresh, and coverage reporting.
- `strategy-backtesting`: Modular strategy selection, configurable A-share simulation, benchmark comparison, and saved results.
- `skill-assistant`: Safe skill import and local DSH strategy assistance.
- `local-dashboard`: Single-user market, search, chart, backtest, sync, and assistant screens.

### Modified Capabilities

None.

## Impact

- Adds a Python 3.12 application and local data directory with SQLite metadata and Parquet bars.
- Depends on MIT-licensed AKQuant and AKShare, FastAPI, and a local DSH service at `127.0.0.1:3080` for optional AI features.
- Uses the public Eastmoney interfaces and, where coverage fails, an explicitly labeled public fallback.
- No trading account integration or order placement is in scope.
