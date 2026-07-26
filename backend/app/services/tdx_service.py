import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.services.map_service import MAP_USER_AGENT, _ssl_context


TDX_TOKEN_URL = (
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/"
    "protocol/openid-connect/token"
)
TDX_ROUTING_URL = "https://tdx.transportdata.tw/api/maas/routing"
_token_lock = threading.Lock()
_cached_token = ""
_token_expires_at = 0.0


def tdx_enabled() -> bool:
    settings = get_settings()
    return bool(settings.tdx_client_id and settings.tdx_client_secret)


def _access_token() -> str:
    global _cached_token, _token_expires_at
    with _token_lock:
        if _cached_token and time.monotonic() < _token_expires_at - 60:
            return _cached_token

        settings = get_settings()
        if not settings.tdx_client_id or not settings.tdx_client_secret:
            raise ValueError("TDX credentials are not configured")
        response = httpx.post(
            TDX_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.tdx_client_id,
                "client_secret": settings.tdx_client_secret,
            },
            headers={"User-Agent": MAP_USER_AGENT},
            timeout=15,
            verify=_ssl_context(),
        )
        response.raise_for_status()
        body = response.json()
        _cached_token = body["access_token"]
        _token_expires_at = (
            time.monotonic() + int(body.get("expires_in", 1200))
        )
        return _cached_token


def _next_weekday_departure() -> str:
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    departure = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if departure <= now:
        departure += timedelta(days=1)
    while departure.weekday() >= 5:
        departure += timedelta(days=1)
    return departure.strftime("%Y-%m-%dT%H:%M:%S")


def _transit_commute(
    token: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    departure: str,
) -> tuple[int, int] | None:
    origin_latitude, origin_longitude = origin
    destination_latitude, destination_longitude = destination
    response = httpx.get(
        TDX_ROUTING_URL,
        params={
            "origin": f"{origin_latitude:.6f},{origin_longitude:.6f}",
            "destination": (
                f"{destination_latitude:.6f},{destination_longitude:.6f}"
            ),
            "gc": 1,
            "top": 1,
            "transit": "4,5,6,7",
            "transfer_time": "5,30",
            "depart": departure,
            "first_mile_mode": "0",
            "first_mile_time": "15",
            "last_mile_mode": "0",
            "last_mile_time": "15",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": MAP_USER_AGENT,
        },
        timeout=35,
        verify=_ssl_context(),
    )
    response.raise_for_status()
    body = response.json()
    routes = body.get("data", {}).get("routes", [])
    if body.get("result") != "success" or not routes:
        return None
    route = routes[0]
    travel_seconds = route.get("travel_time")
    if travel_seconds is None:
        return None
    return (
        max(1, math.ceil(float(travel_seconds) / 60)),
        int(route.get("transfers", 0)),
    )


def transit_commutes(
    property_points: list[tuple[str, float, float]],
    destination: tuple[float, float],
) -> dict[str, tuple[int, int]]:
    if not property_points or not tdx_enabled():
        return {}
    token = _access_token()
    departure = _next_weekday_departure()
    results = {}
    with ThreadPoolExecutor(max_workers=min(4, len(property_points))) as executor:
        futures = {
            executor.submit(
                _transit_commute,
                token,
                (latitude, longitude),
                destination,
                departure,
            ): property_id
            for property_id, latitude, longitude in property_points
        }
        for future in as_completed(futures):
            property_id = futures[future]
            try:
                commute = future.result()
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                commute = None
            if commute:
                results[property_id] = commute
    return results
