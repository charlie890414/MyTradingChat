# MyTradingChat

Agents-native, multi-agent equity research debates for Taiwan and US stocks. The local tool uses Yahoo Finance, Google News RSS, Bing News RSS, FinMind, TWSE OpenAPI/MOPS, Finnhub, and SEC EDGAR for evidence, SQLite for durable history, and Markdown for human-readable reports.

Open this repository with an agent workflow and ask, for example: `分析 NVDA的多空觀點，並提供買入/持有/減碼的投資建議與目標價格`.

Install the local tool once:

```shell
python -m pip install -e .
```

The agent workflow is defined at `.agents/skills/trading-debate/`. It instructs a controller agent to coordinate analyst, bull, bear, and investment-committee subagents. Generated SQLite data and reports stay local and are ignored by Git.

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

Use canonical roles when persisting work. Display names such as
`"Fundamentals Analyst"`, `"Bull Researcher"`, and `"Investment Committee"`
are accepted for compatibility, but are stored as canonical roles.

```shell
trading-debate record --run-id $run.run_id --stage analysis --actor fundamentals --content-file fundamentals.md
trading-debate record --run-id $run.run_id --stage analysis --actor technical --content-file technical.md
trading-debate record --run-id $run.run_id --stage analysis --actor news --content-file news.md
trading-debate record --run-id $run.run_id --stage analysis --actor sentiment --content-file sentiment.md
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bull --content-file bull-round-1.md
trading-debate record --run-id $run.run_id --stage debate --round 1 --actor bear --content-file bear-round-1.md
trading-debate record --run-id $run.run_id --stage verdict --actor committee --verdict hold --confidence medium --content-file committee.md
trading-debate render --run-id $run.run_id
trading-debate search --query NVDA
```

`context` requires a role and returns a role-specific view of the same persisted
evidence. Analyst roles are `fundamentals`, `technical`, `news`, and `sentiment`;
later stages use `debate` and `committee`. The technical view samples the most
recent 30 daily, 26 weekly, and 12 monthly OHLCV bars while preserving the full
history in SQLite.

Each role and debate turn has one logical record. Re-sending identical content
returns a `duplicate` status without adding a row. To change an existing record,
pass `--replace`; replacement is refused once a downstream debate, verdict, or
rendered report depends on it. A committee that cannot rate the evidence must
explicitly use `--abstain` instead of omitting verdict arguments.

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

Open `http://127.0.0.1:8765`. The Compose service mounts the local `data/` and
`reports/` directories, so existing research remains available and new runtime
data survives container recreation. Connector credentials are not passed to the
read-only web service. To use another host port, set `WEB_PORT` before starting
the service, for example `$env:WEB_PORT = "8080"`.

Stop the service with `docker compose down`. This does not remove the mounted
research data or reports.

To delete a run, open its detail page and enter the exact research ID to confirm.
This permanently removes its SQLite run data, evidence, contributions, and its
report directory when available.
