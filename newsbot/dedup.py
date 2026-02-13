import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import mmh3


@dataclass
class DedupResult:
    is_duplicate: bool
    similarity: float
    reason: str
    matched_with: Optional[str] = None


class DeduplicationEngine:
    def __init__(self, max_history: int = 1000, similarity_threshold: float = 0.8):
        self.max_history = max_history
        self.similarity_threshold = similarity_threshold
        
        # Хранилище сигнатур
        self.signatures: Dict[str, Dict] = {}
        self.shingle_cache: Dict[str, Set[int]] = {}
        
        # Временное окно для дедупликации
        self.time_window_hours = 24

        # Event-key дедуп (уровень C)
        self.event_window_hours = 12
        self.event_index: Dict[str, float] = {}
        
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста для сравнения"""
        if not text:
            return ""
            
        # Приведение к нижнему регистру
        text = text.lower()
        
        # Удаление ссылок
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        
        # Удаление упоминаний и хештегов
        text = re.sub(r'[@#]\w+', '', text)
        
        # Удаление специальных символов
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Удаление лишних пробелов
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Удаление стоп-слов
        stop_words = {
            'the', 'and', 'for', 'with', 'that', 'this', 'from',
            'в', 'на', 'и', 'или', 'но', 'а', 'то', 'же', 'бы', 'ли'
        }
        words = [w for w in text.split() if w not in stop_words and len(w) > 2]
        
        return ' '.join(words)
        
    def _create_shingles(self, text: str, k: int = 3) -> Set[int]:
        """Создание шинглов для MinHash"""
        if not text:
            return set()
            
        # Используем кеш
        cache_key = f"{hashlib.md5(text.encode()).hexdigest()}_{k}"
        if cache_key in self.shingle_cache:
            return self.shingle_cache[cache_key]
            
        words = text.split()
        if len(words) < k:
            shingles = {hash(' '.join(words))}
        else:
            shingles = set()
            for i in range(len(words) - k + 1):
                shingle = ' '.join(words[i:i + k])
                shingles.add(mmh3.hash(shingle))
                
        self.shingle_cache[cache_key] = shingles
        return shingles
        
    def _jaccard_similarity(self, set1: Set[int], set2: Set[int]) -> float:
        """Расчет коэффициента Жаккара"""
        if not set1 or not set2:
            return 0.0
            
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0.0
        
    def _create_signature(self, text: str) -> Dict:
        """Создание сигнатуры текста"""
        normalized = self._normalize_text(text)
        
        if not normalized:
            return {}
            
        # MinHash с несколькими хеш-функциями
        hashes = []
        for seed in range(10):  # 10 хеш-функций
            min_hash = float('inf')
            words = normalized.split()
            
            for i in range(0, len(words), 3):
                chunk = ' '.join(words[i:i+3])
                hash_val = mmh3.hash(chunk, seed)
                min_hash = min(min_hash, hash_val)
                
            hashes.append(min_hash)
            
        # TF-IDF like вектор (упрощенный)
        word_freq = {}
        words = normalized.split()
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1
            
        # Основные сущности
        entities = re.findall(r'\b[A-Z][a-z]+\b', text)
        
        return {
            'minhash': hashes,
            'word_freq': word_freq,
            'entities': list(set(entities)),
            'length': len(normalized),
            'hash': hashlib.md5(normalized.encode()).hexdigest()
        }
        
    def check(self, news_item) -> DedupResult:
        """Проверка на дубликаты"""
        from .types import NewsItem
        
        if not isinstance(news_item, NewsItem):
            return DedupResult(False, 0.0, "invalid_type")
            
        # Проверка по ссылке (с проверкой атрибута)
        if hasattr(news_item, 'source_link') and news_item.source_link and news_item.source_link in self.signatures:
            return DedupResult(True, 1.0, "exact_link", news_item.source_link)
            
        # Создание сигнатуры
        text_to_check = ""
        if hasattr(news_item, 'raw_text') and news_item.raw_text:
            text_to_check = news_item.raw_text
        elif hasattr(news_item, 'text') and news_item.text:
            text_to_check = news_item.text
        elif hasattr(news_item, 'content') and news_item.content:
            text_to_check = news_item.content
        elif hasattr(news_item, 'title') and news_item.title:
            text_to_check = news_item.title
            
        signature = self._create_signature(text_to_check)
        if not signature:
            return DedupResult(False, 0.0, "empty_signature")
            
        # Поиск похожих
        best_match = None
        best_similarity = 0.0
        
        for existing_id, existing_sig in list(self.signatures.items()):
            # Проверка по MinHash
            minhash_sim = sum(
                1 for a, b in zip(signature['minhash'], existing_sig['minhash'])
                if a == b
            ) / len(signature['minhash'])
            
            if minhash_sim > best_similarity:
                best_similarity = minhash_sim
                best_match = existing_id
                
            # Если найдено явное совпадение
            if minhash_sim > self.similarity_threshold:
                return DedupResult(
                    True, minhash_sim, "similar_content", existing_id
                )
                
        # Проверка по шинглам
        if best_similarity > 0.5:
            text1 = self._normalize_text(text_to_check)
            existing_text = None
            
            for item in self.signatures.values():
                if 'original_text' in item:
                    existing_text = item['original_text']
                    break
                    
            if existing_text:
                shingles1 = self._create_shingles(text1)
                shingles2 = self._create_shingles(self._normalize_text(existing_text))
                
                jaccard = self._jaccard_similarity(shingles1, shingles2)
                
                if jaccard > self.similarity_threshold:
                    return DedupResult(True, jaccard, "similar_shingles", best_match)
                    
        # Сохраняем сигнатуру
        sig_id = signature['hash']
        signature['original_text'] = text_to_check
        signature['timestamp'] = datetime.now().timestamp()
        
        if hasattr(news_item, 'source'):
            signature['source'] = news_item.source
            
        self.signatures[sig_id] = signature
        
        # Очистка старых записей
        self._cleanup_old_signatures()
        
        return DedupResult(False, best_similarity, "unique")
        

    def set_event_window_hours(self, hours: int):
        """Настроить окно event-key дедупликации"""
        try:
            self.event_window_hours = max(1, int(hours))
        except Exception:
            self.event_window_hours = 12

    def check_event_key(self, event_key: str) -> bool:
        """Вернёт True если event_key уже встречался в окне, иначе False и запишет его"""
        if not event_key:
            return False
        now = datetime.now().timestamp()
        cutoff = now - (self.event_window_hours * 3600)
        # cleanup
        for k, ts in list(self.event_index.items()):
            if ts < cutoff:
                self.event_index.pop(k, None)
        if event_key in self.event_index:
            return True
        self.event_index[event_key] = now
        return False

    def _cleanup_old_signatures(self):
        """Очистка старых сигнатур"""
        current_time = datetime.now().timestamp()
        cutoff = current_time - (self.time_window_hours * 3600)
        
        to_remove = []
        for sig_id, sig_data in self.signatures.items():
            if sig_data.get('timestamp', 0) < cutoff:
                to_remove.append(sig_id)
                
        for sig_id in to_remove:
            self.signatures.pop(sig_id, None)
            
        # Ограничение размера
        if len(self.signatures) > self.max_history:
            sorted_items = sorted(
                self.signatures.items(),
                key=lambda x: x[1].get('timestamp', 0)
            )
            for sig_id, _ in sorted_items[:len(self.signatures) - self.max_history]:
                self.signatures.pop(sig_id, None)