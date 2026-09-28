# A Share Lab

Local A-share market research and modular backtesting platform. The project is under development; its accepted behavior and delivery phases are tracked in [OpenSpec](openspec/changes/a-share-local-platform/).

The intended application uses [AKQuant](https://github.com/akfamily/akquant) for backtesting and [AKShare](https://github.com/akfamily/akshare) for Eastmoney daily data. It will keep data on this computer, show actual history coverage and sources, and provide an optional local DSH assistant.

## Development status

The initial OpenSpec proposal is complete. Application code is being implemented task by task. Runtime data and local environments are excluded from Git.

## Requirements

- Python 3.12
- Git
- Network access for the initial historical data download
- Optional DSH service at `127.0.0.1:3080`

This is research software. Backtest results depend on data coverage and stated execution assumptions.

## Public-data coverage

Eastmoney is the primary daily-bar source. BaoStock can fill Shanghai and Shenzhen bars and provide a delisted-stock catalog. Beijing bars currently depend on Eastmoney; if that endpoint fails, the affected symbols remain marked as failed for a later retry. The app records actual dates and sources and does not assume that every delisted security has a public 20-year history.
