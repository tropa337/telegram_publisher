from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union


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
    TECHNOLOGY = "technology"
    EXCHANGE = "exchange"
    STABLECOIN = "stablecoin"
    OTHER = "other"


class MarketImpact(Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    EXTREME = 4


@dataclass
class MediaItem:
    """Медиа элемент (фото, видео, гифка)"""
    url: str
    type: str  # 'photo', 'video', 'gif', 'document'
    caption: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    
    @property
    def is_image(self) -> bool:
        """Проверка, является ли медиа изображением"""
        return self.type in ['photo', 'gif']


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
class MarketSignal:
    """Обнаруженный сигнал влияния на рынок"""
    type: str
    confidence: float
    impact_score: float
    details: Dict[str, Any]
    extracted_data: Optional[Dict] = None
    
    @classmethod
    def from_filter_result(cls, filter_data: Dict) -> 'MarketSignal':
        """Создание MarketSignal из данных фильтра"""
        return cls(
            type="filter_analysis",
            confidence=float(filter_data.get('score', 0.5)),
            impact_score=min(float(filter_data.get('score', 0.5)) * 2, 1.0),
            details={
                'signals_count': filter_data.get('signals_count', 0),
                'numbers_count': filter_data.get('numbers_count', 0),
                'entities': filter_data.get('entities', {}),
                'score': float(filter_data.get('score', 0.0))
            }
        )


@dataclass
class NewsItem:
    """Сырая новость из источника"""
    raw_text: str
    source: str
    url: str
    created_at: datetime
    media_urls: List[str] = field(default_factory=list)
    media_items: List[MediaItem] = field(default_factory=list)
    author: Optional[str] = None
    language: Optional[str] = None
    
    def __hash__(self):
        return hash((self.source, self.raw_text[:100], self.created_at.timestamp()))
    
    @property
    def has_media(self) -> bool:
        """Проверка наличия медиа"""
        return bool(self.media_urls) or bool(self.media_items)
    
    def add_media_item(self, url: str, media_type: str = None) -> None:
        """Добавление медиа элемента"""
        self.media_urls.append(url)
        
        if not media_type:
            url_lower = url.lower()
            if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                media_type = 'photo'
            elif '.gif' in url_lower:
                media_type = 'gif'
            elif any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm']):
                media_type = 'video'
            else:
                media_type = 'document'
        
        self.media_items.append(MediaItem(
            url=url,
            type=media_type
        ))


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
    
    @property
    def is_relevant(self) -> bool:
        """Является ли новость релевантной"""
        return self.relevance_score > 0.5


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
    
    @classmethod
    def from_ai_response(cls, news_item: NewsItem, ai_response) -> 'AnalyzedNews':
        """Создание AnalyzedNews из AIResponse или любого объекта с похожими атрибутами"""
        import re
        
        def safe_float(value, default=0.0):
            """Безопасное преобразование в float"""
            try:
                # Пробуем напрямую
                return float(value)
            except (ValueError, TypeError):
                # Если не получилось, ищем число в строке
                if isinstance(value, str):
                    numbers = re.findall(r'\d+\.?\d*', value)
                    if numbers:
                        num = float(numbers[0])
                        # Обработка процентов
                        if '%' in value:
                            return num / 100
                        return num
                    # Пытаемся определить по тексту
                    text = value.lower()
                    if any(word in text for word in ['высокий', 'high', 'сильный', 'extreme']):
                        return 0.9
                    elif any(word in text for word in ['средний', 'medium', 'умеренный', 'среднее']):
                        return 0.5
                    elif any(word in text for word in ['низкий', 'low', 'слабый']):
                        return 0.2
                return default
        
        # Безопасное получение атрибутов
        def get_attr(obj, attr, default):
            try:
                return getattr(obj, attr)
            except AttributeError:
                return default
        
        is_relevant = get_attr(ai_response, 'is_relevant', True)
        reason = get_attr(ai_response, 'reason', '')
        translated_text = get_attr(ai_response, 'translated_text', '')
        editor_note = get_attr(ai_response, 'editor_note', '')
        
        market_impact_value = get_attr(ai_response, 'market_impact', '0.5')
        confidence_value = get_attr(ai_response, 'confidence', '0.8')
        tags = get_attr(ai_response, 'tags', [])
        
        market_impact_float = safe_float(market_impact_value, 0.5)
        confidence_float = safe_float(confidence_value, 0.8)
        
        # Определяем MarketImpact
        if market_impact_float > 0.8:
            market_impact = MarketImpact.EXTREME
        elif market_impact_float > 0.6:
            market_impact = MarketImpact.HIGH
        elif market_impact_float > 0.4:
            market_impact = MarketImpact.MEDIUM
        elif market_impact_float > 0.2:
            market_impact = MarketImpact.LOW
        else:
            market_impact = MarketImpact.NONE
        
        # Определяем NewsPriority
        if confidence_float > 0.8:
            priority = NewsPriority.HIGH
        elif confidence_float > 0.6:
            priority = NewsPriority.MEDIUM
        else:
            priority = NewsPriority.LOW
        
        return cls(
            source_item=news_item,
            is_relevant=is_relevant,
            relevance_reason=reason,
            translated_text=translated_text,
            editor_note=editor_note,
            confidence=confidence_float,
            market_impact=market_impact,
            priority=priority,
            tags=tags,
            metadata={
                'ai_analysis': True,
                'original_market_impact': str(market_impact_value),
                'original_confidence': str(confidence_value)
            }
        )
    
    @classmethod
    def from_content_analysis(cls, news_item: NewsItem, content_analysis: ContentAnalysis, 
                              reason: str = "AI анализ") -> 'AnalyzedNews':
        """Создание AnalyzedNews из ContentAnalysis"""
        # Конвертация market_impact float в MarketImpact enum
        if content_analysis.market_impact > 0.8:
            market_impact = MarketImpact.EXTREME
        elif content_analysis.market_impact > 0.6:
            market_impact = MarketImpact.HIGH
        elif content_analysis.market_impact > 0.4:
            market_impact = MarketImpact.MEDIUM
        elif content_analysis.market_impact > 0.2:
            market_impact = MarketImpact.LOW
        else:
            market_impact = MarketImpact.NONE
        
        return cls(
            source_item=news_item,
            is_relevant=content_analysis.is_relevant,
            relevance_reason=reason,
            summary=content_analysis.summary,
            category=content_analysis.category,
            priority=content_analysis.priority,
            market_impact=market_impact,
            confidence=content_analysis.confidence,
            tags=content_analysis.tags,
            metadata={
                'ai_analysis': True,
                'content_analysis': content_analysis
            }
        )


@dataclass
class ProcessedNews:
    """Обработанная готовая новость"""
    source_item: NewsItem
    analysis: Union[AnalyzedNews, AIResponse, ContentAnalysis]
    formatted_text: str = ""
    editor_note: Optional[str] = None
    publish_time: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    media_items: List[MediaItem] = field(default_factory=list)
    
    def __post_init__(self):
        if self.publish_time is None:
            self.publish_time = datetime.now()
        
        if not self.media_items and hasattr(self.source_item, 'media_items'):
            self.media_items = self.source_item.media_items[:5]
        
        if not self.editor_note:
            if isinstance(self.analysis, AnalyzedNews) and self.analysis.editor_note:
                self.editor_note = self.analysis.editor_note
            elif isinstance(self.analysis, AIResponse) and self.analysis.editor_note:
                self.editor_note = self.analysis.editor_note
        
        if 'analysis_type' not in self.metadata:
            self.metadata['analysis_type'] = type(self.analysis).__name__
        
        self.metadata['has_media'] = bool(self.media_items)
        self.metadata['media_count'] = len(self.media_items)
    
    @property
    def has_media(self) -> bool:
        """Проверка наличия медиа"""
        return bool(self.media_items)
    
    @property
    def image_urls(self) -> List[str]:
        """Получение URL изображений"""
        return [item.url for item in self.media_items if item.is_image]
    
    @property
    def main_image_url(self) -> Optional[str]:
        """Получение URL главного изображения"""
        image_urls = self.image_urls
        return image_urls[0] if image_urls else None


@dataclass
class FilterResult:
    """Результат фильтрации"""
    passed: bool
    reason: str
    score: float = 0.0
    matched_patterns: List[str] = field(default_factory=list)
    extracted_data: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if self.extracted_data is None:
            self.extracted_data = {}


@dataclass
class DedupResult:
    """Результат дедупликации"""
    is_duplicate: bool
    similarity: float = 0.0
    reason: str = ""
    matched_item: Optional[NewsItem] = None


@dataclass
class PublishResult:
    """Результат публикации"""
    success: bool
    message_id: Optional[int] = None
    channel: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def is_success(self) -> bool:
        return self.success


def create_news_item(raw_text: str, source: str, url: str = "", 
                    media_urls: List[str] = None, author: str = None) -> NewsItem:
    """Создание NewsItem с минимальными параметрами"""
    return NewsItem(
        raw_text=raw_text,
        source=source,
        url=url or f"https://example.com/{hash(raw_text[:50])}",
        created_at=datetime.now(),
        media_urls=media_urls or [],
        author=author
    )


def create_processed_news(news_item: NewsItem, analyzed_news: AnalyzedNews, 
                         formatted_text: str) -> ProcessedNews:
    """Создание ProcessedNews из AnalyzedNews"""
    return ProcessedNews(
        source_item=news_item,
        analysis=analyzed_news,
        formatted_text=formatted_text,
        editor_note=analyzed_news.editor_note,
        metadata={
            'confidence': analyzed_news.confidence,
            'market_impact': analyzed_news.market_impact.value,
            'tags': analyzed_news.tags,
            'has_media': news_item.has_media,
            'entities': analyzed_news.entities,
            'signals_count': len(analyzed_news.signals)
        }
    )


__all__ = [
    'NewsPriority',
    'NewsCategory',
    'MarketImpact',
    'MediaItem',
    'AIResponse',
    'MarketSignal',
    'NewsItem',
    'ContentAnalysis',
    'AnalyzedNews',
    'ProcessedNews',
    'FilterResult',
    'DedupResult',
    'PublishResult',
    'create_news_item',
    'create_processed_news'
]