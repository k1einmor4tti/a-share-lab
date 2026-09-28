## Purpose

Present local market data, download progress, strategy selection, backtests and assistant guidance in one usable browser interface for a single researcher.

## ADDED Requirements

### Requirement: Market overview
The dashboard SHALL show the five configured index close values, their dates and day-over-day changes, plus full-market download counts and the current job state.

#### Scenario: Initial download underway
- **WHEN** the background download is running
- **THEN** the dashboard shows completed, failed and remaining symbol counts without blocking navigation

### Requirement: Stock discovery and chart
The dashboard SHALL search stocks by code or name and display a selected stock's historical daily price chart, source and coverage, including a clear empty state if no bars exist.

#### Scenario: Search a code
- **WHEN** the user enters a partial six-digit code
- **THEN** matching stocks are selectable and the selected stock's saved history can be viewed

### Requirement: Update and recovery controls
The dashboard SHALL expose one full-market Update action and a way to retry failed or incomplete downloads. It SHALL show a clear result when an update is already running.

#### Scenario: Duplicate update click
- **WHEN** an update job is active and the user clicks Update again
- **THEN** no second competing full-market job starts and the existing progress is shown

### Requirement: Local-only access
The default launch command SHALL bind the application to loopback only and SHALL not require an external account for ordinary market or backtest use.

#### Scenario: Start application
- **WHEN** the user runs the documented launch command
- **THEN** the dashboard is available on a localhost URL

