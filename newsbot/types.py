from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class NewsPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class NewsCategory(Enum):
    MARKET_MOVEMENT = "market_movement"
    REGULATION = "regulation"
    SECURITY = "security"
    ECOSYSTEM = "ecosystem"
    INSTITUTIONAL = "institutional"
    MACRO = "macro"
    OTHER = "other"


@dataclass
class AIResponse:
    """Ответ от AI анализа"""
    is_relevant: bool
    reason: str
    translated_text: str = ""
    editor_note: str = ""
    confidence: float = 0.0
    market_impact: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class NewsItem:
    """Сырая новость из источника"""
    source: str
    created_at: datetime
    raw_text: str
    source_link: Optional[str] = None
    media_url: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)  # Добавляем поддержку нескольких медиа
    author: Optional[str] = None
    language: str = "auto"
    
    def __hash__(self):
        return hash((self.source, self.raw_text[:100], self.created_at.timestamp()))


@dataclass
class ContentAnalysis:
    """Результат AI-анализа контента"""
    relevance_score: float  # 0.0 - 1.0
    priority: NewsPriority
    category: NewsCategory
    summary: str
    tags: List[str] = field(default_factory=list)
    market_impact: float = 0.5  # 0.0 - 1.0
    confidence: float = 0.8  # 0.0 - 1.0
    
    @property
    def priority_score(self) -> float:
        """Общая оценка приоритета"""
        return (
            self.relevance_score * 0.4 +
            self.market_impact * 0.4 +
            self.confidence * 0.2
        )


@dataclass
class ProcessedNews:
    """Обработанная готовая новость"""
    source_item: NewsItem
    analysis: Any  # Может быть AIResponse или ContentAnalysis
    formatted_text: str = ""
    editor_note: Optional[str] = None
    publish_time: Optional[datetime] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

# ============ ДОБАВЬТЕ ПОСЛЕ СУЩЕСТВУЮЩЕГО КОДА ============

class MarketImpact(Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    EXTREME = 4


@dataclass
class MarketSignal:
    """Обнаруженный сигнал влияния на рынок"""
    type: str
    confidence: float
    impact_score: float
    details: Dict[str, Any]
    extracted_data: Optional[Dict] = None


@dataclass
class AnalyzedNews:
    """Проанализированная новость"""
    source_item: NewsItem
    is_relevant: bool
    relevance_reason: str
    
    translated_text: str = ""
    summary: str = ""
    editor_note: str = ""
    
    category: Optional[NewsCategory] = None
    priority: NewsPriority = NewsPriority.LOW
    market_impact: MarketImpact = MarketImpact.NONE
    
    signals: List[MarketSignal] = field(default_factory=list)
    confidence: float = 0.0
    impact_score: float = 0.0
    
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)