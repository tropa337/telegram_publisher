import asyncio
import json
import logging
import re
from typing import Optional

from mistralai import Mistral

from .config import get_config
from .types import AnalyzedNews, NewsItem


class CryptoNewsAnalyzer:
    """AI анализатор крипто-новостей с улучшенным переводом"""
    
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
            
            # 2. Предварительная нормализация текста
            normalized_text = self._normalize_text(news_item.raw_text)
            
            # 3. Качественный перевод на русский
            translated = await self._translate_text(normalized_text)
            
            # 4. Пост-обработка перевода
            translated = self._post_process_translation(translated)
            
            # 5. Возвращаем результат С медиа информацией из оригинала
            return AnalyzedNews(
                source_item=news_item,  # Сохраняем оригинал с медиа
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
                    'translation_quality': 'high',
                    'normalized': True,
                    'has_media': len(news_item.media_items) > 0 if hasattr(news_item, 'media_items') else False,
                    'media_count': len(news_item.media_items) if hasattr(news_item, 'media_items') else 0
                }
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа: {e}")
            return AnalyzedNews(
                source_item=news_item,
                is_relevant=False,
                relevance_reason=f"Ошибка AI: {str(e)[:50]}"
            )
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста перед переводом"""
        # Исправляем кривые форматы чисел
        text = re.sub(r'(\d+),(\d{3})', r'\1.\2', text)
        text = re.sub(r'(\d),(\d{1,2}[MBK])', r'\1.\2', text)
        text = re.sub(r'(\d),(\d{1,2})\s*([MBK])', r'\1.\2\3', text)
        
        # Исправляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,$%!?])', r'\1', text)
        text = re.sub(r'([(])\s+', r'\1', text)
        text = re.sub(r'\s+([)])', r'\1', text)
        
        # Форматирование валют
        text = re.sub(r'(\$)\s*(\d+)', r'\1\2', text)
        text = re.sub(r'(\d+)\s*([MBK])', r'\1\2', text)
        
        # Удаляем лишние символы
        text = re.sub(r'…\s*\.+', '…', text)
        text = re.sub(r'\.{3,}', '…', text)
        
        return text.strip()
    
    def _post_process_translation(self, text: str) -> str:
        """Пост-обработка перевода"""
        # Форматирование чисел в русском стиле
        text = re.sub(r'(\d+)\.(\d+)\s*([млрдMBK])', r'\1,\2 \3', text)
        text = re.sub(r'(\$)(\d+\.?\d*)\s*([млрдMBK]?)', r'\1\2\3', text)
        
        # Исправляем кривой перевод валют
        text = re.sub(r'долларов\s*(\$)', r'\1', text)
        text = re.sub(r'\$\s*долларов', r'$', text)
        
        # Убираем лишние пробелы после запятых и точек
        text = re.sub(r'([.,])\s+', r'\1 ', text)
        
        # Форматирование процентов
        text = re.sub(r'(\d+)\s*процентов', r'\1%', text)
        text = re.sub(r'(\d+)%\s*процентов', r'\1%', text)
        
        # Удаляем дублированные знаки препинания
        text = re.sub(r'([!?.,]){2,}', r'\1', text)
        
        # Корректируем пробелы вокруг тире
        text = re.sub(r'\s*-\s*', ' — ', text)
        
        return text.strip()
    
    async def _check_relevance(self, text: str) -> bool:
        """Проверка релевантности для крипторынка"""
        try:
            normalized = self._normalize_text(text[:800])
            
            prompt = f"""Ты анализатор крипто-новостей. Ответь ONLY 'RELEVANT' или 'IRRELEVANT'.

RELEVANT если новость содержит:
1. Конкретные рыночные события (листинг, делистинг, взломы, переводы)
2. Регуляторные решения (SEC, CFTC, одобрения ETF)
3. Институциональные действия (BlackRock, Fidelity, Binance, Coinbase)
4. Крупные финансовые операции (>$1M)
5. Важные обновления протоколов
6. Движение крупных кошельков (китов)
7. Ликвидации, данные по деривативам
8. Политические новости, влияющие на крипто

