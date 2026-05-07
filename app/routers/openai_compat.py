from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from app.auth.jwt_auth import get_current_user
from app.services.chat import stream_chat_messages
from app.utils import _get_message_history
from helpers.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["openai-compat"])


class OAChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class OAChatCompletionsRequest(BaseModel):
    model: str
    messages: List[OAChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    body: OAChatCompletionsRequest,
    user_info: dict = Depends(get_current_user),
):
    """
    OpenAI-compatible Chat Completions endpoint.

    Minimal implementation for non-streaming requests:
    - reads the last user message from `messages`
    - runs the existing agent streaming generator and concatenates output
    - returns an OpenAI-style JSON response
    """
    # Minimal support for the curl you shared (non-streaming).
    # If stream=true is needed later, we can emit OpenAI SSE "chat.completion.chunk".
    user_messages = [m.content for m in body.messages if m.role == "user" and m.content]
    query = user_messages[-1] if user_messages else ""

    session_id = str(uuid.uuid4())
    history = await _get_message_history(session_id)

    started = time.time()
    out_chunks: List[str] = []
    async for chunk in stream_chat_messages(
        query=query,
        session_id=session_id,
        source_lang="en",
        target_lang="en",
        user_id=str(user_info.get("sub") or user_info.get("user_id") or "anonymous"),
        history=history,
        user_info=user_info,
        background_tasks=background_tasks,
    ):
        out_chunks.append(chunk)

    content = "".join(out_chunks).strip()
    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(f"OpenAI compat completion finished in {elapsed_ms}ms")

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            # We don't have accurate token usage here from the current agent surface.
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }

