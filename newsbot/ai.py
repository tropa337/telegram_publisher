import asyncio
import json
import logging
import re
from typing import Optional

from mistralai import Mistral

from .config import get_config
from .types import AnalyzedNews, NewsItem


class CryptoNewsAnalyzer:
    """AI анализатор крипто-новостей"""
    
    def __init__(self):
        """Инициализация"""
        config = get_config()
        self.client = Mistral(api_key=config.MISTRAL_API_KEY)
        self.model = config.MISTRAL_MODEL
        self.logger = logging.getLogger(__name__)
        
        # Кэш переводов для одинаковых текстов
        self.translation_cache = {}
    
    async def analyze_news(self, 
                          news_item: NewsItem, 
                          market_signals: Optional[dict] = None) -> AnalyzedNews:
        """Анализ новости - ТОЛЬКО перевод и оценка релевантности"""
        try:
            # 1. Проверка релевантности
            is_relevant = await self._check_relevance(news_item.raw_text)
            
            if not is_relevant:
                return AnalyzedNews(
                    source_item=news_item,
                    is_relevant=False,
                    relevance_reason="Не соответствует критериям релевантности AI"
                )
            
            # 2. Качественный перевод на русский
            translated = await self._translate_text(news_item.raw_text)
            
            # 3. ТОЛЬКО перевод, без редакторских заметок и тегов
            return AnalyzedNews(
                source_item=news_item,
                is_relevant=True,
                relevance_reason="Прошла AI анализ",
                translated_text=translated,
                editor_note="",
                tags=[],
                confidence=0.85,
                market_impact='medium',
                metadata={
                    'ai_processed': True,
                    'original_language': 'en',
                    'translation_quality': 'high'
                }
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа: {e}")
            return AnalyzedNews(
                source_item=news_item,
                is_relevant=False,
                relevance_reason=f"Ошибка AI: {str(e)[:50]}"
            )
    
    async def _check_relevance(self, text: str) -> bool:
        """Проверка релевантности для крипторынка"""
        try:
            prompt = f"""Ты анализатор крипто-новостей. Ответь ONLY 'RELEVANT' или 'IRRELEVANT'.

RELEVANT если новость содержит:
1. Конкретные рыночные события (листинг, делистинг, взломы, переводы)
2. Регуляторные решения (SEC, CFTC, одобрения ETF)
3. Институциональные действия (BlackRock, Fidelity)
4. Крупные финансовые операции (>$1M)
5. Важные обновления протоколов

IRRELEVANT если:
1. Мнения, прогнозы, speculation
2. Реклама, промо, airdrop
3. Образовательный контент, tutorials
4. Мемы, юмор, несерьезный контент
5. Общие обсуждения без конкретики

Новость: {text[:800]}

Ответ:"""
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.chat.complete,
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=10
                ),
                timeout=15
            )
            
            answer = response.choices[0].message.content.strip().upper()
            return "RELEVANT" in answer
            
        except asyncio.TimeoutError:
            self.logger.warning("⚠️ Таймаут при проверке релевантности")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки релевантности: {e}")
            return False
    
    async def _translate_text(self, text: str) -> str:
        """Перевод текста на русский БЕЗ служебных комментариев"""
        try:
            # Кэширование переводов
            text_hash = hash(text[:500])
            if text_hash in self.translation_cache:
                return self.translation_cache[text_hash]
            
            prompt = f"""Переведи этот крипто-новостной текст на русский язык профессионально и точно.
Сохрани все числа, даты, имена компаний и технические термины без изменений.
Сделай перевод естественным для русского читателя.
НЕ добавляй никаких служебных комментариев, примечаний или пояснений.
ТОЛЬКО перевод текста.

Текст для перевода:
{text[:1500]}

Перевод:"""
            
            response = await asyncio.to_thread(
                self.client.chat.complete,
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            
            translated = response.choices[0].message.content.strip()
            
            # УДАЛЯЕМ ВСЕ служебные комментарии
            translated = self._remove_service_comments(translated)
            
            # Сохраняем в кэш
            self.translation_cache[text_hash] = translated
            
            # Очистка кэша если слишком большой
            if len(self.translation_cache) > 100:
                self.translation_cache.clear()
            
            return translated
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка перевода: {e}")
            return text[:1000]
    
    def _remove_service_comments(self, text: str) -> str:
        """Удаление служебных комментариев AI"""
        lines = text.split('\n')
        cleaned_lines = []
        
        in_service_block = False
        for line in lines:
            line_lower = line.lower().strip()
            
            # Пропускаем служебные блоки
            if any(marker in line_lower for marker in [
                'примечание:', 'заметка:', 'комментарий:', '---',
                'сохранены', 'даты', 'текст адаптирован', 'via @',
                'перевод:', 'translation:', 'note:'
            ]):
                in_service_block = True
                continue
            
            # Пропускаем пустые строки после служебных блоков
            if in_service_block and line.strip() == '':
                in_service_block = False
                continue
            
            # Удаляем Twitter упоминания в любой строке
            line = re.sub(r'via\s+@\w+', '', line, flags=re.IGNORECASE)
            line = re.sub(r'@\w+', '', line)
            
            if not in_service_block and line.strip():
                cleaned_lines.append(line.strip())
        
        result = '\n'.join(cleaned_lines)
        
        # Дополнительно удаляем короткие ссылки
        result = re.sub(r'\S+\.\.\.$', '', result)
        
        return result.strip()


# Глобальный анализатор
_analyzer: Optional[CryptoNewsAnalyzer] = None

def get_analyzer() -> CryptoNewsAnalyzer:
    """Получить глобальный анализатор"""
    global _analyzer
    if _analyzer is None:
        _analyzer = CryptoNewsAnalyzer()
    return _analyzer