"""Langfuse SDK helpers aligned with OpenTelemetry-based client (langfuse ≥3.x)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional

from pydantic_core import to_jsonable_python

from helpers import langfuse_helper  # noqa: F401 — initializes Langfuse env before get_client()
from langfuse import get_client


def build_agent_run_result_payload(
    *,
    output: str,
    message_history: list,
    usage: Any | None = None,
    new_message_index: int = 0,
) -> dict[str, Any]:
    """AgentRunResult-shaped dict for Langfuse agent.vistaar output (matches Pydantic AI serialization)."""
    state: dict[str, Any] = {
        "message_history": to_jsonable_python(message_history),
        "retries": 0,
    }
    if usage is not None:
        state["usage"] = asdict(usage) if is_dataclass(usage) else to_jsonable_python(usage)
    else:
        state["usage"] = {}

    return {
        "output": output,
        "_output_tool_name": None,
        "_state": state,
        "_new_message_index": new_message_index,
        "_traceparent_value": None,
    }


def lf_set_trace_io(*, input: Any = None, output: Any = None) -> None:
    """Trace-level input/output for the Langfuse trace detail view."""
    client = get_client()
    client.update_current_trace(input=input, output=output)

def lf_update_current_observation(
    *,
    input: Any = None,
    output: Any = None,
    metadata: Optional[Mapping[str, Any]] = None,
    model: Optional[str] = None,
    request_tokens: Optional[int] = None,
    response_tokens: Optional[int] = None,
) -> None:
    """Update the active observation. Uses generation updates when model/usage are set so Langfuse can aggregate tokens and cost."""
    meta: dict[str, Any] = dict(metadata) if metadata else {}
    if model is not None:
        meta["model"] = model

    has_usage = request_tokens is not None or response_tokens is not None
    usage_details: Optional[dict[str, int]] = None
    if has_usage:
        pt = int(request_tokens or 0)
        ct = int(response_tokens or 0)
        usage_details = {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        }

    client = get_client()
    if model is not None or usage_details is not None:
        client.update_current_generation(
            input=input,
            output=output,
            metadata=meta or None,
            model=model,
            usage_details=usage_details,
        )
    else:
        client.update_current_span(
            input=input,
            output=output,
            metadata=meta or None,
        )