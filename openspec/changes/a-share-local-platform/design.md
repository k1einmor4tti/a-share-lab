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

Store each symbol's raw and forward-adjusted bars in compressed Parquet, retaining per-bar source. Store catalog, verified date-range coverage, jobs, skill metadata and run metadata in SQLite with WAL enabled. Atomic file replacement protects each saved series from interrupted writes. The job worker retries unchecked date ranges, including failed interior ranges, without relying solely on the last saved bar. Gaps caused by genuine trading suspensions are distinguished from failed fetches by recording successfully checked ranges; suspicious long gaps can be checked against the trading calendar and a second source. The prior sampled JSON cache is never treated as daily bars.

### Source and adjustment policy

Use Eastmoney daily interfaces first. Try BaoStock for unavailable Shanghai and Shenzhen stock histories and label the result on each bar. Beijing histories currently depend on Eastmoney; any failure must remain visible rather than counted as covered. Normal updates request unchecked ranges after the last verified date and failed interior intervals. Verify expected sessions against the independent XSHG exchange calendar rather than an index series that might itself have gaps; fall back to conservative weekdays if the installed calendar lacks a future year. Reconcile saved index coverage on update so old false intervals reopen. Confirm an older apparent stock suspension with a second source before recording an empty date as covered. Always leave an absent current-day close open for another update. Compare an old adjusted anchor with the current source; when it changes, re-fetch that adjusted series only if every previously saved trading date remains present. Exclude today's bar until after the close in Asia/Shanghai. Delisted catalogs are assembled from BaoStock and available Shanghai and Shenzhen delisting lists; report coverage gaps rather than implying completeness.

### Simulation contract

Each strategy module generates signals only from bars available through that close. AKQuant receives forward-adjusted bars as an execution-price proxy so splits and cash distributions do not create false mark-to-market losses without corporate-action accounting. It applies next-open fills, T+1, 100-share submitted orders and configured fees; absolute historical prices, quantities and minimum commissions are approximate under this proxy. A volume participation cap is not offered because the selected AKQuant version can produce non-lot partial fills. Suspensions and price limits remain approximate and are stated in each report. Results include equity, metrics, orders/trades and a date-aligned CSI 300 benchmark. A run is blocked when required date intervals remain unverified. A per-symbol lock keeps the raw and adjusted snapshot from mixing revisions during updates. Each run stores compressed immutable input files, SHA-256 checksums, exact engine/dependency versions, a local strategy/execution-code hash and the source of each input bar; later data corrections cannot silently change a saved run. Modules declare a schema of parameter defaults and bounds so the UI can render forms without strategy-specific code.

### Assistant boundary

Store imported Markdown text under a managed directory. The browser uploads a selected local directory; GitHub downloads are size-limited and path-checked. Neither path executes imported content. Before skill-aware chat, verify that the DSH preset has no tools, then create a dedicated session using that preset and send selected skill text as explicitly delimited untrusted reference data. If a tool-free preset cannot be verified, disable skill-aware DSH chat and report the setup needed. Assistant failure leaves the rest of the app working.

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
