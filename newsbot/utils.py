"""
Вспомогательные функции для Crypto News Bot
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import List, Optional


def clean_text(text: str) -> str:
    """Очистка текста"""
    if not text:
        return ""
    
    # Удаление HTML тегов
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Удаление URL
    text = re.sub(r'https?://\S+', '', text)
    
    # Удаление упоминаний и хештегов
    text = re.sub(r'[@#]\w+', '', text)
    
    # Удаление лишних пробелов
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def extract_hashtags(text: str) -> List[str]:
    """Извлечение хештегов из текста"""
    hashtags = re.findall(r'#(\w+)', text, re.UNICODE)
    return list(set(hashtags))


def extract_mentions(text: str) -> List[str]:
    """Извлечение упоминаний из текста"""
    mentions = re.findall(r'@(\w+)', text, re.UNICODE)
    return list(set(mentions))


def generate_news_hash(news_item) -> str:
    """Генерация хеша для новости"""
    content = f"{news_item.source}:{news_item.raw_text[:500]}"
    if news_item.source_link:
        content += f":{news_item.source_link}"
    return hashlib.md5(content.encode()).hexdigest()


def format_datetime(dt: datetime) -> str:
    """Форматирование даты-времени"""
    if not dt:
        return ""
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def truncate_text(text: str, max_length: int = 200) -> str:
    """Обрезка текста с сохранением слов"""
    if len(text) <= max_length:
        return text
    
    # Находим последний пробел перед максимальной длиной
    truncated = text[:max_length]
    last_space = truncated.rfind(' ')
    
    if last_space > max_length * 0.7:  # Если есть подходящий пробел
        return truncated[:last_space] + "..."
    else:
        return truncated + "..."


def parse_money_amount(text: str) -> Optional[float]:
    """Парсинг денежной суммы из текста"""
    patterns = [
        r'\$?\s*(\d+\.?\d*)\s*(?:million|m|mln)\b',
        r'\$?\s*(\d+\.?\d*)\s*(?:billion|b|bln)\b',
        r'\$?\s*(\d+\.?\d*)\s*(?:thousand|k)\b',
        r'\$?\s*(\d+\.?\d*)\s*(?:usd|доллар)\b',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1).replace(',', ''))
                
                # Применяем множитель
                if 'million' in match.group(0).lower() or 'mln' in match.group(0).lower():
                    return amount * 1000000
                elif 'billion' in match.group(0).lower() or 'bln' in match.group(0).lower():
                    return amount * 1000000000
                elif 'thousand' in match.group(0).lower() or 'k' in match.group(0).lower():
                    return amount * 1000
                else:
                    return amount
            except (ValueError, AttributeError):
                continue
    
    return None


def is_valid_url(url: str) -> bool:
    """Проверка валидности URL"""
    import re
    pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(pattern.match(url)) if url else False