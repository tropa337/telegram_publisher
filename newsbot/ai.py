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
            
            # Извлекаем сущности из текста
            entities = self._extract_entities(news_item.raw_text)
            
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
                    {"role": "user", "content": f"Новость для анализа: {text[:2000]}"}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Удаляем возможные маркеры кода
            result_text = result_text.strip('```json').strip('```')
            
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                self.logger.warning(f"Не удалось распарсить JSON, используем текстовый парсинг: {result_text[:100]}")
                return self._parse_text_response(result_text)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка AI анализа: {e}")
            return {"is_relevant": False, "reason": "Ошибка AI анализа", "confidence": 0.0}
    
    def _parse_text_response(self, text: str) -> Dict:
        """Парсинг текстового ответа"""
        text_lower = text.lower()
        
        positive_indicators = ['relevant', 'важн', 'публику', 'approve', 'reject', 'hack', 'да', 'yes']
        negative_indicators = ['not relevant', 'не relev', 'opinion', 'прогноз', 'digest', 'нет', 'no', 'реклама']
        
        pos_count = sum(1 for indicator in positive_indicators if indicator in text_lower)
        neg_count = sum(1 for indicator in negative_indicators if indicator in text_lower)
        
        if pos_count > neg_count:
            is_relevant = True
            reason = "AI определил как релевантную новость"
            impact_level = "medium"
            confidence = 0.6
        else:
            is_relevant = False
            reason = "AI определил как нерелевантную"
            impact_level = "none"
            confidence = 0.4
        
        # Извлекаем теги из текста
        tags = []
        tag_keywords = ['bitcoin', 'btc', 'ethereum', 'eth', 'sec', 'etf', 'regulation', 'hack']
        for keyword in tag_keywords:
            if keyword in text_lower:
                tags.append(keyword)
        
        return {
            "is_relevant": is_relevant,
            "reason": reason,
            "summary": text[:150] + "..." if len(text) > 150 else text,
            "impact_level": impact_level,
            "confidence": confidence,
            "tags": tags[:5]
        }
    
    async def _translate_and_format(self, text: str) -> str:
        """Перевод и форматирование"""
        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.translation_prompt},
                    {"role": "user", "content": f"Текст для перевода и форматирования: {text[:1500]}"}
                ],
                temperature=0.05,
                max_tokens=400
            )
            
            result = response.choices[0].message.content.strip()
            result = self._clean_formatted_text(result)
            
            # Гарантируем, что текст на русском
            if not self._is_russian_text(result):
                # Если AI не перевел, делаем простой перевод ключевых слов
                result = self._simple_translate(text[:500])
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка перевода: {e}")
            return self._simple_translate(text[:500])
    
    def _is_russian_text(self, text: str) -> bool:
        """Проверка, является ли текст русским"""
        # Простая проверка по наличию кириллических символов
        return bool(re.search('[а-яА-Я]', text))
    
    def _simple_translate(self, text: str) -> str:
        """Простой перевод для fallback"""
        # Упрощенный перевод ключевых терминов
        translations = {
            'bitcoin': 'биткоин',
            'ethereum': 'эфириум', 
            'sec': 'SEC',
            'etf': 'ETF',
            'hack': 'взлом',
            'approve': 'одобрил',
            'reject': 'отклонил',
            'openai': 'OpenAI',
            'chatgpt': 'ChatGPT',
            'age verification': 'проверка возраста',
            'teen': 'подросток',
            'minor': 'несовершеннолетний'
        }
        
        result = text
        for eng, rus in translations.items():
            result = re.sub(f'\\b{eng}\\b', rus, result, flags=re.IGNORECASE)
        
        return result[:400] + ("..." if len(text) > 400 else "")
    
    def _clean_formatted_text(self, text: str) -> str:
        """Очистка отформатированного текста"""
        # Удаляем лишние теги, кроме разрешенных
        allowed_tags = ['b', 'i', 'strong', 'em', 'code']
        for tag in allowed_tags:
            text = re.sub(f'<{tag}\\s[^>]*>', f'<{tag}>', text)  # Убираем атрибуты
        
        # Удаляем запрещенные теги
        text = re.sub(r'<(?!\/?(b|i|strong|em|code)\b)[^>]+>', '', text)
        
        # Удаляем ссылки
        text = re.sub(r'https?://\S+', '', text)
        
        # Удаляем хештеги и упоминания
        text = re.sub(r'[@#]\w+', '', text)
        
        # Удаляем лишние пробелы и переносы
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Ограничиваем длину
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
                    {"role": "user", "content": f"Контекст новости для редакторской заметки: {text[:1000]}"}
                ],
                temperature=0.3,
                max_tokens=100
            )
            
            note = response.choices[0].message.content.strip()
            note = note.strip('"\'').strip()
            
            # Проверяем качество заметки
            if len(note) < 10 or len(note) > 200 or "возможно" in note.lower() or "вероятно" in note.lower():
                # Генерируем простую заметку
                note = self._generate_simple_note(text)
            
            return note
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка генерации заметки: {e}")
            return self._generate_simple_note(text)
    
    def _generate_simple_note(self, text: str) -> str:
        """Генерация простой заметки редактора"""
        text_lower = text.lower()
        
        if 'bitcoin' in text_lower or 'btc' in text_lower:
            return "Изменения в регулировании биткоина могут повлиять на институциональное принятие."
        elif 'etf' in text_lower:
            return "Одобрение ETF является ключевым драйвером для притока институционального капитала."
        elif 'sec' in text_lower or 'regulation' in text_lower:
            return "Регуляторные решения формируют правовую среду для развития криптоиндустрии."
        elif 'hack' in text_lower or 'взлом' in text_lower:
            return "Инциденты безопасности подчеркивают необходимость усиления мер защиты активов."
        elif 'openai' in text_lower or 'chatgpt' in text_lower:
            return "Внедрение возрастных ограничений в AI-сервисах влияет на доступность технологий для молодежи."
        else:
            return "Это изменение отражает эволюцию технологической экосистемы и её интеграцию в общество."
    
    def _extract_entities(self, text: str) -> List[str]:
        """Извлечение сущностей"""
        entities = []
        text_upper = text.upper()
        
        cryptos = ['BTC', 'BITCOIN', 'ETH', 'ETHEREUM', 'BNB', 'XRP', 'SOL', 'SOLANA', 'ADA', 'CARDANO', 'DOGE', 'DOGECOIN']
        companies = ['SEC', 'CFTC', 'BINANCE', 'COINBASE', 'BLACKROCK', 'FIDELITY', 'OPENAI', 'CHATGPT']
        actions = ['APPROVE', 'REJECT', 'BAN', 'HACK', 'TRANSFER', 'LIST', 'DELIST']
        
        # Проверяем криптовалюты
        for crypto in cryptos:
            if crypto in text_upper:
                entities.append(crypto)
        
        # Проверяем компании
        for company in companies:
            if company in text_upper:
                entities.append(company)
        
        # Проверяем действия
        for action in actions:
            if action in text_upper:
                entities.append(action)
        
        return list(set(entities))[:10]


# Глобальный инстанс
_analyzer: Optional[CryptoNewsAnalyzer] = None

def get_analyzer() -> CryptoNewsAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = CryptoNewsAnalyzer()
    return _analyzer