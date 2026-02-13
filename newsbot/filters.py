import re
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class FilterResult:
    passed: bool
    reason: str
    score: float = 0.5
    matched_patterns: List[str] = field(default_factory=list)
    statistics: Dict[str, int] = field(default_factory=dict)

class StrictMarketFilter:
    def __init__(self):
        self.hard = [re.compile(p, re.IGNORECASE) for p in [
            r'^\s*rt\b', r'\bзакреплено\b', r'^\s*конечно\s*$',
            r'\bдайджест\b', r'\bтоп\s*-\s*\d+\b',
        ]]
        self.signals = [re.compile(p, re.IGNORECASE) for p in [
            r'\b\d+[\.,]?\d*\s*%\b',
            r'\$\d',
            r'\b(btc|eth|sol|sec|cftc|etf|binance|coinbase)\b',
        ]]
    def quick_filter(self, text: str) -> FilterResult:
        t=(text or '').strip()
        if len(t) < 60:
            return FilterResult(False, 'Слишком короткий/пустой текст', 0.0)
        for p in self.hard:
            if p.search(t):
                return FilterResult(False, 'Запрещенный паттерн', 0.0)
        sig=sum(1 for p in self.signals if p.search(t))
        if sig < 1:
            return FilterResult(False, f'Недостаточно сигналов: {sig}', 0.2)
        return FilterResult(True, f'Прошло ({sig} сигналов)', 0.7, statistics={'signals': sig})
    def analyze_content_quality(self, text: str) -> Dict:
        r=self.quick_filter(text)
        return {'passed': r.passed, 'score': r.score, 'reason': r.reason, 'statistics': {'length': len(text or '')}}
    def get_filter_stats(self) -> Dict:
        return {}
