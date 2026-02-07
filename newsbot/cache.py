import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class CacheEntry:
    item_hash: str
    timestamp: float
    status: str  # 'processed', 'published', 'rejected'
    reason: Optional[str] = None
    metadata: Optional[Dict] = None


class NewsCache:
    def __init__(self, cache_file: str = "news_cache.json", ttl_hours: int = 24):
        self.cache_file = Path(cache_file)
        self.ttl_seconds = ttl_hours * 3600
        
        # In-memory кеш
        self.entries: Dict[str, CacheEntry] = {}
        self.processed_hashes: Set[str] = set()
        
        # Статистика
        self.stats = {
            'hits': 0,
            'misses': 0,
            'total_processed': 0,
            'total_published': 0
        }
        
        self._load_cache()
        
    def _load_cache(self):
        """Загрузка кеша из файла"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for key, entry_data in data.get('entries', {}).items():
                    entry = CacheEntry(**entry_data)
                    self.entries[key] = entry
                    self.processed_hashes.add(entry.item_hash)
                    
                self.stats = data.get('stats', self.stats)
                
                # Очистка устаревших записей
                self._cleanup_old_entries()
                
            except Exception as e:
                print(f"⚠️ Ошибка загрузки кеша: {e}")
                
    def _save_cache(self):
        """Сохранение кеша в файл"""
        try:
            data = {
                'entries': {k: asdict(v) for k, v in self.entries.items()},
                'stats': self.stats,
                'timestamp': time.time()
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"⚠️ Ошибка сохранения кеша: {e}")
            
    def _cleanup_old_entries(self):
        """Очистка устаревших записей"""
        current_time = time.time()
        to_remove = []
        
        for key, entry in self.entries.items():
            if current_time - entry.timestamp > self.ttl_seconds:
                to_remove.append(key)
                self.processed_hashes.discard(entry.item_hash)
                
        for key in to_remove:
            del self.entries[key]
            
        if to_remove:
            self._save_cache()
            
    def _generate_hash(self, news_item) -> str:
        """Генерация хеша для новости"""
        import hashlib

        # Собираем доступные поля
        content_parts = []
        
        # Источник
        if hasattr(news_item, 'source') and news_item.source:
            content_parts.append(str(news_item.source))
        
        # Текст
        text = ""
        if hasattr(news_item, 'raw_text') and news_item.raw_text:
            text = news_item.raw_text[:200]
        elif hasattr(news_item, 'text') and news_item.text:
            text = news_item.text[:200]
        elif hasattr(news_item, 'content') and news_item.content:
            text = news_item.content[:200]
        elif hasattr(news_item, 'title') and news_item.title:
            text = news_item.title
        content_parts.append(text)
        
        # Ссылка (с проверкой атрибута)
        if hasattr(news_item, 'source_link') and news_item.source_link:
            content_parts.append(news_item.source_link)
        elif hasattr(news_item, 'link') and news_item.link:
            content_parts.append(news_item.link)
        elif hasattr(news_item, 'url') and news_item.url:
            content_parts.append(news_item.url)
        
        # ID
        if hasattr(news_item, 'id') and news_item.id:
            content_parts.append(str(news_item.id))
        
        # Хеш
        content = ":".join(content_parts)
        return hashlib.md5(content.encode('utf-8')).hexdigest()
        
    def is_processed(self, news_item) -> bool:
        """Проверка, обрабатывалась ли уже новость"""
        item_hash = self._generate_hash(news_item)
        
        if item_hash in self.processed_hashes:
            self.stats['hits'] += 1
            return True
            
        self.stats['misses'] += 1
        return False
        
    def mark_processed(self, news_item, status: str, reason: Optional[str] = None):
        """Пометка новости как обработанной"""
        item_hash = self._generate_hash(news_item)
        
        # Метаданные
        metadata = {}
        if hasattr(news_item, 'source'):
            metadata['source'] = news_item.source
        
        # Превью текста
        if hasattr(news_item, 'raw_text'):
            metadata['text_preview'] = news_item.raw_text[:100]
        elif hasattr(news_item, 'text'):
            metadata['text_preview'] = news_item.text[:100]
        elif hasattr(news_item, 'content'):
            metadata['text_preview'] = news_item.content[:100]
        elif hasattr(news_item, 'title'):
            metadata['text_preview'] = news_item.title
        
        # Дата создания
        if hasattr(news_item, 'created_at') and news_item.created_at:
            if hasattr(news_item.created_at, 'isoformat'):
                metadata['created_at'] = news_item.created_at.isoformat()
            else:
                metadata['created_at'] = str(news_item.created_at)
        
        # Информация о медиа
        if hasattr(news_item, 'media_items') and news_item.media_items:
            metadata['has_media'] = True
            metadata['media_count'] = len(news_item.media_items)
            metadata['media_types'] = list(set([m.type for m in news_item.media_items[:3]]))
        else:
            metadata['has_media'] = False
        
        entry = CacheEntry(
            item_hash=item_hash,
            timestamp=time.time(),
            status=status,
            reason=reason,
            metadata=metadata if metadata else None
        )
        
        self.entries[item_hash] = entry
        self.processed_hashes.add(item_hash)
        self.stats['total_processed'] += 1
        
        # Периодическое сохранение
        if len(self.entries) % 10 == 0:
            self._save_cache()
            
    def update_stats(self, processed_news):
        """Обновление статистики публикаций"""
        self.stats['total_published'] += 1
        self._save_cache()
        
    def get_stats(self) -> Dict:
        """Получение статистики"""
        total = max(1, self.stats['hits'] + self.stats['misses'])
        return {
            **self.stats,
            'cache_size': len(self.entries),
            'hit_rate': self.stats['hits'] / total
        }
        
    def clear(self):
        """Очистка кеша"""
        self.entries.clear()
        self.processed_hashes.clear()
        self.stats = {'hits': 0, 'misses': 0, 'total_processed': 0, 'total_published': 0}
        self._save_cache()
        
    def save_now(self):
        """Немедленное сохранение кеша"""
        self._save_cache()