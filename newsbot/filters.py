import re

# ═══════════════════════════════════════════════════════════════════
# УРОВЕНЬ 1: ЖЁСТКИЙ БАН — удаляем заведомый мусор
# ═══════════════════════════════════════════════════════════════════

HARD_BAN = [
    # реклама / промо / казино
    r"\b(click here|узнайте здесь|read more|подробнее|здесь)\b",
    r"\b(casino|betting|gambling|ставки на спорт)\b",
    r"\b(airdrop|referral|ref code|реф ссылка)\b",
    r"\b(pump|шумиха|хайп|fomo)\b",
    r"\b(telegram bot|бот|invest now)\b",
    
    # контент без ценности
    r"\b(top \d+|топ.*\d+|нарратив|narrative|recap|обзор|дайджест)\b",
    r"\b(мнение|opinion|think|считаю|opinion piece)\b",
    r"\b(guide|гайд|how to|как)\b.*\b(trade|invest|buy)\b",
    r"\b(poll|опрос|choose|выбери|vote)\b",
    r"\b(итоги года|year in review|best of)\b",
    
    # чистый кликбейт
    r"\b(shocking|шокирующий|unbelievable|incredible)\b",
    r"\b(you won't believe|не поверишь)\b",
    r"\b(this changes everything|всё изменилось)\b",
    r"\b(finally|наконец-то)\b.*\b(truth|правда|revealed)\b",
]

# ═══════════════════════════════════════════════════════════════════
# УРОВЕНЬ 2: РЫНОЧНО-ЗНАЧИМЫЕ СИГНАЛЫ (один = ОК)
# ═══════════════════════════════════════════════════════════════════

MARKET_SIGNALS = {
    # ОНЧЕЙН (whale activity, inflow/outflow, резервы)
    "onchain": [
        r"\bwhale\b.*\b(transfer|moved|sent)\b",
        r"\b(transfer|moved|sent)\b.*\b(\d+[.,]\d*\s*)?(btc|eth|bitcoin|ethereum)\b",
        r"\b(inflow|outflow|flowing|резерв|reserve)\b",
        r"\bexchange\b.*\b(inflow|outflow|flow)\b",
        r"\bmining\b.*\b(difficulty|hash rate)\b",
        r"\bstaking\b.*\b(ratio|amount)\b",
    ],
    
    # ДЕРИВАТИВЫ (ликвидации, funding, OI)
    "derivatives": [
        r"\b(liquidation|liquidations|liquidated|ликвидац)\b",
        r"\bliquid(ed|ating)?\b.*\b(btc|eth|usd)\b",
        r"\b(funding rate|rate.*change)\b",
        r"\b(open interest|oi|oi.*increase|oi.*decrease)\b",
        r"\b(shorts|longs)\b.*\b(liquidated|squeezed)\b",
        r"\b(rekt|wrekt)\b",
    ],
    
    # ETF / ИНСТИТУЦИОНАЛЫ
    "institutional": [
        r"\betf\b.*\b(inflow|outflow|flow)\b",
        r"\b(blackrock|fidelity|vanguard|grayscale)\b.*\b(btc|eth|flow)\b",
        r"\b(institution|institutional)\b.*\b(buy|adopt|hold)\b",
        r"\b(bank|банк)\b.*\b(crypto|bitcoin|ethereum|custody)\b",
        r"\b(standard chartered|jp morgan|goldman|morgan stanley)\b",
    ],
    
    # БЕЗОПАСНОСТЬ / ВЗЛОМЫ
    "security": [
        r"\b(hack|hacked|breach|exploited|exploit)\b",
        r"\b(взлом|эксплойт|stolen|украдено)\b",
        r"\b(tornado cash|mixer|отмыл)\b",
        r"\b(stolen funds|frozen|заморозен)\b",
        r"\b(vulnerability|уязвим)\b.*\b(found|обнаружена)\b",
        r"\b(drain|drained|rug pull)\b",
    ],
    
    # РЕГУЛЯЦИЯ / СУДЫ / САНКЦИИ
    "regulation": [
        r"\b(sec|cftc|esma|ecb|fed)\b.*\b(approve|ban|rule|fine|lawsuit)\b",
        r"\b(регулятор|регулирование)\b.*\b(запрет|одобр|штраф|решение)\b",
        r"\b(ban|banned|prohibit|restriction|запрет|огранич)\b",
        r"\b(lawsuit|court|судебный|судья|решение суда)\b",
        r"\b(sanction|sanctions|санкц)\b",
        r"\b(arrested|indicted|charges|арест)\b",
        r"\b(prosecution|расследование)\b",
    ],
    
    # ЛИСТИНГ / ДЕЛИСТИНГ (Tier-1)
    "listings": [
        r"\b(binance|coinbase|okx|bybit)\b.*\b(list|listing|delisting|support)\b",
        r"\b(list(ing|ed))\b.*\b(binance|coinbase|okx|bybit)\b",
        r"\bdelisting\b.*\b(binance|coinbase|okx|bybit)\b",
    ],
    
    # МАКРО / КРУПНЫЕ СОБЫТИЯ
    "macro": [
        r"\b(fed|ecb|central bank)\b.*\b(rate|interest|decision)\b",
        r"\b(inflation|deflation|economic data)\b",
        r"\b(usd|dollar)\b.*\b(strength|weakness)\b",
        r"\b(geopolitic|war|conflict|sanctions)\b",
        r"\b(recession|crisis|collapse)\b",
    ],
    
    # СТЕЙБЛКОЙНЫ (эмиссия / сжигание)
    "stablecoins": [
        r"\b(usdt|usdc|dai|busd)\b.*\b(mint|burn|redeem)\b",
        r"\b(stablecoin)\b.*\b(emission|supply|increase|decrease)\b",
        r"\b(fractional reserve|backing)\b",
    ],
}

# ═══════════════════════════════════════════════════════════════════
# УРОВЕНЬ 3: ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ
# ═══════════════════════════════════════════════════════════════════

# Должны быть цифры (за исключением регуляторки)
HAS_NUMBERS = re.compile(r"(\$?\d[\d,.\s]*\s?(btc|eth|млн|m|b|k|тыс)?|%)", re.IGNORECASE)

# Если текст совсем коротко и без цифр — вероятно мусор
MIN_LENGTH = 20  # минимум символов для коротких текстов


def looks_actionable(text: str) -> bool:
    """
    Трёхуровневая фильтрация:
    1. Жёсткий бан
    2. Минимум один рыночный сигнал
    3. Плюс цифры (или это регуляторка)
    """
    if not text or len(text) < 10:
        return False
    
    t = text.lower()
    
    # ━━━ УРОВЕНЬ 1: ЖЁСТКИЙ БАН ━━━
    for pattern in HARD_BAN:
        if re.search(pattern, t, re.IGNORECASE):
            return False
    
    # ━━━ УРОВЕНЬ 2: РЫНОЧНЫЙ СИГНАЛ ━━━
    has_signal = False
    signal_type = None
    
    for signal_category, patterns in MARKET_SIGNALS.items():
        for pattern in patterns:
            if re.search(pattern, t, re.IGNORECASE):
                has_signal = True
                signal_type = signal_category
                break
        if has_signal:
            break
    
    if not has_signal:
        return False
    
    # ━━━ УРОВЕНЬ 3: ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА ━━━
    # Регуляторка может быть без цифр
    if signal_type == "regulation":
        return True
    
    # Остальное должно иметь цифры или быть достаточно длинным
    has_numbers = bool(HAS_NUMBERS.search(t))
    is_long_enough = len(text) >= MIN_LENGTH
    
    return has_numbers or is_long_enough
