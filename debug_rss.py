# newsbot/debug_rss.py
import asyncio
import time
from newsbot.sources.twitter_source import fetch_twitter_rss
from newsbot.config import TWITTER_RSS_FEEDS, RSS_AUTH_TOKEN

async def debug_rss():
    print("🔍 Дебаг RSS-источников")
    last_ts = time.time() - 3600  # 1 час назад
    
    for name, url in TWITTER_RSS_FEEDS.items():
        print(f"\n=== {name} ===")
        print(f"URL: {url}")
        
        try:
            items = fetch_twitter_rss({name: url}, last_ts, RSS_AUTH_TOKEN)
            print(f"Найдено элементов: {len(items)}")
            
            for i, item in enumerate(items[:5]):  # первые 5
                print(f"\n[{i+1}] {item.created_at}")
                print(f"Текст: {item.raw_text[:100]}...")
                print(f"Ссылка: {item.source_link}")
                print(f"Медиа: {item.media}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_rss())