import asyncio
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from newsbot.types import MediaItem


class MediaHandler:
    """Обработчик медиа для постов"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.session: Optional[aiohttp.ClientSession] = None
        

    async def get_primary_media(self, news_item, max_size_mb: int = 10) -> Optional[MediaItem]:
        """Получение медиа если есть, иначе None"""
        try:
            # 1. Проверяем media_items из новости
            if hasattr(news_item, 'media_items') and news_item.media_items:
                return news_item.media_items[0]
            
            # 2. Извлекаем медиа из текста
            if hasattr(news_item, 'raw_text'):
                urls = self._extract_media_urls(news_item.raw_text)
                if urls:
                    return MediaItem(
                        url=urls[0],
                        type=self._detect_media_type(urls[0])
                    )
            
            # 3. Если нет медиа - возвращаем None
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения медиа: {e}")
            return None


    
    def _detect_media_type(self, url: str) -> str:
        """Определение типа медиа по URL"""
        if not url:
            return 'photo'
        
        url_lower = url.lower()
        
        # Изображения
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']):
            return 'photo'
        
        # Видео
        if any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']):
            return 'video'
        
        # Документы
        if any(ext in url_lower for ext in ['.pdf', '.doc', '.docx', '.txt']):
            return 'document'
        
        # По умолчанию фото
        return 'photo'
    
    def _extract_media_urls(self, text: str) -> List[str]:
        """Извлечение URL медиа из текста"""
        if not text:
            return []
        
        # Паттерны для медиа URL
        patterns = [
            r'https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^\s]*)?',
            r'https?://[^\s]+\.(?:mp4|mov|avi|webm|mkv)(?:\?[^\s]*)?',
            r'https?://(?:pbs\.twimg\.com|cdn\.discordapp\.com|i\.imgur\.com)/[^\s]+',
            r'https?://[^\s]*\.(?:youtube\.com|youtu\.be)/[^\s]+',
        ]
        
        urls = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)
        
        return list(set(urls))[:5]  # Убираем дубликаты, макс 5
    
    async def _get_fallback_media(self, news_item) -> Optional[MediaItem]:
        """Получение заглушки если нет медиа"""
        # В зависимости от содержания новости
        text = getattr(news_item, 'raw_text', '').lower()
        
        # Определяем тему для выбора заглушки
        if any(word in text for word in ['btc', 'bitcoin']):
            return MediaItem(
                url='https://cryptoslate.com/wp-content/uploads/2023/10/bitcoin-price-2023.jpg',
                type='photo'
            )
        elif any(word in text for word in ['eth', 'ethereum']):
            return MediaItem(
                url='https://cryptoslate.com/wp-content/uploads/2023/09/ethereum-price-2023.jpg',
                type='photo'
            )
        elif any(word in text for word in ['sec', 'regulation', 'etf']):
            return MediaItem(
                url='https://images.cointelegraph.com/cdn-cgi/image/format=auto,onerror=redirect,quality=90,width=1200/https://s3.cointelegraph.com/uploads/2023-10/5678a7b4-2b9a-4e2d-9a6c-3c8b5d7e9f1a.jpg',
                type='photo'
            )
        else:
            # Общая крипто-картинка
            return MediaItem(
                url='https://cdn.pixabay.com/photo/2017/01/25/12/31/bitcoin-2007769_1280.jpg',
                type='photo'
            )
    
    async def validate_media(self, media_item: MediaItem) -> bool:
        """Проверка доступности медиа"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            # Проверяем только фото для скорости
            if media_item.type != 'photo':
                return True
            
            async with self.session.head(media_item.url, timeout=5) as response:
                return response.status == 200
                
        except Exception:
            return True  # Если не смогли проверить, все равно используем
    
    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None
