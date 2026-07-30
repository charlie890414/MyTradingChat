# MyTradingChat

Agents-native, multi-agent equity research debates for Taiwan and US stocks. The local tool uses Yahoo Finance, Google News RSS, Bing News RSS, FinMind, TWSE OpenAPI/MOPS, Finnhub, and SEC EDGAR for evidence, SQLite for durable history, and Markdown for human-readable reports.

Open this repository with an agent workflow and ask, for example: `分析 NVDA，現在是否值得投入`.

Install the local tool once:

```powershell
python -m pip install -e .
```

The agent workflow is defined at `.agents/skills/trading-debate/`. It instructs a controller agent to coordinate analyst, bull, bear, and investment-committee subagents. Generated SQLite data and reports stay local and are ignored by Git.

Optional connectors are enabled only when their credentials exist in the environment:

```powershell
$env:FINNHUB_API_KEY = "..."
$env:FINMIND_TOKEN = "..."
```

## Local historical research UI

Start the local UI after creating research runs:

```powershell
trading-debate serve
```

Open `http://127.0.0.1:8765` to search and filter prior research, inspect its
evidence, analyst reports, debate history, and rendered Markdown report. Every
view labels stored research as historical context and shows its recorded dates.

To delete a run, open its detail page and enter the exact research ID to confirm.
This permanently removes its SQLite run data, evidence, contributions, and its
report directory when available.
