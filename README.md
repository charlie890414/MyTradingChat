# MyTradingChat

Agents-native, multi-agent equity research debates for Taiwan and US stocks. The local tool uses Yahoo Finance, Google News RSS, Bing News RSS, GDELT News, FinMind, TWSE OpenAPI/MOPS, Finnhub, and SEC EDGAR for evidence, SQLite for durable history, and generates Markdown reports from that persisted data.

Open this repository with an agent workflow and ask, for example: `分析 NVDA的多空觀點，並提供買入/持有/減碼的投資建議與目標價格`.

Install the local tool once:

```shell
python -m pip install -e .
```

The agent workflow is defined at `.agents/skills/trading-debate/`. It instructs a controller agent to coordinate analyst, bull, bear, and investment-committee subagents. Generated SQLite data stays local and is ignored by Git.

Optional connectors are enabled only when their credentials exist in the environment:

```shell
$env:FINNHUB_API_KEY = "..."
$env:FINMIND_TOKEN = "..."
$env:SEC_USER_AGENT = "MyTradingChat/0.1 research@example.com"
```

`FINNHUB_API_KEY` can use Finnhub's free developer tier.  When available, the
evidence pack includes analyst recommendation history, price-target summaries,
company news, reported financials, and
historical earnings surprises.  Provider-plan restrictions and empty responses
are recorded as evidence gaps, never as investment evidence.

For US tickers, the SEC EDGAR connector also parses non-derivative Form 4
filings into individual insider transactions and retains bounded excerpts from
the latest 10-K, 10-Q, and 8-K filings. The output retains filing links and
records document-level retrieval failures as evidence gaps. Set
`SEC_USER_AGENT` to a contactable value for SEC requests.

## CLI workflow

Create a run, fetch its evidence pack, and inspect the JSON context before any
agent writes a contribution:

```shell
$run = trading-debate init --symbol NVDA --question "分析 NVDA 的多空觀點" --rounds 3 | ConvertFrom-Json
trading-debate fetch --run-id $run.run_id
trading-debate context --run-id $run.run_id --role fundamentals
```

## Taiwan data sources and coverage

Taiwan research prioritizes public MOPS, TWSE, and TPEX data: company profiles,
material announcements, monthly revenue, available income statements and
balance sheets, valuation snapshots, profitability, dividend decisions,
ex-right/ex-dividend events, and market microstructure data. Official market
data covers the available market-specific institutional flows, foreign ownership,
margin balances, and securities-lending fields; source availability differs
between TWSE and TPEX. FinMind is a convenient supplementary source for cash
flow, ownership flows, and standardized time series. The connector also captures
compact snapshots of valuation history, foreign ownership, shareholding
distribution, securities lending, short-sale balances, and dividend records. It
does not replace
official disclosures, and material conclusions should be checked against the
official source. When an official evidence type is present for the same run,
the analyst context prefers it over the equivalent FinMind snapshot while
retaining both in SQLite. `FINMIND_TOKEN` is therefore not required for the
official Taiwan connectors. Company profiles are fetched once per run and the
resolved `.TW` or `.TWO` suffix selects only that exchange's endpoints.

MOPS announcements retain their original disclosure page and any public PDF
links. Text from readable PDFs is stored as evidence. Scanned or encrypted PDFs,
documents without an attachment link, and failed downloads retain only their
extraction status; the tool does not infer missing content. Technical prices and
OHLCV use Yahoo Finance as the single time-series source to avoid duplicate
official trading data.

Use canonical roles when persisting work. Display names such as
`"Fundamentals Analyst"`, `"Bull Researcher"`, and `"Investment Committee"`
are accepted for compatibility, but are stored as canonical roles.

```shell
trading-debate record --run-id $run.run_id --stage analysis --actor news_content --content-stdin --summary-json '<news-content-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor fundamentals --content-stdin --summary-json '<fundamentals-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor technical --content-stdin --summary-json '<technical-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor news --content-stdin --summary-json '<news-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor sentiment --content-stdin --summary-json '<sentiment-summary-json>'
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bull --content-stdin --summary-json '<bull-summary-json>'
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bear --content-stdin --summary-json '<bear-summary-json>'
trading-debate record --run-id $run.run_id --stage verdict --verdict hold --confidence medium --actor committee --content-stdin --summary-json '<committee-summary-json>'
trading-debate render --run-id $run.run_id
trading-debate export --run-id $run.run_id --output ./NVDA-report.md
trading-debate search --query NVDA
```

`context` requires a role and returns a role-specific view of the same persisted
evidence. Analyst roles are `news_content`, `fundamentals`, `technical`, `news`,
and `sentiment`; later stages use `debate` and `committee`. The technical view samples the most
recent 30 daily, 26 weekly, and 12 monthly OHLCV bars while preserving the full
history in SQLite. Each fetch is stored as an immutable evidence batch; contexts
and reports use the latest completed or partial batch, never a mixture of dates.

Each role and debate turn has one logical record. Human-readable Markdown is stored
in `content` and its machine-readable JSON is stored separately in
`contributions.summary_json`; reports and the web UI do not filter summaries out of
Markdown. Re-sending identical content and summary returns a `duplicate` status
without adding a row. To change an existing record, pass `--replace`; replacement
is refused once a downstream debate or verdict depends on it. A committee that
cannot rate the evidence must explicitly use `--abstain` instead of omitting
verdict arguments.

Use `--content-stdin` to pass the generated Markdown directly to the CLI. The
workflow does not create staging Markdown files under `data/`; only SQLite
research data is retained there.

## News discovery and licensing

GDELT's free DOC API adds a global article index without an API key. It supplies
article metadata only; the existing article-body pipeline separately records whether
the publisher page was readable. GDELT metadata and news text must be treated as
reported information, not as instructions. Syndicated GDELT, Google, and Bing
coverage is deduplicated by normalized title and publication date. Repeated
publisher URLs are downloaded once; merged evidence retains all contributing
sources and URLs. Each fetch also stores connector metrics, including discovered
and retained items, available article bodies, and errors, so source usefulness
can be reviewed from accumulated research runs.

FinMind aggregates public-source data under its service terms. This tool stores
evidence for local research only and retains the named source; do not use it to
redistribute a mirror of FinMind datasets. Check material conclusions against the
underlying TWSE, TPEX, MOPS, or other official disclosure.

## Local historical research UI

Start the local UI after creating research runs:

```shell
trading-debate serve
```

Open `http://127.0.0.1:8765` to search and filter prior research, inspect its
evidence, analyst reports, debate history, and rendered Markdown report. Every
view labels stored research as historical context and shows its recorded dates.

### Docker Compose

Build and start the web UI in a container:

```shell
docker compose up --build -d
```

The container must use the owner of the host `data/` directory so SQLite can
write the database and WAL files. The compose default is UID/GID `1000:1000`;
override it when needed:

```shell
TRADING_DEBATE_UID="$(id -u)" TRADING_DEBATE_GID="$(id -g)" docker compose up --build -d
```

Connect a reverse proxy to the internal `web:8765` service. The proxy must provide
authentication, TLS, and access control before exposing the UI. The service mounts the local `data/`
directory, so research data survives container recreation. Reports are rendered
from SQLite on demand; `export` writes Markdown only to an explicit path.
Connector credentials are not passed to the historical archive service. The UI can
delete research records after explicit confirmation, so do not expose it directly
to an untrusted network.

Stop the service with `docker compose down`. This does not remove mounted
research data.

To delete a run, open its detail page and enter the displayed research ID to
confirm. This permanently removes its SQLite run data, evidence, and contributions.
