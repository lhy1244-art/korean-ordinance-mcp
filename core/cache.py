import hashlib
import json
from typing import Any

import diskcache

from core.config import CACHE_PATH, DATA_DIR, settings

DATA_DIR.mkdir(parents=True, exist_ok=True)
_cache = diskcache.Cache(str(CACHE_PATH))


def _key(namespace: str, payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"{namespace}:{digest}"


def get(namespace: str, payload: Any) -> Any | None:
    return _cache.get(_key(namespace, payload))


def set(namespace: str, payload: Any, value: Any) -> None:
    ttl = settings.cache_ttl_hours * 3600
    _cache.set(_key(namespace, payload), value, expire=ttl)


def delete(namespace: str, payload: Any) -> None:
    """Invalidate a single cached entry — useful for forcing re-fetch after prompt changes."""
    _cache.delete(_key(namespace, payload))


def clear() -> None:
    _cache.clear()
