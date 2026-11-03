#!/usr/bin/env python3
"""PokéStock V8.1 nationwide store discovery.

Discovers real OSM-listed trading-card and tabletop-game shops.
One metro search region per run. No inventory assertions.
Does not modify status.json, products, releases or shipments.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORES = DATA / "stores.json"
STATE = DATA / "discovery_state.json"

ENDPOINT = "https://overpass-api.de/api/interpreter"

HEADERS = {
    "User-Agent": "PokeStockStoreDiscovery/8.1 "
                  "(GitHub: failordie2002-bit/PokeStocking)",
    "Accept": "application/json",
}

# Search regions are geographic bounding boxes, not store records.
# Format: name, south, west, north, east.
# Expand these regions in future versions for broader US coverage.
REGIONS = [
    ("New York City", 40.48, -74.27, 40.94, -73.68),
    ("Los Angeles", 33.70, -118.67, 34.35, -118.10),
    ("Chicago", 41.64, -87.94, 42.03, -87.52),
    ("Houston", 29.52, -95.77, 30.11, -95.02),
    ("Phoenix", 33.25, -112.38, 33.73, -111.85),
    ("Philadelphia", 39.84, -75.29, 40.14, -74.95),
    ("San Antonio", 29.25, -98.75, 29.70, -98.32),
    ("San Diego", 32.55, -117.29, 33.12, -116.90),
    ("Dallas", 32.57, -97.02, 33.05, -96.57),
    ("Jacksonville", 30.15, -81.90, 30.52, -81.45),
    ("Fort Worth", 32.58, -97.55, 32.95, -97.15),
    ("San Jose", 37.20, -122.05, 37.48, -121.75),
    ("Austin", 30.10, -97.95, 30.52, -97.55),
    ("Charlotte", 35.05, -81.10, 35.40, -80.65),
    ("Columbus", 39.83, -83.20, 40.16, -82.80),
    ("Indianapolis", 39.60, -86.33, 39.93, -85.98),
    ("Seattle", 47.45, -122.45, 47.75, -122.20),
    ("Denver", 39.60, -105.15, 39.88, -104.75),
    ("Washington DC", 38.75, -77.20, 39.02, -76.88),
    ("Boston", 42.23, -71.20, 42.46, -70.95),
    ("Atlanta", 33.60, -84.55, 33.93, -84.25),
    ("Miami", 25.65, -80.34, 25.90, -80.12),
    ("Nashville", 36.00, -86.95, 36.30, -86.62),
    ("Portland", 45.40, -122.85, 45.65, -122.48),
]

KEYWORDS = re.compile(
    r"trading.cards?|collectible.cards?|"
    r"card.games?|pokemon|pokémon|"
    r"tabletop|hobby.games?|game.store|"
    r"comic.and.games|tcg|ccg",
    re.IGNORECASE,
)

EXCLUDED = re.compile(
    r"casino|gambling|sports.betting|"
    r"video.games?.only|arcade.only",
    re.IGNORECASE,
)


def read_json(path, fallback):
    if not path.exists():
        return fallback
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def safe_url(value):
    try:
        u = urlparse(str(value or "").strip())
        if u.scheme == "https" and u.hostname:
            if not u.username and not u.password:
                return u.geturl()
    except ValueError:
        pass
    return ""


def clean(value):
    return " ".join(str(value or "").split())


def query_region(region):
    _, south, west, north, east = region

    bbox = f"({south},{west},{north},{east})"

    # The search is deliberately limited to gaming-oriented
    # shops and explicit trading-card-related tagging.
    q = f"""
