from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage

from tradingagents.agents.analysts.prompts import (
    TOOL_CALLING_COLLABORATION_PROMPT,
    build_news_analyst_system_message,
)
from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)
from tradingagents.dataflows.evidence_models import (
    remove_uncited_material_claims,
    validate_report_citations,
)
from tradingagents.dataflows.untrusted_content import isolate_untrusted_content


def _validate_final_report_with_retry(chain, messages, result, evidence_texts):
    """Give one deterministic citation error back to the LLM for correction."""
    try:
        return result, validate_report_citations(str(result.content), evidence_texts)
    except ValueError as exc:
        correction = HumanMessage(content=(
            "Your news report was rejected by deterministic citation validation: "
            f"{exc}. Rewrite the report once. Cite only source_id values copied "
            "exactly from the validated tool evidence already present in this "
            "conversation; do not invent, alter, or omit required citations."
        ))
        retried = chain.invoke([*messages, result, correction])
        if retried.tool_calls:
            return retried, ""
        try:
            report = validate_report_citations(str(retried.content), evidence_texts)
        except ValueError as retry_exc:
            if str(retry_exc) != "decision-material news claim is missing a source_id citation":
                raise
            report = remove_uncited_material_claims(str(retried.content))
            report = validate_report_citations(report, evidence_texts)
            retried = retried.model_copy(update={"content": report})
        return retried, report


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
            get_macro_indicators,
            get_prediction_markets,
        ]

        system_message = build_news_analyst_system_message(asset_label)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    TOOL_CALLING_COLLABORATION_PROMPT,
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            evidence_texts = [
                getattr(message, "content", "")
                for message in state["messages"]
                if getattr(message, "type", "") == "tool"
            ]
            result, report = _validate_final_report_with_retry(
                chain, state["messages"], result, evidence_texts
            )
            report = isolate_untrusted_content("news_report", report).content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
