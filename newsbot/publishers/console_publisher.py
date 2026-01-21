# newsbot/publishers/console_publisher.py
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from newsbot.types import ProcessedNews

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
            if analysis.market_impact:
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
        
        print(f"[{index}] {time_str} | {source}: {text_preview}")
    
    def _strip_html(self, text: str) -> str:
        """Удаление HTML тегов из текста"""
        import re

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