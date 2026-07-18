from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tradingagents.runtime.stats_handler import StatsCallbackHandler


def _response(tokens_in: int, tokens_out: int) -> LLMResult:
    return LLMResult(generations=[[
        ChatGeneration(message=AIMessage(
            content="done",
            usage_metadata={
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        ))
    ]])


def test_stats_handler_attributes_llm_tokens_and_tools_to_langgraph_agent():
    handler = StatsCallbackHandler()
    market_run = uuid4()
    news_run = uuid4()
    handler.on_chat_model_start(
        {}, [[]], run_id=market_run,
        metadata={"langgraph_node": "Market Analyst"},
    )
    handler.on_chat_model_start(
        {}, [[]], run_id=news_run,
        metadata={"langgraph_node": "News Analyst"},
    )
    # End out of order to prove run_id, rather than callback order, owns tokens.
    handler.on_llm_end(_response(200, 20), run_id=news_run)
    handler.on_llm_end(_response(100, 10), run_id=market_run)
    handler.on_tool_start(
        {}, "NVDA", metadata={"langgraph_node": "News Analyst"}
    )

    assert handler.get_stats() == {
        "llm_calls": 2,
        "tool_calls": 1,
        "tokens_in": 300,
        "tokens_out": 30,
        "by_agent": {
            "Market Analyst": {
                "llm_calls": 1, "tool_calls": 0,
                "tokens_in": 100, "tokens_out": 10,
            },
            "News Analyst": {
                "llm_calls": 1, "tool_calls": 1,
                "tokens_in": 200, "tokens_out": 20,
            },
        },
    }


def test_stats_handler_maps_unknown_metadata_to_bounded_unattributed_bucket():
    handler = StatsCallbackHandler()
    run_id = uuid4()
    handler.on_llm_start(
        {}, ["prompt"], run_id=run_id,
        metadata={"langgraph_node": "attacker-controlled-name"},
    )
    handler.on_llm_end(_response(5, 2), run_id=run_id)
    handler.on_tool_start({}, "input", metadata={"langgraph_node": 42})
    assert handler.get_stats()["by_agent"] == {
        "Unattributed": {
            "llm_calls": 1,
            "tool_calls": 1,
            "tokens_in": 5,
            "tokens_out": 2,
        }
    }


def test_stats_handler_tolerates_unhashable_node_and_malformed_usage():
    handler = StatsCallbackHandler()
    run_id = uuid4()
    handler.on_chat_model_start(
        {}, [[]], run_id=run_id,
        metadata={"langgraph_node": ["not", "hashable"]},
    )
    response = _response(0, 0)
    response.generations[0][0].message.usage_metadata["input_tokens"] = "invalid"
    response.generations[0][0].message.usage_metadata["output_tokens"] = -5

    handler.on_llm_end(response, run_id=run_id)

    assert handler.get_stats()["by_agent"]["Unattributed"] == {
        "llm_calls": 1,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def test_stats_handler_omits_empty_by_agent_for_backward_compatibility():
    assert StatsCallbackHandler().get_stats() == {
        "llm_calls": 0,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def test_stats_handler_cleans_run_mapping_when_usage_is_missing():
    handler = StatsCallbackHandler()
    run_id = uuid4()
    handler.on_chat_model_start(
        {}, [[]], run_id=run_id,
        metadata={"langgraph_node": "Market Analyst"},
    )
    response = LLMResult(generations=[[
        ChatGeneration(message=AIMessage(content="done"))
    ]])

    handler.on_llm_end(response, run_id=run_id)

    assert run_id not in handler._llm_agents
    assert handler.get_stats()["by_agent"]["Market Analyst"] == {
        "llm_calls": 1,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }
