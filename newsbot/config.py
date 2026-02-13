import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Загрузка .env
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Конфигурация бота с валидацией"""
    
    # Telegram API
    TG_API_ID: int = field(default_factory=lambda: int(os.getenv("TG_API_ID", "0")))
    TG_API_HASH: str = field(default_factory=lambda: os.getenv("TG_API_HASH", ""))
    TARGET_CHANNEL: str = field(default_factory=lambda: os.getenv("TARGET_CHANNEL", ""))
    
    # Mistral AI
    MISTRAL_API_KEY: str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""))
    MISTRAL_MODEL: str = field(default_factory=lambda: os.getenv("MISTRAL_MODEL", "mistral-small-latest"))
    
    # Источники новостей
    SOURCE_TG_CHANNELS: List[str] = field(default_factory=lambda: [
        s.strip() for s in (os.getenv("SOURCE_TG_CHANNELS", "") or "").split(",") 
        if s.strip()
    ])
    
    TWITTER_RSS_FEEDS: Dict[str, str] = field(default_factory=dict)
    RSS_AUTH_TOKEN: str = field(default_factory=lambda: os.getenv("RSS_AUTH_TOKEN", ""))
    
    # Интервалы
    POLL_INTERVAL_RSS: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_RSS", "300")))
    MAX_WORKERS: int = field(default_factory=lambda: int(os.getenv("MAX_WORKERS", "3")))

    # Публикация / rate limit
    MAX_POSTS_PER_CYCLE: int = field(default_factory=lambda: int(os.getenv("MAX_POSTS_PER_CYCLE", "3")))
    MIN_GAP_SECONDS: int = field(default_factory=lambda: int(os.getenv("MIN_GAP_SECONDS", "60")))

    # Дедуп событий
    EVENT_DEDUP_HOURS: int = field(default_factory=lambda: int(os.getenv("EVENT_DEDUP_HOURS", "12")))
    
    # Фильтры
    MIN_PRIORITY_SCORE: float = field(default_factory=lambda: float(os.getenv("MIN_PRIORITY_SCORE", "0.6")))
    MAX_NEWS_PER_HOUR: int = field(default_factory=lambda: int(os.getenv("MAX_NEWS_PER_HOUR", "20")))
    
    # Кешевание и хранилище
    CACHE_TTL_HOURS: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_HOURS", "24")))
    STATE_PATH: str = field(default_factory=lambda: os.getenv("STATE_PATH", "state.json"))
    
    # Режим отладки
    DEBUG_MODE: bool = field(default_factory=lambda: os.getenv("DEBUG_MODE", "false").lower() == "true")
    
    # Медиа
    MAX_MEDIA_PER_POST: int = field(default_factory=lambda: int(os.getenv("MAX_MEDIA_PER_POST", "4")))
    ALWAYS_INCLUDE_MEDIA: bool = field(default_factory=lambda: os.getenv("ALWAYS_INCLUDE_MEDIA", "true").lower() == "true")
    
    def __post_init__(self):
        """Инициализация и валидация конфигурации"""
        # Загрузка RSS фидов
        i = 1
        while True:
            key = f"TWITTER_RSS_{i}"
            val = os.getenv(key, "").strip()
            if not val:
                break
            self.TWITTER_RSS_FEEDS[f"twitter_{i}"] = val
            i += 1
        
        # Валидация критических параметров
        self._validate()
    
    def _validate(self):
        """Валидация конфигурации"""
        errors = []
        
        if not self.TG_API_ID or self.TG_API_ID == 0:
            errors.append("TG_API_ID не установлен")
        
        if not self.TG_API_HASH:
            errors.append("TG_API_HASH не установлен")
        
        # MISTRAL_API_KEY может отсутствовать: тогда работаем в режиме без AI
        if not self.MISTRAL_API_KEY:
            logger.warning("⚠️ MISTRAL_API_KEY не установлен — бот будет работать без AI (без перевода/умной релевантности)")
        
        if not self.TARGET_CHANNEL:
            errors.append("TARGET_CHANNEL не установлен")
        
        if not self.SOURCE_TG_CHANNELS and not self.TWITTER_RSS_FEEDS:
            errors.append("Не настроены источники новостей")
        
        if errors:
            error_msg = "\n".join(f"- {e}" for e in errors)
            logger.error(f"❌ Ошибки конфигурации:\n{error_msg}")
            raise ValueError(f"Конфигурация некорректна:\n{error_msg}")
        
        logger.info("✅ Конфигурация валидна")
    
    def get_log_level(self) -> int:
        """Получение уровня логирования"""
        return logging.DEBUG if self.DEBUG_MODE else logging.INFO


# Глобальный экземпляр конфига
config: Optional[BotConfig] = None

def get_config() -> BotConfig:
    """Получить глобальную конфигурацию"""
    global config
    if config is None:
        config = BotConfig()
    return config