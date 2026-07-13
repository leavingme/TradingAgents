from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.prompts import (
    TOOL_CALLING_COLLABORATION_PROMPT,
    build_market_analyst_system_message,
)
from tradingagents.agents.utils.agent_utils import (
    get_indicators,
    get_instrument_context_from_state,
    get_stock_data,
    get_verified_market_snapshot,
)
from tradingagents.dataflows.untrusted_content import isolate_untrusted_content


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_stock_data,
            get_indicators,
            get_verified_market_snapshot,
        ]

        system_message = build_market_analyst_system_message()

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
                "market_report", result.content
            ).content

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
