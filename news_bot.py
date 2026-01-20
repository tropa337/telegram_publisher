import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from mistralai import Mistral
from telethon import TelegramClient

# =========================
# ЗАГРУЗКА .env
# =========================
load_dotenv()

TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")  # @имя твоего канала

# Каналы-источники
SOURCE_CHANNELS = [
    "@trade001k",
    "@svoicrypto",
]

MESSAGES_PER_CHANNEL = 10      # сколько постов брать с каждого канала
HOURS_BACK = 24                # за сколько часов брать свежие посты
MISTRAL_MODEL = "mistral-small-latest"

if not all([TG_API_ID, TG_API_HASH, MISTRAL_API_KEY, TARGET_CHANNEL]):
    raise RuntimeError("❌ Заполни TG_API_ID, TG_API_HASH, MISTRAL_API_KEY, TARGET_CHANNEL в .env")

# =========================
# MISTRAL
# =========================
mistral = Mistral(api_key=MISTRAL_API_KEY)

# --- Фильтр по темам ---
TOPIC_SYSTEM_PROMPT = """
Ти — фільтр контенту для новинного Telegram-каналу.

Тобі ПІДХОДИТЬ:
- світові та європейські новини
- політика, економіка, фінанси
- війна, безпека, оборона
- технології, IT, наука
- важливі суспільні події

Тобі НЕ ПІДХОДИТЬ:
- меми, жарти, розважальний контент
- гороскопи, особисті історії, стосунки
- конкурси, знижки, розіграші
- реклама, промокоди, «підпишись на наш канал»
- криптоскам, казино, ставки

Відповідай ТІЛЬКИ одним словом:
OK   — якщо новина підходить для серйозного новинного каналу,
SKIP — якщо це сміття або не по темі.
"""

def is_relevant_topic(text: str) -> bool:
    """AI-фильтр: решает, брать ли эту новость вообще."""
    try:
        resp = mistral.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": TOPIC_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
        answer = resp.choices[0].message.content.strip().upper()
        return answer.startswith("OK")
    except Exception as e:
        print(f"    [!] Ошибка AI-фильтра темы: {e}")
        # если AI сломался — лучше не постить, чем залить мусор
        return False

# --- Красивое оформление текста ---
SYSTEM_PROMPT = """
Ти — український редактор новин для Telegram.
Оформи текст красиво для телеграм-поста українською.

Формат:
<b>Короткий заголовок (1 рядок)</b>
Потім 2–4 речення пояснення (1 абзац).
Потім список з 2–4 маркованих пунктів з ключовими фактами, кожен рядок починай з «• ».

Вимоги:
- Зберігай факти, дати, цифри.
- Не вигадуй нових деталей.
- Пиши простою, живою мовою.
- Не додавай жодних хештегів.
Виводь ТІЛЬКИ текст у форматі HTML для Telegram.
"""

def prettify_text(original_text: str) -> str:
    """Отправляем текст в Mistral и получаем красиво оформленный укр-пост."""
    resp = mistral.chat.complete(
        model=MISTRAL_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": original_text},
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()

# =========================
# ХЕВРИСТИЧЕСКИЙ ФИЛЬТР "ГОВНА"
# =========================

SPAM_KEYWORDS = [
    "подпишись", "подписывайтесь", "наш канал", "подписаться",
    "реклама", "реклам", "sponsored", "спонсор",
    "промокод", "скидка", "розыгрыш", "розіграш",
    "конкурс", "ставки", "казино",
    "жми на кнопку", "жми кнопку", "переходи по ссылке",
    "перейдите по ссылке", "подробности по ссылке",
]

def looks_like_trash(text: str) -> bool:
    """Быстрый чек: явный шлак/реклама/мусор."""
    t = text.strip()
    low = t.lower()

    # совсем короткое
    if len(t) < 40:
        return True

    # если почти всё — ссылки, без нормальных слов
    parts = t.split()
    if parts and all(p.startswith("http://") or p.startswith("https://") for p in parts):
        return True

    # если буквы почти отсутствуют, а ссылки есть
    letters = sum(ch.isalpha() for ch in t)
    if letters < 10 and "http" in low:
        return True

    # спам-словечки
    if any(kw in low for kw in SPAM_KEYWORDS):
        return True

    return False

# =========================
# MAIN
# =========================
async def main():
    print("🚀 Запуск клиента Telegram...")
    client = TelegramClient("news_session", TG_API_ID, TG_API_HASH)
    await client.start()
    print("✅ Авторизация выполнена")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    print(f"📆 Берём посты новее {cutoff}\n")

    for source in SOURCE_CHANNELS:
        print(f"📡 Канал-источник: {source}")
        async for msg in client.iter_messages(source, limit=MESSAGES_PER_CHANNEL):
            # пропускаем сообщения без текста вообще
            if not msg.message:
                continue

            # дата сообщения
            msg_date = msg.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date < cutoff:
                continue

            text = msg.message.strip()

            # базовый мусор-фильтр
            if looks_like_trash(text):
                print(f"  [-] Сообщение {msg.id} отфильтровано как мусор (хевристика)")
                continue

            print(f"📝 Сообщение {msg.id}, {len(text)} символов, {msg_date}")

            # AI-фильтр по теме
            if not is_relevant_topic(text):
                print(f"  [-] Сообщение {msg.id} отфильтровано AI как не по теме")
                continue

            # пробуем получить ссылку на оригинал (если есть)
            original_link = None
            try:
                original_link = msg.link
            except Exception:
                pass

            # генерим красивый текст
            try:
                pretty = prettify_text(text)
            except Exception as e:
                print(f"❌ Ошибка Mistral (prettify): {e}")
                continue

            # собираем финальный пост
            post = pretty
            if original_link:
                post += f"\n\n<i>Джерело:</i> {original_link}"

            # отправляем с медиа, если оно есть
            try:
                if msg.media:
                    await client.send_file(
                        TARGET_CHANNEL,
                        msg.media,
                        caption=post,
                        parse_mode="html",
                        link_preview=False,
                    )
                    print("✅ Отправлено в канал (с медиа)")
                else:
                    await client.send_message(
                        TARGET_CHANNEL,
                        post,
                        parse_mode="html",
                        link_preview=True,
                    )
                    print("✅ Отправлено в канал (только текст)")
            except Exception as e:
                print(f"❌ Ошибка отправки в канал: {e}")

        print()

    await client.disconnect()
    print("✔️ Готово, клиент отключен.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
