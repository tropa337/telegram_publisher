from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

from telethon import TelegramClient, events

from ..types import NewsItem


class TelegramSource:
    def __init__(self, client: TelegramClient, channels: List[str]):
        self.name = "telegram"
        self.client = client
        self.channels = channels
        self.callback = None
        self.handler = None
        
    async def fetch(self) -> List[NewsItem]:
        """Получение новых сообщений из каналов"""
        # Этот метод будет вызываться при получении новых сообщений
        # через обработчик событий. Для совместимости возвращаем пустой список.
        return []
        
    async def start_monitoring(self, callback: Callable[[NewsItem], Awaitable[None]]):
        """Запуск мониторинга каналов"""
        self.callback = callback
        
        @self.client.on(events.NewMessage(chats=self.channels))
        async def handler(event):
            await self._handle_message(event)
            
        self.handler = handler
        
    async def _handle_message(self, event):
        """Обработка нового сообщения"""
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
            media_url=None,  # TelegramSource пока не обрабатывает медиа
        )
        
        if self.callback:
            await self.callback(item)


# Старая функция для обратной совместимости
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
            media_url=None,
        )

        await push_callback(item)
        await push_callback(item)