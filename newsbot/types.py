from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class NewsItem:
    source: str
    created_at: datetime
    raw_text: str              # сырой текст из источника (для дедупа)
    final_text: str = ""       # готовый текст для публикации
    source_link: Optional[str] = None
    media: Optional[Any] = None   # telethon media или URL картинки (str)
