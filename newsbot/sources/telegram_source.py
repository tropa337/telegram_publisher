from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

from telethon import TelegramClient, events
from telethon.tl.types import Message

from ..types import NewsItem

logger = logging.getLogger(__name__)


def _safe_message_datetime(msg: Message) -> datetime:
    dt = getattr(msg, "date", None)
    if not dt:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _build_tg_link(event) -> str:
    """Строим ссылку на сообщение.

    - Для публичных каналов: https://t.me/<username>/<msg_id>
    - Для приватных супергрупп/каналов без username: https://t.me/c/<internal_id>/<msg_id>
      (internal_id = abs(chat_id) без префикса -100)
    """
    msg = event.message
    msg_id = getattr(msg, "id", None) or 0
    chat = getattr(event, "chat", None)
    username = getattr(chat, "username", None) if chat else None
    if username:
        return f"https://t.me/{username}/{msg_id}"

    chat_id = getattr(event, "chat_id", None)
    if isinstance(chat_id, int) and str(chat_id).startswith("-100"):
        internal = str(abs(chat_id))[3:]
        return f"https://t.me/c/{internal}/{msg_id}"

    return f"tg://openmessage?chat_id={chat_id}&message_id={msg_id}"


class TelegramSource:
    """Реактивный источник: новые сообщения приходят через Telethon events.

    fetch() возвращает пустой список — новости пушатся через callback в очередь.
    """

    def __init__(self, client: TelegramClient, channels: List[str]):
        self.name = "telegram"
        self.client = client
        self.channels = channels
        self._callback: Optional[Callable[[NewsItem], Awaitable[None]]] = None
        self._started = False

    async def fetch(self) -> List[NewsItem]:
        return []

    async def start_monitoring(self, callback: Callable[[NewsItem], Awaitable[None]]):
        self._callback = callback

        if self._started:
            return
        self._started = True

        @self.client.on(events.NewMessage(chats=self.channels))
        async def _handler(event):
            try:
                await self._handle_event(event)
            except Exception as e:
                logger.error(f"❌ TG source handler error: {e}", exc_info=True)

    async def _handle_event(self, event):
        msg = getattr(event, "message", None)
        if not msg:
            return

        text = getattr(msg, "message", None) or ""
        text = text.strip()
        if not text:
            return

        created_at = _safe_message_datetime(msg)
        link = _build_tg_link(event)

        chat = getattr(event, "chat", None)
        chat_name = getattr(chat, "username", None) or getattr(chat, "title", None) or str(getattr(event, "chat_id", "unknown"))

        item = NewsItem(
            raw_text=text,
            source=f"tg:{chat_name}",
            url=link,
            created_at=created_at,
            media_items=[],
            author=None,
            language="ru",
        )

        if self._callback:
            await self._callback(item)


async def register_tg_handlers(client: TelegramClient, source_channels: List[str], push_callback: Callable[[NewsItem], Awaitable[None]]):
    """Backwards compatible helper."""
    src = TelegramSource(client=client, channels=source_channels)
    await src.start_monitoring(push_callback)
    return src
