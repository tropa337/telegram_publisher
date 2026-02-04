import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class FilterResult:
    """Результат фильтрации"""
    passed: bool
    reason: str
    score: float = 0.5
    matched_patterns: List[str] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=dict)
    
    def __post_init__(self):
        self.score = max(0.0, min(1.0, self.score))


class StrictMarketFilter:
    """Строгий фильтр для рыночных новостей"""
    
    def __init__(self):
        """Инициализация паттернов"""
        # Жесткое отклонение
        self.hard_reject = self._compile_patterns([
            r'\b(мнение|opinion|прогноз|forecast|predict|think)\b',
            r'\b(дайджест|digest|recap|обзор|summary)\b',
            r'\b(реклама|promo|airdrop|гивавей|subscribe|подписывайтесь)\b',
            r'\b(вопрос\?|what do you think|как вы думаете)\b',
        ])
        
        # Мягкое отклонение (штраф)
        self.soft_reject = self._compile_patterns([
            r'\b(может быть|возможно|probably|could)\b',
            r'\b(слух|rumor|according to sources)\b',
        ])
        
        # Обязательные сигналы
        self.required_signals = self._compile_patterns([
            r'\$?\d+[.,]?\d*\s*(?:m|b|k|млн|млрд)\b',
            r'\b\d+[.,]?\d*\s*%\b',
            r'\b(btc|bitcoin|eth|ethereum|sec|etf|approve|reject|hack|transfer)\b',
        ])
        
        # Статистика по паттернам
        self.stats = {
            'hard_reject_patterns': len(self.hard_reject),
            'soft_reject_patterns': len(self.soft_reject),
            'required_signals': len(self.required_signals),
            'boost_patterns': 0,
            'entity_types': 0,
        }
    
    @staticmethod
    def _compile_patterns(patterns: List[str]) -> List[re.Pattern]:
        """Компиляция regex паттернов"""
        return [re.compile(p, re.IGNORECASE) for p in patterns]
    
    def quick_filter(self, text: str) -> FilterResult:
        """Быстрая фильтрация новости"""
        if not text or len(text.strip()) < 50:
            return FilterResult(False, "Текст слишком короткий")
        
        text_lower = text.lower()
        
        # Проверка на жесткое отклонение
        for pattern in self.hard_reject:
            if pattern.search(text_lower):
                return FilterResult(False, "Обнаружен запрещенный паттерн", 0.0)
        
        # Подсчет сигналов
        signals = sum(1 for p in self.required_signals if p.search(text_lower))
        if signals < 1:
            return FilterResult(False, f"Недостаточно сигналов: {signals}", 0.2)
        
        # Проверка на мягкое отклонение
        soft_count = sum(1 for p in self.soft_reject if p.search(text_lower))
        score = 0.7 - (soft_count * 0.1)
        
        return FilterResult(
            passed=True,
            reason=f"Пройдено ({signals} сигналов)",
            score=max(0.3, score),
            matched_patterns=[],
            statistics={'signals_count': signals}
        )
    
    def analyze_content_quality(self, text: str) -> Dict:
        """Полный анализ качества контента"""
        result = self.quick_filter(text)
        
        return {
            'passed': result.passed,
            'score': result.score,
            'reason': result.reason,
            'statistics': {
                'length': len(text),
                'signals_count': result.statistics.get('signals_count', 0),
                'numbers_count': len(re.findall(r'\d+', text)),
            },
            'entities': {}
        }
    
    def get_filter_stats(self) -> Dict:
        """Получить статистику фильтров"""
        return self.stats
