---
name: trading-debate
description: Run an evidence-grounded, persistent multi-agent equity research debate in Codex. Use for requests to analyse a Taiwan- or US-listed stock, debate a bull and bear case, challenge an investment thesis, retrieve a past research report, or produce a buy/hold/reduce research recommendation without placing trades.
---

# Trading Debate

Use Codex subagents for reasoning; use `trading_debate.py` for evidence, persistence, and reports. Do not make any trade or connect a brokerage.

## Research workflow

1. Start a run and fetch a single shared evidence pack.

   ```powershell
   python .\trading_debate.py init --symbol NVDA --question "分析 NVDA" --rounds 3
   python .\trading_debate.py fetch --run-id <run-id>
   python .\trading_debate.py context --run-id <run-id>
   ```

   Give every subagent the same JSON context. Treat it as the source of record. State data gaps instead of inventing facts. Yahoo Finance News is public-news coverage, not an exhaustive news wire; use it for the news and sentiment proxy only.

2. Spawn four independent Codex subagents in parallel: `Fundamentals Analyst`, `Technical Analyst`, `News & Events Analyst`, and `Sentiment Analyst`. Require each to cite evidence-item titles, separate facts from inference, list upside/downside catalysts, and end with an initial stance. The Sentiment Analyst must label its output as a proxy based on public Yahoo Finance headlines.

3. Persist the returned reports through the parent agent, one record per analyst.

   Write returned Markdown to `data/staging/<actor>.md` first; that directory is local and ignored by Git.

   ```powershell
   python .\trading_debate.py record --run-id <run-id> --stage analysis --actor "Fundamentals Analyst" --content-file <markdown-file>
   ```

4. Spawn a `Bull Researcher` and `Bear Researcher`. Give them the evidence and all analyst reports. Run the requested number of rounds. Each turn must directly rebut a named opposing claim, point to evidence or explicitly identify missing evidence, and update its thesis. Persist every turn with `--stage debate --round <n>`.

5. Spawn an `Investment Committee` subagent. It must resolve conflicts by evidence quality, not majority vote. Require: recommendation (`buy`, `hold`, or `reduce`), confidence (`low`, `medium`, or `high`), time horizon, valuation/price assumptions, catalysts, invalidation conditions, and evidence gaps. It must clearly say this is research, not investment advice. Persist it as `verdict`.

6. Generate and return only a compact chat response plus the report path.

   ```powershell
   python .\trading_debate.py render --run-id <run-id>
   ```

## Past research

Search SQLite before rerunning work when the user asks for history or follow-up context.

```powershell
python .\trading_debate.py search --query "NVDA"
```

Use a prior report as context only after telling the user its creation time. Refresh evidence for a new current-market recommendation.

## Quality gates

- Do not claim real-time data; cite the evidence pack's fetch time.
- Do not conceal disagreement. Preserve analyst reports and every debate turn in the report.
- Do not manufacture citations, targets, financial metrics, or price levels.
- Recommendations are research outputs only; do not produce execution instructions.
