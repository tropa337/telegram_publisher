import re

from mistralai import Mistral

from .config import MISTRAL_API_KEY, MISTRAL_MODEL

mistral = Mistral(api_key=MISTRAL_API_KEY)

# ════════════════════════════════════════════════════════════════════
# TOPIC FILTER (МИНИМАЛИСТИЧНЫЙ)
# ════════════════════════════════════════════════════════════════════

TOPIC_SYSTEM_PROMPT = """
Ты — строгий гейткипер для крипто-канала.
ТОЛЬКО рыночно-значимые новости.

Ответь ДА или НЕТ.

ДА если может повлиять на цену/волатильность/риск:
- крупные переводы, whale activity, inflow/outflow
- ликвидации, funding rate, open interest
- ETF flow, институционалы, банки
- взломы, суды, регуляторка, санкции
- листинг/делистинг на Tier-1 биржах
- макро-события

НЕТ если:
- мнения, прогнозы без цифр
- дайджесты, топы, итоги
- реклама, рефки, казино
- опросы, "выбери сторону"
- повтор старой новости

Ответь одним словом: ДА или НЕТ
"""


TRANSLATE_SYSTEM_PROMPT = """
Ты — редактор новостей для Telegram крипто-канала.

ПРАВИЛА (ОБЯЗАТЕЛЬНЫЕ):

1. Переведи на РУССКИЙ, убрав ненужное
2. ИСПОЛЬЗУЙ ТОЛЬКО HTML:
   <b> для важного
   <i> для примечаний
   <blockquote> для цитат

3. ВЫДЕЛЯЙ <b>ЖИРНЫМ</b>:
   - заголовок / главная мысль
   - суммы денег, цифры
   - названия компаний, стран, регуляторов
   - действия: одобрили, запретили, заморозили, ликвидировали

4. ЕСЛИ ТЕКСТ КОРОТКИЙ (1-2 предложения) — весь текст <b>жирный</b>

5. УДАЛЯЙ:
   - слова-паразиты (ПОСЛЕДНИЕ НОВОСТИ, BREAKING, СЕЙЧАС, UPDATE)
   - ссылки
   - эмодзи-мусор
   - теги HTML
   - дублирующий alt-текст

6. Сохраняй переносы строк

7. БЕЗ footer, БЕЗ ссылок, БЕЗ источников

8. Итоговый текст должен быть КОРОТКИМ и ПОНЯТНЫМ

Верни ТОЛЬКО готовый HTML.
"""


EDITOR_NOTE_PROMPT = """
Ты — крипто-аналитик.

Напиши ОДНУ мысль в блокквот (для blockquote HTML):

• 1 предложение
• 15-25 слов
• зачем это важно рынку
• ТОЛЬКО факты, без прогнозов
• нейтральный тон
• без "возможно", "вероятно", без эмодзи

Пример:
"Снижение ликвидности на бирже исторически предшествует росту волатильности."

Верни ТОЛЬКО текст мысли, без HTML-тегов.
"""

_LINK_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+|x\.com/\S+")
_HTML_RE = re.compile(r"<[^>]+>")
_BAD_PREFIXES = re.compile(
    r"^(СЕЙЧАС|ПОСЛЕДНИЕ НОВОСТИ|BREAKING|UPDATE|NEWS|JUST IN)[:\-–—]\s*",
    re.IGNORECASE
)


def _clean_input(text: str) -> str:
    """Очистка перед отправкой в ИИ"""
    text = _HTML_RE.sub("", text or "")
    text = _LINK_RE.sub("", text)
    text = _BAD_PREFIXES.sub("", text)
    # убираем избыточные переносы
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_relevant_topic(text: str) -> bool:
    """Фильтр по теме (финальная проверка)"""
    txt = _clean_input(text)
    if not txt or len(txt) < 15:
        return False
    
    try:
        resp = mistral.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": TOPIC_SYSTEM_PROMPT},
                {"role": "user", "content": txt},
            ],
            temperature=0.0,
            max_tokens=5,
        )
        result = resp.choices[0].message.content.strip().upper()
        return "ДА" in result or "YES" in result or "OK" in result
    except Exception as e:
        print(f"❌ Mistral API error (is_relevant_topic): {e}")
        raise


def translate_clean(text: str) -> str:
    """Перевод + форматирование для Telegram"""
    txt = _clean_input(text)
    if not txt:
        return ""
    
    try:
        resp = mistral.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": txt},
            ],
            temperature=0.05,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Mistral API error (translate_clean): {e}")
        raise


def editor_note(text: str) -> str:
    """Мысль ИИ для blockquote"""
    txt = _clean_input(text)
    if not txt:
        return ""
    
    try:
        resp = mistral.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": EDITOR_NOTE_PROMPT},
                {"role": "user", "content": txt},
            ],
            temperature=0.3,
            max_tokens=50,
        )
        note = resp.choices[0].message.content.strip()
        # Убираем кавычки если есть
        note = note.strip('"\'')
        return note if len(note) > 5 else ""
    except Exception as e:
        print(f"⚠️ Mistral API error (editor_note): {e}")
        return ""

