from datetime import datetime, timedelta, timezone
from typing import Optional

from telethon import events

from ..types import NewsItem


def register_tg_handlers(client, source_channels: list[str], push_callback):
    """
    Реакция на новые сообщения в Telegram-каналах = максимально быстро.
    push_callback(item: NewsItem) -> await
    """

    @client.on(events.NewMessage(chats=source_channels))
    async def handler(event):
        msg = event.message
        if not msg or not msg.message:
            return

        # Безопасное получение даты
        if msg.date:
            created_at = msg.date
        else:
            created_at = datetime.now(timezone.utc)

        # Безопасное получение ссылки
        link: Optional[str] = None
        try:
            link = msg.link
        except Exception as e:
            print(f"⚠️ Failed to get message link: {e}")

        # Безопасное получение username канала
        chat_name = getattr(event.chat, 'username', None) or str(event.chat_id)

        item = NewsItem(
            source=f"tg:{chat_name}",
            created_at=created_at,
            raw_text=msg.message,
            source_link=link,
            media=msg.media,
        )

        await push_callback(item)
