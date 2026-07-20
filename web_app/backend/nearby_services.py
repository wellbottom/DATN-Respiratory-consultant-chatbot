from __future__ import annotations

import math
import os
import re
from typing import Any

import requests

from .schemas import NearbyService


OVERPASS_API_URL = os.getenv("WEBAPP_OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_TIMEOUT_SECONDS = float(os.getenv("WEBAPP_OVERPASS_TIMEOUT_SECONDS", "18"))

SERVICE_SELECTORS: dict[str, list[str]] = {
    "all": [
        '["amenity"="childcare"]',
        '["amenity"="kindergarten"]',
        '["education"="kindergarten"]',
        '["amenity"="hospital"]',
        '["healthcare"="hospital"]',
        '["amenity"="clinic"]',
        '["amenity"="doctors"]',
        '["healthcare"="clinic"]',
        '["healthcare"="doctor"]',
    ],
    "daycare": [
        '["amenity"="childcare"]',
        '["amenity"="kindergarten"]',
    ],
    "preschool": [
        '["amenity"="kindergarten"]',
        '["education"="kindergarten"]',
    ],
    "babysitter": [
        '["amenity"="childcare"]',
    ],
    "hospital": [
        '["amenity"="hospital"]',
        '["healthcare"="hospital"]',
    ],
    "clinic": [
        '["amenity"="clinic"]',
        '["amenity"="doctors"]',
        '["healthcare"="clinic"]',
        '["healthcare"="doctor"]',
    ],
}


def _normalize_category(category: str) -> str:
    cleaned = (category or "all").strip().lower()
    return cleaned if cleaned in SERVICE_SELECTORS else "all"


def _distance_km(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    earth_radius_km = 6371.0
    d_lat = math.radians(to_lat - from_lat)
    d_lng = math.radians(to_lng - from_lng)
    lat1 = math.radians(from_lat)
    lat2 = math.radians(to_lat)
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_query(lat: float, lng: float, radius_m: int, category: str) -> str:
    selectors = SERVICE_SELECTORS[_normalize_category(category)]
    statements = "\n".join(f"  nwr(around:{radius_m},{lat:.6f},{lng:.6f}){selector};" for selector in selectors)
    return f"""[out:json][timeout:18];
(
{statements}
);
out center tags 80;
"""


def _tag_value(tags: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = str(tags.get(name) or "").strip()
        if value:
            return value
    return None


def _address(tags: dict[str, Any]) -> str | None:
    direct = _tag_value(tags, "addr:full", "address")
    if direct:
        return direct

    parts = [
        _tag_value(tags, "addr:housenumber"),
        _tag_value(tags, "addr:street"),
        _tag_value(tags, "addr:ward", "addr:suburb"),
        _tag_value(tags, "addr:district"),
        _tag_value(tags, "addr:city", "addr:province"),
    ]
    compact = [part for part in parts if part]
    return ", ".join(compact) if compact else None


def _service_type_and_category(tags: dict[str, Any]) -> tuple[str, str]:
    amenity = str(tags.get("amenity") or "").strip().lower()
    healthcare = str(tags.get("healthcare") or "").strip().lower()
    education = str(tags.get("education") or "").strip().lower()

    if amenity == "hospital" or healthcare == "hospital":
        return "Bệnh viện", "hospital"
    if amenity in {"clinic", "doctors"} or healthcare in {"clinic", "doctor"}:
        return "Phòng khám", "clinic"
    if education == "kindergarten" or amenity == "kindergarten":
        return "Trường mầm non", "preschool"
    if amenity == "childcare":
        return "Nhà trẻ / giữ trẻ", "daycare"
    return "Dịch vụ", "service"


def _osm_url(element: dict[str, Any]) -> str:
    element_type = str(element.get("type") or "node")
    element_id = str(element.get("id") or "")
    return f"https://www.openstreetmap.org/{element_type}/{element_id}"


def _element_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    lat = element.get("lat")
    lng = element.get("lon")
    if lat is None or lng is None:
        center = element.get("center") or {}
        lat = center.get("lat")
        lng = center.get("lon")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _compact_tags(tags: dict[str, Any]) -> dict[str, str]:
    useful_keys = (
        "amenity",
        "healthcare",
        "education",
        "operator",
        "opening_hours",
        "phone",
        "contact:phone",
        "website",
        "contact:website",
    )
    return {key: str(tags[key]) for key in useful_keys if tags.get(key)}


def fetch_nearby_services(
    *,
    lat: float,
    lng: float,
    category: str,
    radius_m: int,
    limit: int,
) -> list[NearbyService]:
    query = _build_query(lat, lng, radius_m, category)
    response = requests.post(
        OVERPASS_API_URL,
        data={"data": query},
        headers={"User-Agent": "HealthyLung/0.1"},
        timeout=OVERPASS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    elements = payload.get("elements") or []

    services: list[NearbyService] = []
    seen_names: set[tuple[str, str]] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            continue

        name = _tag_value(tags, "name:vi", "name", "official_name", "operator")
        if not name:
            continue
        coordinates = _element_coordinates(element)
        if coordinates is None:
            continue

        service_type, service_category = _service_type_and_category(tags)
        normalized_name = re.sub(r"\s+", " ", name).strip().casefold()
        dedupe_key = (service_category, normalized_name)
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)

        service_lat, service_lng = coordinates
        services.append(
            NearbyService(
                id=f"osm-{element.get('type')}-{element.get('id')}",
                name=name,
                type=service_type,
                category=service_category,
                latitude=service_lat,
                longitude=service_lng,
                distance_km=round(_distance_km(lat, lng, service_lat, service_lng), 3),
                address=_address(tags),
                phone=_tag_value(tags, "phone", "contact:phone"),
                website=_tag_value(tags, "website", "contact:website"),
                opening_hours=_tag_value(tags, "opening_hours"),
                source_url=_osm_url(element),
                tags=_compact_tags(tags),
            )
        )

    services.sort(key=lambda item: (item.distance_km, item.name))
    return services[:limit]
