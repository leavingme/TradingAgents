"""The market analyst is bound (and prompt-instructed) to call
get_verified_market_snapshot; if the executor ToolNode doesn't register it, the
call fails and the model reports the tool "unavailable" and skips verification.

Regression guard for that wiring gap (snapshot bound to the LLM but missing from
the market ToolNode).
"""
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.graph.tool_error_handling import recover_invalid_tool_arguments


def _invoke_tool_node(node, messages):
    workflow = StateGraph(MessagesState)
    workflow.add_node("tools", node)
    workflow.add_edge(START, "tools")
    workflow.add_edge("tools", END)
    return workflow.compile().invoke({"messages": messages})


@pytest.mark.unit
def test_market_toolnode_can_execute_verified_snapshot():
    # _create_tool_nodes does not use self -> call unbound (avoids building LLMs).
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    market_tools = set(nodes["market"].tools_by_name)
    assert "get_verified_market_snapshot" in market_tools, (
        "get_verified_market_snapshot is bound to the market analyst but not "
        "registered in the market ToolNode, so the model's call fails."
    )
    # the other core market tools must remain too
    assert {"get_stock_data", "get_indicators"} <= market_tools


@pytest.mark.unit
def test_data_tool_nodes_only_wrap_model_argument_errors():
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    assert all(node._handle_tool_errors is False for node in nodes.values())
    assert all(node._wrap_tool_call is not None for node in nodes.values())


@pytest.mark.unit
def test_invalid_tool_arguments_are_returned_for_one_correction_round():
    node = TradingAgentsGraph._create_tool_nodes(None)["market"]
    invalid_call = {
        "name": "get_indicators",
        "args": {"symbol": ""},
        "id": "bad-1",
        "type": "tool_call",
    }

    result = _invoke_tool_node(
        node, [AIMessage(content="", tool_calls=[invalid_call])]
    )

    message = result["messages"][-1]
    assert isinstance(message, ToolMessage)
    assert message.status == "error"
    assert "[tool-argument-correction]" in message.content
    assert "indicator: Field required" in message.content
    assert "curr_date: Field required" in message.content


@pytest.mark.unit
def test_repeated_invalid_tool_arguments_fail_instead_of_looping():
    node = TradingAgentsGraph._create_tool_nodes(None)["market"]
    first_call = {
        "name": "get_indicators",
        "args": {"symbol": ""},
        "id": "bad-1",
        "type": "tool_call",
    }
    first_ai_message = AIMessage(content="", tool_calls=[first_call])
    first = _invoke_tool_node(node, [first_ai_message])
    retry_call = {**first_call, "id": "bad-2"}
    retry_messages = [
        first_ai_message,
        first["messages"][-1],
        AIMessage(content="", tool_calls=[retry_call]),
    ]

    with pytest.raises(ToolInvocationError):
        _invoke_tool_node(node, retry_messages)


@pytest.mark.unit
def test_tool_execution_errors_still_propagate():
    @tool
    def failing_tool(value: str) -> str:
        """Always fail after argument validation succeeds."""
        raise RuntimeError(f"vendor failed for {value}")

    node = ToolNode(
        [failing_tool],
        handle_tool_errors=False,
        wrap_tool_call=recover_invalid_tool_arguments,
    )
    call = {
        "name": "failing_tool",
        "args": {"value": "NVDA"},
        "id": "runtime-1",
        "type": "tool_call",
    }

    with pytest.raises(RuntimeError, match="vendor failed for NVDA"):
        _invoke_tool_node(node, [AIMessage(content="", tool_calls=[call])])
