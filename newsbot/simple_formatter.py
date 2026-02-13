import logging
import re
from newsbot.text_cleaner import clean_after_ai
from newsbot.types import ProcessedNews

class SimpleFormatter:
    def __init__(self, channel_link: str="https://t.me/onchain_20226", partner_link: str="https://bingxzone.com/partner/McDuckk/"):
        self.channel_link=channel_link
        self.partner_link=partner_link
        self.logger=logging.getLogger(__name__)

    def format_post(self, processed_news: ProcessedNews) -> str:
        text = getattr(processed_news.analysis, "translated_text", None) or getattr(processed_news.source_item, "raw_text", "")
        text = clean_after_ai(text)
        text = self._remove_urls_handles(text)
        text = self._html_highlight(text)
        links = f'🗽 <a href="{self.channel_link}">OnChain News</a> | 🌐 <a href="{self.partner_link}">BingX</a>'
        post = f"{text}\n\n{links}"
        return post[:4000]

    def _remove_urls_handles(self, text: str) -> str:
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"@\w+", "", text)
        text = re.sub(r"\b\w[\w\-]*\.(?:com|org|net|io|xyz|info|co|ai|me|rs|ly)\S*\b", "", text, flags=re.IGNORECASE)
        return clean_after_ai(text)

    def _html_highlight(self, text: str) -> str:
        text = re.sub(r'(?<!\w)([$#])([A-Z]{2,10})\b', r'<b>\1\2</b>', text)
        text = re.sub(r'\$(\d[\d,\.]*)(?:\s*)([KMB])\b', r'<b>$\1\2</b>', text)
        text = re.sub(r'\b(\+|-)?\s*(\d+[\.,]?\d*)\s*%\b', r'<b>\1\2%</b>', text)
        return text.strip()
