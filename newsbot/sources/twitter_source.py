
import asyncio
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
            'feed_stats': {}
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
            
            # Параллельное выполнение запросов
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
                
                self.logger.info(f"✅ RSS {label}: {len(items)} новостей")
        
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
        
        self.logger.info(f"Получено {len(all_items)} новостей после фильтрации")
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
            
        # Извлечение медиа и создание MediaItem объектов
        media_urls = self._extract_media_urls(entry)
        media_items = []
        for url in media_urls[:5]:  # Максимум 5 медиа
            media_type = self._detect_media_type(url)
            media_items.append(MediaItem(
                url=url,
                type=media_type
            ))
        
        # Извлечение автора
        author = self._extract_author(entry)
        
        # Получение ссылки
        url = getattr(entry, 'link', None)
        if not url:
            url = f"twitter_rss:{source_label}:{entry_id}"
        
        # Создание объекта новости с ПРАВИЛЬНЫМИ параметрами
        news_item = NewsItem(
            raw_text=raw_text,
            source=f"twitter_rss:{source_label}",
            url=url,
            created_at=created_at,
            media_items=media_items,  # Используем media_items, а не media_urls
            author=author
        )
        
        # Добавляем в кеш
        self.processed_ids.add(entry_id)
        self._cleanup_cache()
        
        return news_item

    def _detect_media_type(self, url: str) -> str:
        """Определение типа медиа по URL"""
        if not url:
            return 'photo'
        
        url_lower = url.lower()
        
        # Изображения
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']):
            return 'photo'
        
        # Видео
        if any(ext in url_lower for ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv']):
            return 'video'
        
        # Документы
        if any(ext in url_lower for ext in ['.pdf', '.doc', '.docx', '.txt']):
            return 'document'
        
        # Проверяем домены
        if any(domain in url_lower for domain in ['youtube.com', 'youtu.be', 'vimeo.com']):
            return 'video'
        
        # По умолчанию фото
        return 'photo'

        
    def _get_entry_id(self, entry) -> Optional[str]:
        """Получение уникального ID записи"""
        # Пробуем разные поля для ID
        id_fields = ['id', 'guid', 'link', 'published', 'updated']
        
        for field in id_fields:
            value = getattr(entry, field, None)
            if value:
                # Нормализация ID
                if isinstance(value, dict) and 'value' in value:
                    value = value['value']
                return str(value).strip()
                
        return None
        
    def _parse_date(self, entry) -> datetime:
        """Парсинг даты из RSS-записи"""
        date_fields = ['published', 'updated', 'created', 'pubDate']
        
        for field in date_fields:
            date_str = getattr(entry, field, None)
            if date_str:
                try:
                    # Иногда дата может быть в словаре
                    if isinstance(date_str, dict) and 'value' in date_str:
                        date_str = date_str['value']
                    
                    parsed_date = parser.parse(date_str)
                    
                    # Если дата без часового пояса, считаем UTC
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
            ('content', 0, 'value'),  # content[0].value
            ('summary_detail', None, 'value'),  # summary_detail.value
            ('summary', None, None),  # summary
            ('title', None, None),  # title
            ('description', None, None)  # description
        ]
        
        best_text = ""
        for field_name, index, subfield in content_fields:
            field_value = getattr(entry, field_name, None)
            
            if not field_value:
                continue
                
            # Обработка списков
            if isinstance(field_value, list) and index is not None:
                if len(field_value) > index:
                    field_value = field_value[index]
                    if subfield and hasattr(field_value, subfield):
                        field_value = getattr(field_value, subfield)
                else:
                    continue
                    
            # Обработка объектов с атрибутом value
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
            
        # Удаление тегов
        text = re.sub(r'<[^>]+>', ' ', html)
        
        # Декодирование HTML-сущностей
        text = unescape(text)
        
        # Удаление URL
        text = re.sub(r'https?://\S+', '', text)
        
        # Удаление подписей Twitter
        text = re.sub(r'\s*—\s*.*\(@\w+\)[^—]*$', '', text)
        text = re.sub(r'pic\.twitter\.com/\w+', '', text)
        
        # Удаление лишних пробелов и переносов строк
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n+', ' ', text)
        
        return text.strip()
        
    def _extract_media_urls(self, entry) -> List[str]:
        """Извлечение ВСЕХ URL медиа из записи"""
        media_urls = []
        
        # 1. Медиа контент (стандартное поле RSS)
        if hasattr(entry, 'media_content'):
            for media in entry.media_content:
                if hasattr(media, 'url') and media.url:
                    media_urls.append(media.url)
        
        # 2. Вложения
        if hasattr(entry, 'enclosures'):
            for enclosure in entry.enclosures:
                url = getattr(enclosure, 'href', None) or getattr(enclosure, 'url', None)
                if url and self._is_media_url(url):
                    media_urls.append(url)
        
        # 3. Парсим HTML контент на наличие медиа
        content_fields = ['content', 'summary', 'description']
        for field in content_fields:
            field_value = getattr(entry, field, None)
            if field_value:
                html_content = ""
                
                if isinstance(field_value, list):
                    for item in field_value:
                        if hasattr(item, 'value'):
                            html_content += item.value + " "
                        else:
                            html_content += str(item) + " "
                else:
                    html_content = str(field_value)
                    
                media_urls.extend(self._extract_media_urls_from_html(html_content))
        
        # 4. Twitter специфичные медиа
        media_urls.extend(self._extract_twitter_media(entry))
        
        # Удаляем дубликаты и невалидные URL
        unique_urls = []
        seen = set()
        for url in media_urls:
            if (url not in seen and 
                self._is_media_url(url) and 
                self._is_valid_url(url)):
                unique_urls.append(url)
                seen.add(url)
        
        return unique_urls[:10]  # Ограничиваем количество
        
    def _extract_media_urls_from_html(self, html: str) -> List[str]:
        """Извлечение URL медиа из HTML"""
        # Паттерны для изображений
        img_patterns = [
            r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|bmp)[^"\']*)["\']',
            r'data-src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|bmp)[^"\']*)["\']',
            r'data-url=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|bmp)[^"\']*)["\']',
            r'url\(["\']?([^"\'\)]+\.(?:jpg|jpeg|png|gif|webp|bmp)[^"\'\)]*)\)',
        ]
        
        # Паттерны для видео
        video_patterns = [
            r'src=["\']([^"\']+\.(?:mp4|webm|mov|avi|mkv)[^"\']*)["\']',
            r'data-video-url=["\']([^"\']+)["\']',
            r'href=["\']([^"\']+\.(?:mp4|webm|mov)[^"\']*)["\']',
        ]
        
        # Паттерны для embed-видео
        embed_patterns = [
            r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)',
            r'(https?://youtu\.be/[\w-]+)',
            r'(https?://(?:www\.)?vimeo\.com/\d+)',
            r'(https?://(?:www\.)?twitter\.com/\w+/status/\d+)',
        ]
        
        all_patterns = img_patterns + video_patterns + embed_patterns
        
        urls = []
        for pattern in all_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            urls.extend(matches)
        
        return urls
    
    def _extract_twitter_media(self, entry) -> List[str]:
        """Извлечение Twitter-специфичных медиа"""
        twitter_media = []
        
        # Проверяем Twitter-специфичные поля
        twitter_fields = ['twitter_image', 'twitter_video', 'twitter_media']
        
        for field in twitter_fields:
            value = getattr(entry, field, None)
            if value:
                if isinstance(value, list):
                    twitter_media.extend(value)
                else:
                    twitter_media.append(value)
        
        return twitter_media
    
    def _is_media_url(self, url: str) -> bool:
        """Проверка, является ли URL медиа файлом"""
        if not url or not isinstance(url, str):
            return False
            
        url_lower = url.lower()
        
        # Проверяем расширения файлов
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
        video_extensions = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv']
        
        for ext in image_extensions + video_extensions:
            if url_lower.endswith(ext) or f'{ext}?' in url_lower:
                return True
        
        # Проверяем домены и пути
        media_domains = [
            'twimg.com',
            'pbs.twimg.com',
            'cdn.twitter.com',
            'imgur.com',
            'i.imgur.com',
            'i.redd.it',
            'media.tweet',
            'youtube.com',
            'youtu.be',
            'vimeo.com',
            'giphy.com',
            'tenor.com',
            'gfycat.com',
            'streamable.com'
        ]
        
        for domain in media_domains:
            if domain in url_lower:
                return True
        
        # Проверяем пути
        media_paths = [
            '/media/',
            '/photo/',
            '/image/',
            '/video/',
            '/gif/',
            '/thumb/',
            '/avatar/',
        ]
        
        for path in media_paths:
            if path in url_lower:
                return True
        
        return False
    
    def _is_valid_url(self, url: str) -> bool:
        """Проверка валидности URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _extract_author(self, entry) -> Optional[str]:
        """Извлечение автора"""
        author = getattr(entry, 'author', None)
        if author:
            # Извлекаем имя из формата "Name (@handle)"
            match = re.search(r'([^(@]+)\(@', author)
            if match:
                return match.group(1).strip()
            
            # Удаляем email и другие метаданные
            author = re.sub(r'<[^>]+>', '', author)  # Удаляем email в <>
            author = re.sub(r'\([^)]+\)', '', author)  # Удаляем скобочные комментарии
            author = re.sub(r'@\w+', '', author)  # Удаляем @упоминания
            
            return author.strip()
        
        # Пробуем извлечь из title
        title = getattr(entry, 'title', '')
        if ':' in title:
            author_part = title.split(':', 1)[0]
            return self._clean_html(author_part.strip())
            
        return None
    
    def _cleanup_cache(self):
        """Очистка кеша обработанных ID"""
        if len(self.processed_ids) > self.max_cache_size:
            # Оставляем только последние записи
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
