"""
Standalone verification of per-tool call capping via Tool.prepare.

Uses FunctionModel so no network / API key is needed.

Scenarios verified:
  1. Without `prepare`: model can call `search_terms` indefinitely (we observe the
     overall tool_calls_limit kicking in instead).
  2. With `prepare` capping at 3: once 3 calls happen in the run, the tool is
     omitted from subsequent steps and the model is forced to respond with text.
  3. Tool-call + tool-return parts from the capped calls remain in the final
     message history.
  4. Feeding that history back into a second run resets behaviour or not —
     we test both: naive counting (sees prior calls, tool stays hidden) vs
     per-turn counting (resets each run).
"""

import asyncio
from typing import cast

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dump_history(label: str, messages: list[ModelMessage]) -> None:
    print(f"\n----- {label} -----")
    for i, msg in enumerate(messages):
        kind = type(msg).__name__
        parts_repr = []
        for p in msg.parts:
            pname = type(p).__name__
            if isinstance(p, ToolCallPart):
                parts_repr.append(f"{pname}(name={p.tool_name!r}, args={p.args!r})")
            elif isinstance(p, ToolReturnPart):
                parts_repr.append(f"{pname}(name={p.tool_name!r}, content={p.content!r})")
            elif isinstance(p, TextPart):
                parts_repr.append(f"{pname}({p.content!r})")
            elif isinstance(p, UserPromptPart):
                parts_repr.append(f"{pname}({p.content!r})")
            elif isinstance(p, RetryPromptPart):
                parts_repr.append(f"{pname}(tool={p.tool_name!r}, content={p.content!r})")
            else:
                parts_repr.append(pname)
        print(f"  [{i}] {kind}: {parts_repr}")


# ---------------------------------------------------------------------------
# Fake model: always wants to call `search_terms` if it's available,
# otherwise emits a final text response.
# ---------------------------------------------------------------------------

def loopy_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A model that keeps calling search_terms whenever it's offered."""
    tool_names = {t.name for t in info.function_tools}
    step = sum(1 for m in messages if isinstance(m, ModelResponse))
    if "search_terms" in tool_names:
        return ModelResponse(parts=[
            ToolCallPart(tool_name="search_terms", args={"q": f"query-{step}"})
        ])
    # tool no longer available -> respond with text
    return ModelResponse(parts=[TextPart(content=f"final answer after {step} steps")])


# ---------------------------------------------------------------------------
# Configurable cap — default 5. Tweak for experiments.
# ---------------------------------------------------------------------------

MAX_SEARCH_TERMS_CALLS = 5


# ---------------------------------------------------------------------------
# Prepare functions
# ---------------------------------------------------------------------------


def make_prepare(scope: str):
    """
    scope='all_history' -> counts every ToolCallPart in ctx.messages (could leak across turns)
    scope='current_turn' -> resets after the last UserPromptPart in ctx.messages
    """
    async def prepare(ctx: RunContext, tool_def: ToolDefinition) -> ToolDefinition | None:
        msgs = ctx.messages
        if scope == "current_turn":
            # find last user prompt index
            last_user_idx = -1
            for i, m in enumerate(msgs):
                if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts):
                    last_user_idx = i
            relevant = msgs[last_user_idx:] if last_user_idx >= 0 else msgs
        else:
            relevant = msgs

        count = sum(
            1
            for m in relevant
            if isinstance(m, ModelResponse)
            for p in m.parts
            if isinstance(p, ToolCallPart) and p.tool_name == tool_def.name
        )
        print(f"    [prepare:{scope}] search_terms calls so far = {count}; "
              f"{'OMITTED' if count >= MAX_SEARCH_TERMS_CALLS else 'EXPOSED'}")
        if count >= MAX_SEARCH_TERMS_CALLS:
            return None
        return tool_def
    return prepare


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def make_agent(prepare_scope: str | None):
    agent = Agent(
        model=FunctionModel(loopy_model),
        name="loop-tester",
        retries=0,
    )

    if prepare_scope is None:
        @agent.tool_plain
        def search_terms(q: str) -> str:
            return f"results for {q!r}"
    else:
        @agent.tool_plain(prepare=make_prepare(prepare_scope))
        def search_terms(q: str) -> str:
            return f"results for {q!r}"

    return agent


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

