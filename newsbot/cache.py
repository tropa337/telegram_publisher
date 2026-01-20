import time
from typing import Any, Dict, Optional


def _now() -> float:
    return time.time()


def cache_get_topic(state: Dict[str, Any], key: str) -> Optional[bool]:
    rec = state.get("ai_cache", {}).get(key)
    if not rec:
        return None
    val = rec.get("topic_ok", None)
    if val is None:
        return None
    return bool(val)


def cache_set_topic(state: Dict[str, Any], key: str, topic_ok: bool) -> None:
    state.setdefault("ai_cache", {})
    rec = state["ai_cache"].get(key, {})
    rec["ts"] = _now()
    rec["topic_ok"] = bool(topic_ok)
    state["ai_cache"][key] = rec


def cache_get_translation(state: Dict[str, Any], key: str) -> Optional[str]:
    rec = state.get("ai_cache", {}).get(key)
    if not rec:
        return None
    tr = rec.get("tr", None)
    if not tr:
        return None
    return str(tr)


def cache_set_translation(state: Dict[str, Any], key: str, translation: str) -> None:
    state.setdefault("ai_cache", {})
    rec = state["ai_cache"].get(key, {})
    rec["ts"] = _now()
    rec["tr"] = str(translation)
    state["ai_cache"][key] = rec
