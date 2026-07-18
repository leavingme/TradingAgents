from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.prompts import (
    TOOL_CALLING_COLLABORATION_PROMPT,
    build_fundamentals_analyst_system_message,
)
from tradingagents.agents.utils.agent_utils import (
    get_financial_evidence,
    get_instrument_context_from_state,
)
from tradingagents.dataflows.untrusted_content import isolate_untrusted_content

FUNDAMENTALS_ANALYST_TOOLS = (get_financial_evidence,)
FUNDAMENTALS_ANALYST_TOOL_NAMES = tuple(
    tool.name for tool in FUNDAMENTALS_ANALYST_TOOLS
)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = list(FUNDAMENTALS_ANALYST_TOOLS)

        system_message = build_fundamentals_analyst_system_message()

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
            report = isolate_untrusted_content(
                "fundamentals_report", result.content
            ).content

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
