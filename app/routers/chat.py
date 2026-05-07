from fastapi import APIRouter, Depends, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from app.auth.jwt_auth import get_current_user
from app.services.chat import stream_chat_messages
from app.utils import _get_message_history
from app.models.requests import ChatRequest
from app.core.limiter import limiter
from helpers.utils import get_logger
import uuid
import json

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


async def _as_sse(text_iter):
    """
    Wrap plain text chunks as Server-Sent Events.
    Many clients (EventSource) require the 'data:' framing.
    """
    async for chunk in text_iter:
        if chunk is None:
            continue
        data = str(chunk)
        if not data:
            continue
        # Ensure each SSE message is a single event.
        for line in data.splitlines() or [""]:
            yield f"data: {line}\n"
        yield "\n"
    yield "data: [DONE]\n\n"


@router.get("/")
@limiter.limit("1000/hour")
async def chat_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    chat_request: ChatRequest = Depends(),
    user_info: dict = Depends(get_current_user)
):
    """
    Chat endpoint that streams responses back to the client.
    Requires JWT authentication.
    """
    session_id = chat_request.session_id or str(uuid.uuid4())
    
    logger.info(
        f"Chat request received - session_id: {session_id}, user_id: {chat_request.user_id}, "
        f"authenticated_user: {user_info}, source_lang: {chat_request.source_lang}, "
        f"target_lang: {chat_request.target_lang}, query: {chat_request.query}"
    )
    
    history = await _get_message_history(session_id)
    logger.debug(f"Retrieved message history for session {session_id} - length: {len(history)}")

    return StreamingResponse(
        _as_sse(stream_chat_messages(
            query=chat_request.query,
            session_id=session_id,
            source_lang=chat_request.source_lang,
            target_lang=chat_request.target_lang,
            user_id=chat_request.user_id,
            history=history,
            user_info=user_info,
            background_tasks=background_tasks
        )),
        media_type="text/event-stream"
    )