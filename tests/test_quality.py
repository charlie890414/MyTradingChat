from __future__ import annotations

import pytest

from trading_debate.quality import validate_contribution_content


def test_analysis_requires_cited_confirmed_facts():
    content = """# 基本面分析師

## 執行摘要
摘要。
## 已確認事實
- 未引用的事實。
## 分析與推論
推論。
## 上行催化劑
- 催化劑。
## 下行催化劑與風險
- 風險。
## 關鍵證據缺口
- 缺口。
## 初始立場
- neutral。
"""

    with pytest.raises(ValueError, match="confirmed facts"):
        validate_contribution_content("analysis", "fundamentals", content, {})


def test_debate_rejects_context_as_evidence_reference():
    content = """# 多方研究員

## 直接反駁
- 證據：依 context evidence。
## 更新後論點
- 核心論點：維持。
## 本輪結論
- 立場：bullish。
"""

    with pytest.raises(ValueError, match="specific evidence IDs"):
        validate_contribution_content("debate", "bull", content, {})


def test_summary_ids_must_be_cited_in_structured_report():
    content = """# 基本面分析師

## 執行摘要
摘要。
## 已確認事實
- [EVID-0001] 已確認事實。
## 分析與推論
推論。
## 上行催化劑
- 催化劑。
## 下行催化劑與風險
- 風險。
## 關鍵證據缺口
- 缺口。
## 初始立場
- neutral。
"""

    with pytest.raises(ValueError, match="EVID-0002"):
        validate_contribution_content(
            "analysis",
            "fundamentals",
            content,
            {"evidence_ids": ["EVID-0001", "EVID-0002"]},
        )
