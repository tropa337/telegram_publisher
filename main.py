import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from telethon import TelegramClient

from newsbot import config
from newsbot.ai import get_analyzer
from newsbot.cache import NewsCache
from newsbot.dedup import DeduplicationEngine
from newsbot.filters import StrictMarketFilter
from newsbot.market_filter import looks_market_moving
from newsbot.publishers.telegram_publisher import (ConsolePublisher,
                                                   PublisherManager,
                                                   TelegramPublisher)
from newsbot.sources.telegram_source import TelegramSource
from newsbot.sources.twitter_source import TwitterRSSSource
from newsbot.types import AnalyzedNews, NewsItem, ProcessedNews

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('newsbot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class NewsBot:
    """Основной бот для сбора и публикации новостей"""
    
    def __init__(self):
        self.logger = logger
        self.config = config
        
        # Инициализация компонентов
        self.cache = NewsCache()
        self.dedup = DeduplicationEngine()
        self.market_filter = StrictMarketFilter()
        self.ai_analyzer = get_analyzer()
        
        # Источники новостей
        self.sources = {}
        
        # Публикаторы
        self.publisher_manager = PublisherManager()
        
        # Статистика
        self.stats = {
            'total_fetched': 0,
            'total_processed': 0,
            'total_published': 0,
            'total_rejected': 0,
            'filter_stats': {},
            'start_time': datetime.now(timezone.utc)
        }
        
        self._init_sources()
        self._init_publishers()
        
        self.logger.info("🤖 Новостной бот инициализирован")
        self._log_filter_stats()
        
    def _log_filter_stats(self):
        """Логирование статистики фильтров"""
        filter_stats = self.market_filter.get_filter_stats()
        self.stats['filter_stats'] = filter_stats
        
        logger.info(f"📊 Статистика фильтров:")
        logger.info(f"  ├─ Паттернов отклонения: {filter_stats['hard_reject_patterns']}")
        logger.info(f"  ├─ Мягких отклонений: {filter_stats['soft_reject_patterns']}")
        logger.info(f"  ├─ Обязательных сигналов: {filter_stats['required_signals']}")
        logger.info(f"  ├─ Буст-паттернов: {filter_stats['boost_patterns']}")
        logger.info(f"  └─ Типов сущностей: {filter_stats['entity_types']}")
        
    def _init_sources(self):
        """Инициализация источников новостей"""
        # Twitter RSS источники
        if hasattr(self.config, 'TWITTER_RSS_FEEDS') and self.config.TWITTER_RSS_FEEDS:
            twitter_source = TwitterRSSSource(
                feeds=self.config.TWITTER_RSS_FEEDS,
                auth_token=getattr(self.config, 'RSS_AUTH_TOKEN', ''),
                poll_interval=getattr(self.config, 'POLL_INTERVAL_RSS', 300),
                filters=[self._basic_filter]
            )
            self.sources['twitter_rss'] = twitter_source
            self.logger.info(f"✅ Twitter RSS: {len(self.config.TWITTER_RSS_FEEDS)} фидов")
        
        # Telegram источники (опционально)
        if hasattr(self.config, 'SOURCE_TG_CHANNELS') and self.config.SOURCE_TG_CHANNELS:
            try:
                telegram_client = TelegramClient(
                    'newsbot_session',
                    self.config.TG_API_ID,
                    self.config.TG_API_HASH
                )
                telegram_source = TelegramSource(
                    client=telegram_client,
                    channels=self.config.SOURCE_TG_CHANNELS
                )
                self.sources['telegram'] = telegram_source
                self.logger.info(f"✅ Telegram: {len(self.config.SOURCE_TG_CHANNELS)} каналов")
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации Telegram: {e}")
    
    def _init_publishers(self):
        """Инициализация публикаторов"""
        # Консольный публикатор для отладки
        console_publisher = ConsolePublisher(
            pretty_print=True,
            max_items=5
        )
        self.publisher_manager.add_publisher('console', console_publisher)
        
        # Telegram публикатор (основной)
        if hasattr(self.config, 'TG_API_ID') and self.config.TG_API_ID and \
           hasattr(self.config, 'TG_API_HASH') and self.config.TG_API_HASH and \
           hasattr(self.config, 'TARGET_CHANNEL') and self.config.TARGET_CHANNEL:
            try:
                telegram_client = TelegramClient(
                    'publisher_session',
                    self.config.TG_API_ID,
                    self.config.TG_API_HASH
                )
                
                telegram_publisher = TelegramPublisher(
                    client=telegram_client,
                    channel=self.config.TARGET_CHANNEL,
                    max_media_per_post=getattr(self.config, 'MAX_MEDIA_PER_POST', 4),
                    parse_mode='html',
                    always_include_media=getattr(self.config, 'ALWAYS_INCLUDE_MEDIA', True)
                )
                
                self.publisher_manager.add_publisher('telegram', telegram_publisher)
                self.logger.info(f"✅ Telegram публикатор: {self.config.TARGET_CHANNEL}")
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации Telegram публикатора: {e}")
    
    def _basic_filter(self, news_item: NewsItem) -> bool:
        """Базовый фильтр новостей"""
        # Проверка кеша
        if self.cache.is_processed(news_item):
            return False
        
        # Минимальная длина текста
        if not news_item.raw_text or len(news_item.raw_text.strip()) < 30:
            return False
        
        # Проверка дубликатов
        dedup_result = self.dedup.check(news_item)
        if dedup_result.is_duplicate:
            self.logger.debug(f"📄 Дубликат: {dedup_result.reason} ({dedup_result.similarity:.2f})")
            return False
        
        # Расширенный рыночный фильтр с детальным анализом
        filter_result = self.market_filter.quick_filter(news_item.raw_text)
        
        if not filter_result.passed:
            self.logger.debug(f"📄 Не прошел рыночный фильтр: {filter_result.reason}")
            self.stats['total_rejected'] += 1
            self.cache.mark_processed(news_item, 'rejected', filter_result.reason)
            return False
        
        # Дополнительный анализ качества контента
        if filter_result.score < 0.3:
            self.logger.debug(f"📄 Низкое качество контента: оценка {filter_result.score:.2f}")
            self.cache.mark_processed(news_item, 'rejected', f'low_quality_score_{filter_result.score}')
            return False
        
        # Фильтр по движению рынка
        if not looks_market_moving(news_item.raw_text):
            self.logger.debug("📄 Не прошел фильтр движения рынка")
            self.cache.mark_processed(news_item, 'rejected', 'not_market_moving')
            return False
        
        # Логирование успешной проверки фильтра
        self.logger.debug(f"✅ Прошел фильтр с оценкой {filter_result.score:.2f}")
        if filter_result.matched_patterns:
            self.logger.debug(f"   Совпадения: {filter_result.matched_patterns[:3]}")
        
        return True
    
    async def _process_news_item(self, news_item: NewsItem) -> Optional[ProcessedNews]:
        """Обработка одной новости"""
        try:
            # Расширенный анализ фильтра (для деталей)
            filter_analysis = self.market_filter.analyze_content_quality(news_item.raw_text)
            
            # Подготовка market_signals для AI анализа
            market_signals = {
                'score': filter_analysis['score'],
                'signals_count': filter_analysis['statistics']['signals_count'],
                'numbers_count': filter_analysis['statistics']['numbers_count'],
                'entities': filter_analysis.get('entities', {}),
                'passed': filter_analysis['passed'],
                'reason': filter_analysis.get('reason', '')
            }
            
            # AI анализ с передачей market_signals
            ai_response = await self.ai_analyzer.analyze_news(news_item, market_signals)
            
            if not ai_response.is_relevant:
                self.cache.mark_processed(news_item, 'rejected', ai_response.relevance_reason)
                self.stats['total_rejected'] += 1
                self.logger.debug(f"🤖 AI отклонил: {ai_response.relevance_reason}")
                return None
            
            # ФОРМАТИРОВАНИЕ для Telegram
            formatted_text = self._format_for_telegram(news_item, ai_response)
            
            # Создание обработанной новости
            processed = ProcessedNews(
                source_item=news_item,
                analysis=ai_response,  # Используем ai_response напрямую
                formatted_text=formatted_text,
                editor_note=ai_response.editor_note,
                metadata={
                    'filter_score': filter_analysis['score'],
                    'entities': filter_analysis.get('entities', {}),
                    'numbers_count': filter_analysis['statistics'].get('numbers_count', 0),
                    'signals_count': filter_analysis['statistics'].get('signals_count', 0),
                    'media_count': len(news_item.media_items) if hasattr(news_item, 'media_items') else 0,
                    'ai_analysis': ai_response.metadata.get('ai_analysis', {}) if hasattr(ai_response, 'metadata') else {},
                    'impact_level': ai_response.metadata.get('impact_level', 'medium') if hasattr(ai_response, 'metadata') else 'medium',
                    'market_signals': market_signals
                },
                media_items=news_item.media_items[:5] if hasattr(news_item, 'media_items') else []
            )
            
            self.cache.mark_processed(news_item, 'approved', "passed_all_filters")
            self.stats['total_processed'] += 1
            
            media_count = len(news_item.media_items) if hasattr(news_item, 'media_items') else 0
            self.logger.info(f"✅ Новость обработана: оценка фильтра {filter_analysis['score']:.2f}, "
                           f"сигналов: {filter_analysis['statistics']['signals_count']}, "
                           f"медиа: {media_count}")
            
            return processed
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки новости: {e}", exc_info=True)
            return None
    
    def _format_for_telegram(self, news_item: NewsItem, analyzed_news: AnalyzedNews) -> str:
        """Форматирование в HTML для Telegram с использованием AI-перевода"""
        
        # Используем AI-переведенный текст если есть
        if analyzed_news.translated_text:
            content = analyzed_news.translated_text
        else:
            content = news_item.raw_text
        
        # Дополнительное форматирование: выделяем заголовок если он есть
        lines = content.split('\n')
        if len(lines) > 1 and len(lines[0].strip()) < 100:
            # Первая строка как заголовок
            title = lines[0].strip()
            body = '\n'.join(lines[1:]).strip()
            
            # Делаем заголовок жирным
            if not title.startswith('<b>'):
                title = f"<b>{title}</b>"
            
            content = f"{title}\n\n{body}"
        
        # Убедимся, что ключевые слова выделены жирным
        content = self._enhance_formatting(content)
        
        # Добавляем заметку редактора если есть
        if analyzed_news.editor_note:
            editor_block = f"\n\n💭 <i>{analyzed_news.editor_note}</i>"
        else:
            editor_block = ""
        
        # Добавляем маркет-импакт если есть
        if analyzed_news.market_impact:
            impact_block = f"\n\n📊 <b>Влияние на рынок:</b> {analyzed_news.market_impact}"
        else:
            impact_block = ""
        
        # Добавляем теги если есть
        if analyzed_news.tags:
            tags_text = " ".join([f"#{tag.lower().replace(' ', '_').replace('-', '_')}" 
                                 for tag in analyzed_news.tags[:5]])
            tags_block = f"\n\n🏷️ {tags_text}"
        else:
            tags_block = ""
        
        # Форматируем полный пост
        formatted = f"{content}{editor_block}{impact_block}{tags_block}"
        
        # Добавляем фиксированные ссылки (обновите на свои)
        formatted += "\n\n🗽 <a href='https://t.me/+9l6cLNCMTHs3ZDM8'>OnChain News</a> | 🌐 <a href='https://bingxzone.com/partner/McDuckk/'>BingX</a>"
        
        return formatted
    
    def _enhance_formatting(self, text: str) -> str:
        """Улучшение форматирования текста"""
        # Ключевые слова для выделения жирным
        keywords = [
            # Криптовалюты
            r'\b(BTC|Bitcoin|ETH|Ethereum|XRP|SOL|Solana|ADA|Cardano|DOGE|Dogecoin)\b',
            # Компании
            r'\b(OpenAI|ChatGPT|SEC|Binance|Coinbase|BlackRock|Fidelity|Vanguard)\b',
            # Действия
            r'\b(approve|reject|ban|hack|transfer|list|delist|одобрил|отклонил|запретил|взлом)\b',
            # Суммы
            r'\$?\d+[.,]?\d*\s*(?:million|mln|billion|bln|тыс|млн|млрд)?\s*(?:USD|BTC|ETH)?\b',
            # Проценты
            r'[+-]?\d+[.,]?\d*\s*%\b'
        ]
        
        for pattern in keywords:
            text = re.sub(pattern, r'<b>\g<0></b>', text, flags=re.IGNORECASE)
        
        return text
    
    async def _process_batch(self, news_items: List[NewsItem]) -> List[ProcessedNews]:
        """Обработка партии новостей"""
        processed_items = []
        
        for item in news_items:
            processed = await self._process_news_item(item)
            if processed:
                processed_items.append(processed)
        
        return processed_items
    
    async def run_single_fetch(self):
        """Однократный сбор и обработка новостей"""
        self.logger.info("🚀 Начинаем сбор новостей...")
        
        all_news = []
        
        # Сбор из всех источников
        for source_name, source in self.sources.items():
            try:
                if source_name == 'twitter_rss':
                    news_items = await source.fetch()
                elif source_name == 'telegram':
                    # Telegram работает через callback
                    continue
                else:
                    news_items = []
                
                if news_items:
                    self.logger.info(f"📥 {source_name}: получено {len(news_items)} новостей")
                    all_news.extend(news_items)
                    self.stats['total_fetched'] += len(news_items)
                    
            except Exception as e:
                self.logger.error(f"❌ Ошибка источника {source_name}: {e}")
        
        # Обработка новостей
        if all_news:
            processed_news = await self._process_batch(all_news)
            
            # Публикация
            if processed_news:
                results = await self.publisher_manager.publish_all(processed_news)
                
                for pub_name, success in results.items():
                    if success:
                        self.logger.info(f"✅ {pub_name}: успешно опубликовано {len(processed_news)} новостей")
                        self.stats['total_published'] += len(processed_news)
                    else:
                        self.logger.warning(f"⚠️ {pub_name}: ошибка публикации")
                        
                # Детальная статистика по обработанным новостям
                if processed_news:
                    avg_score = sum(n.metadata.get('filter_score', 0) for n in processed_news) / len(processed_news)
                    total_signals = sum(n.metadata.get('signals_count', 0) for n in processed_news)
                    total_media = sum(n.metadata.get('media_count', 0) for n in processed_news)
                    self.logger.info(f"📊 Средняя оценка: {avg_score:.2f}, "
                                   f"сигналов: {total_signals}, "
                                   f"медиа: {total_media}")
        else:
            self.logger.info("📭 Новостей не найдено")
    
    async def start_monitoring(self):
        """Запуск постоянного мониторинга"""
        self.logger.info("👁️ Запуск постоянного мониторинга...")
        
        # Запуск мониторинга Telegram (если есть)
        if 'telegram' in self.sources:
            telegram_source = self.sources['telegram']
            
            async def telegram_callback(news_item: NewsItem):
                self.logger.info(f"📥 Telegram: получена новая новость")
                processed = await self._process_news_item(news_item)
                if processed:
                    result = await self.publisher_manager.publish_all([processed])
                    for pub_name, success in result.items():
                        if success:
                            self.logger.info(f"✅ {pub_name}: опубликовано")
                            self.stats['total_published'] += 1
            
            # Запуск в отдельной задаче
            asyncio.create_task(
                telegram_source.start_monitoring(telegram_callback)
            )
        
        # Запуск периодического опроса RSS
        if 'twitter_rss' in self.sources:
            twitter_source = self.sources['twitter_rss']
            
            async def rss_callback(news_items: List[NewsItem]):
                if news_items:
                    self.logger.info(f"📥 RSS: получено {len(news_items)} новых новостей")
                    processed_news = await self._process_batch(news_items)
                    if processed_news:
                        result = await self.publisher_manager.publish_all(processed_news)
                        for pub_name, success in result.items():
                            if success:
                                self.logger.info(f"✅ {pub_name}: опубликовано {len(processed_news)} новостей")
                                self.stats['total_published'] += len(processed_news)
            
            # Запуск в отдельной задаче
            asyncio.create_task(
                twitter_source.start_polling(rss_callback)
            )
        
        # Бесконечный цикл для статистики
        while True:
            await asyncio.sleep(300)  # 5 минут
            
            # Вывод статистики
            self._print_stats()
    
    def _print_stats(self):
        """Вывод статистики"""
        uptime = datetime.now(timezone.utc) - self.stats['start_time']
        hours, remainder = divmod(uptime.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        
        stats_text = f"""
📊 СТАТИСТИКА БОТА:
├─ Получено: {self.stats['total_fetched']}
├─ Обработано: {self.stats['total_processed']}
├─ Опубликовано: {self.stats['total_published']}
├─ Отклонено: {self.stats['total_rejected']}
├─ Фильтров: {self.stats['filter_stats'].get('hard_reject_patterns', 0)}
├─ Сигналов: {self.stats['filter_stats'].get('required_signals', 0)}
├─ Медиа включено: {getattr(self.config, 'ALWAYS_INCLUDE_MEDIA', True)}
└─ Время работы: {int(hours)}ч {int(minutes)}мин
"""
        self.logger.info(stats_text.strip())
    
    async def shutdown(self):
        """Корректное завершение работы"""
        self.logger.info("🛑 Завершение работы...")
        self._print_stats()
        await self.publisher_manager.close_all()


async def main():
    """Основная функция"""
    try:
        # Проверка конфигурации
        if not hasattr(config, 'TG_API_ID') or not config.TG_API_ID or \
           not hasattr(config, 'TG_API_HASH') or not config.TG_API_HASH:
            logger.error("❌ Не настроены Telegram API credentials")
            return
        
        if (not hasattr(config, 'TWITTER_RSS_FEEDS') or not config.TWITTER_RSS_FEEDS) and \
           (not hasattr(config, 'SOURCE_TG_CHANNELS') or not config.SOURCE_TG_CHANNELS):
            logger.error("❌ Не настроены источники новостей")
            return
        
        # Создание и запуск бота
        bot = NewsBot()
        
        # Тестирование соединений
        logger.info("🔍 Тестирование соединений...")
        await bot.publisher_manager.test_all_connections()
        
        # Запуск
        if len(sys.argv) > 1 and sys.argv[1] == '--once':
            # Однократный запуск
            await bot.run_single_fetch()
            await bot.shutdown()
        elif len(sys.argv) > 1 and sys.argv[1] == '--test-filter':
            # Тестовый режим фильтра
            logger.info("🧪 Тестовый режим фильтра")
            await test_filter_mode(bot)
        else:
            # Постоянный мониторинг
            try:
                await bot.start_monitoring()
            except KeyboardInterrupt:
                await bot.shutdown()
        
    except KeyboardInterrupt:
        logger.info("👋 Остановка по запросу пользователя")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


async def test_filter_mode(bot: NewsBot):
    """Тестовый режим для проверки фильтров"""
    test_texts = [
        "Bitcoin surged 15% today reaching $50,000 amid ETF approval news.",
        "In my opinion, Bitcoin will go to the moon soon.",
        "BlackRock files for spot Bitcoin ETF with SEC.",
        "Sign up now for free Bitcoin airdrop!",
        "Breaking: Federal Reserve announces 0.25% interest rate hike.",
        "Daily crypto market recap for today.",
        "Tesla buys additional $500 million in Bitcoin according to filings.",
        "What do you think about the current market situation?",
    ]
    
    logger.info("🧪 Тестирование фильтров на примерах:")
    
    for i, text in enumerate(test_texts, 1):
        logger.info(f"\nПример {i}: {text[:80]}...")
        
        # Создаем тестовый NewsItem
        test_item = NewsItem(
            raw_text=text,
            source="test",
            url=f"https://test.example.com/{i}",
            created_at=datetime.now(timezone.utc),
            media_urls=[]
        )
        
        # Проверяем базовый фильтр
        basic_pass = bot._basic_filter(test_item)
        logger.info(f"   Базовый фильтр: {'✅ ПРОШЕЛ' if basic_pass else '❌ ОТКЛОНЕН'}")
        
        # Детальный анализ фильтра
        if basic_pass:
            analysis = bot.market_filter.analyze_content_quality(text)
            logger.info(f"   Оценка: {analysis['score']:.2f}")
            logger.info(f"   Сигналы: {analysis['statistics']['signals_count']}")
            logger.info(f"   Числа: {analysis['statistics']['numbers_count']}")
            if analysis.get('entities'):
                logger.info(f"   Сущности: {analysis['entities']}")


if __name__ == "__main__":
    asyncio.run(main())