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
    
    def _is_target_news_type(self, text: str) -> bool:
        """Проверяем, соответствует ли новость нужному формату"""
        if not text:
            return False
            
        text_lower = text.lower()
        
        # ТОЧНО ПУБЛИКУЕМ (как в примерах):
        # - Финансовые отчеты и данные
        if any(word in text_lower for word in ['отчет', 'report', 'данные', 'флоу', 'flow', 'статистика', 'поток']):
            return True
        
        # - Крупные покупки/продажи
        if any(word in text_lower for word in ['приобрел', 'купил', 'продал', 'покупка', 'продажа', 'куплено', 'приобрела']):
            return True
        
        # - Регуляторные новости
        if any(word in text_lower for word in ['sec', 'etf', 'регулятор', 'закон', 'одобрил', 'отклонил', 'регулирование']):
            return True
        
        # - Крупные транзакции и переводы
        if any(word in text_lower for word in ['перевел', 'транзакция', 'перевод', 'whale', 'кит', 'кошелек']):
            return True
        
        # - Листинги/делистинги
        if any(word in text_lower for word in ['листинг', 'listing', 'delist', 'делистинг', 'биржа']):
            return True
        
        # - Инциденты безопасности
        if any(word in text_lower for word in ['взлом', 'hack', 'кража', 'убыток', 'потерял', 'украл']):
            return True
        
        # - Новости компаний
        if any(word in text_lower for word in ['blackrock', 'vanguard', 'fidelity', 'tether', 'microstrategy', 'binance', 'coinbase']):
            return True
        
        # - Рыночные индикаторы
        if any(word in text_lower for word in ['индекс', 'страх', 'жадность', 'капитализация', 'объем']):
            return True
        
        # НЕ ПУБЛИКУЕМ:
        # - Мнения и прогнозы
        if any(word in text_lower for word in ['мнение', 'прогноз', 'анализ', 'считаю', 'думаю', 'opinion', 'view', 'think']):
            return False
        
        # - Реклама и промо
        if any(word in text_lower for word in ['реклама', 'промо', 'скидка', 'bonus', 'airdrop', 'giveaway']):
            return False
        
        # - Общие обзоры
        if any(word in text_lower for word in ['обзор', 'дайджест', 'резюме', 'итоги', 'digest', 'summary', 'recap']):
            return False
        
        # - Вопросы
        if text_lower.strip().endswith('?') or any(word in text_lower for word in ['как вы думаете', 'что думаете', 'ваше мнение']):
            return False
        
        # - Призывы к действию
        if any(word in text_lower for word in ['подписывайтесь', 'подписка', 'subscribe', 'join us', 'follow']):
            return False
        
        return True
    
    def _basic_filter(self, news_item: NewsItem) -> bool:
        """Базовый фильтр новостей"""
        # Проверка кеша
        if self.cache.is_processed(news_item):
            return False
        
        # Минимальная длина текста
        if not news_item.raw_text or len(news_item.raw_text.strip()) < 30:
            return False
        
        # Проверка типа новости (наши критерии)
        if not self._is_target_news_type(news_item.raw_text):
            self.logger.debug("📄 Не соответствует типу целевых новостей")
            self.cache.mark_processed(news_item, 'rejected', 'wrong_news_type')
            return False
        
        # Проверка дубликатов
        dedup_result = self.dedup.check(news_item)
        if dedup_result.is_duplicate:
            self.logger.debug(f"📄 Дубликат: {dedup_result.reason} ({dedup_result.similarity:.2f})")
            self.cache.mark_processed(news_item, 'rejected', f'duplicate_{dedup_result.reason}')
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
                analysis=ai_response,
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
                # Исправляем получение медиа - проверяем наличие атрибута и что это не пустой список
                media_items=news_item.media_items[:5] if hasattr(news_item, 'media_items') and news_item.media_items else []
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
    
    def _get_emoji_prefix(self, text: str) -> str:
        """Определяем эмодзи для начала поста на основе содержания"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['btc', 'bitcoin', 'биткоин']):
            return "💰 "
        elif any(word in text_lower for word in ['eth', 'ethereum', 'эфириум']):
            return "🔷 "
        elif any(word in text_lower for word in ['sec', 'etf', 'регулятор', 'regulation', 'закон', 'одобрил', 'отклонил']):
            return "⚖️ "
        elif any(word in text_lower for word in ['взлом', 'hack', 'кража', 'убыток', 'украл', 'потерял']):
            return "🚨 "
        elif any(word in text_lower for word in ['приобрел', 'купил', 'куплено', 'acquisition', 'покупка']):
            return "🛒 "
        elif any(word in text_lower for word in ['отчет', 'report', 'данные', 'статистика', 'флоу', 'поток']):
            return "📊 "
        elif any(word in text_lower for word in ['запуск', 'launch', 'новый', 'new', 'анонс']):
            return "🚀 "
        elif any(word in text_lower for word in ['листинг', 'listing', 'delist', 'делистинг']):
            return "📈 "
        elif any(word in text_lower for word in ['объем', 'капитализация', 'индекс', 'страх', 'жадность']):
            return "📉 "
        else:
            return "📰 "
    
    def _clean_links(self, text: str) -> str:
        """Очищаем текст от ссылок, которые Telegram показывает блоками"""
        # Удаляем обычные ссылки
        text = re.sub(r'https?://\S+', '', text)
        # Удаляем telegram.me/t.me ссылки
        text = re.sub(r't\.me/\S+', '', text)
        text = re.sub(r'telegram\.me/\S+', '', text)
        # Удаляем упоминания каналов
        text = re.sub(r'@\w+', '', text)
        # Удаляем хештеги
        text = re.sub(r'#\w+', '', text)
        return text.strip()
    
    def _format_for_telegram(self, news_item: NewsItem, analyzed_news: AnalyzedNews) -> str:
        """Форматирование в HTML для Telegram в стиле целевых каналов"""
        
        # Используем AI-переведенный текст если есть
        if analyzed_news.translated_text:
            content = analyzed_news.translated_text
        else:
            content = news_item.raw_text
        
        # Очищаем от лишних ссылок (телеграм показывает их блоком)
        content = self._clean_links(content)
        
        # Добавляем эмодзи в начало
        emoji_prefix = self._get_emoji_prefix(content)
        
        # Улучшаем форматирование
        content = self._enhance_formatting(content)
        
        # Удаляем лишние пробелы и переносы
        content = re.sub(r'\s+', ' ', content).strip()
        
        # Добавляем заметку редактора если есть (в виде отдельной строки с отступом)
        if analyzed_news.editor_note:
            editor_block = f"\n\n💭 <i>{analyzed_news.editor_note}</i>"
        else:
            editor_block = ""
        
        # Добавляем теги в конце (не больше 3-х)
        if analyzed_news.tags:
            tags_text = " ".join([f"#{tag.lower().replace(' ', '_').replace('-', '_')}" 
                                 for tag in analyzed_news.tags[:3]])
            tags_block = f"\n\n🏷️ {tags_text}"
        else:
            tags_block = ""
        
        # Формируем финальный текст
        formatted = f"{emoji_prefix}{content}"
        
        if editor_block:
            formatted += editor_block
        
        if tags_block:
            formatted += tags_block
        
        # Фиксированные ссылки в конце
        formatted += "\n\n🗽 <a href='https://t.me/onchain_20226'>OnChain News</a> | 🌐 <a href='https://bingxzone.com/partner/McDuckk/'>BingX</a>"
        
        return formatted
    
    def _enhance_formatting(self, text: str) -> str:
        """Улучшение форматирования текста - выделяем ключевые элементы"""
        patterns = [
            # Суммы денег (разные форматы)
            (r'(\$?\d+(?:[.,]\d+)?\s*(?:млн|миллион|млрд|миллиард|тыс|т|M|B|K|m|b|k)?\s*(?:USD|\$)?)', r'<b>\1</b>'),
            # Проценты
            (r'([+-]?\d+(?:[.,]\d+)?\s*%)', r'<b>\1</b>'),
            # Криптовалюты
            (r'\b(BTC|Bitcoin|ETH|Ethereum|XRP|SOL|Solana|ADA|Cardano|DOGE|Dogecoin|USDT|USDC|TRX|BNB)\b', r'<b>\1</b>'),
            # Компании и организации
            (r'\b(SEC|ETF|Binance|Coinbase|BlackRock|Fidelity|Vanguard|OpenAI|ChatGPT|Tether|MicroStrategy|Strategy|Tesla|GameStop|Gemini)\b', r'<b>\1</b>'),
            # Действия
            (r'\b(approve|reject|ban|hack|transfer|list|delist|buy|sell|acquire|одобрил|отклонил|запретил|взлом|купил|продал|приобрел)\b', r'<b>\1</b>'),
            # Ключевые термины
            (r'\b(ETF|staking|стейкинг|whale|кит|отчет|report|листинг|listing|регулятор|regulation)\b', r'<b>\1</b>'),
        ]
        
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
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
        elif len(sys.argv) > 1 and sys.argv[1] == '--test-format':
            # Тестовый режим форматирования
            logger.info("🧪 Тестовый режим форматирования")
            await test_format_mode(bot)
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
        "Отчет: ETF биткоина показали отток $1.33 млрд на прошлой неделе.",
        "Bitmine приобрели 40,302 ETH на прошлой неделе.",
        "Кит перевел 50,000 ETH ($146M) на Gemini.",
        "Подписывайтесь на наш канал для получения новостей!",
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


async def test_format_mode(bot: NewsBot):
    """Тестовый режим для проверки форматирования"""
    test_texts = [
        "Bitcoin ETF отток составил $1.33 млрд на прошлой неделе - второй по величине в истории.",
        "Кит перевел 50,000 ETH ($146M) на биржу Gemini после 9 лет бездействия.",
        "Bitmine приобрели 40,302 ETH на прошлой неделе, увеличив свои запасы.",
        "SEC одобрила новый Bitcoin ETF от BlackRock.",
        "Отчет CoinShares: общий отток составил $1.73 млрд за неделю.",
    ]
    
    logger.info("🧪 Тестирование форматирования:")
    
    for i, text in enumerate(test_texts, 1):
        logger.info(f"\nПример {i}: {text}")
        
        # Создаем тестовый NewsItem
        test_item = NewsItem(
            raw_text=text,
            source="test",
            url=f"https://test.example.com/{i}",
            created_at=datetime.now(timezone.utc),
            media_urls=[]
        )
        
        # Создаем тестовый AnalyzedNews
        analyzed_news = AnalyzedNews(
            source_item=test_item,
            is_relevant=True,
            relevance_reason="Тестовый пример",
            translated_text=text,
            editor_note="Это тестовая заметка редактора для проверки форматирования.",
            tags=["BTC", "ETF", "Новости"],
            market_impact="📈 Среднее"
        )
        
        # Тестируем форматирование
        formatted = bot._format_for_telegram(test_item, analyzed_news)
        logger.info(f"\n   Отформатированный текст:\n{formatted}")


if __name__ == "__main__":
    asyncio.run(main()) 