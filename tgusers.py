import asyncio
import re

from telethon import TelegramClient
from telethon.errors import FloodWaitError

api_id = 39020386
api_hash = '718c2362bc1fa0e1866d9d263dbf45e9'

# Можно:
# "MerlinOfficialChat"
# "@MerlinOfficialChat"
# "https://t.me/MerlinOfficialChat"
chat_username = "MerlinOfficialChat"

OUT_FILE = "usernames.txt"
LIMIT = None  # None = вся история

def clean_chat_username(link: str) -> str:
    link = link.replace("https://t.me/", "")
    link = link.replace("http://t.me/", "")
    link = link.replace("t.me/", "")
    return link.strip("@")

def normalize_username(u: str):
    if not u:
        return None
    u = u.strip().lstrip("@")

    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", u):
        return None

    return f"@{u}"   # <-- строго нужный формат

async def main():
    client = TelegramClient("session", api_id, api_hash)
    await client.start()

    chat = clean_chat_username(chat_username)

    seen = set()
    total = 0
    added = 0

    print("🚀 Начинаем сбор...")

    try:
        async for msg in client.iter_messages(chat, limit=LIMIT):
            total += 1

            if not msg.sender_id:
                continue

            sender = await msg.get_sender()
            if not sender:
                continue

            username = normalize_username(sender.username)

            if username and username not in seen:
                seen.add(username)

                with open(OUT_FILE, "a", encoding="utf-8") as f:
                    f.write(username + "\n")

                added += 1

                if added % 20 == 0:
                    print(f"➕ Добавлено: {added}")

            if total % 5000 == 0:
                print(f"Просмотрено сообщений: {total}")

    except FloodWaitError as e:
        print(f"⏳ FloodWait {e.seconds} сек. Запусти снова позже.")

    await client.disconnect()

    print(f"\n✅ Готово!")
    print(f"Всего сообщений просмотрено: {total}")
    print(f"Уникальных username добавлено: {added}")

if __name__ == "__main__":
    asyncio.run(main())  