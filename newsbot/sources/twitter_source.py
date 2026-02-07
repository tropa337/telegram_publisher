import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

import aiohttp
import feedparser
from dateutil import parser

from ..types import MediaItem, NewsItem


class TwitterRSSSource:
    """
    Источник новостей из Twitter через RSS.
    Поддерживает множественные RSS-ленты, извлечение медиа и обработку ошибок.
    """
    
    def __init__(self, 
                 feeds: Dict[str, str], 
                 auth_token: Optional[str] = None, 
                 poll_interval: int = 60,
                 max_cache_size: int = 1000,
                 logger: Optional[logging.Logger] = None,
                 filters: Optional[List[Callable[[NewsItem], bool]]] = None):
        """
        Инициализация источника Twitter RSS.
        
        Args:
            feeds: Словарь {метка: RSS_URL} фидов
            auth_token: Токен аутентификации (опционально)
            poll_interval: Интервал опроса в секундах
            max_cache_size: Максимальный размер кеша обработанных ID
            logger: Логгер (если None, создается новый)
            filters: Список фильтров для новостей
        """
        self.name = "twitter_rss"
        self.feeds = feeds
        self.auth_token = auth_token
        self.poll_interval = poll_interval
        self.max_cache_size = max_cache_size
        self.filters = filters or []
        
        # Настройка логирования
        self.logger = logger or self._setup_logger()
        
        # Кеш обработанных элементов
        self.processed_ids: Set[str] = set()
        self.processed_count = 0
        self.error_count = 0
        
        # Статистика
        self.stats = {
            'total_fetched': 0,
            'total_processed': 0,
            'total_errors': 0,
            'last_fetch': None,
            'feed_stats': {},
            'media_stats': {
                'with_media': 0,
                'without_media': 0,
                'total_media_items': 0,
                'media_by_type': {}
            }
        }
        
        self.logger.info(f"Инициализирован источник Twitter RSS с {len(feeds)} фидами")
        
    def _setup_logger(self) -> logging.Logger:
        """Настройка логгера"""
        logger = logging.getLogger(f"{__name__}.TwitterRSSSource")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
        
    async def fetch(self) -> List[NewsItem]:
        """Асинхронное получение новостей из всех RSS-фидов"""
        all_items = []
        
        self.logger.info(f"Начинаем получение новостей из {len(self.feeds)} источников")
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for label, url in self.feeds.items():
                task = self._fetch_feed(session, label, url)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, (label, url) in enumerate(self.feeds.items()):
                result = results[i]
                
                if isinstance(result, Exception):
                    self.logger.error(f"❌ Ошибка RSS {label}: {result}")
                    self.error_count += 1
                    continue
                    
                items = result
                all_items.extend(items)
                self.stats['feed_stats'][label] = len(items)
                
                with_media = sum(1 for item in items if hasattr(item, 'media_items') and item.media_items)
                total_media = sum(len(item.media_items) for item in items if hasattr(item, 'media_items') and item.media_items)
                
                self.logger.info(f"✅ RSS {label}: {len(items)} новостей ({with_media} с медиа, всего {total_media} медиафайлов)")
        
        # Фильтрация новостей
        if self.filters:
            filtered_items = []
            for item in all_items:
                if all(filter_func(item) for filter_func in self.filters):
                    filtered_items.append(item)
            all_items = filtered_items
        
        # Обновление статистики
        self.stats['total_fetched'] += len(all_items)
        self.stats['total_processed'] = self.processed_count
        self.stats['total_errors'] = self.error_count
        self.stats['last_fetch'] = datetime.now(timezone.utc).isoformat()
        
        # Детальная статистика медиа
        for item in all_items:
            if hasattr(item, 'media_items') and item.media_items:
                self.stats['media_stats']['with_media'] += 1
                self.stats['media_stats']['total_media_items'] += len(item.media_items)
                
                # Статистика по типам медиа
                for media in item.media_items:
                    media_type = media.type
                    self.stats['media_stats']['media_by_type'][media_type] = \
                        self.stats['media_stats']['media_by_type'].get(media_type, 0) + 1
            else:
                self.stats['media_stats']['without_media'] += 1
        
        self.logger.info(f"Получено {len(all_items)} новостей после фильтрации")
        
        if self.stats['media_stats']['media_by_type']:
            media_types_str = ", ".join([f"{count} {typ}" for typ, count in self.stats['media_stats']['media_by_type'].items()])
            self.logger.info(f"📊 Детальная статистика медиа: {media_types_str}")
        
        return all_items
        
    async def _fetch_feed(self, 
                         session: aiohttp.ClientSession, 
                         label: str, 
                         url: str) -> List[NewsItem]:
        """Получение одного RSS-фида"""
        headers = self._get_headers()
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        try:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    self.logger.warning(f"RSS {label}: HTTP {response.status}")
                    return []
                    
                content = await response.text()
                return self._parse_feed_content(content, label)
                
        except asyncio.TimeoutError:
            self.logger.error(f"Таймаут при получении RSS {label}")
            return []
        except aiohttp.ClientError as e:
            self.logger.error(f"Ошибка клиента при получении RSS {label}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении RSS {label}: {e}")
            return []
            
    def _get_headers(self) -> Dict[str, str]:
        """Получение заголовков HTTP-запроса"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; TwitterRSSBot/1.0)',
            'Accept': 'application/rss+xml, application/xml, text/xml',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        if self.auth_token:
            headers['Authorization'] = f'Bearer {self.auth_token}'
            
        return headers
        
    def _parse_feed_content(self, content: str, label: str) -> List[NewsItem]:
        """Парсинг содержимого RSS-фида"""
        feed = feedparser.parse(content)
        
        if feed.bozo:
            self.logger.warning(f"Ошибка парсинга RSS {label}: {feed.bozo_exception}")
            return []
            
        items = []
        for entry in feed.entries:
            try:
                news_item = self._parse_entry(entry, label)
                if news_item:
                    items.append(news_item)
                    self.processed_count += 1
            except Exception as e:
                self.logger.error(f"Ошибка парсинга записи: {e}", exc_info=True)
                continue
                
        return items

    def _parse_entry(self, entry, source_label: str) -> Optional[NewsItem]:
        """Парсинг одной RSS-записи"""
        # Получение уникального ID
        entry_id = self._get_entry_id(entry)
        if not entry_id:
            return None
            
        # Проверка на дубликат
        if entry_id in self.processed_ids:
            return None
            
        # Парсинг даты
        created_at = self._parse_date(entry)
        
        # Проверка на актуальность (не старше 7 дней)
        time_difference = datetime.now(timezone.utc) - created_at
        if time_difference.days > 7:
            return None
        
        # Извлечение текста
        raw_text = self._extract_text(entry)
        if not raw_text or len(raw_text.strip()) < 5:
            return None
        
        # ИЗВЛЕЧЕНИЕ МЕДИА ИЗ RSS - КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ
        media_urls = self._extract_rss_media_urls(entry)
        
        # Если нет медиа в RSS, проверяем текст
        if not media_urls:
            media_urls = self._extract_media_urls_from_text(raw_text)
        
        # Создаем MediaItem объекты
        media_items = []
        for url in list(set(media_urls))[:5]:  # Уникальные, макс 5
            if url and self._is_valid_media_url(url):
                media_type = self._detect_media_type(url)
                media_items.append(MediaItem(
                    url=url,
                    type=media_type,
                    caption=None
                ))
        
        # Логируем информацию о медиа
        if media_items:
            self.logger.info(f"📸 RSS {source_label}: найдено {len(media_items)} медиа")
            for i, media in enumerate(media_items[:3]):
                self.logger.info(f"   Медиа {i+1}: {media.type} - {media.url[:100]}")
        else:
            self.logger.debug(f"🚫 RSS {source_label}: нет медиа")
        
        # Извлечение автора
        author = self._extract_author(entry)
        
        # Получение ссылки
        url = getattr(entry, 'link', None)
        if not url:
            url = f"twitter_rss:{source_label}:{entry_id}"
        
        # Создание объекта новости
        news_item = NewsItem(
            raw_text=raw_text,
            source=f"twitter_rss:{source_label}",
            url=url,
            created_at=created_at,
            media_items=media_items,
            author=author
        )
        
        # Добавляем в кеш
        self.processed_ids.add(entry_id)
        self._cleanup_cache()
        
        return news_item

    def _extract_rss_media_urls(self, entry) -> List[str]:
        """Извлечение медиа URL из RSS тегов (главное исправление)"""
        media_urls = []
        
        try:
            # 1. Проверяем media_content (feedparser помещает media:content сюда)
            if hasattr(entry, 'media_content') and entry.media_content:
                self.logger.debug(f"Найдено media_content: {len(entry.media_content)} элементов")
                for i, media in enumerate(entry.media_content):
                    if hasattr(media, 'url') and media.url:
                        media_urls.append(media.url)
                        self.logger.debug(f"  Медиа из media_content[{i}]: {media.url[:100]}")
            
            # 2. Проверяем media_thumbnail
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                thumbnails = entry.media_thumbnail
                if isinstance(thumbnails, list):
                    for thumb in thumbnails:
                        if hasattr(thumb, 'url') and thumb.url:
                            media_urls.append(thumb.url)
                            self.logger.debug(f"  Медиа из media_thumbnail[list]: {thumb.url[:100]}")
                elif isinstance(thumbnails, dict) and 'url' in thumbnails:
                    media_urls.append(thumbnails['url'])
                    self.logger.debug(f"  Медиа из media_thumbnail[dict]: {thumbnails['url'][:100]}")
            
            # 3. Проверяем все атрибуты на наличие url
            for attr_name in dir(entry):
                if not attr_name.startswith('_'):
                    try:
                        attr_value = getattr(entry, attr_name)
                        if isinstance(attr_value, str) and attr_value.startswith('http'):
                            if self._is_media_url(attr_value):
                                media_urls.append(attr_value)
                                self.logger.debug(f"  Медиа из атрибута {attr_name}: {attr_value[:100]}")
                    except:
                        pass
            
            # 4. Проверяем enclosures (вложения)
            if hasattr(entry, 'enclosures') and entry.enclosures:
                self.logger.debug(f"Найдено enclosures: {len(entry.enclosures)}")
                for i, enclosure in enumerate(entry.enclosures):
                    url = getattr(enclosure, 'href', None) or getattr(enclosure, 'url', None)
                    if url and self._is_media_url(url):
                        media_urls.append(url)
                        self.logger.debug(f"  Медиа из enclosure[{i}]: {url[:100]}")
            
            # 5. Проверяем теги с медиа в названии
            media_fields = ['media', 'image', 'photo', 'thumbnail', 'picture']
            for field in media_fields:
                for attr_name in dir(entry):
                    if field in attr_name.lower() and not attr_name.startswith('_'):
                        try:
                            field_value = getattr(entry, attr_name)
                            if isinstance(field_value, dict) and 'url' in field_value:
                                media_urls.append(field_value['url'])
                                self.logger.debug(f"  Медиа из {attr_name}[dict]: {field_value['url'][:100]}")
                            elif isinstance(field_value, str) and field_value.startswith('http'):
                                if self._is_media_url(field_value):
                                    media_urls.append(field_value)
                                    self.logger.debug(f"  Медиа из {attr_name}: {field_value[:100]}")
                        except:
                            pass
            
        except Exception as e:
            self.logger.error(f"Ошибка извлечения медиа из RSS: {e}")
        
        # Удаляем дубликаты
        unique_urls = []
        seen = set()
        for url in media_urls:
            if url not in seen and self._is_valid_media_url(url):
                unique_urls.append(url)
                seen.add(url)
        
        return unique_urls[:10]

    def _extract_media_urls_from_text(self, text: str) -> List[str]:
        """Извлечение URL медиа из текста"""
        if not text:
            return []
        
        patterns = [
            r'https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^\s]*)?',
            r'https?://[^\s]+\.(?:mp4|mov|avi|webm|mkv)(?:\?[^\s]*)?',
            r'https?://(?:pbs\.twimg\.com|pic\.twitter\.com)/[^\s]+',
            r'https?://[^\s]*\.(?:youtube\.com|youtu\.be)/[^\s]+',
        ]
        
        urls = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)
        
        return list(set(urls))[:5]

    def _is_valid_media_url(self, url: str) -> bool:
        """Проверка валидности медиа URL"""
        try:
            result = urlparse(url)
            if result.scheme not in ['http', 'https']:
                return False
            
            # Для Twitter URL всегда валидны
            if any(domain in url.lower() for domain in ['twitter.com', 'twimg.com', 'x.com']):
                return True
            
            # Проверяем расширения файлов
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
            for ext in image_extensions:
                if url.lower().endswith(ext):
                    return True
            
            return True
        except:
            return False

    def _detect_media_type(self, url: str) -> str:
        """Определение типа медиа по URL"""
        if not url:
            return 'photo'
        
        url_lower = url.lower()
        
        # Twitter специфичные URL
        if 'pbs.twimg.com' in url_lower:
            if any(param in url_lower for param in ['format=jpg', 'format=png', 'name=large', '.jpg', '.png']):
                return 'photo'
            elif 'format=mp4' in url_lower or '.mp4' in url_lower:
                return 'video'
            elif 'format=gif' in url_lower or '.gif' in url_lower:
                return 'animation'
            elif 'card_img' in url_lower:
                return 'photo'  # Карточки Twitter - всегда фото
            else:
                return 'photo'
        
        # Изображения
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']):
            return 'photo'
        
        # Видео
        if any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv']):
            return 'video'
        
        # По умолчанию фото
        return 'photo'
        
    def _get_entry_id(self, entry) -> Optional[str]:
        """Получение уникального ID записи"""
        id_fields = ['id', 'guid', 'link', 'published', 'updated']
        
        for field in id_fields:
            value = getattr(entry, field, None)
            if value:
                if isinstance(value, dict) and 'value' in value:
                    value = value['value']
                
                id_str = str(value).strip()
                if 'http' in id_str:
                    return hashlib.md5(id_str.encode()).hexdigest()
                return id_str
                
        return None
        
    def _parse_date(self, entry) -> datetime:
        """Парсинг даты из RSS-записи"""
        date_fields = ['published', 'updated', 'created', 'pubDate']
        
        for field in date_fields:
            date_str = getattr(entry, field, None)
            if date_str:
                try:
                    if isinstance(date_str, dict) and 'value' in date_str:
                        date_str = date_str['value']
                    
                    parsed_date = parser.parse(date_str)
                    
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                        
                    return parsed_date
                except Exception as e:
                    self.logger.debug(f"Не удалось распарсить дату из поля {field}: {e}")
                    continue
                    
        return datetime.now(timezone.utc)
        
    def _extract_text(self, entry) -> str:
        """Извлечение текста из RSS-записи"""
        content_fields = [
            ('content', 0, 'value'),
            ('summary_detail', None, 'value'),
            ('summary', None, None),
            ('title', None, None),
            ('description', None, None)
        ]
        
        best_text = ""
        for field_name, index, subfield in content_fields:
            field_value = getattr(entry, field_name, None)
            
            if not field_value:
                continue
                
            if isinstance(field_value, list) and index is not None:
                if len(field_value) > index:
                    field_value = field_value[index]
                    if subfield and hasattr(field_value, subfield):
                        field_value = getattr(field_value, subfield)
                else:
                    continue
                    
            elif hasattr(field_value, 'value'):
                field_value = field_value.value
                
            if field_value:
                text = self._clean_html(str(field_value))
                if len(text) > len(best_text):
                    best_text = text
                    
        return best_text.strip()
        
    def _clean_html(self, html: str) -> str:
        """Очистка HTML"""
        if not html:
            return ""
            
        text = re.sub(r'<[^>]+>', ' ', html)
        text = unescape(text)
        
        # Удаляем URL из текста (они уже извлечены отдельно)
        text = re.sub(r'https?://\S+', '', text)
        
        # Удаление подписей Twitter
        text = re.sub(r'\s*—\s*.*\(@\w+\)[^—]*$', '', text)
        text = re.sub(r'pic\.twitter\.com/\w+', '', text, flags=re.IGNORECASE)
        
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
        
        return text.strip()
        
    def _extract_author(self, entry) -> Optional[str]:
        """Извлечение автора"""
        author = getattr(entry, 'author', None)
        if author:
            match = re.search(r'([^(@]+)\(@', author)
            if match:
                return match.group(1).strip()
            
            author = re.sub(r'<[^>]+>', '', author)
            author = re.sub(r'\([^)]+\)', '', author)
            author = re.sub(r'@\w+', '', author)
            
            return author.strip()
        
        title = getattr(entry, 'title', '')
        if ':' in title:
            author_part = title.split(':', 1)[0]
            return self._clean_html(author_part.strip())
            
        return None
    
    def _cleanup_cache(self):
        """Очистка кеша обработанных ID"""
        if len(self.processed_ids) > self.max_cache_size:
            items = list(self.processed_ids)
            self.processed_ids = set(items[-self.max_cache_size:])
            self.logger.info(f"Кеш очищен: {len(self.processed_ids)} элементов")
    
    async def start_polling(self, callback: Callable[[List[NewsItem]], Any]):
        """
        Запуск периодического опроса RSS-лент.
        
        Args:
            callback: Функция, которая будет вызвана с новыми новостями
        """
        self.logger.info(f"Запуск периодического опроса с интервалом {self.poll_interval} секунд")
        
        while True:
            try:
                self.logger.debug("Начало цикла опроса")
                news_items = await self.fetch()
                
                if news_items:
                    self.logger.info(f"Найдено {len(news_items)} новых новостей")
                    try:
                        await callback(news_items)
                    except Exception as e:
                        self.logger.error(f"Ошибка в callback: {e}", exc_info=True)
                else:
                    self.logger.debug("Новых новостей не найдено")
                    
            except Exception as e:
                self.logger.error(f"Критическая ошибка при опросе: {e}", exc_info=True)
            
            await asyncio.sleep(self.poll_interval)
    
    def add_filter(self, filter_func: Callable[[NewsItem], bool]):
        """Добавление фильтра новостей"""
        self.filters.append(filter_func)
        self.logger.info(f"Добавлен фильтр: {filter_func.__name__}")
    
    def clear_cache(self):
        """Очистка кеша обработанных ID"""
        self.processed_ids.clear()
        self.logger.info("Кеш очищен")
    
    def get_stats(self) -> Dict[str, any]:
        """Получение статистики по источнику"""
        return {
            'source': self.name,
            'feeds': {
                'total': len(self.feeds),
                'list': list(self.feeds.keys())
            },
            'cache': {
                'size': len(self.processed_ids),
                'max_size': self.max_cache_size
            },
            'performance': {
                'processed': self.processed_count,
                'errors': self.error_count,
                'last_fetch': self.stats['last_fetch']
            },
            'media_stats': self.stats['media_stats'],
            'feed_stats': self.stats['feed_stats']
        }
    
    def add_feed(self, label: str, url: str):
        """Добавление нового RSS-фида"""
        if label in self.feeds:
            self.logger.warning(f"Фидер с меткой '{label}' уже существует, будет заменен")
        
        self.feeds[label] = url
        self.logger.info(f"Добавлен новый фидер: {label} -> {url}")
    
    def remove_feed(self, label: str):
        """Удаление RSS-фида"""
        if label in self.feeds:
            del self.feeds[label]
            self.logger.info(f"Удален фидер: {label}")
        else:
            self.logger.warning(f"Фидер с меткой '{label}' не найден")