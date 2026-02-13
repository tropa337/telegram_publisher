import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

import aiohttp
import feedparser
from dateutil import parser as dtparser

from ..types import MediaItem, NewsItem


class TwitterRSSSource:
    """
    Источник новостей из Twitter через RSS.
    Поддерживает множественные RSS-ленты, извлечение медиа и обработку ошибок.
    """

    def __init__(
        self,
        feeds: Dict[str, str],
        auth_token: Optional[str] = None,
        poll_interval: int = 60,
        max_cache_size: int = 1000,
        logger: Optional[logging.Logger] = None,
        filters: Optional[List[Callable[[NewsItem], bool]]] = None,
    ):
        self.name = "twitter_rss"
        self.feeds = feeds
        self.auth_token = auth_token
        self.poll_interval = poll_interval
        self.max_cache_size = max_cache_size
        self.filters = filters or []

        self.logger = logger or self._setup_logger()

        self.processed_ids: Set[str] = set()
        self.processed_count = 0
        self.error_count = 0

        self.stats = {
            "total_fetched": 0,
            "total_processed": 0,
            "total_errors": 0,
            "last_fetch": None,
            "feed_stats": {},
            "media_stats": {
                "with_media": 0,
                "without_media": 0,
                "total_media_items": 0,
                "media_by_type": {},
            },
        }

        self.logger.info(f"Инициализирован источник Twitter RSS с {len(feeds)} фидами")

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("newsbot.sources.twitter_source.TwitterRSSSource")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    # =========================
    # PUBLIC API
    # =========================
    async def fetch(self) -> List[NewsItem]:
        """Асинхронное получение новостей из всех RSS-фидов"""
        all_items: List[NewsItem] = []
        self.logger.info(f"Начинаем получение новостей из {len(self.feeds)} источников")

        async with aiohttp.ClientSession() as session:
            tasks = []
            labels = []
            for label, url in self.feeds.items():
                labels.append((label, url))
                tasks.append(self._fetch_feed(session, label, url))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, (label, _url) in enumerate(labels):
                result = results[i]
                if isinstance(result, Exception):
                    self.logger.error(f"❌ Ошибка RSS {label}: {result}")
                    self.error_count += 1
                    continue

                items: List[NewsItem] = result
                all_items.extend(items)
                self.stats["feed_stats"][label] = len(items)

                with_media = sum(1 for it in items if getattr(it, "media_items", None))
                total_media = sum(len(it.media_items) for it in items if getattr(it, "media_items", None))

                self.logger.info(
                    f"✅ RSS {label}: {len(items)} новостей ({with_media} с медиа, всего {total_media} медиафайлов)"
                )

        # Фильтрация новостей
        if self.filters:
            filtered: List[NewsItem] = []
            for it in all_items:
                try:
                    if all(fn(it) for fn in self.filters):
                        filtered.append(it)
                except Exception:
                    # если фильтр упал — просто не ломаем поток
                    continue
            all_items = filtered

        # Обновление статистики
        self.stats["total_fetched"] += len(all_items)
        self.stats["total_processed"] = self.processed_count
        self.stats["total_errors"] = self.error_count
        self.stats["last_fetch"] = datetime.now(timezone.utc).isoformat()

        # Статистика медиа (сбрасываем на каждый fetch, чтобы не раздувалась бесконечно)
        self.stats["media_stats"] = {
            "with_media": 0,
            "without_media": 0,
            "total_media_items": 0,
            "media_by_type": {},
        }

        for it in all_items:
            if getattr(it, "media_items", None):
                self.stats["media_stats"]["with_media"] += 1
                self.stats["media_stats"]["total_media_items"] += len(it.media_items)
                for m in it.media_items:
                    mt = m.type
                    self.stats["media_stats"]["media_by_type"][mt] = (
                        self.stats["media_stats"]["media_by_type"].get(mt, 0) + 1
                    )
            else:
                self.stats["media_stats"]["without_media"] += 1

        self.logger.info(f"Получено {len(all_items)} новостей после фильтрации")

        if self.stats["media_stats"]["media_by_type"]:
            media_types_str = ", ".join(
                [f"{count} {typ}" for typ, count in self.stats["media_stats"]["media_by_type"].items()]
            )
            self.logger.info(f"📊 Детальная статистика медиа: {media_types_str}")

        return all_items

    async def start_polling(self, callback: Callable[[List[NewsItem]], Any]):
        """Периодический опрос RSS-лент."""
        self.logger.info(f"Запуск периодического опроса с интервалом {self.poll_interval} секунд")

        while True:
            try:
                news_items = await self.fetch()
                if news_items:
                    self.logger.info(f"Найдено {len(news_items)} новых новостей")
                    try:
                        res = callback(news_items)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        self.logger.error(f"Ошибка в callback: {e}", exc_info=True)
            except Exception as e:
                self.logger.error(f"Критическая ошибка при опросе: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    # =========================
    # FEED FETCH
    # =========================
    async def _fetch_feed(self, session: aiohttp.ClientSession, label: str, url: str) -> List[NewsItem]:
        headers = self._get_headers()
        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        try:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    self.logger.warning(f"RSS {label}: HTTP {response.status}")
                    return []
                content = await response.text()
                return self._parse_feed_content(content, label)
        except asyncio.TimeoutError:
            self.logger.error(f"Таймаут при получении RSS {label}")
            return []
        except aiohttp.ClientError as e:
            self.logger.error(f"Ошибка клиента при получении RSS {label}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении RSS {label}: {e}", exc_info=True)
            return []

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TwitterRSSBot/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    # =========================
    # PARSING
    # =========================
    def _parse_feed_content(self, content: str, label: str) -> List[NewsItem]:
        feed = feedparser.parse(content)

        if getattr(feed, "bozo", False):
            self.logger.warning(f"Ошибка парсинга RSS {label}: {getattr(feed, 'bozo_exception', None)}")
            # bozo иногда true даже на нормальном фиде — поэтому не всегда возвращаем []
            # но если entries нет — выходим
            if not getattr(feed, "entries", None):
                return []

        items: List[NewsItem] = []
        for entry in getattr(feed, "entries", []) or []:
            try:
                news_item = self._parse_entry(entry, label)
                if news_item:
                    items.append(news_item)
                    self.processed_count += 1
            except Exception as e:
                self.logger.error(f"Ошибка парсинга записи: {e}", exc_info=True)
                self.error_count += 1
                continue

        return items

    def _parse_entry(self, entry, source_label: str) -> Optional[NewsItem]:
        entry_id = self._get_entry_id(entry)
        if not entry_id:
            return None

        if entry_id in self.processed_ids:
            return None

        created_at = self._parse_date(entry)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # не старше 7 дней
        if (datetime.now(timezone.utc) - created_at).days > 7:
            return None

        raw_text = self._extract_text(entry)
        if not raw_text or len(raw_text.strip()) < 5:
            return None

        media_urls = self._extract_rss_media_urls(entry)

        if not media_urls:
            media_urls = self._extract_media_urls_from_text(raw_text)

        media_items: List[MediaItem] = []
        for url in list(dict.fromkeys(media_urls))[:5]:  # уникальные, макс 5
            url = self._normalize_twitter_media_url(url)
            if url and self._is_valid_media_url(url) and self._is_media_url(url):
                media_items.append(MediaItem(url=url, type=self._detect_media_type(url), caption=None))

        author = self._extract_author(entry)

        link = getattr(entry, "link", None)
        url = link or f"twitter_rss:{source_label}:{entry_id}"

        news_item = NewsItem(
            raw_text=raw_text,
            source=f"twitter_rss:{source_label}",
            url=url,
            created_at=created_at,
            media_items=media_items,
            author=author,
        )

        self.processed_ids.add(entry_id)
        self._cleanup_cache()

        return news_item

    # =========================
    # MEDIA EXTRACTION
    # =========================
    def _extract_rss_media_urls(self, entry) -> List[str]:
        media_urls: List[str] = []

        # 1) media_content
        mc = getattr(entry, "media_content", None)
        if mc:
            if isinstance(mc, list):
                for obj in mc:
                    u = None
                    if isinstance(obj, dict):
                        u = obj.get("url") or obj.get("href")
                    else:
                        u = getattr(obj, "url", None) or getattr(obj, "href", None)
                    if u:
                        media_urls.append(str(u))

        # 2) media_thumbnail
        mt = getattr(entry, "media_thumbnail", None)
        if mt:
            if isinstance(mt, list):
                for obj in mt:
                    u = obj.get("url") if isinstance(obj, dict) else getattr(obj, "url", None)
                    if u:
                        media_urls.append(str(u))
            elif isinstance(mt, dict) and mt.get("url"):
                media_urls.append(str(mt["url"]))

        # 3) enclosures
        enc = getattr(entry, "enclosures", None)
        if enc and isinstance(enc, list):
            for obj in enc:
                u = None
                if isinstance(obj, dict):
                    u = obj.get("href") or obj.get("url")
                else:
                    u = getattr(obj, "href", None) or getattr(obj, "url", None)
                if u:
                    media_urls.append(str(u))

        # 4) HTML внутри summary/content (ищем img/src и видео)
        html_candidates: List[str] = []
        sd = getattr(entry, "summary_detail", None)
        if sd and hasattr(sd, "value"):
            html_candidates.append(str(sd.value))
        summary = getattr(entry, "summary", None)
        if summary:
            html_candidates.append(str(summary))
        content = getattr(entry, "content", None)
        if content and isinstance(content, list):
            for c in content[:3]:
                v = c.get("value") if isinstance(c, dict) else getattr(c, "value", None)
                if v:
                    html_candidates.append(str(v))

        for html in html_candidates:
            # <img src="...">
            for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
                media_urls.append(m)
            # <video src="..."> или source src
            for m in re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
                media_urls.append(m)

        # 5) иногда RSS кладёт прямые ссылки в любых полях
        for attr_name in dir(entry):
            if attr_name.startswith("_"):
                continue
            try:
                v = getattr(entry, attr_name)
                if isinstance(v, str) and v.startswith("http"):
                    if self._is_media_url(v):
                        media_urls.append(v)
            except Exception:
                pass

        # нормализация + уникальность
        out: List[str] = []
        seen = set()
        for u in media_urls:
            u = self._normalize_twitter_media_url(u)
            if not u:
                continue
            if u in seen:
                continue
            if self._is_valid_media_url(u) and self._is_media_url(u):
                out.append(u)
                seen.add(u)

        return out[:10]

    def _extract_media_urls_from_text(self, text: str) -> List[str]:
        if not text:
            return []

        patterns = [
            r"https?://[^\s]+?\.(?:jpg|jpeg|png|gif|webp|bmp|svg)(?:\?[^\s]*)?",
            r"https?://[^\s]+?\.(?:mp4|mov|avi|webm|mkv)(?:\?[^\s]*)?",
            r"https?://(?:pbs\.twimg\.com|pic\.twitter\.com)/[^\s]+",
        ]

        urls: List[str] = []
        for p in patterns:
            urls.extend(re.findall(p, text, flags=re.IGNORECASE))

        # чистим/уникализируем
        uniq = []
        seen = set()
        for u in urls:
            u = self._normalize_twitter_media_url(u)
            if u and u not in seen and self._is_valid_media_url(u) and self._is_media_url(u):
                uniq.append(u)
                seen.add(u)
        return uniq[:5]

    def _normalize_twitter_media_url(self, url: str) -> str:
        """Нормализация Twitter/PBS media URL."""
        if not url:
            return url

        url = unescape(str(url)).strip()

        if url.startswith("//"):
            url = "https:" + url

        try:
            parsed = urlparse(url)
            if parsed.scheme == "http":
                url = "https://" + parsed.netloc + parsed.path
                if parsed.query:
                    url += "?" + parsed.query
        except Exception:
            return url

        return url

    def _is_media_url(self, url: str) -> bool:
        """Грубая проверка: ссылка похожа на медиа (картинка/видео/твимг)."""
        if not url:
            return False
        u = url.lower()

        if "pbs.twimg.com" in u:
            return True
        if "video.twimg.com" in u:
            return True
        if "pic.twitter.com" in u:
            return True

        if any(ext in u for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"]):
            return True
        if any(ext in u for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]):
            return True

        # иногда media идут без расширений, но с параметром format=
        if "format=jpg" in u or "format=png" in u or "format=gif" in u or "format=mp4" in u:
            return True

        return False

    def _is_valid_media_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            return True
        except Exception:
            return False

    def _detect_media_type(self, url: str) -> str:
        if not url:
            return "photo"
        u = url.lower()

        if "video.twimg.com" in u or any(ext in u for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]):
            return "video"
        if any(ext in u for ext in [".gif"]) or "format=gif" in u:
            return "animation"
        return "photo"

    # =========================
    # ID / DATE / TEXT
    # =========================
    def _get_entry_id(self, entry) -> Optional[str]:
        id_fields = ["id", "guid", "link", "published", "updated"]
        for field in id_fields:
            value = getattr(entry, field, None)
            if not value:
                continue

            if isinstance(value, dict) and "value" in value:
                value = value["value"]

            s = str(value).strip()
            if not s:
                continue

            if "http" in s:
                return hashlib.md5(s.encode("utf-8")).hexdigest()
            return s

        # fallback: хеш текста
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        if title or link:
            return hashlib.md5((title + "|" + link).encode("utf-8")).hexdigest()

        return None

    def _parse_date(self, entry) -> datetime:
        date_fields = ["published", "updated", "created", "pubDate"]
        for field in date_fields:
            date_str = getattr(entry, field, None)
            if not date_str:
                continue

            if isinstance(date_str, dict) and "value" in date_str:
                date_str = date_str["value"]

            try:
                d = dtparser.parse(str(date_str))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return d
            except Exception:
                continue

        return datetime.now(timezone.utc)

    def _extract_text(self, entry) -> str:
        candidates: List[str] = []

        # content[0].value
        content = getattr(entry, "content", None)
        if content and isinstance(content, list) and len(content) > 0:
            v = content[0].get("value") if isinstance(content[0], dict) else getattr(content[0], "value", None)
            if v:
                candidates.append(str(v))

        # summary_detail.value
        sd = getattr(entry, "summary_detail", None)
        if sd and hasattr(sd, "value"):
            candidates.append(str(sd.value))

        # summary/title/description
        for f in ["summary", "title", "description"]:
            v = getattr(entry, f, None)
            if v:
                candidates.append(str(v))

        best = ""
        for c in candidates:
            t = self._clean_html(c)
            if len(t) > len(best):
                best = t

        return best.strip()

    def _clean_html(self, html: str) -> str:
        if not html:
            return ""

        text = re.sub(r"<[^>]+>", " ", str(html))
        text = unescape(text)

        # вырезаем URL из текста (они отдельно собираются как медиа)
        text = re.sub(r"https?://\S+", "", text)

        # убираем pic.twitter.com хвосты и типичные подписи
        text = re.sub(r"pic\.twitter\.com/\w+", "", text, flags=re.IGNORECASE)

        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", text)

        return text.strip()

    def _extract_author(self, entry) -> Optional[str]:
        author = getattr(entry, "author", None)
        if author:
            a = re.sub(r"<[^>]+>", "", str(author))
            a = re.sub(r"\([^)]+\)", "", a)
            a = re.sub(r"@\w+", "", a).strip()
            return a if a else None

        title = getattr(entry, "title", "") or ""
        if ":" in title:
            author_part = title.split(":", 1)[0].strip()
            author_part = self._clean_html(author_part)
            return author_part if author_part else None

        return None

    # =========================
    # CACHE / UTILS
    # =========================
    def _cleanup_cache(self):
        if len(self.processed_ids) > self.max_cache_size:
            items = list(self.processed_ids)
            self.processed_ids = set(items[-self.max_cache_size :])
            self.logger.info(f"Кеш очищен: {len(self.processed_ids)} элементов")

    def add_filter(self, filter_func: Callable[[NewsItem], bool]):
        self.filters.append(filter_func)
        self.logger.info(f"Добавлен фильтр: {getattr(filter_func, '__name__', 'filter')}")

    def clear_cache(self):
        self.processed_ids.clear()
        self.logger.info("Кеш очищен")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "source": self.name,
            "feeds": {"total": len(self.feeds), "list": list(self.feeds.keys())},
            "cache": {"size": len(self.processed_ids), "max_size": self.max_cache_size},
            "performance": {"processed": self.processed_count, "errors": self.error_count, "last_fetch": self.stats["last_fetch"]},
            "media_stats": self.stats["media_stats"],
            "feed_stats": self.stats["feed_stats"],
        }

    def add_feed(self, label: str, url: str):
        if label in self.feeds:
            self.logger.warning(f"Фидер '{label}' уже существует, будет заменен")
        self.feeds[label] = url
        self.logger.info(f"Добавлен новый фидер: {label} -> {url}")

    def remove_feed(self, label: str):
        if label in self.feeds:
            del self.feeds[label]
            self.logger.info(f"Удален фидер: {label}")
        else:
            self.logger.warning(f"Фидер с меткой '{label}' не найден")
