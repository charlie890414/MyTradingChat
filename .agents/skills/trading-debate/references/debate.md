# Debate Stage

## Contents

- [Subagent run ownership](#subagent-run-ownership)
- [Debate rules](#debate-rules)
- [Debate order](#debate-order)
- [Compact debate state](#compact-debate-state)

After all available analyst reports are persisted, spawn two subagents:

- `Bull Researcher`
- `Bear Researcher`

Before each turn, run `context --run-id <run-id> --role debate`. Give the expected researcher:

- Analyst and completed-debate machine summaries
- Original payloads for evidence IDs referenced by those summaries
- The immediately preceding opposing turn required for direct rebuttal
- The compact state carried in completed debate summaries

All debate turns must be written in Traditional Chinese.

## Subagent run ownership

When applying these rules as a subagent, do not assume ownership of the research run.

- Use only the run-id provided in the role context for every `record` command.
- Never invoke `init`, `fetch`, or `render`.
- If the run-id is missing, or `context --run-id <id> --role debate` fails, stop and report to the orchestrator instead of creating a new run.

## Debate rules

Each turn must:

1. Name at least one opposing claim.
2. Quote or precisely paraphrase that claim.
3. Cite evidence IDs supporting the rebuttal.
4. Identify missing evidence when no decisive evidence exists.
5. Separate fact from inference.
6. Update the researcher's thesis.
7. State whether conviction increased, decreased, or remained unchanged.
8. Preserve unresolved disagreement.
9. Avoid repeating the same argument without new evidence or reasoning.

### Direct rebuttal format

A valid rebuttal contains:

````markdown
## 直接反駁
- 對方主張：
- 回應：
- 證據：
- 證據品質：
- 尚缺資料：

## 更新後論點
- 核心論點：
- 相較上一輪的變化：
- 信心變化：增加 / 不變 / 降低

## 本輪結論
- 立場：
- 信心：
- 最關鍵證據：
- 最大弱點：

The separate `--summary-json` payload must contain:
```json
{
  "actor": "bull|bear",
  "round": 1,
  "stance": "bullish|bearish",
  "confidence": "low|medium|high",
  "opposing_claims": [],
  "updated_claims": [],
  "accepted_claims": [],
  "disputed_claims": [],
  "resolved_claims": [],
  "rejected_claims": [],
  "open_questions": [],
  "unresolved_disagreements": [],
  "bull_thesis": "",
  "bear_thesis": "",
  "bull_confidence": "low|medium|high",
  "bear_confidence": "low|medium|high",
  "evidence_ids": [],
  "critical_evidence_ids": []
}
```
````

The JSON summary is required for every turn and must agree with the Markdown. Later turns and the Committee consume it as the compact debate state. Include all evidence IDs needed to verify its claims. Do not append it to the Markdown report.

`record` rejects a structured turn without the three required headings, a direct
rebuttal without a concrete `[EVID-xxxx]` citation, or a placeholder such as
"依 context evidence" in place of a source reference.

## Debate order

For each requested round:

1. Bull Researcher responds.
2. Bear Researcher receives the Bull turn and responds.
3. The researcher updates the compact state in the machine-readable summary.
4. Persist both turns.

### Persist debate turns

```shell
uv run python -m trading_debate.cli record --run-id <run-id> --stage debate --actor bull --round <N> --content-stdin --summary-json '<bull-summary-json>'

uv run python -m trading_debate.cli record --run-id <run-id> --stage debate --actor bear --round <N> --content-stdin --summary-json '<bear-summary-json>'
```

Recommended idempotency key:

```text
run_id + stage + actor + round
```

Never silently omit a debate turn.

## Compact debate state

To control context growth, carry the following fields in each machine-readable debate summary:

```json
{
  "accepted_claims": [],
  "disputed_claims": [],
  "resolved_claims": [],
  "rejected_claims": [],
  "open_questions": [],
  "bull_thesis": "",
  "bear_thesis": "",
  "bull_confidence": "low|medium|high",
  "bear_confidence": "low|medium|high",
  "critical_evidence_ids": []
}
```

Persist full debate turns in the database and final report. Later rounds receive all completed summaries and only the immediately preceding opposing turn in full. Do not replace the preserved database or rendered history with summaries.
