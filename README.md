# MyTradingChat

Agents-native, multi-agent equity research debates for Taiwan and US stocks. The local tool uses Yahoo Finance, Google News RSS, Bing News RSS, FinMind, TWSE OpenAPI/MOPS, Finnhub, and SEC EDGAR for evidence, SQLite for durable history, and generates Markdown reports from that persisted data.

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
```

`FINNHUB_API_KEY` can use Finnhub's free developer tier.  When available, the
evidence pack includes analyst recommendation history, price-target summaries,
and EPS estimates in addition to company news, reported financials, and
historical earnings surprises.  Provider-plan restrictions and empty responses
are recorded as evidence gaps, never as investment evidence.

For US tickers, the SEC EDGAR connector also parses non-derivative Form 4
filings into individual insider transactions.  The output retains the filing
links and records any document-level retrieval failures as evidence gaps.

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
balance sheets, and valuation snapshots. FinMind is a convenient supplementary
source for cash flow, ownership flows, and standardized time series; it does
not replace official disclosures, and material conclusions should be checked
against the official source. `FINMIND_TOKEN` is therefore not required for the
official Taiwan connectors.

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
trading-debate record --run-id $run.run_id --stage analysis --actor news_content --content-file news-content.md --summary-json '<news-content-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor fundamentals --content-file fundamentals.md --summary-json '<fundamentals-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor technical --content-file technical.md --summary-json '<technical-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor news --content-file news.md --summary-json '<news-summary-json>'
trading-debate record --run-id $run.run_id --stage analysis --actor sentiment --content-file sentiment.md --summary-json '<sentiment-summary-json>'
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bull --content-file bull-round-1.md --summary-json '<bull-summary-json>'
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bear --content-file bear-round-1.md --summary-json '<bear-summary-json>'
trading-debate record --run-id $run.run_id --stage verdict --verdict hold --confidence medium --actor committee --content-file committee.md --summary-json '<committee-summary-json>'
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

Open `http://127.0.0.1:8765`. Compose publishes only to loopback by default. The service mounts the local `data/`
directory, so research data survives container recreation. Reports are rendered
from SQLite on demand; `export` writes Markdown only to an explicit path.
Connector credentials are not passed to the
read-only web service. To use another host port, set `WEB_PORT` before starting
the service, for example `$env:WEB_PORT = "8080"`.

Stop the service with `docker compose down`. This does not remove mounted
research data.

To delete a run, open its detail page and enter the displayed research ID to
confirm. This permanently removes its SQLite run data, evidence, and contributions.
