import json
import os
import time
from typing import Any, Dict

from .config import STATE_PATH

# сколько держим решения/переводы в кеше
AI_CACHE_TTL_SEC = 24 * 3600       # 24 часа
SEEN_LINKS_TTL_SEC = 72 * 3600     # 3 суток
MAX_SEEN_FPS = 2000                # Снизили до согласованности с процессом
MAX_AI_CACHE = 3000               # ограничим кеш


def _now() -> float:
    return time.time()


def _default_state() -> Dict[str, Any]:
    return {
        "seen_links": {},     # link -> ts
        "seen_fps": [],       # list[int]
        "ai_cache": {},       # fp(str)-> {"ts": float, "topic_ok": bool, "tr": str}
    }


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return _default_state()

    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # гарантируем ключи
        base = _default_state()
        base.update(data or {})
        base.setdefault("seen_links", {})
        base.setdefault("seen_fps", [])
        base.setdefault("ai_cache", {})

        # очистка при загрузке
        cleanup_state(base)
        return base
    except Exception:
        return _default_state()


def save_state(state: Dict[str, Any]) -> None:
    cleanup_state(state)

    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        # Безопасный replace для Windows
        if os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
        os.rename(tmp, STATE_PATH)
    except Exception as e:
        print(f"⚠️ Failed to save state: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def cleanup_state(state: Dict[str, Any]) -> None:
    """
    Чистит state, чтобы не рос бесконечно:
    - seen_links по TTL
    - ai_cache по TTL и лимиту
    - seen_fps по лимиту
    """
    now = _now()

    # 1) seen_links -> ts, чистим по TTL
    seen_links = state.get("seen_links", {})
    if isinstance(seen_links, dict) and seen_links:
        to_del = []
        for link, ts in seen_links.items():
            try:
                if (now - float(ts)) > SEEN_LINKS_TTL_SEC:
                    to_del.append(link)
            except Exception:
                to_del.append(link)
        for k in to_del:
            seen_links.pop(k, None)
        state["seen_links"] = seen_links

    # 2) seen_fps ограничиваем по длине
    seen_fps = state.get("seen_fps", [])
    if isinstance(seen_fps, list) and len(seen_fps) > MAX_SEEN_FPS:
        state["seen_fps"] = seen_fps[-MAX_SEEN_FPS:]

    # 3) ai_cache чистим по TTL и лимиту
    ai_cache = state.get("ai_cache", {})
    if isinstance(ai_cache, dict) and ai_cache:
        # TTL
        to_del = []
        for k, v in ai_cache.items():
            try:
                ts = float(v.get("ts", 0.0))
                if (now - ts) > AI_CACHE_TTL_SEC:
                    to_del.append(k)
            except Exception:
                to_del.append(k)
        for k in to_del:
            ai_cache.pop(k, None)

        # лимит по размеру: удаляем самые старые
        if len(ai_cache) > MAX_AI_CACHE:
            items = sorted(ai_cache.items(), key=lambda kv: float(kv[1].get("ts", 0.0)))
            for k, _ in items[: len(ai_cache) - MAX_AI_CACHE]:
                ai_cache.pop(k, None)

        state["ai_cache"] = ai_cache
