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
        
        # Для Twitter URL определяем тип более точно
        if 'pbs.twimg.com' in url_lower:
            if any(param in url_lower for param in ['format=jpg', 'format=png', 'name=large']):
                return 'photo'
            elif 'format=mp4' in url_lower:
                return 'video'
            elif 'format=gif' in url_lower:
                return 'animation'
            else:
                # По умолчанию для twimg - фото
                return 'photo'
        
        # pic.twitter.com всегда фото для Telegram
        if 'pic.twitter.com' in url_lower:
            return 'photo'
        
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
        
        # Паттерны для медиа URL с приоритетом для Twitter
        patterns = [
            r'https?://(?:pbs\.twimg\.com|pic\.twitter\.com)/[^\s]+',
            r'https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^\s]*)?',
            r'https?://[^\s]+\.(?:mp4|mov|avi|webm|mkv)(?:\?[^\s]*)?',
            r'https?://[^\s]*\.(?:youtube\.com|youtu\.be)/[^\s]+',
        ]
        
        urls = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)
        
        return list(set(urls))[:5]  # Убираем дубликаты, макс 5
    
    async def validate_media(self, media_item: MediaItem) -> bool:
        """Проверка доступности медиа"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            # Для Twitter URL не проверяем - Telegram сам умеет их скачивать
            if any(domain in media_item.url.lower() for domain in ['twitter.com', 'twimg.com', 'pic.twitter.com']):
                return True
            
            # Проверяем только не-Twitter URL
            async with self.session.head(media_item.url, timeout=5) as response:
                return response.status == 200
                
        except Exception:
            return True  # Если не смогли проверить, все равно используем
    
    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None