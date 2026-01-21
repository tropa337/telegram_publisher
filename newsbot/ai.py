import asyncio
import json
import logging
import re
from typing import Dict, List, Optional

from mistralai import Mistral

from .config import config
from .types import AnalyzedNews, NewsItem


class CryptoNewsAnalyzer:
    """AI анализатор криптоновостей"""
    
    def __init__(self):
        if not config.mistral_api_key:
            raise ValueError("Mistral API key is not configured")
        
        self.client = Mistral(api_key=config.mistral_api_key)
        self.model = config.mistral_model
        self.logger = logging.getLogger(__name__)
        
        self.analysis_prompt = """Ты — старший аналитик крипто-трейдинг фонда. 
        Анализируй новости ТОЛЬКО на предмет влияния на рынок криптовалют.

        КРИТЕРИИ ВАЖНОСТИ:
        1. 🚨 КРИТИЧЕСКИЕ (публикуем ВСЕГДА):
           - SEC/CFTC решения по ETF/регуляции
           - Крупные взломы (>$10M)
           - Blackrock/Fidelity/Vanguard заявки/решения
        
        2. 🔥 ВАЖНЫЕ (публикуем если есть КОНКРЕТИКА):
           - Листинг/делистинг на Binance/Coinbase
           - Крупные переводы (>1000 BTC или >$50M)
           - Судебные решения
        
        3. 🚫 НЕ ПУБЛИКУЕМ:
           - Мнения, прогнозы, анализ
           - Дайджесты, обзоры, подборки
           - Реклама, промо, аирдропы

        Ответь строго в JSON формате:
        {
            "is_relevant": boolean,
            "reason": "string",
            "summary": "string (1-2 предложения на русском)",
            "impact_level": "critical|high|medium|low|none",
            "confidence": 0.0-1.0,
            "tags": ["tag1", "tag2"]
        }"""
        
        self.translation_prompt = """Ты — редактор крипто-новостей для Telegram канала трейдеров.
        
        ПРАВИЛА ФОРМАТИРОВАНИЯ:
        1. 🔥 ВСЕГДА выделяй жирным (<b>...</b>):
           - Суммы денег: $10M, 500 BTC
           - Проценты: +5%, -10%
           - Компании: Binance, SEC, Blackrock
           - Действия: запретили, одобрили, взломали
        
        2. 🚫 НИКОГДА не включай:
           - Ссылки, хештеги, @упоминания
           - Кликбейт (BREAKING, URGENT, SHOCKING)
           - Мнения, прогнозы, предположения
        
        3. 📋 СТРУКТУРА:
           - 1-3 предложения
           - Только факты
           - Конкретные цифры
        
        Переведи и отформатируй текст:"""
        
        self.editor_note_prompt = """Напиши ОДНУ мысль редактора для блока цитаты:
        
        ТРЕБОВАНИЯ:
        - 1 предложение, 15-25 слов
        - Только факты о ВЛИЯНИИ НА РЫНОК
        - Нейтральный тон, без эмоций
        - Без "возможно", "вероятно", "может быть"
        
        Контекст новости:"""
    
    async def analyze_news(self, news_item: NewsItem, market_signals: Optional[Dict] = None) -> AnalyzedNews:
        """Полный AI анализ новости"""
        if market_signals is None:
            market_signals = {}
        
        try:
            # AI анализ релевантности
            ai_analysis = await self._perform_ai_analysis(news_item.raw_text)
            
            if not ai_analysis.get('is_relevant', False):
                return AnalyzedNews(
                    source_item=news_item,
                    is_relevant=False,
                    relevance_reason=ai_analysis.get('reason', 'AI анализ: не релевантно')
                )
            
            # AI перевод и форматирование
            translated_text = await self._translate_and_format(news_item.raw_text)
            
            # Генерация заметки редактора
            editor_note = await self._generate_editor_note(news_item.raw_text)
            
            # Извлечение тегов
            tags = ai_analysis.get('tags', [])
            entities = self._extract_entities(news_item.raw_text)
            
            # Дополнительные поля из анализа
            confidence = ai_analysis.get('confidence', 0.5)
            impact_level = ai_analysis.get('impact_level', 'medium')
            
            # Определяем market_impact на основе impact_level
            impact_mapping = {
                'critical': '🚨 Критическое',
                'high': '🔥 Высокое',
                'medium': '📈 Среднее',
                'low': '📉 Низкое',
                'none': '⚪ Незначительное'
            }
            market_impact = impact_mapping.get(impact_level, '📈 Среднее')
            
            # Создание результата
            analyzed_news = AnalyzedNews(
                source_item=news_item,
                is_relevant=True,
                relevance_reason=ai_analysis.get('reason', 'Релевантная рыночная новость'),
                translated_text=translated_text,
                summary=ai_analysis.get('summary', ''),
                editor_note=editor_note,
                tags=tags,
                entities=entities,
                confidence=confidence,
                market_impact=market_impact,
                metadata={
                    'ai_analysis': ai_analysis,
                    'original_length': len(news_item.raw_text),
                    'market_signals': market_signals,
                    'impact_level': impact_level
                }
            )
            
            return analyzed_news
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка AI анализа: {e}")
            return AnalyzedNews(
                source_item=news_item,
                is_relevant=False,
                relevance_reason=f"Ошибка анализа: {str(e)[:100]}"
            )
    
    async def _perform_ai_analysis(self, text: str) -> Dict:
        """AI анализ текста"""
        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.analysis_prompt},
                    {"role": "user", "content": f"Новость: {text[:2000]}"}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                return self._parse_text_response(result_text)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка AI анализа: {e}")
            return {"is_relevant": False, "reason": "Ошибка AI анализа"}
    
    def _parse_text_response(self, text: str) -> Dict:
        """Парсинг текстового ответа"""
        text_lower = text.lower()
        
        positive_indicators = ['relevant', 'важн', 'публику', 'approve', 'reject', 'hack']
        negative_indicators = ['not relevant', 'не relev', 'opinion', 'прогноз', 'digest']
        
        pos_count = sum(1 for indicator in positive_indicators if indicator in text_lower)
        neg_count = sum(1 for indicator in negative_indicators if indicator in text_lower)
        
        if pos_count > neg_count:
            is_relevant = True
            reason = "AI определил как релевантную новость"
        else:
            is_relevant = False
            reason = "AI определил как нерелевантную"
        
        return {
            "is_relevant": is_relevant,
            "reason": reason,
            "summary": text[:100],
            "impact_level": "medium" if is_relevant else "none",
            "confidence": 0.6,
            "tags": []
        }
    
    async def _translate_and_format(self, text: str) -> str:
        """Перевод и форматирование"""
        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.translation_prompt},
                    {"role": "user", "content": text[:1500]}
                ],
                temperature=0.05,
                max_tokens=300
            )
            
            result = response.choices[0].message.content.strip()
            result = self._clean_formatted_text(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка перевода: {e}")
            return text[:400] + ("..." if len(text) > 400 else "")
    
    def _clean_formatted_text(self, text: str) -> str:
        """Очистка отформатированного текста"""
        import re
        text = re.sub(r'<(?!\/?(b|i|code|strong|em)\b)[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        if len(text) > 1000:
            text = text[:997] + "..."
        
        return text
    
    async def _generate_editor_note(self, text: str) -> str:
        """Генерация заметки редактора"""
        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.editor_note_prompt},
                    {"role": "user", "content": f"Новость: {text[:1000]}"}
                ],
                temperature=0.3,
                max_tokens=100
            )
            
            note = response.choices[0].message.content.strip()
            note = note.strip('"\'')
            
            if len(note) < 10 or len(note) > 200:
                return ""
            
            return note
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка генерации заметки: {e}")
            return ""
    
    def _extract_entities(self, text: str) -> List[str]:
        """Извлечение сущностей"""
        entities = []
        text_upper = text.upper()
        
        cryptos = ['BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'ADA', 'DOGE']
        companies = ['SEC', 'CFTC', 'BINANCE', 'COINBASE', 'BLACKROCK', 'FIDELITY']
        
        for entity_list in [cryptos, companies]:
            for entity in entity_list:
                if entity in text_upper:
                    entities.append(entity)
        
        return list(set(entities))[:10]


# Глобальный инстанс
_analyzer: Optional[CryptoNewsAnalyzer] = None

def get_analyzer() -> CryptoNewsAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = CryptoNewsAnalyzer()
    return _analyzer