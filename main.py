import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from typing import List

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


class NewsBot:
    """Основной класс новостного бота"""
    
    def __init__(self):
        """Инициализация"""
        self.config = get_config()
        self.logger = logger
        
        # Компоненты
        self.cache = NewsCache()
        self.dedup = DeduplicationEngine()
        self.filter = StrictMarketFilter()
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
        
        # Статистика
        self.stats = {
            'fetched': 0,
            'processed': 0,
            'published': 0,
            'rejected': 0,
            'rejected_reasons': {},
            'cycles': 0,
            'start_time': datetime.now()
        }
        
        # Флаг работы
        self.running = False
        
        self._init_sources()
        self._init_publishers()
        
        self.logger.info("🤖 Бот инициализирован с минималистичным форматированием")
    
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
    
    def _init_publishers(self):
        """Инициализация публикаторов"""
        # Консоль для отладки
        console = ConsolePublisher(pretty_print=True, max_items=5)
        self.publisher_manager.add_publisher('console', console)
        
        # Telegram
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
                    always_include_media=True
                )
                self.publisher_manager.add_publisher('telegram', telegram)
                self.logger.info(f"✅ Telegram: {self.config.TARGET_CHANNEL}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка Telegram: {e}")
    
    async def start(self):
        """Запуск бота в непрерывном режиме"""
        self.running = True
        self.logger.info("🚀 Запуск бота в непрерывном режиме...")
        
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
        """Обработка и публикация"""
        processed = []
        
        # Счетчики для отладки
        counters = {
            'total': 0,
            'cache': 0,
            'duplicate': 0,
            'filter': 0,
            'market': 0,
            'ai': 0,
            'passed': 0
        }
        
        items_to_process = news_items[:50]
        counters['total'] = len(items_to_process)
        
        self.logger.info(f"🔍 Обработка {counters['total']} новостей")
        
        for i, item in enumerate(items_to_process):
            # 1. Проверка кеша
            if self.cache.is_processed(item):
                counters['cache'] += 1
                continue
            
            # 2. Проверка дубликатов
            dedup_result = self.dedup.check(item)
            if dedup_result.is_duplicate:
                self.cache.mark_processed(item, 'rejected', 'duplicate')
                counters['duplicate'] += 1
                self._record_rejection('duplicate')
                continue
            
            # 3. Быстрая фильтрация
            filter_result = self.filter.quick_filter(item.raw_text)
            if not filter_result.passed:
                self.cache.mark_processed(item, 'rejected', f'filter_{filter_result.reason[:20]}')
                counters['filter'] += 1
                self.stats['rejected'] += 1
                self._record_rejection('filter')
                continue
            
            # 4. Проверка движения рынка
            if not looks_market_moving(item.raw_text):
                self.cache.mark_processed(item, 'rejected', 'no_market_move')
                counters['market'] += 1
                self.stats['rejected'] += 1
                self._record_rejection('no_market_move')
                continue
            
            # 5. AI анализ
            try:
                analyzed = await self.analyzer.analyze_news(item)
                if not analyzed.is_relevant:
                    self.cache.mark_processed(item, 'rejected', 'ai_reject')
                    counters['ai'] += 1
                    self.stats['rejected'] += 1
                    self._record_rejection('ai_reject')
                    continue
            except Exception as e:
                self.logger.error(f"❌ Ошибка AI анализа: {e}")
                continue
            
            # 6. Получение медиа
            primary_media = None
            try:
                primary_media = await self.media_handler.get_primary_media(item)
            except Exception as e:
                self.logger.error(f"❌ Ошибка получения медиа: {e}")
            
            # 7. Форматирование текста
            try:
                formatted_text = self.formatter.format_post(
                    ProcessedNews(
                        source_item=item,
                        analysis=analyzed,
                        formatted_text="",
                        media_items=[primary_media] if primary_media else []
                    )
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка форматирования: {e}")
                continue
            
            # 8. Создание ProcessedNews
            proc_news = ProcessedNews(
                source_item=item,
                analysis=analyzed,
                formatted_text=formatted_text,
                media_items=[primary_media] if primary_media else [],
                metadata={
                    'filter_score': filter_result.score,
                    'dedup_similarity': dedup_result.similarity,
                    'processed_at': datetime.now().isoformat(),
                    'has_media': primary_media is not None
                }
            )
            
            processed.append(proc_news)
            counters['passed'] += 1
            self.stats['processed'] += 1
            self.cache.mark_processed(item, 'approved', 'passed_all_filters')
        
        # Вывод статистики отсева
        self.logger.info("📊 ДЕТАЛЬНАЯ СТАТИСТИКА ОТСЕВА:")
        self.logger.info(f"  Всего новостей: {counters['total']}")
        self.logger.info(f"  Уже в кеше: {counters['cache']}")
        self.logger.info(f"  Дубликаты: {counters['duplicate']}")
        self.logger.info(f"  Не прошли фильтр: {counters['filter']}")
        self.logger.info(f"  Нет движения рынка: {counters['market']}")
        self.logger.info(f"  Отклонены AI: {counters['ai']}")
        self.logger.info(f"  УСПЕШНО ПРОШЛИ: {counters['passed']}")
        
        # 9. Публикация
        if processed:
            self.logger.info(f"📤 Публикация {len(processed)} новостей...")
            
            for name, publisher in self.publisher_manager.publishers.items():
                try:
                    result = await publisher.publish(processed)
                    
                    if result:
                        self.stats['published'] += len(processed)
                        self.logger.info(f"✅ {name}: опубликовано {len(processed)} новостей")
                        
                        if processed[0].formatted_text:
                            preview = processed[0].formatted_text[:200].replace('\n', ' ')
                            self.logger.info(f"📤 Пример поста: {preview}...")
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