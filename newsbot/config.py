import os
from dataclasses import dataclass, field
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    # Telegram API
    tg_api_id: int = int(os.getenv("TG_API_ID", "0"))
    tg_api_hash: str = os.getenv("TG_API_HASH", "")
    target_channel: str = os.getenv("TARGET_CHANNEL", "")
    
    # Mistral AI
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    
    # Источники
    source_tg_channels: List[str] = field(
        default_factory=lambda: [
            s.strip() for s in (os.getenv("SOURCE_TG_CHANNELS", "") or "").split(",") 
            if s.strip()
        ]
    )
    
    # RSS источники
    twitter_rss_feeds: Dict[str, str] = field(default_factory=dict)
    
    # Опциональный токен для rss.app
    rss_auth_token: str = os.getenv("RSS_AUTH_TOKEN", "")
    
    # Интервалы
    poll_interval_rss: int = int(os.getenv("POLL_INTERVAL_RSS", "60") or "60")
    max_workers: int = int(os.getenv("MAX_WORKERS", "3") or "3")
    
    # Фильтры
    min_priority_score: float = float(os.getenv("MIN_PRIORITY_SCORE", "0.7") or "0.7")
    max_news_per_hour: int = int(os.getenv("MAX_NEWS_PER_HOUR", "10") or "10")
    
    # Кеширование
    cache_ttl_hours: int = int(os.getenv("CACHE_TTL_HOURS", "24") or "24")
    state_path: str = os.getenv("STATE_PATH", "state.json")
    
    # Режим отладки
    debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    def __post_init__(self):
        """Загрузка RSS фидов"""
        i = 1
        while True:
            key = f"TWITTER_RSS_{i}"
            val = os.getenv(key, "").strip()
            if not val:
                break
            self.twitter_rss_feeds[f"twitter_{i}"] = val
            i += 1


# Глобальный конфиг
config = BotConfig()

# Экспорт настроек для обратной совместимости
TG_API_ID = config.tg_api_id
TG_API_HASH = config.tg_api_hash
TARGET_CHANNEL = config.target_channel
SOURCE_TG_CHANNELS = config.source_tg_channels
TWITTER_RSS_FEEDS = config.twitter_rss_feeds
RSS_AUTH_TOKEN = config.rss_auth_token
POLL_INTERVAL_RSS = config.poll_interval_rss
MIN_PRIORITY_SCORE = config.min_priority_score
DEBUG_MODE = config.debug_mode