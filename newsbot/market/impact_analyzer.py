import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..types import MarketImpact, MarketSignal, NewsCategory, NewsPriority


class ImpactAnalyzer:
    """Анализатор влияния новости на рынок"""
    
    def __init__(self, context_tracker):
        self.logger = logging.getLogger(__name__)
        self.context_tracker = context_tracker
        
        self.impact_weights = {
            'signal_strength': 0.4,
            'market_context': 0.3,
            'source_credibility': 0.15,
            'timeliness': 0.1,
            'data_completeness': 0.05
        }
        
        self.category_impact_map = {
            NewsCategory.REGULATION: MarketImpact.HIGH,
            NewsCategory.ETF: MarketImpact.EXTREME,
            NewsCategory.SECURITY: MarketImpact.HIGH,
            NewsCategory.INSTITUTIONAL: MarketImpact.HIGH,
            NewsCategory.WHALE: MarketImpact.MEDIUM,
            NewsCategory.EXCHANGE: MarketImpact.MEDIUM,
            NewsCategory.LEGAL: MarketImpact.MEDIUM,
            NewsCategory.ADOPTION: MarketImpact.LOW,
            NewsCategory.TECHNOLOGY: MarketImpact.LOW,
            NewsCategory.MACRO: MarketImpact.LOW,
        }
    
    def analyze_impact(self, signals: List[MarketSignal], news_text: str, 
                      source: str, created_at: datetime) -> Dict:
        """Анализ влияния новости"""
        
        # Анализ силы сигналов
        signal_analysis = self._analyze_signals(signals)
        
        # Контекстный анализ
        context_analysis = self.context_tracker.get_market_context_for_news(news_text)
        
        # Анализ источника
        source_analysis = self._analyze_source(source)
        
        # Анализ своевременности
        timeliness_analysis = self._analyze_timeliness(created_at)
        
        # Анализ данных
        data_analysis = self._analyze_data_completeness(news_text, signals)
        
        # Комбинированный счет
        combined_score = self._combine_scores(
            signal_analysis['score'],
            context_analysis['relevance_score'],
            source_analysis['score'],
            timeliness_analysis['score'],
            data_analysis['score']
        )
        
        # Определение категории и приоритета
        category = self._determine_category(signals, news_text)
        priority = self._determine_priority(combined_score, category)
        market_impact = self._determine_market_impact(combined_score, category)
        
        return {
            'overall_score': combined_score,
            'category': category,
            'priority': priority,
            'market_impact': market_impact,
            'signal_analysis': signal_analysis,
            'context_analysis': context_analysis,
            'recommendation': self._get_recommendation(combined_score)
        }
    
    def _analyze_signals(self, signals: List[MarketSignal]) -> Dict:
        """Анализ силы сигналов"""
        if not signals:
            return {'score': 0.0, 'strongest_signal': None, 'count': 0}
        
        strongest = max(signals, key=lambda x: x.impact_score * x.confidence)
        total_score = sum(s.impact_score * s.confidence for s in signals)
        avg_score = total_score / len(signals)
        
        critical_count = sum(1 for s in signals if s.impact_score > 0.7)
        if critical_count > 0:
            avg_score = min(1.0, avg_score * (1 + critical_count * 0.2))
        
        return {
            'score': avg_score,
            'strongest_signal': strongest.type,
            'count': len(signals),
            'critical_count': critical_count
        }
    
    def _analyze_source(self, source: str) -> Dict:
        """Анализ надежности источника"""
        source_scores = {
            'sec.gov': 0.95,
            'cftc.gov': 0.95,
            'reuters.com': 0.9,
            'bloomberg.com': 0.9,
            'coindesk.com': 0.8,
            'cointelegraph.com': 0.8,
            'twitter.com/binance': 0.8,
            'twitter.com/coinbase': 0.8,
            'twitter.com/': 0.4,
            'reddit.com': 0.3,
            'telegram': 0.3,
            'default': 0.5
        }
        
        score = source_scores['default']
        for key, value in source_scores.items():
            if key in source.lower():
                score = value
                break
        
        reliability = 'high' if score >= 0.8 else 'medium' if score >= 0.6 else 'low'
        
        return {
            'score': score,
            'reliability': reliability
        }
    
    def _analyze_timeliness(self, created_at: datetime) -> Dict:
        """Анализ своевременности"""
        now = datetime.now(timezone.utc)
        age_hours = (now - created_at).total_seconds() / 3600
        
        if age_hours <= 0.5:
            score = 1.0
            timeliness = 'very_fresh'
        elif age_hours <= 2:
            score = 0.9
            timeliness = 'fresh'
        elif age_hours <= 6:
            score = 0.7
            timeliness = 'recent'
        elif age_hours <= 12:
            score = 0.5
            timeliness = 'aging'
        elif age_hours <= 24:
            score = 0.3
            timeliness = 'old'
        else:
            score = 0.1
            timeliness = 'very_old'
        
        return {
            'score': score,
            'timeliness': timeliness,
            'age_hours': age_hours
        }
    
    def _analyze_data_completeness(self, text: str, signals: List[MarketSignal]) -> Dict:
        """Анализ полноты данных"""
        completeness_factors = []
        
        has_numbers = any('numbers' in s.details for s in signals)
        completeness_factors.append(0.3 if has_numbers else 0.0)
        
        time_indicators = ['today', 'yesterday', 'hours', 'minutes', 'q1', 'q2']
        has_time = any(indicator in text.lower() for indicator in time_indicators)
        completeness_factors.append(0.2 if has_time else 0.0)
        
        specific_entities = ['sec', 'binance', 'blackrock', 'ethereum', 'bitcoin']
        has_entities = any(entity in text.lower() for entity in specific_entities)
        completeness_factors.append(0.2 if has_entities else 0.0)
        
        text_length_score = min(1.0, len(text) / 500)
        completeness_factors.append(text_length_score * 0.1)
        
        total_score = sum(completeness_factors)
        
        return {
            'score': total_score,
            'has_numbers': has_numbers,
            'has_time': has_time,
            'has_entities': has_entities,
            'text_length': len(text)
        }
    
    def _combine_scores(self, *scores) -> float:
        """Комбинирование оценок"""
        weighted_sum = 0.0
        total_weight = 0.0
        
        for score, weight in zip(scores, self.impact_weights.values()):
            weighted_sum += score * weight
            total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def _determine_category(self, signals: List[MarketSignal], text: str) -> NewsCategory:
        """Определение категории"""
        for signal in signals:
            if signal.type == 'regulation' and signal.confidence > 0.7:
                return NewsCategory.REGULATION
            elif signal.type == 'etf' and signal.confidence > 0.7:
                return NewsCategory.ETF
            elif signal.type == 'security' and signal.confidence > 0.7:
                return NewsCategory.SECURITY
            elif signal.type == 'institutional' and signal.confidence > 0.7:
                return NewsCategory.INSTITUTIONAL
            elif signal.type == 'whale' and signal.confidence > 0.6:
                return NewsCategory.WHALE
        
        text_lower = text.lower()
        if any(word in text_lower for word in ['court', 'judge', 'суди']):
            return NewsCategory.LEGAL
        elif any(word in text_lower for word in ['adopt', 'accept', 'принят']):
            return NewsCategory.ADOPTION
        
        return NewsCategory.OTHER
    
    def _determine_priority(self, score: float, category: NewsCategory) -> NewsPriority:
        """Определение приоритета"""
        if score >= 0.8:
            base_priority = NewsPriority.CRITICAL
        elif score >= 0.6:
            base_priority = NewsPriority.HIGH
        elif score >= 0.4:
            base_priority = NewsPriority.MEDIUM
        else:
            base_priority = NewsPriority.LOW
        
        if category in [NewsCategory.REGULATION, NewsCategory.ETF, NewsCategory.SECURITY]:
            if base_priority.value < NewsPriority.HIGH.value:
                return NewsPriority.HIGH
        
        return base_priority
    
    def _determine_market_impact(self, score: float, category: NewsCategory) -> MarketImpact:
        """Определение влияния на рынок"""
        if score >= 0.8:
            base_impact = MarketImpact.EXTREME
        elif score >= 0.7:
            base_impact = MarketImpact.HIGH
        elif score >= 0.5:
            base_impact = MarketImpact.MEDIUM
        elif score >= 0.3:
            base_impact = MarketImpact.LOW
        else:
            base_impact = MarketImpact.NONE
        
        category_impact = self.category_impact_map.get(category, MarketImpact.LOW)
        return max(base_impact, category_impact, key=lambda x: x.value)
    
    def _get_recommendation(self, score: float) -> str:
        """Рекомендация по публикации"""
        if score >= 0.8:
            return "НЕМЕДЛЕННАЯ ПУБЛИКАЦИЯ"
        elif score >= 0.6:
            return "Рекомендуется публикация"
        elif score >= 0.4:
            return "Рассмотреть публикацию"
        elif score >= 0.2:
            return "Возможна публикация"
        else:
            return "Не публиковать" 