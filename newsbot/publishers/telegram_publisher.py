# newsbot/publishers/telegram_publisher.py
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from telethon import TelegramClient, errors
from telethon.tl.types import InputMediaDocument, InputMediaPhoto

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
                
                # Небольшая задержка между выводом
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
        
        # Основной текст
        if hasattr(news_item, 'formatted_text') and news_item.formatted_text:
            # Убираем HTML теги для консоли
            text = self._strip_html(news_item.formatted_text)
            print(f"📝 Текст:\n{text}")
        
        # Информация о медиа
        if hasattr(news_item, 'media_items') and news_item.media_items:
            print(f"\n🖼️ Медиа: {len(news_item.media_items)} файлов")
            for i, media in enumerate(news_item.media_items[:3], 1):
                print(f"  {i}. {media.type}: {media.url[:60]}...")
        
        # Метаданные
        if hasattr(news_item, 'metadata') and news_item.metadata:
            print(f"\n📊 Метаданные:")
            for key, value in news_item.metadata.items():
                if key in ['filter_score', 'confidence']:
                    print(f"  {key}: {value:.2f}")
                elif isinstance(value, (list, tuple)) and len(value) > 0:
                    print(f"  {key}: {', '.join(map(str, value[:5]))}")
                elif value:
                    print(f"  {key}: {value}")
        
        # Анализ AI
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
        
        # Источник
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
        
        media_info = ""
        if hasattr(news_item, 'media_items') and news_item.media_items:
            media_info = f" [🖼️ {len(news_item.media_items)}]"
        
        print(f"[{index}] {time_str} | {source}: {text_preview}{media_info}")
    
    def _strip_html(self, text: str) -> str:
        """Удаление HTML тегов из текста"""
        # Простая очистка HTML тегов
        text = re.sub(r'<[^>]+>', '', text)
        # Замена HTML сущностей
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
    """Публикатор для Telegram с поддержкой медиа"""
    
    def __init__(self, 
                 client: TelegramClient,
                 channel: str,
                 max_media_per_post: int = 4,
                 parse_mode: str = 'html',
                 rate_limit_delay: float = 1.0,
                 always_include_media: bool = True):
        
        self.client = client
        self.channel = channel
        self.max_media_per_post = max_media_per_post
        self.parse_mode = parse_mode
        self.rate_limit_delay = rate_limit_delay
        self.always_include_media = always_include_media  # Всегда публиковать с медиа если есть
        
        self.is_connected = False
        self.last_post_time = datetime.now() - timedelta(seconds=10)
        
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
        """Публикация новостей в Telegram"""
        try:
            await self.connect()
            
            if not news_items:
                logger.info("📭 Нет новостей для публикации в Telegram")
                return True
            
            success_count = 0
            for news_item in news_items:
                try:
                    await self._post_with_media(news_item)
                    success_count += 1
                    
                    # Задержка для избежания лимитов
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации новости: {e}")
                    continue
            
            logger.info(f"✅ Telegram: опубликовано {success_count}/{len(news_items)} новостей")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка публикатора Telegram: {e}")
            return False
    
    async def _post_with_media(self, news_item: ProcessedNews):
        """Публикация новости с медиа"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            # Получение медиа
            media = await self._prepare_media(news_item)
            
            # Публикация с медиа или без
            if media and self.always_include_media:
                await self._send_with_media(text, media)
                logger.debug(f"📤 Опубликовано с {len(media)} медиа")
            else:
                # Публикуем только текст
                await self.client.send_message(
                    entity=self.channel,
                    message=text,
                    parse_mode=self.parse_mode,
                    link_preview=False
                )
                logger.debug("📤 Опубликовано текстовое сообщение")
            
            # Обновление времени последней публикации
            self.last_post_time = datetime.now()
            
        except errors.FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"⚠️ Flood wait: ждем {wait_time} секунд")
            await asyncio.sleep(wait_time)
            await self._post_with_media(news_item)  # Повторная попытка
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации в Telegram: {e}")
            raise
    
    async def _send_with_media(self, text: str, media_list: List):
        """Отправка сообщения с медиа"""
        if len(media_list) == 1:
            # Одно медиа с подписью
            await self.client.send_file(
                entity=self.channel,
                file=media_list[0],
                caption=text,
                parse_mode=self.parse_mode,
                link_preview=False
            )
        else:
            # Галерея медиа
            await self.client.send_file(
                entity=self.channel,
                file=media_list,
                caption=text,
                parse_mode=self.parse_mode,
                link_preview=False
            )
    
    async def _prepare_media(self, news_item: ProcessedNews) -> Optional[List]:
        """Подготовка медиафайлов для публикации"""
        # Используем media_items из ProcessedNews или из source_item
        media_items = []
        
        # 1. Проверяем media_items в ProcessedNews
        if hasattr(news_item, 'media_items') and news_item.media_items:
            media_items = news_item.media_items
        # 2. Проверяем media_items в source_item
        elif hasattr(news_item.source_item, 'media_items') and news_item.source_item.media_items:
            media_items = news_item.source_item.media_items
        # 3. Проверяем старый формат media_urls
        elif hasattr(news_item.source_item, 'media_urls') and news_item.source_item.media_urls:
            # Конвертируем media_urls в media_items
            media_items = self._convert_media_urls_to_items(news_item.source_item.media_urls)
        
        if not media_items:
            return None
        
        # Ограничиваем количество медиа
        media_items = media_items[:self.max_media_per_post]
        
        # Создаем Telegram медиа объекты
        telegram_media = []
        for media_item in media_items:
            try:
                telegram_media.append(self._create_telegram_media(media_item))
            except Exception as e:
                logger.warning(f"⚠️ Не удалось создать медиа объект для {media_item.url}: {e}")
                continue
        
        return telegram_media if telegram_media else None
    
    def _convert_media_urls_to_items(self, media_urls: List[str]) -> List[MediaItem]:
        """Конвертация старых media_urls в MediaItem"""
        media_items = []
        
        for url in media_urls[:self.max_media_per_post]:
            url_lower = url.lower()
            
            # Определяем тип медиа по расширению
            if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                media_type = 'photo'
            elif any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm']):
                media_type = 'document'  # Используем документ для видео
            else:
                media_type = 'document'
            
            media_items.append(MediaItem(
                url=url,
                type=media_type
            ))
        
        return media_items
    
    def _create_telegram_media(self, media_item: MediaItem):
        """Создание Telegram медиа объекта"""
        if media_item.type == 'photo':
            return InputMediaPhoto(media_item.url)
        else:
            # Для video и document используем InputMediaDocument
            return InputMediaDocument(media_item.url)
    
    async def test_connection(self) -> bool:
        """Тестирование соединения с Telegram"""
        try:
            await self.connect()
            
            # Проверка доступности канала
            entity = await self.client.get_entity(self.channel)
            logger.info(f"✅ Telegram канал доступен: {entity.title}")
            
            # Тестовая публикация (опционально)
            try:
                test_message = "🤖 Бот запущен и готов к работе!"
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

    async def publish_with_media(self, news_items: List[ProcessedNews]) -> bool:
        """Публикация новостей с медиа если есть, без - если нет"""
        try:
            await self.connect()
            
            if not news_items:
                logger.info("📭 Нет новостей для публикации в Telegram")
                return True
            
            success_count = 0
            for news_item in news_items:
                try:
                    # Получаем медиа если есть
                    media_items = []
                    if hasattr(news_item, 'media_items') and news_item.media_items:
                        # Конвертируем MediaItem в Telegram медиа
                        for media_item in news_item.media_items[:self.max_media_per_post]:
                            try:
                                telegram_media = self._create_telegram_media(media_item)
                                media_items.append(telegram_media)
                            except Exception as e:
                                logger.warning(f"⚠️ Не удалось создать медиа объект: {e}")
                    
                    # Публикуем
                    await self._post_with_or_without_media(news_item, media_items)
                    success_count += 1
                    
                    # Задержка для избежания лимитов
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка публикации новости: {e}")
                    continue
            
            logger.info(f"✅ Telegram: опубликовано {success_count}/{len(news_items)} новостей")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка публикатора Telegram: {e}")
            return False
    
    async def _post_with_or_without_media(self, news_item: ProcessedNews, media_items: List):
        """Публикация новости с медиа если есть, без - если нет"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            # Если есть медиа - публикуем с медиа
            if media_items:
                if len(media_items) == 1:
                    # Одно медиа с подписью
                    await self.client.send_file(
                        entity=self.channel,
                        file=media_items[0],
                        caption=text,
                        parse_mode=self.parse_mode,
                        link_preview=False
                    )
                else:
                    # Галерея медиа
                    await self.client.send_file(
                        entity=self.channel,
                        file=media_items,
                        caption=text,
                        parse_mode=self.parse_mode,
                        link_preview=False
                    )
                logger.info(f"📤 Опубликовано с {len(media_items)} медиа")
            else:
                # Нет медиа - публикуем только текст
                await self.client.send_message(
                    entity=self.channel,
                    message=text,
                    parse_mode=self.parse_mode,
                    link_preview=False
                )
                logger.info("📤 Опубликовано текстовое сообщение")
            
            # Обновление времени последней публикации
            self.last_post_time = datetime.now()
            
        except errors.FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"⚠️ Flood wait: ждем {wait_time} секунд")
            await asyncio.sleep(wait_time)
            await self._post_with_or_without_media(news_item, media_items)  # Повторная попытка
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации в Telegram: {e}")
            raise
    
    def _create_telegram_media(self, media_item):
        """Создание Telegram медиа объекта"""
        from telethon.tl.types import InputMediaDocument, InputMediaPhoto
        
        if media_item.type == 'photo':
            return InputMediaPhoto(media_item.url)
        else:
            # Для video и document используем InputMediaDocument
            return InputMediaDocument(media_item.url)




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
                    logger.info(f"✅ {name}: успешно опубликовано {len(news_items)} новостей")
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