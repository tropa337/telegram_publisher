import os

from dotenv import load_dotenv

load_dotenv()

TG_API_ID = int(os.getenv("TG_API_ID", "0") or "0")
TG_API_HASH = os.getenv("TG_API_HASH", "")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

# Скорость для RSS-пуллинга
POLL_INTERVAL_RSS = int(os.getenv("POLL_INTERVAL_RSS", "60") or "60")

STATE_PATH = os.getenv("STATE_PATH", "state.json")

# Telegram источники (каналы через запятую)
SOURCE_TG_CHANNELS = [s.strip() for s in (os.getenv("SOURCE_TG_CHANNELS", "")).split(",") if s.strip()]

# Twitter RSS: парсим переменные TWITTER_RSS_1, TWITTER_RSS_2, и т.д.
TWITTER_RSS_FEEDS = {}
i = 1
while True:
    key = f"TWITTER_RSS_{i}"
    val = os.getenv(key, "").strip()
    if not val:
        break
    TWITTER_RSS_FEEDS[f"twitter_{i}"] = val
    i += 1

# Опциональный токен для avторизации на rss.app (если нужна)
RSS_AUTH_TOKEN = os.getenv("RSS_AUTH_TOKEN", "")


