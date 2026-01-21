import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from ..types import MarketSignal


class MarketSignalDetector:
    """Детектор сигналов, влияющих на крипторынок"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # КРИТИЧЕСКИЕ СИГНАЛЫ
        self.critical_signals = [
            (r'\b(sec|сок)\s+(approves|rejects|denies|одобряет|отклоняет)\b', 'regulation', 0.95),
            (r'\b(etf)\s+(approved|rejected|одобрен|отклонен)\b', 'etf', 0.95),
            (r'\b(hack|взлом|кража)\b.*?\$?\s*(\d+[bmk]?)', 'security', 0.9),
            (r'\b(blackrock|fidelity)\b.*?\b(files|applies|подает)\b', 'institutional', 0.9),
            (r'\b(transferred|переведено)\b.*?\b(\d+)\s*(btc|bitcoin)\b', 'whale', 0.8),
        ]
        
        # ВАЖНЫЕ СИГНАЛЫ
        self.important_signals = [
            (r'\b(binance|coinbase)\s+(lists|delists|листинг|делистинг)\b', 'exchange', 0.7),
            (r'\b(court|суд)\s+(rules|decides|решает)\b', 'legal', 0.7),
        ]
        
        # СИГНАЛЫ-ФИЛЬТРЫ
        self.filter_signals = [
            (r'\b(i think|i believe|по моему мнению)\b', 'opinion', -0.8),
            (r'\b(weekly|daily)\b.*?\b(recap|roundup|обзор)\b', 'digest', -0.6),
            (r'\b(airdrop|giveaway|раздача)\b', 'promo', -0.9),
        ]
    
    def analyze_text(self, text: str) -> List[MarketSignal]:
        """Анализ текста на наличие рыночных сигналов"""
        text_lower = text.lower()
        signals = []
        
        # Критические сигналы
        for pattern, signal_type, confidence in self.critical_signals:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                details = self._extract_signal_details(match, text)
                signal = MarketSignal(
                    type=signal_type,
                    confidence=confidence,
                    impact_score=self._calculate_impact_score(signal_type, details),
                    details=details
                )
                signals.append(signal)
        
        # Важные сигналы
        for pattern, signal_type, confidence in self.important_signals:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                details = self._extract_signal_details(match, text)
                signal = MarketSignal(
                    type=signal_type,
                    confidence=confidence * 0.8,
                    impact_score=self._calculate_impact_score(signal_type, details),
                    details=details
                )
                signals.append(signal)
        
        # Применение фильтров
        filter_score = 1.0
        for pattern, signal_type, penalty in self.filter_signals:
            if re.search(pattern, text_lower, re.IGNORECASE):
                filter_score += penalty
        
        if filter_score < 0.5:
            for signal in signals:
                signal.confidence *= filter_score
        
        return signals
    
    def _extract_signal_details(self, match: re.Match, original_text: str) -> Dict[str, Any]:
        """Извлечение деталей из сигнала"""
        details = {
            'matched_text': match.group(0),
            'position': match.start(),
            'groups': match.groups()
        }
        
        # Извлечение чисел
        numbers = self._extract_numbers(original_text[match.start()-50:match.end()+50])
        if numbers:
            details['numbers'] = numbers
        
        return details
    
    def _extract_numbers(self, text: str) -> List[Dict]:
        """Извлечение числовых данных"""
        patterns = [
            r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|m|mln|billion|b|bln)?',
            r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:btc|bitcoin)',
            r'(\+|-)?\s*(\d+\.?\d*)\s*%',
        ]
        
        numbers = []
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    num_str = match.group(1).replace(',', '')
                    if '.' in num_str:
                        value = float(num_str)
                    else:
                        value = int(num_str)
                    
                    multiplier = 1
                    if 'million' in match.group(0).lower() or 'mln' in match.group(0).lower():
                        multiplier = 1000000
                    elif 'billion' in match.group(0).lower() or 'bln' in match.group(0).lower():
                        multiplier = 1000000000
                    
                    actual_value = value * multiplier
                    
                    numbers.append({
                        'value': actual_value,
                        'text': match.group(0),
                        'type': self._determine_number_type(match.group(0))
                    })
                except (ValueError, InvalidOperation):
                    continue
        
        return numbers
    
    def _determine_number_type(self, text: str) -> str:
        """Определение типа числа"""
        text_lower = text.lower()
        
        if '$' in text or 'usd' in text_lower:
            return 'usd'
        elif 'btc' in text_lower or 'bitcoin' in text_lower:
            return 'btc'
        elif '%' in text:
            return 'percentage'
        else:
            return 'generic'
    
    def _calculate_impact_score(self, signal_type: str, details: Dict) -> float:
        """Расчет оценки влияния"""
        type_weights = {
            'regulation': 0.9,
            'etf': 0.95,
            'security': 0.85,
            'institutional': 0.8,
            'whale': 0.7,
            'exchange': 0.6,
            'legal': 0.65,
        }
        
        base_score = type_weights.get(signal_type, 0.3)
        
        if 'numbers' in details:
            for number in details['numbers']:
                value = number['value']
                num_type = number['type']
                
                if num_type == 'usd':
                    if value >= 1000000000:
                        base_score *= 1.3
                    elif value >= 100000000:
                        base_score *= 1.2
                
                elif num_type == 'btc':
                    if value >= 10000:
                        base_score *= 1.3
                    elif value >= 1000:
                        base_score *= 1.2
                
                elif num_type == 'percentage':
                    if abs(value) >= 10:
                        base_score *= 1.2
        
        return min(1.0, base_score)