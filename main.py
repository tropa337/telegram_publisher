import asyncio
import hashlib
import logging
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Set

from telethon import TelegramClient

from newsbot.ai import get_analyzer
from newsbot.cache import NewsCache
from newsbot.config import get_config
from newsbot.dedup import DeduplicationEngine
from newsbot.filters import StrictMarketFilter
from newsbot.market_filter import looks_market_moving
from newsbot.media_handler import MediaHandler
from newsbot.publishers.telegram_publisher import (ConsolePublisher,
                                                   PublisherManager,
                                                   TelegramPublisher)
from newsbot.simple_formatter import SimpleFormatter
from newsbot.sources.twitter_source import TwitterRSSSource
from newsbot.sources.telegram_source import TelegramSource
from newsbot.types import NewsItem, ProcessedNews

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('newsbot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Пропускаем важные события без явного движения цены
ALLOW_WITHOUT_PRICE = re.compile(r"\b(sec|cftc|lawsuit|indict|arrest|sanction|hack|exploit|drain|coinbase\s+down|outage|offline|halt|suspend)\b", re.I)


class QualityFilter:
    """Фильтр качества контента"""
    
    def __init__(self):
        self.min_length = 20
        self.max_repetitions = 3
        self.min_unique_words = 5
    
    def check(self, text: str) -> bool:
        """Проверка качества текста"""
        if not text or len(text.strip()) < self.min_length:
            return False
        
        text_lower = text.lower()
        
        # Проверка на спам-паттерны
        spam_patterns = [
            r'buy\s+now',
            r'click\s+here',
            r'limited\s+time',
            r'100%\s+free',
            r'sign\s+up',
            r'join\s+now',
            r'exclusive\s+offer',
            r'double\s+your',
            r'make\s+money',
            r'earn\s+free'
        ]
        
        for pattern in spam_patterns:
            if re.search(pattern, text_lower):
                return False
        
        # Проверка на слишком много специальных символов
        special_chars = len(re.findall(r'[!@#$%^&*()_+=|<>?{}\[\]~-]', text))
        if special_chars > len(text) * 0.2:  # Более 20% спецсимволов
            return False
        
        # Проверка уникальности слов
        words = re.findall(r'\b\w{3,}\b', text_lower)
        unique_words = set(words)
        
        if len(unique_words) < self.min_unique_words:
            return False
        
        # Проверка на повторения
        word_counts = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1
            if word_counts[word] > self.max_repetitions:
                return False
        
        return True


class NewsBot:
    """Основной класс новостного бота с улучшенной дедупликацией"""
    
    def __init__(self):
        """Инициализация"""
        self.config = get_config()
        self.logger = logger
        
        # Компоненты
        self.cache = NewsCache()
        self.dedup = DeduplicationEngine()
        try:
            self.dedup.set_event_window_hours(self.config.EVENT_DEDUP_HOURS)
        except Exception:
            pass
        self.filter = StrictMarketFilter()
        self.quality_filter = QualityFilter()
        self.analyzer = get_analyzer()
        
        # Новые компоненты
        self.media_handler = MediaHandler()
        self.formatter = SimpleFormatter(
            channel_link="https://t.me/onchain_20226",
            partner_link="https://bingxzone.com/partner/McDuckk/",
        )
        
        # Источники и публикаторы
        self.sources = {}
        self.publisher_manager = PublisherManager()
        # Очередь новостей из Telegram-каналов (реактивный источник)
        self.tg_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._tg_client = None
        self._tg_source = None
        
        # Для дедупликации в реальном времени
        self.recent_news_hashes: Set[str] = set()
        self.recent_news_texts: List[str] = []
        self.max_recent_items = 50
        
        # Статистика
        self.stats = {
            'fetched': 0,
            'processed': 0,
            'published': 0,
            'rejected': 0,
            'rejected_reasons': {},
            'cycles': 0,
            'start_time': datetime.now(),
            'with_media': 0,
            'without_media': 0,
            'total_media_items': 0,
            'duplicates_filtered': 0,
            'quality_filtered': 0,
            'media_failed': 0
        }
        
        # Флаг работы
        self.running = False
        
        self._init_sources()
        self._init_publishers()
        
        self.logger.info("🤖 Бот инициализирован с улучшенной фильтрацией")
    
    def _init_sources(self):
        """Инициализация источников"""
        if self.config.TWITTER_RSS_FEEDS:
            twitter = TwitterRSSSource(
                feeds=self.config.TWITTER_RSS_FEEDS,
                auth_token=self.config.RSS_AUTH_TOKEN,
                poll_interval=self.config.POLL_INTERVAL_RSS
            )
            self.sources['twitter_rss'] = twitter
            self.logger.info(f"✅ RSS источники: {len(self.config.TWITTER_RSS_FEEDS)} фидов")
    

        if self.config.SOURCE_TG_CHANNELS:
            try:
                self._tg_client = TelegramClient(
                    'source_session',
                    self.config.TG_API_ID,
                    self.config.TG_API_HASH
                )
                self._tg_source = TelegramSource(
                    client=self._tg_client,
                    channels=self.config.SOURCE_TG_CHANNELS
                )
                self.sources['telegram'] = self._tg_source
                self.logger.info(f"✅ Telegram источники: {len(self.config.SOURCE_TG_CHANNELS)} каналов")
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации TelegramSource: {e}", exc_info=True)


    def _init_publishers(self):
        """Инициализация публикаторов"""
        # Консоль для отладки
        console = ConsolePublisher(pretty_print=True, max_items=5)
        self.publisher_manager.add_publisher('console', console)
        
        # Telegram - публикуем ВСЕ посты (с медиа и без)
        if self.config.TARGET_CHANNEL:
            try:
                client = TelegramClient(
                    'publisher_session',
                    self.config.TG_API_ID,
                    self.config.TG_API_HASH
                )
                telegram = TelegramPublisher(
                    client=client,
                    channel=self.config.TARGET_CHANNEL,
                    max_media_per_post=self.config.MAX_MEDIA_PER_POST,
                    rate_limit_delay=1.0,
                    min_gap_seconds=self.config.MIN_GAP_SECONDS,
                    always_include_media=True
                )
                self.publisher_manager.add_publisher('telegram', telegram)
                self.logger.info(f"✅ Telegram: {self.config.TARGET_CHANNEL} (публикуем все посты)")
            except Exception as e:
                self.logger.error(f"❌ Ошибка Telegram: {e}")
    
    def _create_news_hash(self, news_item: NewsItem) -> str:
        """Создание хеша для новости для дедупликации"""
        text = news_item.raw_text.lower()
        
        # Извлекаем ключевые числа (суммы в долларах)
        amounts = re.findall(r'\$[\d,.]+[mbk]?', text)
        amounts_str = ''.join(sorted(amounts))
        
        # Извлекаем основные сущности
        entities = []
        for word in ['bitcoin', 'btc', 'ethereum', 'eth', 'blackrock', 'coinbase', 
                     'binance', 'sec', 'etf', 'vitalik', 'saylor']:
            if word in text:
                entities.append(word)
        
        hash_content = f"{text[:200]}|{amounts_str}|{'|'.join(entities[:3])}"
        return hashlib.md5(hash_content.encode()).hexdigest()
    
    def _is_duplicate_news(self, news_item: NewsItem) -> bool:
        """Проверка, является ли новость дубликатом"""
        news_hash = self._create_news_hash(news_item)
        if news_hash in self.recent_news_hashes:
            return True
        
        text = news_item.raw_text.lower()
        amounts = set(re.findall(r'\$[\d,.]+[mbk]?', text))
        
        for recent_text in self.recent_news_texts[-10:]:
            recent_amounts = set(re.findall(r'\$[\d,.]+[mbk]?', recent_text.lower()))
            if amounts and recent_amounts and amounts == recent_amounts:
                similarity = SequenceMatcher(None, text[:200], recent_text[:200]).ratio()
                if similarity > 0.6:
                    return True
        
        return False
    
    def _add_to_recent_news(self, news_item: NewsItem):
        """Добавление новости в список недавних для дедупликации"""
        news_hash = self._create_news_hash(news_item)
        text = news_item.raw_text.lower()
        
        self.recent_news_hashes.add(news_hash)
        self.recent_news_texts.append(text)
        
        if len(self.recent_news_hashes) > self.max_recent_items:
            old_hash = next(iter(self.recent_news_hashes))
            self.recent_news_hashes.remove(old_hash)
        
        if len(self.recent_news_texts) > self.max_recent_items:
            self.recent_news_texts.pop(0)
    

    async def _start_reactive_sources(self):
        """Старт источников, которые пушат события (Telegram)."""
        if self._tg_source and self._tg_client:
            await self._tg_client.start()
            await self._tg_source.start_monitoring(self._on_tg_item)
            self.logger.info("📡 TelegramSource мониторинг запущен")

    async def _on_tg_item(self, item: NewsItem):
        """Callback из TelegramSource -> кладём в очередь."""
        try:
            self.tg_queue.put_nowait(item)
        except asyncio.QueueFull:
            self.logger.warning("⚠️ TG очередь переполнена, пропускаю новость")


    async def start(self):
        """Запуск бота в непрерывном режиме"""
        self.running = True
        self.logger.info("🚀 Запуск бота в непрерывном режиме...")
        await self._start_reactive_sources()
        
        poll_interval = self.config.POLL_INTERVAL_RSS
        
        cycle = 0
        while self.running:
            cycle += 1
            self.stats['cycles'] = cycle
            
            self.logger.info(f"🔄 Цикл #{cycle} (интервал: {poll_interval} сек)")
            
            try:
                await self.run_once()
                self.print_stats()
                
                if '--once' in sys.argv:
                    self.logger.info("📴 Режим --once: завершение работы")
                    break
                
                if self.running and cycle > 0:
                    self.logger.info(f"⏳ Ожидание {poll_interval} секунд до следующего цикла...")
                    await asyncio.sleep(poll_interval)
                    
            except KeyboardInterrupt:
                self.logger.info("🛑 Получен сигнал прерывания (Ctrl+C)")
                break
            except Exception as e:
                self.logger.error(f"💥 Ошибка в цикле #{cycle}: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def stop(self):
        """Остановка бота"""
        self.running = False
        self.logger.info("🛑 Остановка бота...")
    
    async def run_once(self):
        """Однократный запуск"""
        self.logger.info("📡 Начало сбора новостей...")
        
        news_items = []
        # 0) Сначала забираем новости из очереди Telegram (если есть)
        drained_tg = 0
        while True:
            try:
                tg_item = self.tg_queue.get_nowait()
                news_items.append(tg_item)
                drained_tg += 1
            except asyncio.QueueEmpty:
                break
        if drained_tg:
            self.logger.info(f"📥 telegram(realtime): {drained_tg} новостей")
            self.stats['fetched'] += drained_tg
        for name, source in self.sources.items():
            try:
                items = await source.fetch()
                if items:
                    self.logger.info(f"📥 {name}: {len(items)} новостей")
                    news_items.extend(items)
                    self.stats['fetched'] += len(items)
            except Exception as e:
                self.logger.error(f"❌ Ошибка источника {name}: {e}")
        
        if news_items:
            await self._process_and_publish(news_items)
        else:
            self.logger.info("📭 Новостей не найдено")
    
    async def _process_and_publish(self, news_items: List[NewsItem]):
        """Обработка и публикация ВСЕХ новостей (с медиа и без)"""
        processed = []
        
        counters = {
            'total': 0,
            'cache': 0,
            'duplicate': 0,
            'filter': 0,
            'market': 0,
            'quality': 0,
            'ai': 0,
            'passed': 0,
            'with_media': 0,
            'without_media': 0,
            'real_time_duplicate': 0,
            'media_failed': 0
        }
        
        items_to_process = news_items[:50]
        counters['total'] = len(items_to_process)
        
        self.logger.info(f"🔍 Обработка {counters['total']} новостей")
        
        for i, item in enumerate(items_to_process):
            try:
                self.logger.debug(f"Обработка новости {i+1}: {item.raw_text[:80]}...")
                
                # 1. Проверка кеша
                if self.cache.is_processed(item):
                    counters['cache'] += 1
                    self.logger.debug(f"Новость уже в кеше")
                    continue
                
                # 2. Проверка дубликатов в реальном времени
                if self._is_duplicate_news(item):
                    counters['real_time_duplicate'] += 1
                    self.stats['duplicates_filtered'] += 1
                    self.cache.mark_processed(item, 'rejected', 'real_time_duplicate')
                    self._record_rejection('real_time_duplicate')
                    self.logger.debug(f"Дубликат в реальном времени")
                    continue
                
                # 2.5 Семантическая дедупликация (MinHash)
                dedup_result = self.dedup.check(item)
                if dedup_result.is_duplicate:
                    counters['duplicate'] += 1
                    self.stats['duplicates_filtered'] += 1
                    self.stats['rejected'] += 1
                    self.cache.mark_processed(item, 'rejected', f"dedup_{dedup_result.reason}")
                    self._record_rejection('duplicate')
                    self.logger.debug(f"Дубликат (sem): {dedup_result.reason} sim={dedup_result.similarity:.2f}")
                    continue

                # 3. Проверка качества контента
                if not self.quality_filter.check(item.raw_text):
                    counters['quality'] += 1
                    self.stats['quality_filtered'] += 1
                    self.stats['rejected'] += 1
                    self.cache.mark_processed(item, 'rejected', 'low_quality')
                    self._record_rejection('low_quality')
                    self.logger.debug(f"Низкое качество контента")
                    continue
                
                # 4. Быстрая фильтрация
                filter_result = self.filter.quick_filter(item.raw_text)
                if not filter_result.passed:
                    self.cache.mark_processed(item, 'rejected', f'filter_{filter_result.reason[:20]}')
                    counters['filter'] += 1
                    self.stats['rejected'] += 1
                    self._record_rejection('filter')
                    self.logger.debug(f"Не прошла фильтр: {filter_result.reason}")
                    continue
                # 6. AI анализ
                try:
                    analyzed = await self.analyzer.analyze_news(item)
                    if not analyzed.is_relevant:
                        self.cache.mark_processed(item, 'rejected', 'ai_reject')
                        counters['ai'] += 1
                        self.stats['rejected'] += 1
                        self._record_rejection('ai_reject')
                        self.logger.debug(f"Отклонено AI")
                        continue
                except Exception as e:
                    self.logger.error(f"❌ Ошибка AI анализа: {e}")
                    continue
                

                # 5. Проверка движения рынка (после AI):
                #    - если нет явных цен/%, но AI пометил как сильное MACRO/REGULATION/ALERT — пропускаем
                structured = {}
                try:
                    if hasattr(analyzed, 'metadata') and isinstance(analyzed.metadata, dict):
                        structured = analyzed.metadata.get('structured') or {}
                except Exception:
                    structured = {}
                cat = str((structured.get('category') or (analyzed.metadata.get('category') if hasattr(analyzed, 'metadata') else '') or 'OTHER')).upper()
                try:
                    pr = int(float(structured.get('priority') or (analyzed.metadata.get('priority') if hasattr(analyzed, 'metadata') else 0) or 0))
                except Exception:
                    pr = 0
                allow_macro = (cat in {'MACRO','REGULATION','ALERT','EXCHANGE','ETF_FLOW'}) and pr >= 70
                if not allow_macro:
                    if not looks_market_moving(item.raw_text) and not ALLOW_WITHOUT_PRICE.search(item.raw_text):
                        self.cache.mark_processed(item, 'rejected', 'no_market_move')
                        counters['market'] += 1
                        self.stats['rejected'] += 1
                        self._record_rejection('no_market_move')
                        self.logger.debug(f"Нет движения рынка")
                        continue

                # 6.5 Event-key дедуп (анти-спам одинаковых событий 6-12ч)
                try:
                    event_key = ''
                    if hasattr(analyzed, 'metadata') and isinstance(analyzed.metadata, dict):
                        event_key = analyzed.metadata.get('event_key') or ''
                        # если лежит внутри structured
                        if not event_key and isinstance(analyzed.metadata.get('structured'), dict):
                            event_key = analyzed.metadata['structured'].get('event_key') or ''
                    if event_key and self.dedup.check_event_key(event_key):
                        self.cache.mark_processed(item, 'rejected', 'event_duplicate')
                        self.stats['rejected'] += 1
                        self._record_rejection('event_duplicate')
                        self.logger.debug(f"Event duplicate: {event_key}")
                        continue
                except Exception:
                    pass

                # 7. Проверка и логирование медиа
                media_items = []
                if hasattr(item, 'media_items') and item.media_items:
                    media_items = item.media_items
                    self.logger.info(f"📸 Новость имеет {len(media_items)} медиа-элементов")
                    self.stats['with_media'] += 1
                    self.stats['total_media_items'] += len(media_items)
                    counters['with_media'] += 1
                    
                    # Детальное логирование медиа
                    for idx, media in enumerate(media_items):
                        self.logger.info(f"  Медиа {idx+1}: {media.type} - {media.url[:100]}")
                else:
                    self.logger.info(f"📭 Новость без медиа (текстовый пост)")
                    self.stats['without_media'] += 1
                    counters['without_media'] += 1
                
                # 8. Форматирование текста
                try:
                    formatted_text = self.formatter.format_post(
                        ProcessedNews(
                            source_item=item,
                            analysis=analyzed,
                            formatted_text="",
                            media_items=media_items
                        )
                    )
                except Exception as e:
                    self.logger.error(f"❌ Ошибка форматирования: {e}")
                    continue
                
                # 9. Создание ProcessedNews
                proc_news = ProcessedNews(
                    source_item=item,
                    analysis=analyzed,
                    formatted_text=formatted_text,
                    media_items=media_items,
                    metadata={
                        'filter_score': filter_result.score,
                        'dedup_similarity': 0,
                        'processed_at': datetime.now().isoformat(),
                        'has_media': len(media_items) > 0,
                        'media_count': len(media_items),
                        'news_hash': self._create_news_hash(item),
                        'media_urls': [m.url for m in media_items] if media_items else []
                    }
                )
                
                processed.append(proc_news)
                counters['passed'] += 1
                self.stats['processed'] += 1
                self.cache.mark_processed(item, 'approved', 'passed_all_filters')
                
                # Добавляем в список недавних новостей для дедупликации
                self._add_to_recent_news(item)
                
                # Логируем результат с информацией о медиа
                if media_items:
                    media_info = ', '.join([f"{m.type}:{m.url[:30]}..." for m in media_items[:2]])
                    self.logger.info(f"✅ Новость прошла ({len(media_items)} медиа): {media_info}")
                else:
                    self.logger.info(f"✅ Новость прошла (без медиа): {item.raw_text[:100]}...")
                    
            except Exception as e:
                self.logger.error(f"❌ Ошибка обработки новости: {e}")
                continue
        
        # Вывод подробной статистики
        self.logger.info("📊 ДЕТАЛЬНАЯ СТАТИСТИКА ОТСЕВА:")
        self.logger.info(f"  Всего новостей: {counters['total']}")
        self.logger.info(f"  Уже в кеше: {counters['cache']}")
        self.logger.info(f"  Дубликаты в реальном времени: {counters['real_time_duplicate']}")
        self.logger.info(f"  Низкое качество: {counters['quality']}")
        self.logger.info(f"  Не прошли фильтр: {counters['filter']}")
        self.logger.info(f"  Нет движения рынка: {counters['market']}")
        self.logger.info(f"  Отклонены AI: {counters['ai']}")
        self.logger.info(f"  С МЕДИА: {counters['with_media']}")
        self.logger.info(f"  БЕЗ МЕДИА: {counters['without_media']}")
        self.logger.info(f"  УСПЕШНО ПРОШЛИ: {counters['passed']}")
        
        # 10. Сортировка по приоритету + лимит постов за цикл
        try:
            processed = sorted(
                processed,
                key=lambda x: float(getattr(getattr(x, 'analysis', None), 'metadata', {}).get('priority', 50)),
                reverse=True,
            )
        except Exception:
            pass

        max_cycle = getattr(self.config, 'MAX_POSTS_PER_CYCLE', 3) or 3
        processed_to_post = processed[:max_cycle]
        queued = processed[max_cycle:]
        if queued:
            self.logger.info(f"⏳ В очередь (на следующий цикл): {len(queued)}")

        # 11. Публикация
        if processed_to_post:
            self.logger.info(f"📤 Публикация {len(processed_to_post)} новостей (top за цикл)...")
            
            for name, publisher in self.publisher_manager.publishers.items():
                try:
                    result = await publisher.publish(processed_to_post)
                    
                    if result:
                        self.stats['published'] += len(processed_to_post)
                        self.logger.info(f"✅ {name}: опубликовано {len(processed)} новостей")
                        
                        # Логируем информацию о медиа для каждого поста
                        for i, post in enumerate(processed):
                            media_count = len(post.media_items) if post.media_items else 0
                            if media_count > 0:
                                media_urls = [m.url[:50] + '...' for m in post.media_items[:3]]
                                self.logger.info(f"📤 Пост {i+1}: {media_count} медиа, URL: {media_urls}")
                            else:
                                self.logger.info(f"📤 Пост {i+1}: без медиа, текст: {post.formatted_text[:80]}...")
                            
                    else:
                        self.logger.warning(f"⚠️ {name}: ошибка публикации")
                        
                except Exception as e:
                    self.logger.error(f"❌ Ошибка публикатора {name}: {e}")
        else:
            self.logger.info("📭 Нет новостей для публикации")
    
    def _record_rejection(self, reason: str):
        """Запись причины отклонения"""
        if reason not in self.stats['rejected_reasons']:
            self.stats['rejected_reasons'][reason] = 0
        self.stats['rejected_reasons'][reason] += 1
    
    def print_stats(self):
        """Вывод статистики"""
        uptime = datetime.now() - self.stats['start_time']
        hours, remainder = divmod(uptime.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        self.logger.info(f"📊 СТАТИСТИКА [Цикл #{self.stats['cycles']}]")
        self.logger.info(f"⏱️  Время работы: {int(hours)}ч {int(minutes)}м {int(seconds)}с")
        self.logger.info(f"📥 Получено: {self.stats['fetched']}")
        self.logger.info(f"🔧 Обработано: {self.stats['processed']}")
        self.logger.info(f"📤 Опубликовано: {self.stats['published']}")
        self.logger.info(f"❌ Отклонено: {self.stats['rejected']}")
        self.logger.info(f"🔄 Отфильтровано дубликатов: {self.stats['duplicates_filtered']}")
        self.logger.info(f"⭐ Отфильтровано по качеству: {self.stats['quality_filtered']}")
        self.logger.info(f"📸 С медиа: {self.stats['with_media']}")
        self.logger.info(f"📭 Без медиа: {self.stats['without_media']}")
        self.logger.info(f"🖼️ Всего медиа: {self.stats['total_media_items']}")
        
        if self.stats['rejected_reasons']:
            self.logger.info("📉 Причины отклонений:")
            for reason, count in sorted(self.stats['rejected_reasons'].items(), key=lambda x: x[1], reverse=True):
                percentage = (count / max(1, self.stats['rejected'])) * 100
                self.logger.info(f"  {reason}: {count} ({percentage:.1f}%)")
        
        # Сбрасываем счетчики
        self.stats['fetched'] = 0
        self.stats['processed'] = 0
        self.stats['published'] = 0
        self.stats['rejected'] = 0
        self.stats['rejected_reasons'] = {}
    
    async def close(self):
        """Закрытие ресурсов"""
        await self.media_handler.close()
        self.logger.info("📴 Ресурсы бота закрыты")


async def main():
    """Главная функция"""
    try:
        config = get_config()
        bot = NewsBot()
        
        await bot.start()
        await bot.close()
        
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")