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
        
        # МЕДИА ИНФОРМАЦИЯ - в начале
        if hasattr(news_item, 'media_items') and news_item.media_items:
            media_count = len(news_item.media_items)
            print(f"📸 МЕДИА: {media_count} файлов")
            for i, media in enumerate(news_item.media_items[:3], 1):
                media_type = media.type if hasattr(media, 'type') else 'unknown'
                print(f"  {i}. {media_type.upper()}: {media.url[:60]}...")
        else:
            print("📭 НЕТ МЕДИА (текстовый пост)")
        
        # Основной текст
        if hasattr(news_item, 'formatted_text') and news_item.formatted_text:
            # Убираем HTML теги для консоли
            text = self._strip_html(news_item.formatted_text)
            print(f"\n📝 Текст:\n{text}")
        
        # Метаданные
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
        
        # Медиа информация
        media_count = len(news_item.media_items) if hasattr(news_item, 'media_items') and news_item.media_items else 0
        if media_count > 0:
            media_info = f" [📸 {media_count}]"
        else:
            media_info = " [📭 текст]"
        
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
        self.always_include_media = always_include_media  # Публиковать с медиа если есть
        
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
                    # Проверяем наличие медиа
                    media_items = []
                    if hasattr(news_item, 'media_items') and news_item.media_items:
                        media_items = news_item.media_items
                        logger.info(f"📤 Публикация поста {i+1}/{len(news_items)} с {len(media_items)} медиа...")
                    else:
                        logger.info(f"📤 Публикация поста {i+1}/{len(news_items)} (текстовый пост)...")
                    
                    # Публикуем в зависимости от наличия медиа
                    if media_items:
                        await self._post_with_media(news_item, media_items)
                        logger.info(f"✅ Пост успешно опубликован с {len(media_items)} медиа")
                    else:
                        await self._post_without_media(news_item)
                        logger.info(f"✅ Текстовый пост успешно опубликован")
                    
                    success_count += 1
                    
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
                    logger.error(f"❌ Ошибка публикации новости: {e}")
                    failed_count += 1
                    continue
            
            logger.info(f"📊 Итог публикации: {success_count} успешно, {failed_count} неудачно")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка публикатора Telegram: {e}")
            return False
    
    async def _post_with_media(self, news_item: ProcessedNews, media_items: List[MediaItem]):
        """Публикация новости с медиа"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            # Подготовка медиа
            telegram_media = await self._prepare_media(media_items)
            
            if telegram_media:
                logger.info(f"🖼️ Отправка поста с {len(telegram_media)} медиа...")
                await self._send_with_media(text, telegram_media)
            else:
                # Если не удалось подготовить медиа, отправляем текст
                logger.warning("⚠️ Не удалось подготовить медиа, отправляем как текст")
                await self._post_without_media(news_item)
            
            # Обновление времени последней публикации
            self.last_post_time = datetime.now()
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации поста с медиа: {e}")
            raise
    
    async def _post_without_media(self, news_item: ProcessedNews):
        """Публикация новости без медиа"""
        try:
            text = news_item.formatted_text
            
            # Ограничение длины текста для Telegram
            if len(text) > 4000:
                text = text[:3900] + "...\n\n[текст сокращен]"
            
            await self.client.send_message(
                entity=self.channel,
                message=text,
                parse_mode=self.parse_mode,
                link_preview=False
            )
            logger.debug("📝 Текстовое сообщение опубликовано")
            
        except Exception as e:
            logger.error(f"❌ Ошибка публикации текстового сообщения: {e}")
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
    
    async def _prepare_media(self, media_items: List[MediaItem]) -> Optional[List]:
        """Подготовка медиафайлов для публикации"""
        if not media_items:
            logger.warning("⚠️ Список медиа элементов пуст")
            return None
        
        # Ограничиваем количество медиа
        media_items = media_items[:self.max_media_per_post]
        
        # Создаем Telegram медиа объекты
        telegram_media = []
        for i, media_item in enumerate(media_items):
            try:
                telegram_media.append(self._create_telegram_media(media_item))
                logger.debug(f"  ✅ Медиа {i+1}: {media_item.type} - {media_item.url[:60]}...")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось создать медиа объект для {media_item.url}: {e}")
                continue
        
        if telegram_media:
            logger.info(f"✅ Подготовлено {len(telegram_media)} медиа объектов")
            return telegram_media
        else:
            logger.error("❌ Не удалось создать ни одного медиа объекта")
            return None
    
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
            
            # Тестовая публикация
            try:
                test_message = "🤖 Бот запущен и готов к работе! (публикует все посты)"
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
                    # Подсчитываем медиа
                    with_media = sum(1 for item in news_items if item.media_items)
                    without_media = len(news_items) - with_media
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
