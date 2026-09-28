## Purpose

Provide a transparent local record of A-share and index daily prices so a user can inspect history and run repeatable research without downloading the same dates again.

## ADDED Requirements

### Requirement: Market catalog and coverage
The system SHALL maintain searchable Shanghai, Shenzhen, and Beijing A-share symbols, including identifiable delisted symbols, and SHALL show each symbol's listing state, available date range, bar count, and data source. The system SHALL identify symbols or date ranges for which 20-year coverage cannot be obtained.

#### Scenario: Search a delisted company
- **WHEN** the user searches by a known delisted stock code or name
- **THEN** the matching symbol appears with a delisted label and its actual available history range

### Requirement: Background initial download
The system SHALL download the available daily history for the full symbol catalog, limited to the most recent 20 years or the listing date, in a resumable background job. The dashboard SHALL remain usable while the job runs and SHALL show progress, failures, and retryability.

#### Scenario: Restart during download
- **WHEN** the application restarts after a partial full-market download
- **THEN** the saved bars remain available and the remaining symbols can be resumed without restarting completed histories

### Requirement: Incremental full-market update
The system SHALL offer an Update action covering all cataloged stocks and the five configured indexes. On ordinary updates it SHALL request dates after each stored last date and avoid duplicate bars. It MAY re-fetch older adjusted prices only when necessary to correct a detected corporate-action rebase. It SHALL exclude incomplete current-day bars before the market close.

#### Scenario: Four-day gap
- **WHEN** a stock's last saved bar is September 16 and the user updates on September 20
- **THEN** the stock's normal request begins after September 16 and stored bars remain unique by date

#### Scenario: Update before and after close
- **WHEN** the user updates before the market close and again after the close
- **THEN** the first update does not save an incomplete current-day daily bar and the second can add the completed bar

### Requirement: Daily index history
The system SHALL show completed daily values and recent history for the Shanghai Composite, Shenzhen Component, ChiNext, CSI 300, and CSI 500 indexes.

#### Scenario: Dashboard opens with cached indexes
- **WHEN** at least one index has saved history and the dashboard opens without network access
- **THEN** its latest saved date and closing value remain visible

### Requirement: Source transparency
The system SHALL use Eastmoney as the primary stock source, SHALL label any alternate source used for a symbol, and SHALL retain failures rather than silently treating unavailable history as a full dataset.

#### Scenario: Primary source fails
- **WHEN** Eastmoney fails and an alternate public source supplies history
- **THEN** the saved symbol metadata identifies the alternate source and the available date range

