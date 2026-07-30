---
name: trading-debate-analysis
description: Four-analyst stage for the trading-debate skill. Spawns Fundamentals Analyst, Technical Analyst, News & Events Analyst, and Sentiment Analyst in parallel, each using the shared evidence pack, and persists their reports to staging.
---

# Analyst Stage

Spawn four independent subagents in parallel:

1. `Fundamentals Analyst`
2. `Technical Analyst`
3. `News & Events Analyst`
4. `Sentiment Analyst`

Each analyst receives the same JSON evidence pack. Do not provide one analyst's conclusions to another analyst during this stage.

## Common report requirements

Every analyst report must:

- Be written in Traditional Chinese.
- Cite evidence IDs for every factual claim.
- Separate facts from inference.
- Identify data gaps.
- List upside catalysts.
- List downside catalysts or risks.
- End with an initial stance.
- Avoid unsupported targets or metrics.
- State when evidence is insufficient.

### Required analyst output format

Each analyst must use the following Markdown structure:

````markdown
# <分析師角色>

## 執行摘要

## 已確認事實
- [EVID-001] ...

## 分析與推論
### 推論一
- 推論：
- 證據依據：
- 推理鏈：
- 不確定性：

## 上行催化劑
- ...

## 下行催化劑與風險
- ...

## 關鍵證據缺口
- ...

## 初始立場
- 立場：bullish / neutral / bearish
- 信心：low / medium / high
- 時間範圍：
- 主要依據：

## Machine-readable summary
```json
{
  "actor": "<analyst name>",
  "stance": "bullish|neutral|bearish",
  "confidence": "low|medium|high",
  "time_horizon": "...",
  "evidence_ids": ["EVID-001"],
  "upside_catalysts": [],
  "downside_risks": [],
  "evidence_gaps": []
}
```
````

The JSON summary must be consistent with the Markdown report.

## Fundamentals Analyst

The Fundamentals Analyst must assess, when evidence is available:

- Revenue growth
- Earnings quality
- Margins
- Cash generation
- Balance-sheet strength
- Capital allocation
- Segment or product mix
- Competitive position
- Business cyclicality
- Management guidance
- Valuation

The analyst must provide at least one traceable valuation framework or explicitly abstain from valuation.

Required valuation structure:

```markdown
## 估值框架
- 方法：
- 使用指標：
- 基準或可比資料：
- 關鍵假設：
- 隱含估值或估值區間：
- 敏感度：
- 侷限：
- 引用證據：
```

Do not produce a price target unless all required inputs are present in the evidence pack or transparently calculated from cited evidence. Every calculation must show its formula and inputs.

## Technical Analyst

The Technical Analyst must state:

- Data frequency
- First available observation
- Last available observation
- Number of observations
- Whether prices are adjusted or unadjusted
- Whether volume data is available
- Which indicators were omitted due to insufficient data

Minimum-data rules:

- 200-day moving average: at least 200 valid daily observations
- 50-day moving average: at least 50 valid daily observations
- 52-week high or low: approximately 252 valid daily observations
- RSI-14: at least 15 valid observations, with a warning when history is limited
- Volume trend analysis: valid volume series required
- Support and resistance: must be described as estimated zones, not precise guaranteed levels

If data is insufficient, abstain from the affected indicator.

Do not infer institutional accumulation, distribution, manipulation, or insider activity from price and volume alone.

## News & Events Analyst

The News & Events Analyst must:

- Distinguish event date from article publication date.
- Distinguish company-confirmed events from media reports.
- Identify whether a catalyst is completed, pending, recurring, speculative, or cancelled.
- Avoid double-counting multiple headlines about the same underlying event.
- Separate company-specific events from macro or sector events.
- State that Yahoo Finance coverage is not exhaustive.

## Sentiment Analyst

The Sentiment Analyst must label the report with this disclaimer:

> 本報告為公開新聞標題、可用情緒資料來源與聚合訊號所形成的市場情緒代理，不代表完整市場情緒、實際資金流、機構持倉或直接交易訊號。

For every sentiment signal, identify:

- Source
- Observation window
- Sample size when available
- Whether the signal is headline-based, score-based, engagement-based, or another proxy
- Known bias or coverage limitation

The Sentiment Analyst may use Yahoo Finance headlines and configured sentiment connectors, but must not present sentiment as fact.

## Persist analyst reports

Write each returned Markdown report to:

```text
data/staging/<YYYY-MM-DD>/<SYMBOL>/<actor>.md
```

Recommended stable filenames:

```text
data/staging/<YYYY-MM-DD>/<SYMBOL>/fundamentals-analyst.md
data/staging/<YYYY-MM-DD>/<SYMBOL>/technical-analyst.md
data/staging/<YYYY-MM-DD>/<SYMBOL>/news-events-analyst.md
data/staging/<YYYY-MM-DD>/<SYMBOL>/sentiment-analyst.md
```

Persist one record per analyst:

```powershell
python .\trading_debate.py record --run-id <run-id> --stage analysis --actor "Fundamentals Analyst" --content-file data/staging/<YYYY-MM-DD>/<SYMBOL>/fundamentals-analyst.md
```

Verify that each `record` command succeeds before continuing.

Recommended idempotency key:

```text
run_id + stage + actor
```

A repeated write for the same key must either replace the prior incomplete record explicitly or return a duplicate-record status without creating another logical report.

Do not silently create duplicate analyst records.
