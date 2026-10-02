from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.dependencies import get_current_user
from app.help_models import DBHelpConversation, DBHelpMessage
from app.models import DBUser
from app.schemas import (
    HelpConversationCreate,
    HelpConversationDetailResponse,
    HelpConversationResponse,
    HelpMessageCreate,
    HelpMessageResponse,
)

router = APIRouter(prefix="/help/chat", tags=["Help Chat"])


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _owned_conversation(session: AsyncSession, conversation_id: str, user_id: int) -> DBHelpConversation:
    result = await session.execute(
        select(DBHelpConversation).where(
            DBHelpConversation.public_id == conversation_id,
            DBHelpConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


@router.post("/conversations", response_model=HelpConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: HelpConversationCreate,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    now = _now()
    title = payload.title.strip() if payload.title else None
    conversation = DBHelpConversation(
        user_id=current_user.id,
        title=title or None,
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[HelpConversationResponse])
async def list_conversations(
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(DBHelpConversation)
        .where(DBHelpConversation.user_id == current_user.id)
        .order_by(DBHelpConversation.last_message_at.desc().nullslast(), DBHelpConversation.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}", response_model=HelpConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    conversation = await _owned_conversation(session, conversation_id, current_user.id)
    result = await session.execute(
        select(DBHelpMessage)
        .where(DBHelpMessage.conversation_id == conversation.id)
        .order_by(DBHelpMessage.created_at.asc(), DBHelpMessage.id.asc())
    )
    return HelpConversationDetailResponse(
        id=conversation.public_id,
        title=conversation.title,
        status=conversation.status,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=list(result.scalars().all()),
    )


@router.post("/conversations/{conversation_id}/messages", response_model=HelpMessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: str,
    payload: HelpMessageCreate,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    conversation = await _owned_conversation(session, conversation_id, current_user.id)
    if conversation.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This conversation is closed.")

    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message cannot be empty.")

    now = _now()
    message = DBHelpMessage(conversation_id=conversation.id, role="user", content=content, created_at=now)
    session.add(message)
    if not conversation.title:
        conversation.title = content[:80]
    conversation.last_message_at = now
    conversation.updated_at = now
    await session.commit()
    await session.refresh(message)
    return message


@router.post("/conversations/{conversation_id}/close", response_model=HelpConversationResponse)
async def close_conversation(
    conversation_id: str,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    conversation = await _owned_conversation(session, conversation_id, current_user.id)
    conversation.status = "closed"
    conversation.updated_at = _now()
    await session.commit()
    await session.refresh(conversation)
    return conversation
