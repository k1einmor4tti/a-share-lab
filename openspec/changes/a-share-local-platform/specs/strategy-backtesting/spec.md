## Purpose

Let a single user select a repeatable A-share strategy module, configure its parameters, and evaluate one stock against its own price history and a benchmark.

## ADDED Requirements

### Requirement: Strategy modules
The system SHALL offer selectable turtle breakout, moving-average crossover, RSI reversal, Bollinger Bands, and buy-and-hold modules. Each module SHALL declare editable parameters and their valid ranges.

#### Scenario: Select and configure a module
- **WHEN** the user selects RSI reversal and enters a stock code
- **THEN** the UI shows the RSI parameters and can submit a backtest for that code

### Requirement: A-share execution assumptions
The backtest SHALL use completed daily bars, next-session execution for signals based on a closing bar, T+1 selling restrictions, 100-share lot sizing, configurable commission, stamp tax, transfer fee and slippage, and marked approximations for suspension or daily price-limit handling.

#### Scenario: Same-day sale signal
- **WHEN** a strategy buys shares on a trading day and issues a sell signal later that day
- **THEN** the backtest does not execute a sale of those newly bought shares that day

### Requirement: Reproducible results
Each run SHALL save its stock, strategy, parameters, history range, source and adjustment method, engine version, headline metrics, equity series, orders or trades, and benchmark comparison. The user SHALL be able to reopen and export a completed result.

#### Scenario: Reopen a prior run
- **WHEN** the user reopens a saved backtest
- **THEN** the same inputs, metrics, curve and trade details are shown without rerunning it

### Requirement: Insufficient data is explicit
The system SHALL reject a backtest with insufficient data for the selected strategy and explain which history is missing.

#### Scenario: Missing history
- **WHEN** a stock has no local bars
- **THEN** the UI explains that data must be downloaded before the backtest can run

