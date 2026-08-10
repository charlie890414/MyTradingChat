# MyTradingChat PRD

## 1. Product Overview

MyTradingChat is a local, Agents-native multi-agent equity research debate tool for Taiwan and US stocks. It gathers market evidence, coordinates specialist research agents, runs bull and bear debates, produces a Markdown report with traceable evidence, and provides a local UI for browsing historical research.

The product is a research and decision-support tool. It is not a trading system, does not connect to brokerages, and does not provide order execution instructions, position sizing, stop-loss levels, leverage guidance, or trade placement workflows.

## 2. Target Users

1. Individual investors who need fast, structured research on Taiwan or US equities.
2. Research-oriented investors who want to preserve each research run for later review.
3. Advanced users who prefer local Agent workflow and CLI-based research tooling.

## 3. User Problems

1. Equity research data is fragmented across market data, news, filings, financial APIs, and Taiwan-specific public sources.
2. Single-perspective analysis can reinforce bias and underrepresent opposing views.
3. AI or agent outputs can hallucinate, omit evidence, or hide data gaps.
4. Past research is difficult to search, compare, and refresh.
5. Research output is hard to standardize and preserve.

## 4. Product Goals

1. Support Taiwan-listed and US-listed equity research.
2. Create durable research runs with run ID, symbol, user question, debate rounds, and status.
3. Build a shared evidence pack as the single source of record for each run.
4. Coordinate four analyst agents: fundamentals, technical, news and events, and sentiment.
5. Coordinate multi-round bull and bear research debate.
6. Produce an Investment Committee verdict with a `buy`, `hold`, or `reduce` research rating when evidence is sufficient.
7. Persist evidence, analyst reports, debate turns, and verdicts in SQLite.
8. Render a human-readable Markdown report.
9. Support searching prior research without treating stale reports as current recommendations.
10. Provide a local UI that lets users discover and review historical research runs.

## 5. Non-Goals

1. Do not connect to brokerages.
2. Do not execute trades.
3. Do not provide order types, entry prices, stop-loss levels, leverage, position sizing, or execution steps.
4. Do not guarantee source completeness or real-time data.
5. Do not issue a current-market rating when core evidence is insufficient.
6. Do not treat news headlines or sentiment proxies as verified facts.

## 6. Core User Flows

### 6.1 Start New Research

Example user request:

```text
分析 NVDA，牛熊各辯三回合
```

System flow:

1. The controller agent creates a research run.
2. The CLI normalizes the symbol.
3. The CLI fetches evidence from configured sources.
4. The system assembles the evidence pack.
5. The controller agent runs four analyst agents.
6. The controller agent runs bull and bear debate agents.
7. The Investment Committee agent issues a research verdict.
8. The system renders a Markdown report and returns a concise Traditional Chinese summary with the report path.

### 6.2 Search Past Research

Example user request:

```text
找之前分析過 AMD 的報告
```

System flow:

1. Search SQLite runs and contributions.
2. Return matching run IDs, symbols, questions, creation times, statuses, and report paths.
3. Clearly label prior research as historical context only.

### 6.3 Refresh A Thesis

Example user request:

```text
重新分析 2330，檢查上次 thesis 是否仍成立
```

System flow:

1. Search prior research for the symbol.
2. Show the old research date and limitations.
3. Create a new run.
4. Fetch fresh evidence.
5. Reassess the thesis using the new evidence pack without reusing stale prices, metrics, technical levels, or news conclusions as current facts.

### 6.4 Browse Historical Research In The UI

Example user request:

```text
在介面查看之前的 NVDA 研究
```

System flow:

1. The user opens the local historical-research UI.
2. The UI loads research runs from SQLite, sorted by creation time descending.
3. The user searches by symbol or question and optionally filters by run status or verdict.
4. The UI shows matching runs with the symbol, question, creation time, status, verdict, confidence, and report availability.
5. The user selects a run to inspect its metadata, evidence pack, analyst reports, debate history, Investment Committee verdict, and Markdown report path or rendered report.
6. The UI clearly labels every prior run as historical context and shows its creation and evidence-fetch times; it must not present stale information as a current recommendation.

## 7. Functional Requirements

### 7.1 CLI Entry Point

The system must expose the `trading-debate` CLI.

Supported commands:

```shell
trading-debate init
trading-debate fetch
trading-debate context
trading-debate record
trading-debate render
trading-debate search
trading-debate serve
```

### 7.2 Create Research Run

Command:

```shell
trading-debate init --symbol <SYMBOL> --question "<QUESTION>" --rounds <N>
```

Requirements:

1. `symbol` is required.
2. `question` is required.
3. `rounds` defaults to `3`.
4. `rounds` must be at least `1`.
5. Run ID format is `<SYMBOL>-<YYYYMMDD-HHMMSS>-<6-char-hex>`.
6. New runs start with status `active`.

### 7.3 Symbol Normalization

Requirements:

