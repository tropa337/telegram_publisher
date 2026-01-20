import os
import re
import tempfile

import aiohttp
from telethon import TelegramClient

from ..config import TARGET_CHANNEL
from ..types import NewsItem


async def _download_to_temp(url: str) -> str:
    """
    Скачиваем картинку во временный файл.
    """
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as r:
            r.raise_for_status()
            content_type = (r.headers.get("Content-Type") or "").lower()
            data = await r.read()

    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"

    fd, path = tempfile.mkstemp(suffix=ext, prefix="tgphoto_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path


async def publish_news_item(client: TelegramClient, item: NewsItem) -> None:
    text = getattr(item, "final_text", None) or item.raw_text
    
    # Убрать любые оставшиеся ссылки
    text = re.sub(r"https?://\S+", "", text).strip()

    if item.media:
        media = item.media

        temp_path = None
        try:
            if isinstance(media, str) and media.startswith("http"):
                temp_path = await _download_to_temp(media)
                media_to_send = temp_path
            else:
                media_to_send = media

            await client.send_file(
                TARGET_CHANNEL,
                media_to_send,
                caption=text,
                parse_mode="html",
                force_document=False,
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
    else:
        await client.send_message(
            TARGET_CHANNEL,
            text,
            parse_mode="html",
            link_preview=False,
        )
