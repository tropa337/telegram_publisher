"""
Минималистичный форматировщик постов
ТОЛЬКО текст новости и ссылки внизу
ТОЛЬКО HTML теги для форматирования
"""
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from newsbot.types import ProcessedNews


class SimpleFormatter:
    """Минималистичный форматировщик новостей для Telegram"""
    
    def __init__(self, 
                 channel_link: str = "https://t.me/onchain_20226",
                 partner_link: str = "https://bingxzone.com/partner/McDuckk/"):
        
        self.channel_link = channel_link
        self.partner_link = partner_link
        self.logger = logging.getLogger(__name__)
    
    def format_post(self, processed_news: ProcessedNews) -> str:
        """
        Форматирует пост для Telegram
        ТОЛЬКО текст новости и ссылки внизу
        ТОЛЬКО HTML теги для форматирования
        """
        try:
            self.logger.debug(f"📝 Начало форматирования поста")
            
            # 1. ТЕКСТ НОВОСТИ (перевод от AI)
            main_text = self._format_main_text(processed_news)
            
            # 2. ССЫЛКИ (БЕЗ Twitter, только наши ссылки)
            links = self._format_our_links_only()
            
            # Собираем пост
            post = f"{main_text}\n\n{links}"
            
            # Финальная проверка длины
            if len(post) > 4000:
                self.logger.warning("Пост слишком длинный, обрезаем")
                post = self._truncate_post(post)
            
            # ВАЖНО: Проверяем что есть ТОЛЬКО HTML теги
            if '*' in post or '**' in post or '__' in post:
                post = self._remove_non_html_formatting(post)
            
            return post
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка форматирования поста: {e}")
            return self._format_fallback(processed_news)
    
    def _format_main_text(self, processed_news: ProcessedNews) -> str:
        """Форматирование основного текста новости ТОЛЬКО HTML"""
        text = ""
        
        # Используем перевод от AI
        if hasattr(processed_news.analysis, 'translated_text') and processed_news.analysis.translated_text:
            text = processed_news.analysis.translated_text
        else:
            # Фолбэк на оригинальный текст
            text = getattr(processed_news.source_item, 'raw_text', '')
        
        # Убираем лишние переносы строк (сохраняем структуру абзацев)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Удаляем ВСЕ URL из текста (сохраняем только текст)
        text = self._remove_all_urls(text)
        
        # Удаляем служебные комментарии AI
        text = self._remove_service_comments(text)
        
        # Форматируем числа и ключевые слова HTML тегами
        text = self._format_with_html_tags(text)
        
        # Обрезаем если слишком длинный
        if len(text) > 3800:
            text = text[:3700] + "..."
        
        return text
    
    def _format_with_html_tags(self, text: str) -> str:
        """Форматирование текста ТОЛЬКО HTML тегами"""
        # 1. Выделяем проценты
        text = re.sub(
            r'(\+|-)?\s*(\d+\.?\d*)\s*%',
            r'<b>\1\2%</b>',
            text
        )
        
        # 2. Выделяем суммы в долларах
        text = re.sub(
            r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|m|mln|млн)\b',
            r'<b>$\1M</b>',
            text,
            flags=re.IGNORECASE
        )
        
        text = re.sub(
            r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:billion|b|bln|млрд)\b',
            r'<b>$\1B</b>',
            text,
            flags=re.IGNORECASE
        )
        
        # 3. Выделяем суммы в $ без слова
        text = re.sub(
            r'\$(\d+[.,]?\d*)',
            r'<b>$\1</b>',
            text
        )
        
        # 4. Выделяем криптовалюты
        crypto_keywords = [
            'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol',
            'cardano', 'ada', 'xrp', 'ripple', 'polkadot', 'dot',
            'dogecoin', 'doge', 'shiba', 'shib',
            'биткоин', 'биткойн', 'эфириум', 'эфир'
        ]
        
        for keyword in crypto_keywords:
            pattern = r'\b(' + re.escape(keyword) + r')\b'
            text = re.sub(pattern, r'<b>\1</b>', text, flags=re.IGNORECASE)
        
        # 5. Выделяем компании и регуляторов
        entities = [
            'sec', 'etf', 'blackrock', 'fidelity', 'vanguard', 'grayscale',
            'binance', 'coinbase', 'kraken', 'bybit', 'okx',
            'сок', 'блекрок'
        ]
        
        for entity in entities:
            pattern = r'\b(' + re.escape(entity) + r')\b'
            text = re.sub(pattern, r'<b>\1</b>', text, flags=re.IGNORECASE)
        
        # 6. Выделяем крупные числа (4+ цифры)
        text = re.sub(
            r'\b(\d{4,})\b',
            r'<b>\1</b>',
            text
        )
        
        return text
    
    def _format_our_links_only(self) -> str:
        """Форматирование ТОЛЬКО наших ссылок (без Twitter)"""
        channel_display = self._extract_channel_display_name()
        partner_display = self._get_partner_display_name()
        
        # ТОЛЬКО наши ссылки
        channel_link = f'<a href="{self.channel_link}">{channel_display}</a>'
        partner_link = f'<a href="{self.partner_link}">{partner_display}</a>'
        
        return f"🗽 {channel_link} | 🌐 {partner_link}"
    
    def _remove_all_urls(self, text: str) -> str:
        """Удаление ВСЕХ URL из текста"""
        patterns = [
            r'https?://\S+',
            r'www\.\S+',
            r'\S+\.(com|org|net|io|xyz|info)\S*',
            r'@\w+',  # Удаляем упоминания Twitter
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text)
        
        return text.strip()
    
    def _remove_service_comments(self, text: str) -> str:
        """Удаление служебных комментариев AI"""
        lines = text.split('\n')
        cleaned_lines = []
        
        skip_next = False
        for line in lines:
            line_lower = line.lower().strip()
            
            # Пропускаем служебные строки
            if any(marker in line_lower for marker in [
                'примечание:', 'заметка:', 'комментарий:', '---',
                'сохранены', 'даты', 'текст адаптирован', 'via @',
                'перевод:', 'translation:'
            ]):
                skip_next = True
                continue
            
            if skip_next and line.strip() == '':
                skip_next = False
                continue
            
            if not skip_next and line.strip():
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _remove_non_html_formatting(self, text: str) -> str:
        """Удаление не-HTML форматирования (*, **, __)"""
        text = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', text)
        text = re.sub(r'__(.*?)__', r'\1', text)
        text = re.sub(r'\*(.*?)\*', r'\1', text)
        return text
    
    def _extract_channel_display_name(self) -> str:
        """Отображаемое имя канала"""
        if 'onchain' in self.channel_link.lower():
            return 'OnChain News'
        return 'Канал'
    
    def _get_partner_display_name(self) -> str:
        """Отображаемое имя партнера"""
        if 'bingx' in self.partner_link.lower():
            return 'BingX'
        elif 'binance' in self.partner_link.lower():
            return 'Binance'
        return 'Партнер'
    
    def _truncate_post(self, post: str, max_length: int = 4000) -> str:
        """Обрезка поста"""
        if len(post) <= max_length:
            return post
        
        cutoff = post[:max_length]
        
        last_sentence = max(
            cutoff.rfind('. '),
            cutoff.rfind('! '),
            cutoff.rfind('? ')
        )
        
        if last_sentence > max_length * 0.7:
            return post[:last_sentence + 1] + "..."
        
        return cutoff + "..."
    
    def _format_fallback(self, processed_news: ProcessedNews) -> str:
        """Фолбэк форматирование"""
        text = getattr(processed_news.source_item, 'raw_text', '')
        text = self._remove_all_urls(text)
        text = self._format_with_html_tags(text)
        
        return f"{text[:1500]}\n\n🗽 <a href=\"https://t.me/onchain_20226\">OnChain News</a> | 🌐 <a href=\"https://bingxzone.com/partner/McDuckk/\">BingX</a>"