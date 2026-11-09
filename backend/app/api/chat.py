"""Chat with the AI assistant (Claude when configured), with stored history."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..models.conversation import ChatMessage
from ..models.user import User
from ..providers import get_provider
from ..security.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "You are the owner's private personal assistant inside their LifeOS dashboard. "
    "Be concise, friendly and helpful. Reply in the same language the user writes "
    "in (often Uzbek). Help with productivity, planning and their GitHub activity. "
    "If you don't know something, say so."
)
_HISTORY_FOR_CONTEXT = 12


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatReply(BaseModel):
    reply: str
    ai_available: bool


class ChatMsg(BaseModel):
    id: int
    role: str
    content: str
    ai_generated: bool
    ts: dt.datetime


@router.get("/history", response_model=list[ChatMsg])
def history(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[ChatMessage]:
    rows = db.query(ChatMessage).order_by(ChatMessage.ts.desc()).limit(limit).all()
    return list(reversed(rows))


@router.post("", response_model=ChatReply)
def send(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> ChatReply:
    provider = get_provider()

    # Build context from recent history (oldest first), then store the new message.
    recent = (
        db.query(ChatMessage).order_by(ChatMessage.ts.desc()).limit(_HISTORY_FOR_CONTEXT).all()
    )
    history_ctx = [
        {"role": m.role, "content": m.content} for m in reversed(recent)
    ]
    db.add(ChatMessage(role="user", content=body.message, ai_generated=False))
    db.commit()

    reply = provider.chat(body.message, system=SYSTEM_PROMPT, history=history_ctx)

    db.add(ChatMessage(role="assistant", content=reply, ai_generated=provider.ai_available))
    db.commit()
    record_audit(db, action="chat.message", category="chat")
    return ChatReply(reply=reply, ai_available=provider.ai_available)


@router.delete("/history", response_model=dict)
def clear_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
) -> dict:
    deleted = db.query(ChatMessage).delete()
    db.commit()
    record_audit(db, action="chat.history.cleared", category="chat", detail={"deleted": deleted})
    return {"deleted": deleted}
