
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Set, Tuple


@dataclass
class FilterResult:
    passed: bool
    reason: str
    score: float = 0.0
    matched_patterns: List[str] = None
    extracted_data: Dict = None
    
    def __post_init__(self):
        if self.matched_patterns is None:
            self.matched_patterns = []
        if self.extracted_data is None:
            self.extracted_data = {}


class StrictMarketFilter:
    def __init__(self):
        # Основные паттерны для жесткого отклонения
        self.hard_reject_patterns = [
            # Мнения и предсказания
            r'\b(i think|in my opinion|according to me|предполагаю|мнение|по моему)\b',
            r'\b(predict|forecast|прогноз|предсказание)\b.*\b(price|цена|market|рынок)\b',
            r'\b(will|going to)\b.*\b(moon|explode|crash|взорвется|упадет)\b',
            
            # Обзоры и рекапы
            r'\b(weekly|daily|monthly|недельный|ежедневный|ежемесячный)\b.*\b(recap|roundup|обзор|отчет)\b',
            r'\b(top|топ|лучший)\b.*\d+\b.*\b(coin|token|монет|токен)\b',
            r'\b(year|год)\b.*\b(in review|в обзоре|итоги)\b',
            
            # Промоакции и рефералы
            r'\b(airdrop|раздача|referral|promo|промо|bonus|бонус)\b',
            r'\b(sign up|register|зарегистрируйтесь|зарегистрироваться)\b',
            r'\b(click here|read more|узнать больше|подробнее)\b',
            r'\b(free|бесплатный|giveaway|розыгрыш)\b',
            
            # Вовлечение и опросы
            r'\b(what do you think|что думаете|как вы считаете)\b',
            r'\b(poll|опрос|vote|голосование)\b',
            r'\b(comment|комментарий|share|поделиться)\b',
            
            # Кликбейт и сенсационность
            r'\b(BREAKING|URGENT|ALERT|ЭКСТРЕННО|СРОЧНО|ВНИМАНИЕ)\b.*\!{2,}',
            r'\b(you won\'t believe|не поверите|шокирует|удивительно)\b',
            r'\b(secret|секрет|hidden|скрытый)\b.*\b(trick|strat|стратегия)\b',
            
            # Финансовые советы
            r'\b(invest|инвестировать|buy now|купи сейчас)\b.*\b(guarantee|гарантия)\b',
            r'\b(financial advice|финансовый совет|not advice|не совет)\b',
            
            # Спам и низкокачественный контент
            r'\b(like and subscribe|лайк и подписка|follow me|подпишись)\b',
            r'\b(\$+|\#+|\@+){5,}',  # Множество специальных символов
        ]
        
        # Паттерны мягкого отклонения (снижают оценку)
        self.soft_reject_patterns = [
            r'\b(maybe|возможно|probably|вероятно)\b',
            r'\b(could|might|может|может быть)\b.*\b(happen|произойти)\b',
            r'\b(rumor|слух|hearsay|молва)\b',
            r'\b(according to sources|по данным источников)\b',
        ]
        
        # Обязательные сигналы (должны присутствовать)
        self.required_signals = [
            # Суммы и объемы
            r'\b(\$?\d+[.,]?\d*\s*(?:m|mln|million|b|bln|billion|k|thousand)?\s*(?:usd|btc|eth))\b',
            r'\b(\d+\s*(?:миллион|миллиард|тысяч|млн|млрд|тыс))\b.*\b(доллар|btc|eth)\b',
            
            # Изменения в процентах
            r'\b(\+|-)\d+[.,]?\d*\s*%\b',
            r'\b(increase|decrease|рост|увеличение|падение|снижение)\b.*\b\d+\s*%\b',
            
            # Транзакции и перемещения
            r'\b(transfer|трансфер|перевод)\b.*\b\d+\s*(btc|eth|usd)\b',
            r'\b(liquidat|ликвидация)\b.*\b\d+\s*(?:m|b)?\s*usd\b',
            r'\b(hack|взлом|stolen|украдено)\b.*\b\d+\s*(?:m|b)?\s*usd\b',
            
            # Регуляторные действия
            r'\b(sec|cftc|fed|ecb|фрс|цб)\b.*\b(approve|reject|ban|fine|одобрить|запретить)\b',
            r'\b(binance|coinbase|bybit|kraken)\b.*\b(list|delist|suspend|листинг|делистинг)\b',
            
            # Институциональные действия
            r'\b(blackrock|fidelity|vanguard|ark)\b.*\b(etf|application|заявка)\b',
            r'\b(institution|институционал)\b.*\b(buy|purchase|покупка|приобретение)\b',
            
            # Технические события
            r'\b(upgrade|апгрейд|update|обновление)\b.*\b(version|версия)\b',
            r'\b(hard fork|хард форк|soft fork|софт форк)\b',
            r'\b(halving|халвинг|сокращение)\b',
            
            # Новости компаний
            r'\b(earnings|доход|revenue|выручка)\b.*\b(report|отчет)\b',
            r'\b(partnership|партнерство|collaboration|сотрудничество)\b',
        ]
        
        # Паттерны для дополнительных очков (повышают оценку)
        self.boost_patterns = [
            r'\b(official|официальный|confirmed|подтверждено)\b.*\b(announcement|объявление)\b',
            r'\b(breaking news|экстренные новости)\b.*\b(reliable|надежный)\b',
            r'\b(major|крупный|significant|значительный)\b.*\b(deal|сделка|event|событие)\b',
            r'\b(verified|проверенный|authenticated|аутентифицированный)\b.*\b(source|источник)\b',
            r'\b(exclusive|эксклюзив)\b',
        ]
        
        # Паттерны для извлечения сущностей
        self.entity_patterns = {
            'cryptocurrencies': r'\b(bitcoin|btc|ethereum|eth|solana|sol|cardano|ada|ripple|xrp|dogecoin|doge)\b',
            'companies': r'\b(tesla|microstrategy|square|paypal|visa|mastercard)\b',
            'exchanges': r'\b(binance|coinbase|kraken|huobi|okx|bybit)\b',
            'people': r'\b(elon musk|cathie wood|michael saylor|vitalik buterin)\b',
            'indexes': r'\b(s&p|nasdaq|dow jones|spx|ndx|dji)\b',
        }
        
        self.compiled_reject = [re.compile(p, re.IGNORECASE) for p in self.hard_reject_patterns]
        self.compiled_soft_reject = [re.compile(p, re.IGNORECASE) for p in self.soft_reject_patterns]
        self.compiled_signals = [re.compile(p, re.IGNORECASE) for p in self.required_signals]
        self.compiled_boost = [re.compile(p, re.IGNORECASE) for p in self.boost_patterns]
        self.compiled_entities = {k: re.compile(v, re.IGNORECASE) for k, v in self.entity_patterns.items()}
        
        # Минимальные требования
        self.min_length = 50
        self.min_numbers = 1
        self.min_signals = 1
        
    def quick_filter(self, text: str) -> FilterResult:
        """Быстрая проверка-фильтрация"""
        result = FilterResult(True, "Проверка пройдена")
        
        if not text or len(text.strip()) < self.min_length:
            return FilterResult(False, f"Текст слишком короткий (менее {self.min_length} символов)")
        
        text_lower = text.lower()
        
        # 1. Проверка на жесткие отклонения
        rejected_patterns = []
        for pattern in self.compiled_reject:
            if pattern.search(text_lower):
                rejected_patterns.append(pattern.pattern[:80])
        
        if rejected_patterns:
            result.passed = False
            result.reason = f"Обнаружены запрещенные паттерны: {', '.join(rejected_patterns[:3])}"
            result.matched_patterns = rejected_patterns
            return result
        
        # 2. Проверка обязательных сигналов
        found_signals = []
        for pattern in self.compiled_signals:
            if pattern.search(text_lower):
                found_signals.append(pattern.pattern[:80])
        
        if len(found_signals) < self.min_signals:
            result.passed = False
            result.reason = f"Недостаточно рыночных сигналов (найдено: {len(found_signals)}, требуется: {self.min_signals})"
            return result
        
        # 3. Проверка на наличие чисел
        numbers = self.extract_numbers(text)
        if len(numbers) < self.min_numbers:
            result.passed = False
            result.reason = f"Недостаточно числовых данных (найдено: {len(numbers)}, требуется: {self.min_numbers})"
            return result
        
        # 4. Проверка мягких отклонений (снижают оценку)
        soft_rejects = []
        for pattern in self.compiled_soft_reject:
            if pattern.search(text_lower):
                soft_rejects.append(pattern.pattern[:80])
                result.score -= 0.1
        
        # 5. Проверка на буст-паттерны (повышают оценку)
        boosts = []
        for pattern in self.compiled_boost:
            if pattern.search(text_lower):
                boosts.append(pattern.pattern[:80])
                result.score += 0.2
        
        # 6. Извлечение сущностей
        entities = self.extract_entities(text)
        if entities:
            result.extracted_data['entities'] = entities
        
        # 7. Рассчет финальной оценки
        result.score += self.calculate_score(text, found_signals, numbers, boosts, soft_rejects)
        result.score = max(0.0, min(1.0, result.score))  # Ограничиваем от 0 до 1
        
        # 8. Проверка структуры текста
        if not self.check_text_structure(text):
            result.score -= 0.1
        
        result.matched_patterns = found_signals + boosts
        result.extracted_data['numbers'] = numbers
        result.extracted_data['signal_count'] = len(found_signals)
        
        return result
    
    def calculate_score(self, text: str, signals: List[str], numbers: List[str], 
                       boosts: List[str], soft_rejects: List[str]) -> float:
        """Рассчет оценки качества контента"""
        score = 0.5  # Базовая оценка
        
        # Бонусы за сигналы
        score += min(len(signals) * 0.1, 0.3)
        
        # Бонусы за числа
        score += min(len(numbers) * 0.05, 0.2)
        
        # Бонусы за бусты
        score += len(boosts) * 0.1
        
        # Штрафы за мягкие отклонения
        score -= len(soft_rejects) * 0.05
        
        # Бонус за длину текста
        if len(text) > 200:
            score += 0.1
        if len(text) > 500:
            score += 0.1
        
        # Бонус за разнообразие сущностей
        entities = self.extract_entities(text)
        unique_entities = sum(len(v) for v in entities.values())
        if unique_entities > 3:
            score += 0.1
        
        return score
    
    def extract_numbers(self, text: str) -> List[str]:
        """Извлечение чисел из текста"""
        patterns = [
            r'\$?(\d+[.,]?\d*\s*(?:m|mln|million|b|bln|billion|k|thousand)?)\b',
            r'\b(\d+[.,]?\d*\s*%)\b',
            r'\b(\d+)\s*(?:btc|eth|bitcoin|ethereum)\b',
            r'\b(\d+\s*(?:миллион|миллиард|тысяч|млн|млрд|тыс))\b',
        ]
        
        numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            numbers.extend(matches)
        
        return numbers
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Извлечение сущностей из текста"""
        entities = {}
        
        for entity_type, pattern in self.compiled_entities.items():
            matches = pattern.findall(text)
            if matches:
                entities[entity_type] = list(set(matches))  # Убираем дубликаты
        
        return entities
    
    def check_text_structure(self, text: str) -> bool:
        """Проверка структуры текста"""
        # Проверка на заглавные буквы в начале предложений
        sentences = re.split(r'[.!?]+', text)
        valid_sentences = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence[0].isupper():
                valid_sentences += 1
        
        # Требуем хотя бы 70% корректных предложений
        if sentences and valid_sentences / len(sentences) > 0.7:
            return True
        
        return False
    
    def analyze_content_quality(self, text: str) -> Dict:
        """Полный анализ качества контента"""
        result = self.quick_filter(text)
        
        analysis = {
            'passed': result.passed,
            'score': result.score,
            'reason': result.reason,
            'statistics': {
                'length': len(text),
                'sentences': len(re.split(r'[.!?]+', text)),
                'numbers_count': len(result.extracted_data.get('numbers', [])),
                'signals_count': result.extracted_data.get('signal_count', 0),
                'entities_found': sum(len(v) for v in result.extracted_data.get('entities', {}).values()),
            },
            'entities': result.extracted_data.get('entities', {}),
            'matched_patterns': result.matched_patterns,
            'recommendations': self.generate_recommendations(result)
        }
        
        return analysis
    
    def generate_recommendations(self, result: FilterResult) -> List[str]:
        """Генерация рекомендаций для улучшения контента"""
        recommendations = []
        
        if result.score < 0.7:
            recommendations.append("Добавьте больше конкретных цифр и данных")
        
        if result.extracted_data.get('signal_count', 0) < 2:
            recommendations.append("Укажите больше рыночных сигналов (цены, объемы, изменения)")
        
        if not result.extracted_data.get('entities'):
            recommendations.append("Упоминайте конкретные активы, компании или персоны")
        
        if result.score > 0.8:
            recommendations.append("Контент высокого качества, можно публиковать")
        
        return recommendations
    
    def filter_batch(self, texts: List[str]) -> List[FilterResult]:
        """Фильтрация списка текстов"""
        results = []
        for text in texts:
            results.append(self.quick_filter(text))
        return results
    
    def get_filter_stats(self) -> Dict:
        """Получение статистики по фильтрам"""
        return {
            'hard_reject_patterns': len(self.hard_reject_patterns),
            'soft_reject_patterns': len(self.soft_reject_patterns),
            'required_signals': len(self.required_signals),
            'boost_patterns': len(self.boost_patterns),
            'entity_types': len(self.entity_patterns),
            'min_length': self.min_length,
            'min_numbers': self.min_numbers,
            'min_signals': self.min_signals
        }
