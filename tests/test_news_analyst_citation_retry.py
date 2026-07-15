from langchain_core.messages import AIMessage
import pytest

from tradingagents.agents.analysts.news_analyst import _validate_final_report_with_retry


EVIDENCE = "### [news_12345678] Verified item\n- Published: 2026-07-10"


class FakeChain:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.response


@pytest.mark.unit
def test_unknown_news_citation_is_returned_to_llm_for_one_correction():
    first = AIMessage(content="Claim [news_deadbeef]")
    corrected = AIMessage(content="Claim [news_12345678]")
    chain = FakeChain(corrected)

    result, report = _validate_final_report_with_retry(chain, [], first, [EVIDENCE])

    assert result is corrected
    assert report == corrected.content
    assert len(chain.calls) == 1
    assert "news_deadbeef" in chain.calls[0][-1].content
    assert "copied exactly" in chain.calls[0][-1].content


@pytest.mark.unit
def test_invalid_news_citation_after_retry_remains_a_hard_failure():
    first = AIMessage(content="Claim [news_deadbeef]")
    chain = FakeChain(AIMessage(content="Claim [news_cafebabe]"))

    with pytest.raises(ValueError, match="unknown source_id"):
        _validate_final_report_with_retry(chain, [], first, [EVIDENCE])

    assert len(chain.calls) == 1


@pytest.mark.unit
def test_uncited_material_paragraph_after_retry_is_removed_fail_closed():
    first = AIMessage(content="NVIDIA announced a launch.")
    corrected = AIMessage(content=(
        "Supported context [news_12345678].\n\n"
        "NVIDIA announced revenue growth without a citation."
    ))
    chain = FakeChain(corrected)

    result, report = _validate_final_report_with_retry(chain, [], first, [EVIDENCE])

    assert "Supported context" in report
    assert "announced revenue" not in report
    assert result.content == report