[out:json][timeout:45];
(
  nwr["shop"="games"]{bbox};
  nwr["shop"="collector"]{bbox};
  nwr["shop"="comic"]{bbox};
  nwr["name"~"Trading Card|Card Shop|Card Game|TCG|Game Store",i]{bbox};
  nwr["description"~"trading card|card game|pokemon|pokémon|TCG",i]{bbox};
);
out center tags;
"""

    response = requests.post(
        ENDPOINT,
        data={"data": q},
        headers=HEADERS,
        timeout=80,
    )

    if response.status_code in (429, 502, 503, 504):
        raise RuntimeError(
            f"Overpass temporarily unavailable: HTTP "
            f"{response.status_code}"
        )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload.get("elements"), list):
        raise ValueError("Invalid Overpass response")

    return payload["elements"]


def extract_store(element):
    tags = element.get("tags") or {}

    name = clean(tags.get("name"))

    if not name:
        return None

    category = clean(tags.get("shop")).lower()

    searchable = " ".join([
        name,
        clean(tags.get("description")),
        clean(tags.get("shop")),
        clean(tags.get("name:en")),
        clean(tags.get("product")),
    ])

    if EXCLUDED.search(searchable):
        return None

    # Generic comic shops and ambiguous businesses
    # need explicit card/game relevance.
    if category not in ("games", "collector"):
        if not KEYWORDS.search(searchable):
            return None

    center = element.get("center") or {}

    lat = element.get("lat", center.get("lat"))
    lon = element.get("lon", center.get("lon"))

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    osm_type = element.get("type")
    osm_id = element.get("id")

    if osm_type not in ("node", "way", "relation"):
        return None

    if not isinstance(osm_id, int):
        return None

    source_url = (
        f"https://www.openstreetmap.org/"
        f"{osm_type}/{osm_id}"
    )

    website = safe_url(
        tags.get("website")
        or tags.get("contact:website")
        or ""
    )

    address = clean(" ".join(filter(None, [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
    ])))

    return {
        "id": f"osm-{osm_type}-{osm_id}",
        "name": name,
        "url": website,
        "city": clean(tags.get("addr:city")),
        "state": clean(tags.get("addr:state")),
        "country": clean(
            tags.get("addr:country") or "US"
        ),
        "address": address,
        "lat": lat,
        "lon": lon,
        "games": [],
        "category": category or "possible_tcg_shop",
        "source": "OpenStreetMap",
        "source_url": source_url,
        "discovery_status": "OSM-listed candidate",
        "inventory_status": "Unknown",
        "last_discovered": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    existing = read_json(STORES, [])
    state = read_json(STATE, {})

    if not isinstance(existing, list):
        raise ValueError(
            "stores.json is not a list; refusing overwrite"
        )

    if not isinstance(state, dict):
        raise ValueError(
            "discovery_state.json is invalid"
        )

    cursor = int(state.get("next_region", 0))
    index = cursor % len(REGIONS)
    region = REGIONS[index]

    print("PokéStock V8.1 Store Discovery")
    print("Searching:", region[0])

    try:
        elements = query_region(region)
    except Exception as exc:
        state["last_error"] = str(exc)[:300]
        state["last_attempt"] = datetime.now(
            timezone.utc
        ).isoformat()
        state["last_region"] = region[0]
        write_json(STATE, state)
        print("Discovery failed:", exc)
        print("Existing stores preserved.")
        return

    by_id = {
        str(s["id"]): dict(s)
        for s in existing
        if isinstance(s, dict) and s.get("id")
    }

    discovered = 0
    added = 0

    for element in elements:
        store = extract_store(element)

        if not store:
            continue

        discovered += 1
        sid = store["id"]

        if sid in by_id:
            old = by_id[sid]

            # Preserve manually curated information.
            for field in (
                "games",
                "inventory_status",
                "verified_at",
                "owner_verified",
            ):
                if field in old:
                    store[field] = old[field]

            # Do not erase previously known fields
            # when OSM lacks their values.
            for field, value in old.items():
                if field not in store or store[field] in (
                    "", None, []
                ):
                    store[field] = value
        else:
            added += 1

        by_id[sid] = store

    write_json(
        STORES,
        sorted(
            by_id.values(),
            key=lambda s: (
                str(s.get("state", "")),
                str(s.get("city", "")),
                str(s.get("name", "")),
            ),
        ),
    )

    state.update({
        "version": "8.1",
        "next_region": (index + 1) % len(REGIONS),
        "last_region": region[0],
        "last_success": datetime.now(
            timezone.utc
        ).isoformat(),
        "last_error": None,
        "last_candidates": discovered,
        "last_new_stores": added,
        "total_stores": len(by_id),
        "regions_configured": len(REGIONS),
        "regions_completed_this_cycle": (
            state.get("regions_completed_this_cycle", 0) + 1
        ) % len(REGIONS),
    })

    write_json(STATE, state)

    print("OSM candidates:", discovered)
    print("New stores:", added)
    print("Total stored:", len(by_id))
    print("Next region:", REGIONS[
        state["next_region"]
    ][0])
    print("No inventory claims were generated.")


if __name__ == "__main__":
    main()
