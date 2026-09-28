## Context

See [proposal.md](proposal.md). This is a new repository. An older workspace contains a command-line turtle experiment and about 5 GB of mixed Yahoo and sampled Eastmoney cache, but its sampled bars are not suitable as a complete daily history. The target machine has Python 3.12 and an accessible local DSH service. The requested UI is local and single-user.

## Goals / Non-Goals

**Goals:**

- Keep first use responsive while thousands of symbols download in the background.
- Preserve raw daily bars and a separately tagged adjusted view so normal refreshes only fetch missing dates while detected adjustment changes can repair history.
- Make each backtest's inputs and data provenance inspectable.
- Keep the application launchable with Python alone, without a Node runtime or cloud database.

**Non-Goals:**

- Trading, broker connectivity, minute data, real-time market streaming, or multi-user access.
- A claim of complete point-in-time historical universe membership when public sources do not supply it.
- Executing imported skill code or letting DSH silently install strategy modules.

## Decisions

### Open-source core with a small local web shell

Use AKQuant's MIT-licensed Python/Rust backtest engine and AKShare as dependencies. Build a focused FastAPI application and bundled static frontend around them. A full backtrader_web fork was considered, but its broad trading and user-management surface, large repository, and incompatible local Node version add work unrelated to the confirmed scope.

### Symbol files plus metadata database

Store each symbol's raw and forward-adjusted bars in compressed Parquet. Store catalog, coverage, jobs, skill metadata and run metadata in SQLite with WAL enabled. Atomic file replacement protects each saved series from interrupted writes. The job worker records per-symbol failure and can resume from the last saved date. The prior sampled JSON cache is never treated as daily bars.

### Source and adjustment policy

Use Eastmoney via AKShare first. Try BaoStock for unavailable stock histories and label the result. Keep the source per symbol and in saved run metadata. Normal updates request after the last saved bar. Compare an old adjusted anchor with the current source; when it changes, re-fetch that adjusted series. Exclude today's bar until after the close in Asia/Shanghai. Delisted catalogs are assembled from current stocks plus available Shanghai, Shenzhen and Eastmoney delisting lists; report coverage gaps rather than implying completeness.

### Simulation contract

Each strategy module generates signals only from bars available through that close. AKQuant receives the series and applies next-open fills, T+1, lot size and configured fees. Results include equity, metrics, orders/trades and a CSI 300 benchmark. Modules declare a schema of parameter defaults and bounds so the UI can render forms without strategy-specific code.

### Assistant boundary

Store imported Markdown text under a managed directory. Local directory imports and GitHub downloads are size-limited, path-checked, and never executed. Send selected skill text and current strategy context only to `127.0.0.1:3080` via DSH's RPC protocol. Assistant failure leaves the rest of the app working.

### Delivery and review

Develop in `~/github.com/a-share-lab` on `main`. Commit each completed task, push phase milestones, request a separate sub-agent review after each phase, and commit fixes as distinct follow-up changes. OpenSpec task checkboxes track completion.

## Risks / Trade-offs

- **Public data endpoint failure or throttling** → bounded retries, low request rate, alternate source, visible per-symbol errors and later retry.
- **Incomplete delisted coverage** → visible catalog source and exact data range; do not claim complete survivorship-free research.
- **Corporate-action rebases** → store raw bars separately and re-fetch adjusted history on anchor changes.
- **A-share price-limit and suspension fidelity** → enforce known constraints where data supports them and label approximations in results.
- **DSH or GitHub unavailable** → market and backtest functions work independently; import/assistant actions return clear errors.

## Migration Plan

Initialize an empty local data directory and start the background catalog and history job on first run. Existing experimental cache remains untouched. The platform's SQLite and Parquet files are excluded from Git; removing the application leaves source files and saved data separately recoverable.
