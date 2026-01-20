import asyncio
import time
from collections import deque

from telethon import TelegramClient

from newsbot.ai import editor_note, is_relevant_topic, translate_clean
from newsbot.cache import (cache_get_topic, cache_get_translation,
                           cache_set_topic, cache_set_translation)
from newsbot.config import (POLL_INTERVAL_RSS, RSS_AUTH_TOKEN,
                            SOURCE_TG_CHANNELS, TARGET_CHANNEL, TG_API_HASH,
                            TG_API_ID, TWITTER_RSS_FEEDS)
from newsbot.dedup import cache_key, is_duplicate, mark_seen
from newsbot.filters import looks_actionable
from newsbot.publisher.telegram_publisher import publish_news_item
from newsbot.sources.telegram_source import register_tg_handlers
from newsbot.sources.twitter_source import fetch_twitter_rss
from newsbot.state import load_state, save_state

state_lock = asyncio.Lock()
state = load_state()

# Очередь для входящих новостей (TG events + RSS poll)
queue: asyncio.Queue = asyncio.Queue(maxsize=2000)


async def process_item(client: TelegramClient, item):
    """
    Единая обработка:
    A) heuristic trash
    B) dedup
    C) AI topic (cached)
    D) translate (cached)
    E) publish
    F) mark seen + save
    """

    # A) быстрый мусор - ПРОПУСКАЕМ если НЕ actionable
    if not looks_actionable(item.raw_text):
        print(f"⏭️ SKIP (actionable filter): {item.raw_text[:60]}...")
        return

    # ключ для кеша (одинаковый инфоповод из разных источников)
    key = cache_key(item.raw_text)

    # B) дедуп + быстрый cached-skip
    async with state_lock:
        dup = is_duplicate(state, item.raw_text, item.source_link)
        if not dup.ok:
            print(f"⏭️ SKIP (dedup {dup.reason}): {item.raw_text[:60]}...")
            return

        cached_ok = cache_get_topic(state, key)
        if cached_ok is False:
            print(f"⏭️ SKIP (cached topic=False): {item.raw_text[:60]}...")
            return

    # C) AI topic filter (короткий кусок — быстрее и дешевле)
    try:
        short_text = item.raw_text[:900]
        ok = is_relevant_topic(short_text)
    except Exception as e:
        print(f"❌ is_relevant_topic error: {e}")
        return

    async with state_lock:
        cache_set_topic(state, key, ok)
        save_state(state)

    if not ok:
        print(f"⏭️ SKIP (AI topic filter): {item.raw_text[:60]}...")
        return

    # D) перевод: кешируем
    async with state_lock:
        cached_tr = cache_get_translation(state, key)

    if cached_tr:
        translated = cached_tr
        print(f"📦 Translation from cache")
    else:
        try:
            print(f"🔄 Translating...")
            translated = translate_clean(item.raw_text[:3500])
        except Exception as e:
            print(f"❌ translate_clean error: {e}")
            return

        async with state_lock:
            cache_set_translation(state, key, translated)
            save_state(state)

    # E) мысль редактора
    try:
        note = editor_note(translated)
    except Exception as e:
        print(f"⚠️ editor_note error: {e}")
        note = ""

    # Формируем финальный текст БЕЗ FOOTER
    final = translated
    if note:
        final += "\n\n<blockquote><i>" + note + "</i></blockquote>"

    item.final_text = final

    # F) publish
    try:
        await publish_news_item(client, item)
        print(f"✅ PUBLISHED: {item.source} @ {item.created_at}")
    except Exception as e:
        print(f"❌ publish_news_item error: {e}")
        return

    # G) mark seen + save
    async with state_lock:
        mark_seen(state, item.raw_text, item.source_link)
        save_state(state)


async def worker_loop(client: TelegramClient):
    """
    Один воркер = стабильная скорость, без одновременных 20 запросов к ИИ.
    """
    while True:
        item = await queue.get()
        try:
            await process_item(client, item)
        except Exception as e:
            print(f"❌ worker error: {e}")
        finally:
            queue.task_done()


