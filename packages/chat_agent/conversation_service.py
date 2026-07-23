"""Conversation storage.

`InMemoryConversationRepository` is the only implementation shipped: it is fully
unit-testable and safe by construction (nothing to misconfigure). A durable
implementation would need its own connection to this repository's existing Postgres
infrastructure (packages/persistence) -- that integration is NOT implemented here (see
docs/AI_TRADING_ADVISOR_ARCHITECTURE.md "Known gaps"), so conversation history does not
currently survive a process restart. Do not point this at an unknown database.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from packages.chat_agent.models import ChatMessage


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationRepository(ABC):
    @abstractmethod
    async def create(self) -> Conversation: ...

    @abstractmethod
    async def get(self, conversation_id: str) -> Optional[Conversation]: ...

    @abstractmethod
    async def append_message(self, conversation_id: str, message: ChatMessage) -> Conversation: ...


class InMemoryConversationRepository(ConversationRepository):
    def __init__(self, max_conversations: int = 5000) -> None:
        self._store: Dict[str, Conversation] = {}
        self._max_conversations = max_conversations

    async def create(self) -> Conversation:
        conversation = Conversation()
        self._store[conversation.conversation_id] = conversation
        if len(self._store) > self._max_conversations:
            oldest_id = min(self._store, key=lambda cid: self._store[cid].updated_at)
            del self._store[oldest_id]
        return conversation

    async def get(self, conversation_id: str) -> Optional[Conversation]:
        return self._store.get(conversation_id)

    async def append_message(self, conversation_id: str, message: ChatMessage) -> Conversation:
        conversation = self._store.get(conversation_id)
        if conversation is None:
            conversation = Conversation(conversation_id=conversation_id)
            self._store[conversation_id] = conversation
        updated = conversation.model_copy(
            update={"messages": [*conversation.messages, message], "updated_at": datetime.now(timezone.utc)}
        )
        self._store[conversation_id] = updated
        return updated


conversation_repository = InMemoryConversationRepository()
