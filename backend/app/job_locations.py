"""Public workplace locations only. Never geocode a candidate's address."""

import json
import math
import re

# City centres are deliberately coarse fallbacks, never street-address geocodes.
CITY_CENTRES = {
    "서울": (37.5665, 126.9780),
    "성남": (37.4200, 127.1265),
    "수원": (37.2636, 127.0286),
    "인천": (37.4563, 126.7052),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "대전": (36.3504, 127.3845),
    "광주광역시": (35.1595, 126.8526),
    "울산": (35.5384, 129.3114),
    "세종": (36.4800, 127.2890),
    "제주": (33.4996, 126.5312),
    "용인": (37.2411, 127.1776),
    "안양": (37.3943, 126.9568),
    "고양": (37.6584, 126.8320),
}


def validated_point(latitude: object, longitude: object) -> tuple[float, float] | None:
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return None
    try:
        lat, lng = float(latitude), float(longitude)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if not -90 <= lat <= 90 or not -180 <= lng <= 180 or (lat == 0 and lng == 0):
        return None
    return lat, lng


def source_coordinates(source: str, raw: str | None) -> dict | None:
    """Use only a known source's explicit workplace geometry, not arbitrary nested data."""
    if source != "wanted" or not raw or len(raw) > 2_000_000:
        return None
    try:
        payload = json.loads(raw)
        job = payload["data"]["job"]
        address = job["address"]
        geo = address.get("geo_location") or address.get("geo")
        if not isinstance(geo, dict):
            return None
        geo = geo.get("location", geo)
        point = validated_point(geo.get("n", geo.get("lat")), geo.get("e", geo.get("lng")))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if point is None:
        return None
    return {"latitude": point[0], "longitude": point[1], "provider": source}


def map_location(location: str | None, coordinates: dict | None) -> dict:
    if isinstance(coordinates, dict):
        point = validated_point(coordinates.get("latitude"), coordinates.get("longitude"))
        if point:
            return {"latitude": point[0], "longitude": point[1], "precision": "source"}
    text = (location or "").strip()
    for city, point in CITY_CENTRES.items():
        if re.search(rf"(?:^|\s){city}(?:시|특별시|광역시)?(?:\s|$)", text):
            return {"latitude": point[0], "longitude": point[1], "precision": "region"}
    if re.search(r"\bSeoul\b", text, re.I):
        point = CITY_CENTRES["서울"]
        return {"latitude": point[0], "longitude": point[1], "precision": "region"}
    return {"latitude": None, "longitude": None, "precision": "unknown"}
