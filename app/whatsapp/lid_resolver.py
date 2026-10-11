"""
LID (WhatsApp Linked Identifier) resolver.

Under the GOWS engine, some inbound chatIds arrive as '<lid>@lid' instead of
a real phone number ('<phone>@c.us'). This module resolves those to an
actual normalized phone number by querying WAHA's lids endpoint, with an
in-memory cache to avoid hammering the API on every message.
"""
import logging
import time
from typing import Dict, Optional, Tuple

import httpx

from app.config import get_settings
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h
_cache: Dict[str, Tuple[str, float]] = {}


async def resolve_to_phone(from_raw: str) -> Optional[str]:
    """
    Resolves an inbound WAHA chatId ('...@c.us' or '...@lid') to a
    normalized 8-digit local phone number, or None if it can't be resolved.
    """
    if not from_raw:
        return None

    if from_raw.endswith("@c.us"):
        digits = from_raw.split("@")[0]
        phone = normalize_phone(digits)
        if not phone:
            logger.warning(f"Could not normalize phone from chatId: {from_raw}")
            return None
        return phone

    if from_raw.endswith("@lid"):
        cached = _get_cached(from_raw)
        if cached is not None:
            return cached

        lid = from_raw.split("@")[0]
        phone = await _resolve_lid_via_waha(lid)
        if not phone:
            logger.warning(f"Could not resolve LID to a phone number: {from_raw}")
            return None
        _set_cached(from_raw, phone)
        return phone

    # Unknown suffix: best-effort normalize whatever digits it carries.
    digits = from_raw.split("@")[0]
    phone = normalize_phone(digits)
    if not phone:
        logger.warning(f"Could not resolve unrecognized chatId format: {from_raw}")
        return None
    return phone


async def _resolve_lid_via_waha(lid: str) -> Optional[str]:
    settings = get_settings()
    url = f"{settings.WAHA_BASE_URL.rstrip('/')}/api/{settings.WAHA_SESSION}/lids/{lid}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"X-Api-Key": settings.WAHA_API_KEY})
    except httpx.TimeoutException as e:
        logger.warning(f"Timeout resolving LID {lid} via WAHA: {e}")
        return None
    except httpx.RequestError as e:
        logger.warning(f"Network error resolving LID {lid} via WAHA: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error resolving LID {lid} via WAHA: {e}")
        return None

    if response.status_code >= 400:
        logger.warning(f"WAHA lids lookup failed for LID {lid}: HTTP {response.status_code} {response.text}")
        return None

    try:
        data = response.json()
    except Exception as e:
        logger.warning(f"WAHA lids lookup returned non-JSON response for LID {lid}: {e}")
        return None

    pn = data.get("pn")
    phone = normalize_phone(pn) if pn else ""
    if not phone:
        logger.warning(f"WAHA lids lookup returned no usable 'pn' for LID {lid}: {data}")
        return None
    return phone


def _get_cached(key: str) -> Optional[str]:
    entry = _cache.get(key)
    if not entry:
        return None
    phone, expires_at = entry
    if time.time() > expires_at:
        _cache.pop(key, None)
        return None
    return phone


def _set_cached(key: str, phone: str) -> None:
    _cache[key] = (phone, time.time() + _CACHE_TTL_SECONDS)


def clear_cache() -> None:
    """Testing helper: clears the in-memory LID cache."""
    _cache.clear()
