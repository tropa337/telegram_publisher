from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class NewsPriority(Enum):
    """Приоритет публикации новости"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class NewsCategory(Enum):
    """Категория новости"""
    REGULATION = "regulation"
    ETF = "etf"
    SECURITY = "security"
    INSTITUTIONAL = "institutional"
    WHALE = "whale"
    EXCHANGE = "exchange"
    LEGAL = "legal"
    ADOPTION = "adoption"
    TECHNOLOGY = "technology"
    MACRO = "macro"
    OTHER = "other"


class MarketImpact(Enum):
    """Влияние на рынок"""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    EXTREME = 4


@dataclass
class MediaItem:
    """Элемент медиа"""
    url: str
    type: str  # photo, video, gif, document
    caption: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    
    def __post_init__(self):
        """Валидация при создании"""
        if not self.url or not isinstance(self.url, str):
            raise ValueError("URL должен быть непустой строкой")
        if self.type not in ['photo', 'video', 'gif', 'document']:
            raise ValueError(f"Неизвестный тип медиа: {self.type}")
    
    @property
    def is_image(self) -> bool:
        return self.type in ['photo', 'gif']


@dataclass
class NewsItem:
    """Сырая новость из источника"""
    raw_text: str
    source: str
    url: str
    created_at: datetime
    media_items: List[MediaItem] = field(default_factory=list)
    author: Optional[str] = None
    language: Optional[str] = "en"
    
    def __post_init__(self):
        """Валидация при создании"""
        if not self.raw_text or not isinstance(self.raw_text, str):
            raise ValueError("raw_text должен быть непустой строкой")
        if not self.source or not isinstance(self.source, str):
            raise ValueError("source должен быть непустой строкой")
        if not self.url or not isinstance(self.url, str):
            raise ValueError("url должен быть непустой строкой")
    
    def __hash__(self) -> int:
        """Хеш для использования в множествах"""
        return hash((self.source, self.raw_text[:100]))
    
    @property
    def has_media(self) -> bool:
        return bool(self.media_items)
    
    @property
    def text_length(self) -> int:
        return len(self.raw_text)


@dataclass
class AnalyzedNews:
    """Проанализированная новость"""
    source_item: NewsItem
    is_relevant: bool
    relevance_reason: str
    translated_text: str = ""
    editor_note: str = ""
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.5
    market_impact: str = "medium"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Валидация и нормализация"""
        self.confidence = max(0.0, min(1.0, self.confidence))
        if not isinstance(self.tags, list):
            self.tags = []
        self.tags = list(set(self.tags))[:10]  # Уникальные, макс 10


@dataclass
class ProcessedNews:
    """Обработанная готовая новость"""
    source_item: NewsItem
    analysis: AnalyzedNews
    formatted_text: str
    media_items: List[MediaItem] = field(default_factory=list)
    editor_note: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Инициализация метаданных"""
        if not self.media_items and self.source_item.media_items:
            self.media_items = self.source_item.media_items[:5]
        
        if not self.editor_note and self.analysis.editor_note:
            self.editor_note = self.analysis.editor_note
        
        if 'published_at' not in self.metadata:
            self.metadata['published_at'] = datetime.now().isoformat()
    
    @property
    def has_media(self) -> bool:
        return bool(self.media_items)


__all__ = [
    'NewsPriority',
    'NewsCategory',
    'MarketImpact',
    'MediaItem',
    'NewsItem',
    'AnalyzedNews',
    'ProcessedNews',
]