IRRELEVANT если:
1. Мнения, прогнозы, speculation без конкретных данных
2. Реклама, промо, airdrop, реферальные ссылки
3. Образовательный контент, tutorials, how-to
4. Мемы, юмор, несерьезный контент
5. Общие обсуждения без конкретики
6. Личные истории без рыночной значимости
7. Спам, повторяющийся контент

Новость: {normalized}

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
            self.logger.debug(f"AI ответ на релевантность: {answer}")
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
                self.logger.debug("Используем кэшированный перевод")
                return self.translation_cache[text_hash]
            
            prompt = f"""Переведи этот крипто-новостной текст на русский язык профессионально и точно.
ВАЖНЫЕ ПРАВИЛА:
1. Сохрани все числа, даты, имена компаний и технические термины без изменений
2. Форматируй числа в русском стиле: 1.5M → 1,5 млн
3. Сохрани символы валют: $100 → $100 (не "100 долларов")
4. Сделай перевод естественным для русского читателя
5. НЕ добавляй никаких служебных комментариев, примечаний или пояснений
6. ТОЛЬКО перевод текста, без вступлений и заключений
7. Сохраняй оригинальную структуру предложений

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
            
            # Дополнительная очистка
            translated = self._clean_translation(translated)
            
            # Сохраняем в кэш
            self.translation_cache[text_hash] = translated
            
            # Очистка кэша если слишком большой
            if len(self.translation_cache) > 100:
                self.translation_cache.clear()
                self.logger.info("Очищен кэш переводов")
            
            return translated
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка перевода: {e}")
            return text[:1000]
    
    def _clean_translation(self, text: str) -> str:
        """Дополнительная очистка перевода"""
        text = re.sub(r'^(перевод|translation|переведено):\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*\[конец перевода\]$', '', text, flags=re.IGNORECASE)
        
        text = re.sub(r'\(примечание:.*?\)', '', text)
        text = re.sub(r'\[примечание.*?\]', '', text)
        text = re.sub(r'\*примечание.*?\*', '', text)
        
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped:
                if not any(marker in line_stripped.lower() for marker in [
                    'перевод текста', 'оригинальный текст', 'текст переведен',
                    'note:', 'примечание:', 'комментарий перевода:'
                ]):
                    cleaned_lines.append(line_stripped)
        
        result = '\n'.join(cleaned_lines)
        result = re.sub(r'\s+', ' ', result)
        
        return result.strip()
    
    def _remove_service_comments(self, text: str) -> str:
        """Удаление служебных комментариев AI"""
        lines = text.split('\n')
        cleaned_lines = []
        
        in_service_block = False
        for line in lines:
            line_lower = line.lower().strip()
            
            if any(marker in line_lower for marker in [
                'примечание:', 'заметка:', 'комментарий:', '---',
                'сохранены', 'даты', 'текст адаптирован', 'via @',
                'перевод:', 'translation:', 'note:', 'comment:',
                'примечание перевода:', 'оригинал:', 'source:'
            ]):
                in_service_block = True
                continue
            
            if in_service_block and line.strip() == '':
                in_service_block = False
                continue
            
            line = re.sub(r'via\s+@\w+', '', line, flags=re.IGNORECASE)
            line = re.sub(r'@\w+', '', line)
            
            line = re.sub(r'pic\.twitter\.com/\w+', '', line, flags=re.IGNORECASE)
            
            if not in_service_block and line.strip():
                cleaned_lines.append(line.strip())
        
        result = '\n'.join(cleaned_lines)
        
        result = re.sub(r'\S+\.\.\.$', '', result)
        
        result = re.sub(r'^["\']+', '', result)
        result = re.sub(r'["\']+$', '', result)
        
        return result.strip()


# Глобальный анализатор
_analyzer: Optional[CryptoNewsAnalyzer] = None

def get_analyzer() -> CryptoNewsAnalyzer:
    """Получить глобальный анализатор"""
    global _analyzer
    if _analyzer is None:
        _analyzer = CryptoNewsAnalyzer()
    return _analyzer