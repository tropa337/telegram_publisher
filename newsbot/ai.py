import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from mistralai import Mistral

from .config import get_config
from .text_cleaner import clean_source_text, clean_after_ai
from .types import AnalyzedNews, NewsItem


_ALLOWED_CATEGORIES = [
    "MARKET_MOVE",
    "WHALE_MOVE",
    "ETF_FLOW",
    "REGULATION",
    "EXCHANGE",
    "MACRO",
    "ALERT",
    "OTHER",
]


class CryptoNewsAnalyzer:
    """AI анализатор: Extract(JSON) -> Render(шаблон)"""

    def __init__(self):
        config = get_config()
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.model = config.MISTRAL_MODEL
        self.client: Optional[Mistral] = None
        if config.MISTRAL_API_KEY:
            self.client = Mistral(api_key=config.MISTRAL_API_KEY)

        # простой кэш по очищенному тексту
        self.extract_cache: Dict[str, Dict[str, Any]] = {}

    async def analyze_news(self, news_item: NewsItem, market_signals: Optional[dict] = None) -> AnalyzedNews:
        """Возвращает готовый RU-пост в translated_text + метаданные (category/priority/event_key)"""
        try:
            cleaned = clean_source_text(news_item.raw_text)
            text = cleaned.text
            if not text:
                return AnalyzedNews(
                    source_item=news_item,
                    is_relevant=False,
                    relevance_reason="empty_after_clean",
                )

            # Extract (AI или правила)
            structured = await self.extract(text=text, url=news_item.url)

            # Приоритет: 0..100 -> 0..1 для сравнения с MIN_PRIORITY_SCORE
            pr = float(structured.get("priority", 50))
            pr01 = max(0.0, min(1.0, pr / 100.0))

            if not structured.get("is_news", True):
                return AnalyzedNews(
                    source_item=news_item,
                    is_relevant=False,
                    relevance_reason="ai_not_news",
                    metadata={"structured": structured},
                )

            if pr01 < float(self.config.MIN_PRIORITY_SCORE):
                return AnalyzedNews(
                    source_item=news_item,
                    is_relevant=False,
                    relevance_reason=f"low_priority_{pr}",
                    metadata={"structured": structured},
                )

            # Render
            rendered = self.render(structured, source_url=news_item.url)
            rendered = clean_after_ai(rendered)

            return AnalyzedNews(
                source_item=news_item,
                is_relevant=True,
                relevance_reason="ai_extract_render_ok" if self.client else "rules_extract_render_ok",
                translated_text=rendered,
                editor_note="",
                tags=list(structured.get("tickers") or [])[:10],
                confidence=0.85 if self.client else 0.65,
                market_impact="medium",
                metadata={
                    "structured": structured,
                    "removed_urls": cleaned.removed_urls,
                    "category": structured.get("category", "OTHER"),
                    "priority": structured.get("priority", 50),
                    "event_key": structured.get("event_key", ""),
                    "risk": structured.get("risk", "low"),
                    "has_media": len(news_item.media_items) > 0 if hasattr(news_item, "media_items") else False,
                    "media_count": len(news_item.media_items) if hasattr(news_item, "media_items") else 0,
                },
            )
        except Exception as e:
            self.logger.error(f"❌ AI analyze_news error: {e}", exc_info=True)
            return AnalyzedNews(
                source_item=news_item,
                is_relevant=False,
                relevance_reason=f"ai_error_{type(e).__name__}",
                metadata={"error": str(e)},
            )

    async def extract(self, text: str, url: str = "") -> Dict[str, Any]:
        """Шаг 1: Extract JSON (AI, retry 1 раз) или rule-based fallback"""
        cache_key = (text[:600] + "|" + (url or ""))[:900]
        if cache_key in self.extract_cache:
            return self.extract_cache[cache_key]

        if not self.client:
            data = self._rule_extract(text, url)
            self.extract_cache[cache_key] = data
            return data

        prompt = self._build_extract_prompt(text, url)
        data = await self._call_json(prompt)
        if not data:
            # retry строгим требованием
            data = await self._call_json(prompt + "\n\nВерни СТРОГО валидный JSON без пояснений.")
        if not data:
            data = self._rule_extract(text, url)

        data = self._normalize_structured(data, url=url, text=text)
        self.extract_cache[cache_key] = data
        return data

    def render(self, structured: Dict[str, Any], source_url: str = "") -> str:
        """Шаг 2: Render по шаблонам (макс 3 строки, 1-2 эмодзи)"""
        cat = (structured.get("category") or "OTHER").upper()
        if cat not in _ALLOWED_CATEGORIES:
            cat = "OTHER"

        tickers = structured.get("tickers") or []
        tickers_str = " / ".join([f"${t}" for t in tickers[:3]]) if tickers else ""

        facts = structured.get("key_facts") or []
        facts = [str(x).strip("•- \t") for x in facts if str(x).strip()][:3]

        nums = structured.get("numbers") or []
        nums = [str(x) for x in nums][:3]
        nums_str = ", ".join(nums)

        link_needed = bool(structured.get("requires_source_link", False))
        link = source_url if (link_needed and source_url) else ""

        def line_join(*parts: str) -> str:
            parts = [p.strip() for p in parts if p and p.strip()]
            return " ".join(parts).strip()

        if cat == "WHALE_MOVE":
            header = "🐋 КИТЫ:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = line_join("Актив:", tickers_str) if tickers_str else ""
            l3 = line_join("Объём:", nums_str) if nums_str else (facts[1] if len(facts) > 1 else "")
        elif cat == "ETF_FLOW":
            header = "📊 ETF:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = line_join("Данные:", nums_str) if nums_str else (facts[1] if len(facts) > 1 else "")
            l3 = facts[2] if len(facts) > 2 else ""
        elif cat == "EXCHANGE":
            header = "🏦 Биржа:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = facts[1] if len(facts) > 1 else ""
            l3 = link
        elif cat == "REGULATION":
            header = "⚖️ Регулирование:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = facts[1] if len(facts) > 1 else ""
            l3 = link
        elif cat == "ALERT":
            header = "🚨 ALERT:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = line_join(tickers_str, nums_str) if (tickers_str or nums_str) else (facts[1] if len(facts) > 1 else "")
            l3 = link
        elif cat == "MARKET_MOVE":
            header = "📉 Рынок:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = line_join(tickers_str, nums_str) if (tickers_str or nums_str) else (facts[1] if len(facts) > 1 else "")
            l3 = link
        elif cat == "MACRO":
            header = "🌍 Макро:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = facts[1] if len(facts) > 1 else ""
            l3 = link
        else:
            header = "🧩 Новость:"
            l1 = line_join(header, facts[0] if facts else "")
            l2 = facts[1] if len(facts) > 1 else ""
            l3 = link

        lines = [l for l in [l1, l2, l3] if l and l.strip()]
        # максимум 3 строки
        lines = lines[:3]
        return "\n".join(lines).strip()

    def _build_extract_prompt(self, text: str, url: str) -> str:
        return f"""Ты — редактор крипто-новостного Telegram-канала.
Вытащи структуру новости и верни СТРОГО валидный JSON (без markdown, без комментариев).

Требования:
- одна главная мысль
- key_facts: 1-3 коротких факта (RU), без воды
- tickers: список тикеров без $ (BTC, ETH, SOL ...)
- numbers: нормализованные суммы/проценты (например $276.3M, -3%, $67K)
- category: один из {', '.join(_ALLOWED_CATEGORIES)}
- priority: 0..100 (важность для публикации)
- risk: one of [scam, low, med, high]
- event_key: короткий ключ события для дедупа в окне 6-12ч (например coinbase_outage, etf_flow_btc, sec_lawsuit, hack_exploit)
- requires_source_link: true если без ссылки не ок

JSON схема:
{{
  "is_news": true,
  "category": "OTHER",
  "tickers": [],
  "key_facts": [],
  "numbers": [],
  "sentiment": "neutral",
  "priority": 50,
  "risk": "low",
  "event_key": "",
  "requires_source_link": false
}}

Текст:
""" + text + f"""\n\nИсточник URL: {url}"""

    async def _call_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await asyncio.to_thread(
                self.client.chat.complete,
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            content = resp.choices[0].message.content if resp and resp.choices else ""
            if not content:
                return None
            content = content.strip()
            # иногда модель оборачивает в ```json
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE).strip()
            content = re.sub(r"```\s*$", "", content).strip()
            return json.loads(content)
        except Exception as e:
            self.logger.warning(f"AI json parse failed: {e}")
            return None

    def _normalize_structured(self, data: Dict[str, Any], url: str, text: str) -> Dict[str, Any]:
        if not isinstance(data, dict):
            data = {}
        out: Dict[str, Any] = {}
        out["is_news"] = bool(data.get("is_news", True))

        cat = (data.get("category") or "OTHER").upper()
        if cat not in _ALLOWED_CATEGORIES:
            cat = "OTHER"
        out["category"] = cat

        tickers = data.get("tickers") or []
        if isinstance(tickers, str):
            tickers = re.findall(r"\b[A-Z]{2,6}\b", tickers.upper())
        tickers = [t.strip().replace("$", "") for t in tickers if isinstance(t, str)]
        tickers = [t for t in tickers if 2 <= len(t) <= 6]
        out["tickers"] = list(dict.fromkeys(tickers))[:8]

        facts = data.get("key_facts") or []
        if isinstance(facts, str):
            facts = [facts]
        facts = [str(x).strip() for x in facts if str(x).strip()]
        out["key_facts"] = facts[:3] if facts else self._fallback_facts(text)

        numbers = data.get("numbers") or []
        if isinstance(numbers, str):
            numbers = [numbers]
        numbers = [self._fix_number_str(str(x)) for x in numbers if str(x).strip()]
        out["numbers"] = list(dict.fromkeys(numbers))[:6]

        out["sentiment"] = (data.get("sentiment") or "neutral").lower()
        try:
            out["priority"] = int(float(data.get("priority", 50)))
        except Exception:
            out["priority"] = 50
        out["priority"] = max(0, min(100, out["priority"]))

        risk = (data.get("risk") or "low").lower()
        if risk not in ["scam", "low", "med", "high"]:
            risk = "low"
        out["risk"] = risk

        out["requires_source_link"] = bool(data.get("requires_source_link", False))

        event_key = str(data.get("event_key") or "").strip()
        if not event_key:
            event_key = self._derive_event_key(text, url)
        out["event_key"] = event_key[:64]

        return out

    def _fallback_facts(self, text: str) -> List[str]:
        t = re.sub(r"\s+", " ", text).strip()
        if len(t) > 180:
            t = t[:180].rsplit(" ", 1)[0] + "…"
        return [t] if t else []

    def _fix_number_str(self, s: str) -> str:
        s = s.strip()
        s = s.replace(" ", "")
        s = re.sub(r"\$(\d+),(\d)([KMB])\b", r"$\1.\2\3", s)
        s = re.sub(r"\$(\d+),(\d{1,2})([KMB])\b", r"$\1.\2\3", s)
        s = s.replace("USDT", "$").replace("USD", "$")
        return s

    def _derive_event_key(self, text: str, url: str = "") -> str:
        t = text.lower()
        if re.search(r"coinbase.*(down|outage|offline)", t):
            return "coinbase_outage"
        if re.search(r"binance.*(halt|outage|suspend)", t):
            return "binance_issue"
        if re.search(r"etf.*(inflow|outflow|flows)", t):
            if "btc" in t or "bitcoin" in t:
                return "etf_flow_btc"
            if "eth" in t or "ethereum" in t:
                return "etf_flow_eth"
            return "etf_flow"
        if re.search(r"sec|cftc|lawsuit|indict|arrest", t):
            return "regulation_legal"
        if re.search(r"hack|exploit|drain|breach", t):
            return "hack_exploit"
        if re.search(r"liquidat", t):
            return "liquidations"
        if re.search(r"whale|transferred|deposit(ed)?|withdraw(al)?", t):
            return "whale_move"
        # fallback: hash url/text
        import hashlib
        return "evt_" + hashlib.md5((url + "|" + text[:200]).encode("utf-8")).hexdigest()[:10]

    def _rule_extract(self, text: str, url: str = "") -> Dict[str, Any]:
        t = text.strip()
        tl = t.lower()

        tickers = re.findall(r"\$?\b([A-Z]{2,6})\b", t)
        # убираем мусорные слова
        stop = {"US", "SEC", "ETF", "FED", "CEO", "ATH", "USD"}
        tickers = [x for x in tickers if x not in stop]

        numbers = re.findall(r"(?:\$\d+[\d\.,]*\s?[KMB]?|[-+]?\d+(?:\.\d+)?%|\$\d+[KMB])", t)
        numbers = [self._fix_number_str(x) for x in numbers][:6]

        if re.search(r"etf", tl) and re.search(r"inflow|outflow|flows", tl):
            cat = "ETF_FLOW"
            pr = 75
        elif re.search(r"hack|exploit|drain|breach", tl):
            cat = "ALERT"
            pr = 85
        elif re.search(r"sec|cftc|lawsuit|indict|arrest|ban", tl):
            cat = "REGULATION"
            pr = 70
        elif re.search(r"coinbase|binance|kraken|okx|bybit", tl) and re.search(r"down|outage|halt|suspend", tl):
            cat = "EXCHANGE"
            pr = 70
        elif re.search(r"whale|transferred|deposit|withdraw", tl):
            cat = "WHALE_MOVE"
            pr = 65
        elif re.search(r"liquidat|dump|pump|breaks|below|above|-\d+%|\+\d+%", tl):
            cat = "MARKET_MOVE"
            pr = 60
        else:
            cat = "OTHER"
            pr = 50

        facts = self._fallback_facts(t)

        return {
            "is_news": True,
            "category": cat,
            "tickers": list(dict.fromkeys([x.replace("$", "") for x in tickers]))[:8],
            "key_facts": facts[:3],
            "numbers": numbers,
            "sentiment": "neutral",
            "priority": pr,
            "risk": "low",
            "event_key": self._derive_event_key(t, url),
            "requires_source_link": False,
        }


# Глобальный анализатор
_analyzer: Optional[CryptoNewsAnalyzer] = None


def get_analyzer() -> CryptoNewsAnalyzer:
    """Получить глобальный анализатор"""
    global _analyzer
    if _analyzer is None:
        _analyzer = CryptoNewsAnalyzer()
    return _analyzer
