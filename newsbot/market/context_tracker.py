import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
import numpy as np

from ..types import NewsCategory


class MarketContextTracker:
    """Трекер рыночного контекста в реальном времени"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Текущее состояние рынка
        self.market_state = {
            'trend': 'neutral',
            'volatility': 'low',
            'sentiment': 'neutral',
            'dominant_topics': [],
            'recent_events': []
        }
        
        # Активные темы
        self.active_topics: Dict[str, Dict] = {}
        self.burned_out_topics: Set[str] = set()
        self.history: List[Dict] = []
        
        # Внешние данные
        self.price_data = {}
        self.fear_greed_index = 50
        
        self.logger.info("📊 MarketContextTracker инициализирован")
    
    async def update_market_state(self):
        """Обновление данных о состоянии рынка"""
        try:
            await self._fetch_price_data()
            await self._fetch_fear_greed()
            self._analyze_trend()
            self._analyze_volatility()
            self._update_active_topics()
            
            self.logger.debug("✅ Контекст рынка обновлен")
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления контекста: {e}")
    
    async def _fetch_price_data(self):
        """Получение данных о ценах"""
        try:
            symbols = ['BTCUSDT', 'ETHUSDT']
            
            async with aiohttp.ClientSession() as session:
                for symbol in symbols:
                    url = f'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}'
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.price_data[symbol] = {
                                'price': float(data['lastPrice']),
                                'change': float(data['priceChangePercent']),
                                'high': float(data['highPrice']),
                                'low': float(data['lowPrice']),
                                'volume': float(data['volume'])
                            }
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось получить данные цен: {e}")
    
    async def _fetch_fear_greed(self):
        """Получение индекса страха и жадности"""
        try:
            url = "https://api.alternative.me/fng/?limit=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data['data']:
                            self.fear_greed_index = int(data['data'][0]['value'])
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось получить Fear & Greed: {e}")
    
    def _analyze_trend(self):
        """Анализ текущего тренда"""
        if not self.price_data:
            return
        
        btc_change = self.price_data.get('BTCUSDT', {}).get('change', 0)
        
        if btc_change > 3.0:
            self.market_state['trend'] = 'bullish'
            self.market_state['sentiment'] = 'positive'
        elif btc_change < -3.0:
            self.market_state['trend'] = 'bearish'
            self.market_state['sentiment'] = 'negative'
        else:
            self.market_state['trend'] = 'neutral'
            self.market_state['sentiment'] = 'neutral'
    
    def _analyze_volatility(self):
        """Анализ волатильности"""
        if not self.price_data.get('BTCUSDT'):
            return
        
        btc_data = self.price_data['BTCUSDT']
        price_range = (btc_data['high'] - btc_data['low']) / btc_data['price'] * 100
        
        if price_range > 10:
            self.market_state['volatility'] = 'extreme'
        elif price_range > 5:
            self.market_state['volatility'] = 'high'
        elif price_range > 2:
            self.market_state['volatility'] = 'medium'
        else:
            self.market_state['volatility'] = 'low'
    
    def _update_active_topics(self):
        """Обновление активных тем"""
        base_topics = []
        
        if self.market_state['trend'] == 'bullish':
            base_topics = ['buying', 'accumulation', 'breakout', 'ath']
        elif self.market_state['trend'] == 'bearish':
            base_topics = ['selling', 'distribution', 'breakdown', 'support']
        else:
            base_topics = ['consolidation', 'ranging']
        
        if self.market_state['volatility'] in ['high', 'extreme']:
            base_topics.extend(['volatility', 'liquidation'])
        
        for topic in base_topics:
            if topic not in self.active_topics:
                self.active_topics[topic] = {
                    'first_seen': datetime.now(timezone.utc),
                    'last_seen': datetime.now(timezone.utc),
                    'count': 1
                }
            else:
                self.active_topics[topic]['last_seen'] = datetime.now(timezone.utct)
                self.active_topics[topic]['count'] += 1
        
        # Удаляем устаревшие темы
        to_remove = []
        for topic, data in self.active_topics.items():
            age = datetime.now(timezone.utc) - data['last_seen']
            if age > timedelta(hours=6):
                to_remove.append(topic)
                self.burned_out_topics.add(topic)
        
        for topic in to_remove:
            del self.active_topics[topic]
    
    def is_topic_burned_out(self, text: str) -> bool:
        """Проверка, не 'выгорела' ли тема"""
        text_lower = text.lower()
        for topic in self.burned_out_topics:
            if topic in text_lower:
                return True
        return False
    
    def get_market_context_for_news(self, news_text: str) -> Dict:
        """Получение контекста рынка для новости"""
        relevance_score = 0.0
        reasons = []
        text_lower = news_text.lower()
        
        # Проверка активных тем
        for topic in self.active_topics:
            if topic in text_lower:
                relevance_score += 0.2
                reasons.append(f"Активная тема: {topic}")
        
        # Штраф за выгоревшие темы
        if self.is_topic_burned_out(text_lower):
            relevance_score -= 0.3
            reasons.append("Тема уже выгорела")
        
        return {
            'relevance_score': min(1.0, max(0.0, relevance_score)),
            'reasons': reasons,
            'market_state': self.market_state.copy()
        }
    
    def get_performance_report(self) -> Dict:
        """Отчет о работе трекера"""
        return {
            'market_state': self.market_state,
            'active_topics': len(self.active_topics),
            'burned_out_topics': len(self.burned_out_topics),
            'fear_greed_index': self.fear_greed_index,
            'btc_price': self.price_data.get('BTCUSDT', {}).get('price', 0),
            'btc_change': self.price_data.get('BTCUSDT', {}).get('change', 0)
        }        