async def rss_loop():
    """
    RSS polling: забираем ТОЛЬКО реально новые элементы.
    Используем timestamp ПЕРЕД запросом как граница.
    """
    last_ts = time.time()  # 🔥 СЕЙЧАС, не 2 минуты назад
    seen_ids = deque(maxlen=500)

    while True:
        print("🔁 RSS poll tick...")
        
        # 🔥 СДВИГАЕМ ДО fetch - это будет граница для СЛЕДУЮЩЕГО цикла
        poll_started_at = time.time()

        try:
            items = fetch_twitter_rss(TWITTER_RSS_FEEDS, since_ts=last_ts, auth_token=RSS_AUTH_TOKEN)
            print(f"📡 Fetched {len(items)} total items from RSS")

            new_items = []

            for i in items:
                ts = i.created_at.timestamp()

                if ts <= last_ts:
                    continue

                # Дедуп по source_link (от entry.link)
                uid = i.source_link or getattr(i, "id", None)
                if uid and uid in seen_ids:
                    print(f"⏭️ Skip duplicate RSS: {uid[:50]}")
                    continue

                new_items.append(i)
                if uid:
                    seen_ids.append(uid)

            print(f"📥 RSS new items: {len(new_items)} (window: {poll_started_at - last_ts:.1f}s)")

            for it in sorted(new_items, key=lambda x: x.created_at):
                try:
                    queue.put_nowait(it)
                    print(f"  ↳ queued: {it.raw_text[:50]}...")
                except asyncio.QueueFull:
                    print("⚠️ queue full: drop rss item")
                    break

            # 🔥 ОБНОВЛЯЕМ окно на СЛЕДУЮЩИЙ цикл
            last_ts = poll_started_at

        except Exception as e:
            print(f"❌ RSS loop error: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(POLL_INTERVAL_RSS)


async def main():
    if not TG_API_ID or not TG_API_HASH or not TARGET_CHANNEL:
        raise RuntimeError("Заполни TG_API_ID, TG_API_HASH, TARGET_CHANNEL в .env")

    if not SOURCE_TG_CHANNELS and not TWITTER_RSS_FEEDS:
        raise RuntimeError("Нет источников: SOURCE_TG_CHANNELS и/или TWITTER_RSS_*")

    print("🚀 Запуск Telegram-клиента...")
    client = TelegramClient("news_session", TG_API_ID, TG_API_HASH)
    await client.start()
    print("✅ Авторизация выполнена")

    # Проверка доступа к TG-каналам
    if SOURCE_TG_CHANNELS:
        for ch in SOURCE_TG_CHANNELS:
            try:
                last = await client.get_messages(ch, limit=1)
                if last:
                    print(f"🧾 TG last msg ok: {ch} | id={last[0].id} | date={last[0].date}")
                else:
                    print(f"🧾 TG empty: {ch}")
            except Exception as e:
                print(f"❌ TG read fail: {ch} -> {e}")

    # TG events: кладём в очередь (не обрабатываем внутри handler)
    async def push_callback(item):
        try:
            queue.put_nowait(item)
            print(f"  ↳ TG queued: {item.raw_text[:50]}...")
        except asyncio.QueueFull:
            print("⚠️ queue full: drop tg item")

    if SOURCE_TG_CHANNELS:
        # register_tg_handlers НЕ async - просто регистрирует обработчик
        register_tg_handlers(client, SOURCE_TG_CHANNELS, push_callback)
        print(f"📡 TG источники (events): {SOURCE_TG_CHANNELS}")

    if TWITTER_RSS_FEEDS:
        print(f"📡 Twitter RSS feeds: {list(TWITTER_RSS_FEEDS.keys())}")

    # Запускаем воркер (ИИ) и RSS loop
    tasks = []
    tasks.append(asyncio.create_task(worker_loop(client)))

    if TWITTER_RSS_FEEDS:
        tasks.append(asyncio.create_task(rss_loop()))

    print("🟢 Бот работает. Ctrl+C чтобы остановить.")
    try:
        await asyncio.gather(*tasks)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())