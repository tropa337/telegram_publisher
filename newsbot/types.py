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
        if self.type not in ['photo', 'video', 'gif', 'document', 'animation', 'youtube']:
            # Расширяем список поддерживаемых типов
            self.type = 'photo'  # По умолчанию фото
    
    @property
    def is_image(self) -> bool:
        return self.type in ['photo', 'gif', 'animation']


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
    source_item: NewsItem  # ✅ Сохраняем оригинал с медиа
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
        self.tags = list(set(self.tags))[:10]
    
    @property
    def has_media(self) -> bool:
        """Проверяем есть ли медиа в оригинальной новости"""
        return self.source_item.has_media if hasattr(self.source_item, 'has_media') else False
    
    @property
    def media_items(self) -> List[MediaItem]:
        """Получаем медиа из оригинальной новости"""
        return self.source_item.media_items if hasattr(self.source_item, 'media_items') else []


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
        # Если media_items не переданы, берем их из source_item
        if not self.media_items and hasattr(self.source_item, 'media_items'):
            self.media_items = self.source_item.media_items[:5]
        
        # Если все еще нет медиа, проверяем в анализе
        if not self.media_items and hasattr(self.analysis, 'media_items'):
            self.media_items = self.analysis.media_items[:5]
        
        if not self.editor_note and self.analysis.editor_note:
            self.editor_note = self.analysis.editor_note
        
        if 'published_at' not in self.metadata:
            self.metadata['published_at'] = datetime.now().isoformat()
        
        # Добавляем информацию о медиа в метаданные
        self.metadata['has_media'] = len(self.media_items) > 0
        self.metadata['media_count'] = len(self.media_items)
        if self.media_items:
            self.metadata['media_types'] = list(set([m.type for m in self.media_items]))
            self.metadata['media_urls'] = [m.url for m in self.media_items[:3]]
    
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