async def scenario_no_cap():
    print("\n=== Scenario 1: NO per-tool cap (with tool_calls_limit=5 as safety net) ===")
    from pydantic_ai import UsageLimits
    agent = make_agent(prepare_scope=None)
    try:
        result = await agent.run(
            "hello",
            usage_limits=UsageLimits(tool_calls_limit=5),
        )
        print(f"Output: {result.output!r}")
    except Exception as exc:
        print(f"Raised: {type(exc).__name__}: {exc}")
        result = None
    if result:
        dump_history("scenario 1 messages", result.all_messages())


async def scenario_capped():
    print("\n=== Scenario 2: prepare cap at 3, single turn ===")
    agent = make_agent(prepare_scope="current_turn")
    result = await agent.run("hello")
    print(f"Output: {result.output!r}")
    dump_history("scenario 2 messages", result.all_messages())
    return result.all_messages()


async def scenario_second_turn_current_turn(history: list[ModelMessage]):
    print("\n=== Scenario 3a: replay history, prepare scope='current_turn' ===")
    agent = make_agent(prepare_scope="current_turn")
    result = await agent.run("hello again", message_history=history)
    print(f"Output: {result.output!r}")
    dump_history("scenario 3a messages", result.all_messages())


async def scenario_second_turn_all_history(history: list[ModelMessage]):
    print("\n=== Scenario 3b: replay history, prepare scope='all_history' (naive) ===")
    agent = make_agent(prepare_scope="all_history")
    result = await agent.run("hello again", message_history=history)
    print(f"Output: {result.output!r}")
    dump_history("scenario 3b messages", result.all_messages())


# ---------------------------------------------------------------------------
# Scenario 4: ModelRetry from inside the tool body
# ---------------------------------------------------------------------------

def adaptive_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """
    Smarter fake model:
      - If the last ModelRequest contains a RetryPromptPart for 'search_terms',
        switch to calling 'search_documents' on the next step.
      - Otherwise: call search_terms if it's available.
      - Once search_documents has been called, finalize with text.
    """
    last_msg = messages[-1] if messages else None
    saw_retry_for_search_terms = isinstance(last_msg, ModelRequest) and any(
        isinstance(p, RetryPromptPart) and p.tool_name == "search_terms"
        for p in last_msg.parts
    )

    used_search_documents = any(
        isinstance(m, ModelResponse)
        and any(isinstance(p, ToolCallPart) and p.tool_name == "search_documents" for p in m.parts)
        for m in messages
    )

    if used_search_documents:
        return ModelResponse(parts=[TextPart(content="answered using docs")])

    if saw_retry_for_search_terms:
        return ModelResponse(parts=[
            ToolCallPart(tool_name="search_documents", args={"q": "follow-up"})
        ])

    step = sum(1 for m in messages if isinstance(m, ModelResponse))
    return ModelResponse(parts=[
        ToolCallPart(tool_name="search_terms", args={"q": f"query-{step}"})
    ])


def count_calls_in_turn(messages: list[ModelMessage], tool_name: str) -> int:
    last_user_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts):
            last_user_idx = i
    relevant = messages[last_user_idx:] if last_user_idx >= 0 else messages
    return sum(
        1
        for m in relevant
        if isinstance(m, ModelResponse)
        for p in m.parts
        if isinstance(p, ToolCallPart) and p.tool_name == tool_name
    )


def make_adaptive_agent():
    agent = Agent(
        model=FunctionModel(adaptive_model),
        name="adaptive",
        retries=3,
    )

    @agent.tool
    def search_terms(ctx: RunContext, q: str) -> str:
        prior = count_calls_in_turn(ctx.messages, "search_terms")
        print(f"    [tool:search_terms] prior calls this turn = {prior - 1} (this is call #{prior})")
        if prior > MAX_SEARCH_TERMS_CALLS:
            raise ModelRetry(
                f"You have called `search_terms` {MAX_SEARCH_TERMS_CALLS} times in this turn — "
                f"the maximum allowed. Do NOT call `search_terms` again. "
                f"If you still need information, use `search_documents` or another "
                f"tool, or proceed to the next step of your reasoning."
            )
        return f"results for {q!r}"

    @agent.tool_plain
    def search_documents(q: str) -> str:
        return f"docs for {q!r}"

    return agent


async def scenario_modelretry():
    print("\n=== Scenario 4: ModelRetry from inside tool body, model can pivot ===")
    agent = make_adaptive_agent()
    result = await agent.run("hello")
    print(f"Output: {result.output!r}")
    dump_history("scenario 4 messages", result.all_messages())


async def main():
    await scenario_no_cap()
    history = await scenario_capped()
    await scenario_second_turn_current_turn(history)
    await scenario_second_turn_all_history(history)
    await scenario_modelretry()


if __name__ == "__main__":
    asyncio.run(main())
