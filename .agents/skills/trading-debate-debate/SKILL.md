---

name: trading-debate-debate
description: Bull vs Bear multi-round debate stage for the trading-debate skill. Spawns Bull Researcher and Bear Researcher, manages turn order, direct rebuttal rules, thesis updates, conviction changes, and persists each turn.
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Debate Stage

After all available analyst reports are persisted, spawn two subagents:

- `Bull Researcher`
- `Bear Researcher`

Give both researchers:

- The shared evidence pack
- All analyst reports
- The current compact debate state
- Prior debate turns required for direct rebuttal

All debate turns must be written in Traditional Chinese.

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

```markdown
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
```

## Debate order

For each requested round:

1. Bull Researcher responds.
2. Bear Researcher receives the Bull turn and responds.
3. The parent agent updates the compact debate state.
4. Persist both turns.

### Persist debate turns

```powershell
python .\trading_debate.py record --run-id <run-id> --stage debate --actor "Bull Researcher" --round 1 --content-file .\data\staging\bull-round-1.md

python .\trading_debate.py record --run-id <run-id> --stage debate --actor "Bear Researcher" --round 1 --content-file .\data\staging\bear-round-1.md
```

Recommended idempotency key:

```text
run_id + stage + actor + round
```

Never silently omit a debate turn.

## Compact debate state

To control context growth, maintain a compact state after each round:

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

Persist full debate turns in the database and final report. Use the compact state for later rounds, while including enough prior text to support direct rebuttal. Do not replace the preserved full debate history with summaries.