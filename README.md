# MyTradingChat

Codex-native, multi-agent equity research debates for Taiwan and US stocks. The local tool uses Yahoo Finance, Alpha Vantage, FinMind, TWSE OpenAPI/MOPS, Finnhub, and Reddit for evidence, SQLite for durable history, and Markdown for human-readable reports.

Open this repository in Codex and ask, for example: `分析 NVDA，牛熊各辯三回合`.

Install the local tool once:

```powershell
python -m pip install -e .
```

The Codex skill is at `.agents/skills/trading-debate/`. It instructs Codex to coordinate analyst, bull, bear, and investment-committee subagents. Generated SQLite data and reports stay local and are ignored by Git.

Optional connectors are enabled only when their credentials exist in the environment:

```powershell
$env:ALPHA_VANTAGE_API_KEY = "..."
$env:FINNHUB_API_KEY = "..."
$env:FINMIND_TOKEN = "..." 
```

