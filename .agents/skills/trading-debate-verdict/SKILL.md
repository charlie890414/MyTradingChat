---
name: trading-debate-verdict
description: Investment Committee and final report stage for the trading-debate skill. Aggregates analyst and debate outputs, produces a buy/hold/reduce research rating, renders the final report, and returns a compact chat summary.
---

# Verdict Stage

## Run ownership

You are a subagent. You do not own the research run.

- Use only the run-id provided in the shared evidence pack for every `record` command.
- Never invoke `init`, `fetch`, or `render`.
- If the run-id is missing, or `context --run-id <id>` fails, stop and report to the orchestrator instead of creating a new run.

## Investment Committee

After the requested debate rounds, spawn one `Investment Committee` subagent. Provide:

- Shared evidence pack
- Four analyst reports
- Every debate turn
- Compact debate state
- Evidence quality framework
- Known connector and evidence gaps

The Investment Committee must resolve conflicts by evidence quality, not majority vote. It must not simply count bullish and bearish agents.

## Research rating definitions

The Committee may issue only one of the following research ratings:

- `buy`: Under the stated assumptions and time horizon, the evidence supports an attractive risk-adjusted upside case.
- `hold`: Upside and downside are approximately balanced, or the available evidence is insufficient to justify increasing or reducing exposure.
- `reduce`: Under the stated assumptions and time horizon, downside, valuation risk, or thesis deterioration outweighs expected upside.

These are research classifications only. They are not instructions to buy, hold, sell, reduce, short, hedge, size, or execute a position.

## Required Investment Committee output

````markdown
# 投資委員會裁決

## 裁決摘要
- 研究評級：buy / hold / reduce
- 信心：low / medium / high
- 時間範圍：
- 證據抓取時間：
- 一句話結論：

## 核心判斷
- ...

## 關鍵多方論點
- ...

## 關鍵空方論點
- ...

## 爭議裁決
### 爭議一
- 多方主張：
- 空方主張：
- 採信結論：
- 證據品質比較：
- 主要證據：
- 仍未解決之處：

## 估值與價格假設
- 估值方法：
- 關鍵假設：
- 合理範圍：
- 計算方式：
- 敏感度：
- 不適用或無法估值的原因：

## 上行催化劑
- ...

## 下行催化劑與風險
- ...

## 論點失效條件
- ...

## 後續應驗證事項
- ...

## 主要證據缺口
- ...

## 研究聲明
本裁決僅為研究輸出，不構成投資建議、交易建議、個人化財務建議或下單指示。

## Machine-readable summary
```json
{
  "recommendation": "buy|hold|reduce",
  "confidence": "low|medium|high",
  "time_horizon": "...",
  "fetch_time": "...",
  "valuation_method": "...",
  "valuation_assumptions": [],
  "upside_catalysts": [],
  "downside_risks": [],
  "invalidation_conditions": [],
  "evidence_gaps": [],
  "critical_evidence_ids": []
}
```
````

The Committee must explicitly explain:

- Why conflicting claims were accepted or rejected.
- Which evidence was most authoritative.
- Which conclusions remain uncertain.
- What future evidence would change the rating.

## Persist verdict

```powershell
python -m trading_debate.cli record --run-id <run-id> --stage verdict --actor "Investment Committee" --verdict <buy|hold|reduce> --confidence <low|medium|high> --content-file data/staging/<YYYY-MM-DD>/<SYMBOL>/investment-committee.md
```

`--verdict` and `--confidence` are required for the verdict stage. The CLI uses these values to write the rating into the runs table. If omitted, `render` will mark the run as `incomplete` because the rating is absent.

After successful validation, verify the render status is `completed`:

```powershell
python -m trading_debate.cli render --run-id <run-id>
```

The rendered report must preserve:

- Evidence metadata
- Evidence fetch time
- Connector status and gaps
- All analyst reports
- Every Bull Researcher turn
- Every Bear Researcher turn
- Compact debate-state evolution when available
- Investment Committee verdict
- Validation status
- Research disclaimer

Do not conceal disagreement or delete losing arguments from the final report.