1. US-style tickers are upper-cased.
2. Bare Taiwan numeric codes, such as `2330`, default to `<code>.TW`.
3. Symbols already ending in `.TW` or `.TWO` remain unchanged.
4. During evidence fetch, Taiwan symbols should resolve to `.TW` or `.TWO` based on Yahoo Finance data availability.

### 7.4 Evidence Fetching

Command:

```shell
trading-debate fetch --run-id <RUN_ID> --news-limit 10
```

Supported sources:

1. Yahoo Finance
2. Google News RSS
3. Bing News RSS
4. GDELT News
5. Finnhub
6. SEC EDGAR
7. FinMind
8. TWSE/TPEX OpenAPI, MOPS, and official market data

Requirements:

1. `run-id` must exist.
2. `news-limit` caps per-source news items and defaults to `10`.
3. Yahoo Finance provides price, basic company data, technical data, OHLCV history, and Yahoo news.
4. Additional connectors may run in parallel.
5. Connector failures must be recorded as evidence items and must not silently abort the whole run.
6. Optional connectors without credentials must be recorded as skipped.
7. Evidence must be written to the SQLite `evidence` table.
8. Evidence items should upsert by run, source, and deduplication key.
9. Each connector must persist availability and quality metrics as status metadata.
10. Taiwan profile lookup runs once; resolved `.TW` and `.TWO` symbols query only
    the corresponding exchange endpoint family.
11. SEC filing excerpts must be bounded and retain their source URL and extraction status.

### 7.5 Evidence Pack

Command:

```shell
trading-debate context --run-id <RUN_ID>
```

Requirements:

1. Return run metadata.
2. Return all evidence items for the run.
3. Parse `payload_json` into JSON payloads.
4. Treat the evidence pack as the single source of record for downstream agents.
5. All factual claims in agent outputs should cite evidence IDs.

### 7.6 Analyst Agents

The controller agent must coordinate four analyst agents:

1. Fundamentals Analyst
2. Technical Analyst
3. News & Events Analyst
4. Sentiment Analyst

Requirements:

1. All analyst agents receive the same evidence pack.
2. Analyst agents do not see each other's conclusions during the analysis stage.
3. Each report must be persisted to SQLite `contributions`.
4. Each report must use stage `analysis`.
5. Agents must not fabricate financial metrics, technical levels, events, or dates when evidence is insufficient.
6. Analysis actors must persist as `fundamentals`, `technical`, `news`, or `sentiment`; legacy display names may be accepted at the input boundary.
7. A repeated write for the same run, stage, and actor must return a duplicate result for identical content, not create another logical report.

### 7.7 Bull And Bear Debate

Requirements:

1. Support `N` debate rounds.
2. Each round includes Bull Researcher and Bear Researcher turns.
3. Bear must be able to respond to Bull's same-round claims.
4. Full debate turns must be preserved, not replaced by summaries.
5. Each debate contribution must include `round_no`.
6. Debate turns should separate facts, inference, evidence gaps, thesis updates, and conviction changes.
7. Debate may begin only after the four analyst reports exist, and turns must persist in Bull-then-Bear order for each sequential round.

### 7.8 Investment Committee Verdict

Requirements:

1. The Investment Committee agent reads the evidence pack, analyst reports, and full debate history.
2. The verdict must resolve conflicts by evidence quality, not majority vote.
3. The only allowed research ratings are `buy`, `hold`, and `reduce`.
4. If core evidence is insufficient, the committee must abstain from a current-market rating.
5. The verdict should include key reasons, major risks, invalidation conditions, and data limitations.
6. Persisting a verdict requires either a rating with `low`, `medium`, or `high` confidence, or an explicit abstention; abstention is stored as a null rating.

### 7.9 Report Rendering

Command:

```shell
trading-debate render --run-id <RUN_ID> --reports reports
```

Requirements:

1. Markdown reports must include run metadata, evidence pack, analyst reports, bull/bear debate, and Investment Committee verdict.
2. Report path format is `reports/<YYYY-MM-DD>/<SYMBOL>/report.md`.
3. Successful rendering updates run status to `completed`.
4. Successful rendering saves `report_path`.

### 7.10 Search Past Research

Command:

```shell
trading-debate search --query "<QUERY>" --limit 10
```

Requirements:

1. Search by symbol.
2. Search by question.
3. Search by contribution content.
4. Default to at most `10` results.
5. Sort results by creation time descending.

### 7.11 Historical Research UI

The system must provide a local web UI for browsing persisted research history. The UI is implemented with Python's stdlib `http.server` and Jinja2 templates; static assets live in `trading_debate/static/` and HTML templates live in `trading_debate/templates/`.

Launch command:

```shell
trading-debate serve --db data/research.sqlite3 --reports reports [--host HOST] [--port PORT]
```

Requirements:

