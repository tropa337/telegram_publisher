import asyncio
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from telethon import TelegramClient, errors

from newsbot.types import MediaItem, ProcessedNews

logger = logging.getLogger(__name__)


class ConsolePublisher:
    """Публикатор для вывода новостей в консоль"""
    
    def __init__(self, pretty_print: bool = True, max_items: int = 10):
        self.pretty_print = pretty_print
        self.max_items = max_items
        self.counter = 0
        
    async def publish(self, news_items: List[ProcessedNews]) -> bool:
        """Публикация новостей в консоль"""
        try:
            if not news_items:
                logger.info("📭 Нет новостей для публикации")
                return True
                
            for i, news_item in enumerate(news_items[:self.max_items]):
                await self._print_news(news_item, i + 1)
                self.counter += 1
                
                if i < len(news_items) - 1:
                    await asyncio.sleep(0.1)
                    
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации в консоль: {e}")
            return False
    
    async def _print_news(self, news_item: ProcessedNews, index: int):
        """Вывод одной новости в консоль"""
        try:
            if self.pretty_print:
                self._print_pretty(news_item, index)
            else:
                self._print_simple(news_item, index)
                
        except Exception as e:
            logger.error(f"❌ Ошибка форматирования новости: {e}")
    
    def _print_pretty(self, news_item: ProcessedNews, index: int):
        """Красивый вывод в консоль"""
        print("\n" + "="*80)
        print(f"📰 НОВОСТЬ #{index} (всего: {self.counter + 1})")
        print("="*80)
        
        if hasattr(news_item, 'media_items') and news_item.media_items:
            media_count = len(news_item.media_items)
            print(f"📸 МЕДИА: {media_count} файлов")
            for i, media in enumerate(news_item.media_items[:3], 1):
                media_type = media.type if hasattr(media, 'type') else 'unknown'
                print(f"  {i}. {media_type.upper()}: {media.url[:60]}...")
        else:
            print("📭 НЕТ МЕДИА (текстовый пост)")
        
        if hasattr(news_item, 'formatted_text') and news_item.formatted_text:
            text = self._strip_html(news_item.formatted_text)
            print(f"\n📝 Текст:\n{text}")
        
        if hasattr(news_item, 'metadata') and news_item.metadata:
            print(f"\n📊 Метаданные:")
            for key, value in news_item.metadata.items():
                if key == 'media_count':
                    print(f"  📸 Количество медиа: {value}")
                elif key == 'has_media':
                    status = "✅ ЕСТЬ" if value else "❌ НЕТ"
                    print(f"  📸 Наличие медиа: {status}")
                elif key in ['filter_score', 'confidence']:
                    print(f"  {key}: {value:.2f}")
                elif isinstance(value, (list, tuple)) and len(value) > 0:
                    print(f"  {key}: {', '.join(map(str, value[:5]))}")
                elif value:
                    print(f"  {key}: {value}")
        
        if hasattr(news_item, 'analysis'):
            analysis = news_item.analysis
            print(f"\n🤖 AI Анализ:")
            print(f"  Актуальность: {'✅ Да' if analysis.is_relevant else '❌ Нет'}")
            if analysis.confidence:
                print(f"  Уверенность: {analysis.confidence:.2f}")
            if hasattr(analysis, 'market_impact'):
                print(f"  Влияние на рынок: {analysis.market_impact}")
            if analysis.tags:
                print(f"  Теги: {', '.join(analysis.tags)}")
        
        if hasattr(news_item, 'source_item') and news_item.source_item:
            source = news_item.source_item
            print(f"\n📡 Источник: {source.source}")
            if source.author:
                print(f"  Автор: {source.author}")
            if source.url:
                print(f"  URL: {source.url}")
            print(f"  Время: {source.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        print("="*80 + "\n")
    
    def _print_simple(self, news_item: ProcessedNews, index: int):
        """Простой вывод в консоль"""
        source = getattr(news_item.source_item, 'source', 'Unknown')
        time_str = news_item.source_item.created_at.strftime('%H:%M') if hasattr(news_item, 'source_item') else ''
        
        text_preview = ""
        if hasattr(news_item, 'formatted_text') and news_item.formatted_text:
            text = self._strip_html(news_item.formatted_text)
            text_preview = text[:100] + "..." if len(text) > 100 else text
        
        media_count = len(news_item.media_items) if hasattr(news_item, 'media_items') and news_item.media_items else 0
        if media_count > 0:
            media_info = f" [📸 {media_count}]"
        else:
            media_info = " [📭 текст]"
        
        print(f"[{index}] {time_str} | {source}: {text_preview}{media_info}")
    
    def _strip_html(self, text: str) -> str:
        """Удаление HTML тегов из текста"""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&amp;', '&').replace('&quot;', '"')
        text = text.replace('&#39;', "'").replace('&nbsp;', ' ')
        return text.strip()
    
    async def test_connection(self) -> bool:
        """Тестирование соединения (всегда успешно для консоли)"""
        print("✅ Консольный публикатор готов к работе")
        return True
    
    async def close(self):
        """Закрытие публикатора (ничего не делает для консоли)"""
        print("📴 Консольный публикатор закрыт")


class TelegramPublisher:
    """Публикатор для Telegram с улучшенной поддержкой медиа"""
    
    def __init__(self,
                 client: TelegramClient,
                 channel: str,
                 max_media_per_post: int = 4,
                 parse_mode: str = 'html',
                 rate_limit_delay: float = 1.0,
                 min_gap_seconds: int = 90,
                 always_include_media: bool = True):
        
        self.client = client
        self.channel = channel
        self.max_media_per_post = max_media_per_post
        self.parse_mode = parse_mode
        self.rate_limit_delay = rate_limit_delay
        self.min_gap_seconds = int(min_gap_seconds) if min_gap_seconds else 0
        self.always_include_media = always_include_media
        
        self.is_connected = False
        self.last_post_time = datetime.now() - timedelta(seconds=10)
        
        self.media_stats = {
            'total_attempted': 0,
            'successful': 0,
            'failed': 0,
            'by_type': {}
        }
        
    async def connect(self):
        """Подключение к Telegram"""
        if not self.is_connected:
            try:
                await self.client.start()
                self.is_connected = True
                logger.info(f"✅ Telegram подключен к каналу: {self.channel}")
            except Exception as e:
                logger.error(f"❌ Ошибка подключения Telegram: {e}")
                raise
    
    async def publish(self, news_items: List[ProcessedNews]) -> bool:
        """Публикация новостей в Telegram (и с медиа, и без)"""
        try:
            await self.connect()
            
            if not news_items:
                logger.info("📭 Нет новостей для публикации в Telegram")
                return True
            
            success_count = 0
            failed_count = 0
            
            for i, news_item in enumerate(news_items):
                try:
                    logger.info(f"📤 Начало публикации поста {i+1}/{len(news_items)}")
                    
                    # Проверяем наличие медиа
                    media_items = []
                    if hasattr(news_item, 'media_items') and news_item.media_items:
                        media_items = news_item.media_items
                        logger.info(f"📸 Пост имеет {len(media_items)} медиа-элементов")
                        self.media_stats['total_attempted'] += len(media_items)
                        
                        # Детальное логирование каждого медиа
                        for idx, media in enumerate(media_items):
                            logger.info(f"  Медиа {idx+1}: {media.type} - {media.url[:100]}")
                    else:
                        logger.info(f"📝 Пост без медиа (чистый текст)")
                    
                    # Минимальный gap между постами (чтобы не спамить канал)
                    try:
                        now = datetime.now()
                        gap = (now - self.last_post_time).total_seconds()
                        if self.min_gap_seconds and gap < self.min_gap_seconds:
                            need_sleep = float(self.min_gap_seconds - gap)
                            logger.info(f"⏳ Gap {gap:.0f}s < {self.min_gap_seconds}s, спим {need_sleep:.0f}s")
                            await asyncio.sleep(need_sleep)
                    except Exception:
                        pass

                    # Публикуем в зависимости от наличия медиа
                    if media_items:
                        result = await self._post_with_media(news_item, media_items)
                        if result:
                            logger.info(f"✅ Пост успешно опубликован с {len(media_items)} медиа")
                            success_count += 1
                        else:
                            logger.warning(f"⚠️ Не удалось опубликовать с медиа, пробуем без...")
                            # Пробуем опубликовать без медиа
                            if await self._post_without_media(news_item):
                                logger.info(f"✅ Текстовый пост успешно опубликован")
                                success_count += 1
                            else:
                                failed_count += 1
                    else:
                        if await self._post_without_media(news_item):
                            logger.info(f"✅ Текстовый пост успешно опубликован")
                            success_count += 1
                        else:
                            failed_count += 1
                    
                    # Задержка для избежания лимитов
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except errors.FloodWaitError as e:
                    wait_time = e.seconds
                    logger.warning(f"⚠️ Flood wait: ждем {wait_time} секунд")
                    await asyncio.sleep(wait_time)
                    # Повторная попытка
                    try:
                        if hasattr(news_item, 'media_items') and news_item.media_items:
                            await self._post_with_media(news_item, news_item.media_items)
                        else:
                            await self._post_without_media(news_item)
                        success_count += 1
                        logger.info(f"✅ Пост опубликован после flood wait")
                    except Exception as retry_e:
                        logger.error(f"❌ Ошибка при повторной попытке: {retry_e}")
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации новости: {e}", exc_info=True)
                    failed_count += 1
                    continue
            
            logger.info(f"📊 Итог публикации: {success_count} успешно, {failed_count} неудачно")
            
            # Логируем статистику медиа
            if self.media_stats['total_attempted'] > 0:
                success_rate = (self.media_stats['successful'] / self.media_stats['total_attempted']) * 100
                logger.info(f"📊 Статистика медиа: {self.media_stats['successful']}/{self.media_stats['total_attempted']} успешно ({success_rate:.1f}%)")
                for media_type, count in self.media_stats['by_type'].items():
                    logger.info(f"  {media_type}: {count}")
            
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка публикатора Telegram: {e}", exc_info=True)
            return False
    
    async def _post_with_media(self, news_item: ProcessedNews, media_items: List[MediaItem]) -> bool:
        """Публикация новости с медиа"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            # Подготовка медиа с улучшенной обработкой
            telegram_media = await self._prepare_media(media_items)
            
            if telegram_media and len(telegram_media) > 0:
                logger.info(f"🖼️ Отправка поста с {len(telegram_media)} медиа...")
                await self._send_with_media(text, telegram_media)
                
                # Обновление статистики
                self.media_stats['successful'] += len(telegram_media)
                
                # Обновление времени последней публикации
                self.last_post_time = datetime.now()
                return True
            else:
                logger.warning("⚠️ Не удалось подготовить медиа")
                return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации поста с медиа: {e}", exc_info=True)
            return False
    
    async def _post_without_media(self, news_item: ProcessedNews) -> bool:
        """Публикация новости без медиа"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            logger.debug(f"📝 Отправка текстового сообщения ({len(text)} символов)")
            await self.client.send_message(
                entity=self.channel,
                message=text,
                parse_mode=self.parse_mode,
                link_preview=False
            )
            logger.debug("📝 Текстовое сообщение опубликовано")
            
            self.last_post_time = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации текстового сообщения: {e}")
            return False
    
    async def _send_with_media(self, text: str, media_list: List):
        """Отправка сообщения с медиа"""
        try:
            if len(media_list) == 1:
                # Одно медиа с подписью
                logger.info(f"📤 Отправка 1 медиа с подписью")
                await self.client.send_file(
                    entity=self.channel,
                    file=media_list[0],
                    caption=text,
                    parse_mode=self.parse_mode,
                    link_preview=False,
                    force_document=False
                )
                logger.debug(f"✅ Отправлено одно медиа")
            else:
                # Галерея медиа
                logger.info(f"📤 Отправка {len(media_list)} медиа в альбоме")
                await self.client.send_file(
                    entity=self.channel,
                    file=media_list,
                    caption=text,
                    parse_mode=self.parse_mode,
                    link_preview=False,
                    force_document=False
                )
                logger.debug(f"✅ Отправлено {len(media_list)} медиа в альбоме")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка отправки медиа: {e}", exc_info=True)
            raise
    
    def _ext_from_content_type(self, content_type: str) -> str:
        ct = (content_type or "").split(";")[0].strip().lower()
        mapping = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        return mapping.get(ct, "bin")

    async def _download_media_filelike(self, url: str, *, idx: int) -> Union[io.BytesIO, str]:
        """
        Скачивает *картинку* в память и возвращает BytesIO с именем файла.
        Это помогает Telegram/Telethon отправлять её как *фото* (inline), а не как документ,
        когда исходная ссылка не содержит расширение (часто у Twitter CDN).
        """
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        logger.warning(f"Не удалось скачать медиа (HTTP {resp.status}): {url}")
                        return url

                    content_type = resp.headers.get("Content-Type", "")
                    data = await resp.read()

            # Только для изображений. Видео/прочее оставляем ссылкой.
            if not (content_type or "").lower().startswith("image/"):
                return url

            ext = self._ext_from_content_type(content_type)
            bio = io.BytesIO(data)
            bio.name = f"image_{idx}.{ext}"  # Telethon использует name как filename/extension
            return bio

        except Exception as e:
            logger.warning(f"Ошибка скачивания медиа: {e} ({url})")
            return url

    async def _prepare_media(self, media_items: List[MediaItem]) -> Optional[List]:
        """Подготовка медиафайлов для публикации"""
        if not media_items:
            logger.warning("⚠️ Список медиа элементов пуст")
            return None

        # Ограничиваем количество медиа
        media_items = media_items[: self.max_media_per_post]

        media_list: List[Union[str, io.BytesIO]] = []

        for idx, item in enumerate(media_items):
            url = getattr(item, "url", None)
            if not url:
                continue

            # Normalize URL (Twitter CDN etc.)
            url = self._normalize_media_url(url)

            # Check accessibility first
            if not await self._is_media_accessible(url):
                logger.warning(f"⚠️ Медиа недоступно, пропускаем: {url}")
                continue

            media_type = (getattr(item, "type", "") or "").lower()

            # Для изображений скачиваем в память, чтобы Telegram показал как фото в посте
            if media_type in {"image", "photo", "picture"}:
                media_list.append(await self._download_media_filelike(url, idx=idx))
            else:
                media_list.append(url)

        if not media_list:
            logger.warning("⚠️ Не удалось подготовить ни одного медиа")
            return None

        logger.debug(f"✅ Подготовлено медиа: {len(media_list)} шт.")
        return media_list
    async def _is_media_accessible(self, url: str) -> bool:
        """Проверка доступности медиа по URL"""
        try:
            # Пропускаем данные URL (data:image/)
            if url.startswith('data:'):
                return True
            
            # Для Twitter URL всегда возвращаем True
            if any(domain in url.lower() for domain in ['twitter.com', 'twimg.com', 'pic.twitter.com', 'x.com']):
                return True
            
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession() as session:
                async with session.head(url, timeout=timeout, allow_redirects=True) as response:
                    status = response.status
                    
                    if status == 200:
                        return True
                    else:
                        logger.warning(f"⚠️ Медиа недоступно, статус: {status}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Таймаут при проверке медиа: {url[:60]}...")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки медиа {url[:60]}...: {e}")
            return False
    
    def _normalize_media_url(self, url: str) -> str:
        """Нормализация URL для Telethon.

        Важно: Telethon умеет отправлять файлы по URL напрямую.
        Для Twitter картинок часто нужно добавить format/name, иначе Telegram
        получает html-страницу вместо файла.
        """
        if not url:
            return url

        u = url.strip()
        low = u.lower()

        # Twitter images: приводим к прямой ссылке на файл
        # Примеры:
        # - https://pbs.twimg.com/media/....?format=jpg&name=large
        # - https://pbs.twimg.com/media/....jpg
        if 'pbs.twimg.com/media/' in low and 'format=' not in low:
            # если расширение уже есть — оставляем
            if not any(low.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                # по умолчанию jpg large
                u = u + ('&' if '?' in u else '?') + 'format=jpg&name=large'

        # twitter thumbnail (video_thumb) — это картинка, но иногда без format
        if 'pbs.twimg.com/ext_tw_video_thumb/' in low and 'format=' not in low:
            u = u + ('&' if '?' in u else '?') + 'format=jpg&name=large'

        return u
    
    async def test_connection(self) -> bool:
        """Тестирование соединения с Telegram"""
        try:
            await self.connect()
            
            entity = await self.client.get_entity(self.channel)
            logger.info(f"✅ Telegram канал доступен: {entity.title}")
            
            try:
                test_message = "🤖 Бот запущен и готов к работе!\n\n" \
                              f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                await self.client.send_message(entity, test_message)
                logger.info(f"✅ Тестовая публикация успешна")
            except Exception as e:
                logger.warning(f"⚠️ Тестовая публикация не удалась: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка тестирования Telegram: {e}")
            return False
    
    async def close(self):
        """Закрытие соединения с Telegram"""
        try:
            if self.is_connected:
                await self.client.disconnect()
                self.is_connected = False
                logger.info("📴 Telegram соединение закрыто")
        except Exception as e:
            logger.error(f"❌ Ошибка при закрытии Telegram: {e}")


class PublisherManager:
    """Менеджер публикаторов"""
    
    def __init__(self):
        self.publishers: Dict[str, Any] = {}
        
    def add_publisher(self, name: str, publisher):
        """Добавление публикатора"""
        self.publishers[name] = publisher
        logger.info(f"✅ Добавлен публикатор: {name}")
    
    async def publish_all(self, news_items: List[ProcessedNews]) -> Dict[str, bool]:
        """Публикация через всех публикаторов"""
        results = {}
        
        if not news_items:
            logger.warning("⚠️ Нет новостей для публикации")
            return {name: False for name in self.publishers}
        
        for name, publisher in self.publishers.items():
            try:
                result = await publisher.publish(news_items)
                results[name] = result
                
                if result:
                    with_media = sum(1 for item in news_items if item.media_items)
                    without_media = len(news_items) - with_media
                    
                    if hasattr(publisher, 'media_stats'):
                        media_stats = publisher.media_stats
                        total_media = media_stats['successful']
                        logger.info(f"✅ {name}: опубликовано {len(news_items)} новостей "
                                   f"({with_media} с медиа, {without_media} текстовых, "
                                   f"{total_media} медиафайлов успешно)")
                    else:
                        logger.info(f"✅ {name}: опубликовано {len(news_items)} новостей "
                                   f"({with_media} с медиа, {without_media} текстовых)")
                else:
                    logger.warning(f"⚠️ {name}: ошибка публикации")
                    
            except Exception as e:
                logger.error(f"❌ Ошибка публикатора {name}: {e}")
                results[name] = False
        
        return results
    
    async def test_all_connections(self) -> Dict[str, bool]:
        """Тестирование всех соединений"""
        results = {}
        
        for name, publisher in self.publishers.items():
            try:
                if hasattr(publisher, 'test_connection'):
                    result = await publisher.test_connection()
                else:
                    logger.warning(f"⚠️ Публикатор {name} не поддерживает тестирование")
                    result = True
                    
                results[name] = result
                
            except Exception as e:
                logger.error(f"❌ Ошибка тестирования {name}: {e}")
                results[name] = False
        
        return results
    
    async def close_all(self):
        """Закрытие всех публикаторов"""
        for name, publisher in self.publishers.items():
            try:
                if hasattr(publisher, 'close'):
                    await publisher.close()
                logger.info(f"📴 Закрыт публикатор: {name}")
            except Exception as e:
                logger.error(f"❌ Ошибка закрытия {name}: {e}")