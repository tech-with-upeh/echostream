from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.models import UTCDateTime


class DBHelpConversation(Base):
    __tablename__ = "help_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_help_conversations_status"),
        Index("ix_help_conversations_user_last_message", "user_id", "last_message_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(36), unique=True, nullable=False, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(120), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    last_message_at = Column(UTCDateTime, nullable=True, index=True)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)

    user = relationship("DBUser")
    messages = relationship(
        "DBHelpMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="DBHelpMessage.created_at",
    )


class DBHelpMessage(Base):
    __tablename__ = "help_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_help_messages_role"),
        Index("ix_help_messages_conversation_created", "conversation_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("help_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, index=True)
    content = Column(Text, nullable=False)
    model = Column(String(100), nullable=True)
    provider = Column(String(50), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, index=True)

    conversation = relationship("DBHelpConversation", back_populates="messages")
