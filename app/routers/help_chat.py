from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.help.ai import FALLBACK_NO_CONTEXT, HelpAIError, generate_help_response
from app.help.retrieval import format_help_context, search_help
from app.help_models import DBHelpConversation, DBHelpMessage
from app.models import DBUser
from app.schemas import (
    HelpChatResponse,
    HelpConversationCreate,
    HelpConversationDetailResponse,
    HelpConversationResponse,
    HelpMessageCreate,
    HelpSourceResponse,
)

router = APIRouter(prefix="/help/chat", tags=["Help Chat"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _owned_conversation(
    session: AsyncSession,
    conversation_id: str,
    user_id: int,
) -> DBHelpConversation:
    result = await session.execute(
        select(DBHelpConversation).where(
            DBHelpConversation.public_id == conversation_id,
            DBHelpConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conversation


async def _history(
    session: AsyncSession,
    conversation_id: int,
    *,
    limit: int = 12,
) -> list[tuple[str, str]]:
    result = await session.execute(
        select(DBHelpMessage.role, DBHelpMessage.content)
        .where(DBHelpMessage.conversation_id == conversation_id)
        .order_by(DBHelpMessage.created_at.desc(), DBHelpMessage.id.desc())
        .limit(limit)
    )
    rows = list(result.all())
    rows.reverse()
    return [(str(role), str(content)) for role, content in rows]


@router.post(
    "/conversations",
    response_model=HelpConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
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

    return HelpConversationResponse(
        id=conversation.public_id,
        title=conversation.title,
        status=conversation.status,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/conversations", response_model=list[HelpConversationResponse])
async def list_conversations(
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(DBHelpConversation)
        .where(DBHelpConversation.user_id == current_user.id)
        .order_by(
            DBHelpConversation.last_message_at.desc().nullslast(),
            DBHelpConversation.created_at.desc(),
        )
    )

    conversations = result.scalars().all()

    return [
        HelpConversationResponse(
            id=conversation.public_id,
            title=conversation.title,
            status=conversation.status,
            last_message_at=conversation.last_message_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        for conversation in conversations
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=HelpConversationDetailResponse,
)
async def get_conversation(
    conversation_id: str,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(__import__("app.dependencies", fromlist=["get_db"]).get_db),
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


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=HelpChatResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: str,
    payload: HelpMessageCreate,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(__import__("app.dependencies", fromlist=["get_db"]).get_db),
):
    conversation = await _owned_conversation(session, conversation_id, current_user.id)

    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation is closed.",
        )

    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty.",
        )

    now = _now()
    user_message = DBHelpMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
        created_at=now,
    )
    session.add(user_message)

    if not conversation.title:
        conversation.title = content[:80]

    conversation.last_message_at = now
    conversation.updated_at = now
    await session.flush()

    results = await search_help(session, content, limit=5)
    context = format_help_context(results, content)
    history = await _history(session, conversation.id, limit=12)

    if not results:
        assistant_content = FALLBACK_NO_CONTEXT
        completion_model = None
        completion_provider = "echostream-help"
        input_tokens = None
        output_tokens = None
        latency_ms = 0
        needs_human_support = True
    else:
        try:
            completion = await generate_help_response(
                user_id=current_user.id,
                user_message=content,
                history=history,
                context=context,
            )
        except HelpAIError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
                headers={"Retry-After": "10"},
            ) from exc

        assistant_content = completion.content
        completion_model = completion.model
        completion_provider = "groq"
        input_tokens = completion.input_tokens
        output_tokens = completion.output_tokens
        latency_ms = completion.latency_ms
        needs_human_support = False

    assistant_message = DBHelpMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=assistant_content,
        model=completion_model,
        provider=completion_provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        created_at=_now(),
    )
    session.add(assistant_message)
    conversation.last_message_at = assistant_message.created_at
    conversation.updated_at = assistant_message.created_at

    await session.commit()
    await session.refresh(user_message)
    await session.refresh(assistant_message)

    return HelpChatResponse(
        user_message=user_message,
        assistant_message=assistant_message,
        sources=[
            HelpSourceResponse(
                id=result.article_id,
                slug=result.slug,
                title=result.title,
                category_slug=result.category_slug,
                category_title=result.category_title,
            )
            for result in results
        ],
        needs_human_support=needs_human_support,
    )


@router.post(
    "/conversations/{conversation_id}/close",
    response_model=HelpConversationResponse,
)
async def close_conversation(
    conversation_id: str,
    current_user: DBUser = Depends(get_current_user),
    session: AsyncSession = Depends(__import__("app.dependencies", fromlist=["get_db"]).get_db),
):
    conversation = await _owned_conversation(session, conversation_id, current_user.id)
    conversation.status = "closed"
    conversation.updated_at = _now()
    await session.commit()
    await session.refresh(conversation)
    return conversation
