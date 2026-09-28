## 1. Repository and specification

- [x] 1.1 Initialize the GitHub-linked local repository with ignored runtime data, dependency manifest, and validated OpenSpec artifacts; commit and push.
- [x] 1.2 Have a sub-agent review phase 1 scope and repository setup; commit any corrections separately.

## 2. Market data

- [x] 2.1 Implement the current and delisted stock catalog with local search and source labeling; verify representative codes; commit.
- [x] 2.2 Implement raw and adjusted stock and index daily Parquet storage with verified coverage ranges, interior-gap repair, per-bar provenance and rebase detection; verify initial and gap updates; commit.
- [x] 2.3 Implement resumable full-market background jobs, progress, failure reporting and retry; commit.
- [x] 2.4 Have a sub-agent review phase 2 data behavior and coverage claims; commit fixes separately.

## 3. Strategy backtesting

- [x] 3.1 Implement five registered single-stock strategy modules and parameter schemas; commit.
- [x] 3.2 Integrate AKQuant with A-share execution settings, benchmark, immutable input snapshots, saved result and exports; verify against synthetic and real daily bars; commit.
- [x] 3.3 Have a sub-agent review phase 3 execution correctness and provenance; commit fixes separately.

## 4. Local web and assistant

- [x] 4.1 Build and verify the local market dashboard, search, historical chart and sync progress; commit.
- [x] 4.2 Build and verify strategy forms, backtest result view, comparison and downloads; commit.
- [ ] 4.3 Implement safe local/GitHub SKILL.md import and tool-free DSH assistant connection; commit.
- [ ] 4.4 Have a sub-agent review phase 4 usability, input handling and assistant boundary; commit fixes separately.

## 5. End-to-end delivery

- [ ] 5.1 Verify clean setup, localhost launch, real stock and index fetch, incremental update, all five strategies, skill import and DSH failure handling; commit documentation and corrections.
- [ ] 5.2 Have a sub-agent review the release candidate; commit corrections separately, push main, and report remaining public-data coverage limits.
