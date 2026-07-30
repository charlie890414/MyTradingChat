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
