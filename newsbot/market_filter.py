import re

# явный мусор/кликбейт/дайджесты
HARD_SKIP = [
    r"\bузнайте\b", r"\bздесь\b", r"\bчитать\b", r"\bподробности\b",
    r"\bтоп[-\s]?\d+\b", r"\bнарратив(ы|ов)\b", r"\bдайджест\b",
    r"\bвыбери\s+сторон(у|ы)\b", r"\bкто\s+победит\b", r"\bопрос\b",
    r"\bитоги\b.*\bгода\b", r"\bгодовой\s+отчет\b",
    r"\bthread\b", r"\bweekly\b", r"\brecap\b",
]

# признаки "движения рынка"
SIGNALS = [
    # ончейн/киты/переводы
    r"\bперев(е|ё)л[аи]?\b.*\b(btc|eth)\b",
    r"\bмлн\b|\bмиллиард\b|\bмлрд\b|\bтыс\b|\b\d{3,}\s*(btc|eth)\b",
    r"\bwhale\b|\bwallet\b|\binflow\b|\boutflow\b|\bexchange reserve\b",

    # деривативы/рыночные метрики
    r"\bliquidat(ion|ions)\b|\bликвидац",
    r"\bfunding\b|\bopen interest\b|\boi\b|\bспотов\b|\bдериватив",
    r"\b(etf)\b.*\b(inflow|outflow|flow)\b|\bETF\b",

    # безопасность/взлом/отмыв
    r"\bhack\b|\bexploit\b|\bdrain(ed)?\b|\btornado cash\b|\bотмыл\b|\bвзлом\b|\bэксплойт\b",

    # регуляторка/суды/санкции
    r"\bsec\b|\bcftc\b|\besma\b|\becb\b|\bfed\b",
    r"\bban\b|\bprohibit\b|\brestrict\b|\bзапрет\b|\bогранич",
    r"\bindict(ed|ment)\b|\barrest\b|\bsanction\b|\bсанкц\b|\bарест\b",

    # инфраструктура / институционалы (банки, брокеры, кастодианы)
    r"\binstitution(al|s)\b|\bинституцион",
    r"\bbank\b|\bбан(к|ки)\b",
    r"\bbroker(ag|age|ing)?\b|\bброкер",
    r"\bcustody\b|\bкастоди",
    r"\bstandard chartered\b|\bblackrock\b|\bfidelity\b|\bcoinbase\b|\bbinance\b",

    # движение цены / пробой уровней (часто встречается в RSS без слов "whale/funding")
    r"\b(btc|bitcoin|eth|ethereum)\b.*\b(above|below|over|under|breaks?|breaks?\s+through|hits?|touches|tops?|drops?|falls?|plunges|surges?|rallies|pumps?|dumps?)\b",
    r"\b(btc|bitcoin|eth|ethereum)\b.*\$\s*\d{1,3}(?:[.,]\d{1,2})?\s*(k|тыс|m|млн|b|млрд)\b",
    r"\$\s*\d{1,3}(?:[.,]\d{1,2})?\s*(k|тыс)\b.*\b(btc|bitcoin|eth|ethereum)\b",
    r"\b(price|цена)\b.*\b(btc|bitcoin|eth|ethereum)\b.*\b(\+|-)\s*\d+(?:[.,]\d+)?\s*%",
]

def looks_market_moving(text: str) -> bool:
    t = (text or "").lower()

    # жёсткий skip по мусорным паттернам
    for p in HARD_SKIP:
        if re.search(p, t, re.IGNORECASE):
            return False

    # должен быть хотя бы один сигнал
    for p in SIGNALS:
        if re.search(p, t, re.IGNORECASE):
            return True

    return False