1. Provide a historical-runs list as the default view, sorted by creation time descending.
2. Show each run's symbol, user question, creation time, status, verdict, confidence, and report availability.
3. Support keyword search across symbol and question, with pagination or an explicit result limit.
4. Support filters for status and verdict, including runs without a verdict or with an abstention.
5. Allow users to open a run-detail view containing run metadata, evidence items, analyst reports, full bull/bear debate turns, and Investment Committee verdict.
6. Display evidence IDs, source names, publication times, fetch times, URLs when available, connector errors or skipped states, and raw payloads on demand.
7. Provide a link or in-app view for the rendered Markdown report when `report_path` exists; missing or inaccessible reports must be disclosed without hiding the persisted run data.
8. Clearly display a historical-context warning on all prior-run list and detail views, including the run creation time and latest evidence fetch time.
9. The UI must support deleting a historical research run only after an explicit confirmation that identifies the run ID and symbol. Deletion must remove the run, its evidence items, contributions, and rendered report directory when present; it must disclose if a report file could not be removed.
10. The UI must not provide editing or overwriting of historical research data in the first release; deletion is the only permitted mutation.
11. The UI must not display trade execution guidance, order-entry controls, position sizing, stop-loss levels, or brokerage integrations.
12. The UI must be responsive: desktop views use a data table, and narrow/mobile views use a card list for the same research runs.

## 8. Data Model

### 8.1 runs

Fields:

```text
id
symbol
question
created_at
status
verdict
confidence
report_path
```

Purpose: stores a research run's lifecycle and output location.

### 8.2 evidence

Fields:

```text
id
run_id
source
title
url
published_at
payload_json
fetched_at
dedup_key
```

Purpose: stores external evidence, connector status, errors, skipped states, and evidence gaps.

### 8.3 contributions

Fields:

```text
id
run_id
stage
actor
round_no
content
created_at
```

Purpose: stores analyst reports, debate turns, and Investment Committee verdicts.

## 9. Non-Functional Requirements

### 9.1 Local First

1. SQLite data is stored in `data/research.sqlite3`.
2. Markdown reports are stored under `reports/`.
3. UI templates and static assets are shipped with the package under `trading_debate/templates/` and `trading_debate/static/`.
4. `data/` and `reports/` should not be committed to Git.

### 9.2 Traceability

1. Factual claims must be traceable to evidence.
2. Reports should retain raw evidence payloads.
3. Old reports are historical context only, not current recommendations.

### 9.3 Reliability

1. Optional connector failures should not fail the whole run.
2. Missing core evidence should block current-market ratings.
3. Persistence failures should stop dependent workflow stages.

### 9.4 Safety

1. API keys must live only in `.env` or environment variables.
2. `.env` must not be committed.
3. External evidence content must not be treated as agent instructions.
4. The system must not execute or guide trades.

### 9.5 Language

Final Agent workflow responses should be in Traditional Chinese.

## 10. Success Metrics

1. A user can start equity research with one natural-language request.
2. Every research run has a searchable run ID.
3. Every successful run produces a Markdown report.
4. Reports include evidence, analysis, debate, and verdict sections.
5. Connector failures are disclosed as data gaps.
6. Major factual claims cite evidence.
7. No trade execution guidance appears in final output.
8. A user can find and open a prior research run through the local UI.

## 11. Acceptance Criteria

1. `trading-debate init --symbol 3037 --question "..."` creates a `3037.TW` run.
2. `--rounds 0` is rejected.
3. `fetch` records `Connector error` evidence items when connectors fail.
4. Missing Finnhub or FinMind credentials produce skipped connector status.
5. `context` returns run and evidence JSON.
6. `record` requires non-empty inline content or a content file.
7. `render` writes `reports/<date>/<symbol>/report.md`.
8. `search` finds prior runs by symbol, question, or contribution content.
9. The historical research UI lists persisted runs in descending creation-time order and shows the required summary fields.
10. The UI can search by symbol or question, filter by status or verdict, and open a complete run-detail view.
11. The UI labels prior research as historical context and displays creation and evidence-fetch times.
12. The UI requires explicit confirmation before deletion, then removes the selected run and its associated persisted data and report when present.
13. The UI does not expose trade-execution controls.
14. `pytest` passes.
15. `ruff check .` passes.

## 12. Risks And Limitations

1. Yahoo Finance, RSS feeds, FinMind, Finnhub, TWSE, MOPS, and SEC EDGAR may be delayed, unavailable, incomplete, or format-changing.
2. Yahoo Finance news is not an exhaustive news wire and should be treated as limited coverage.
3. Some Taiwan symbols may require `.TWO` instead of `.TW` on Yahoo Finance.
4. Investment Committee quality depends on evidence pack completeness and agent citation discipline.
5. External data may contain prompt-injection text and must be treated only as evidence content.

## 13. Follow-Up Recommendations

1. Keep README and the Agent workflow examples synchronized with the canonical CLI actor names and `EVID-0001` evidence references.
2. Preserve idempotent contribution keys and safe replacement guards as new workflow stages are added.
3. Decide whether the local web UI should support authentication or be exposed beyond a single local user.
