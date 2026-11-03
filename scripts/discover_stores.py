
#!/usr/bin/env python3
"""PokéStock V8.2 — All-50-State Store Discovery.

Searches OpenStreetMap for real, mapped store candidates.
Includes cities, suburbs, small towns and rural locations.

Preserves existing store records and catalogue data.
Never invents stores, inventory or shipments.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORES_FILE = DATA / "stores.json"
STATE_FILE = DATA / "discovery_state.json"

OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

HEADERS = {
    "User-Agent": (
        "PokeStock/8.2 "
        "(https://github.com/failordie2002-bit/PokeStocking)"
    ),
    "Accept": "application/json",
}

# Actual US state abbreviations.
# These are geographic search targets, not store records.
STATES = [
    "AL", "AK", "AZ", "AR", "CA",
    "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY",
]

# Start near the user's Virginia region,
# then progressively cover every other state.
PRIORITY = [
    "VA", "WV", "MD", "NC", "PA",
    "TN", "DC",
]

# DC is an additional district, not a 51st state.
SEARCH_ORDER = [
    x for x in PRIORITY if x in STATES or x == "DC"
] + [
    x for x in STATES if x not in PRIORITY
]

STORE_TERMS = re.compile(
    r"trading[\s-]*cards?|"
    r"collectible[\s-]*cards?|"
    r"card[\s-]*games?|"
    r"pok[eé]mon|"
    r"tabletop|"
    r"hobby[\s-]*games?|"
    r"game[\s-]*store|"
    r"comic.*games|"
    r"\btcg\b|\bccg\b",
    re.IGNORECASE,
)

EXCLUDED = re.compile(
    r"casino|gambling|sports.betting|"
    r"arcade.only|video.games?.only",
    re.IGNORECASE,
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, fallback):
    if not path.exists():
        return fallback

    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temporary.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def safe_url(value):
    try:
        parsed = urlparse(clean(value))

        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return parsed.geturl()

    except ValueError:
        pass

    return ""


def overpass_query(state):
    # OpenStreetMap state administrative area.
    # This covers mapped rural and urban locations.
    iso = "US-" + state

    return f"""
[out:json][timeout:90];
area
  ["ISO3166-2"="{iso}"]
  ["boundary"="administrative"]
  ->.searchArea;
(
  nwr["shop"="games"](area.searchArea);
  nwr["shop"="collector"](area.searchArea);
  nwr["shop"="comic"](area.searchArea);
  nwr["name"~"Trading Card|Card Shop|Card Game|TCG|Game Store",i](area.searchArea);
  nwr["description"~"trading card|card game|pokemon|pokémon|TCG",i](area.searchArea);
);
out center tags;
"""


def query_state(state):
    query = overpass_query(state)
    failures = []

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=HEADERS,
                timeout=115,
            )

            response.raise_for_status()

            result = response.json()

            if not isinstance(
                result.get("elements"), list
            ):
                raise ValueError(
                    "Invalid Overpass response"
                )

            return result["elements"]

        except (
            requests.RequestException,
            ValueError
        ) as exc:
            failures.append(
                f"{urlparse(endpoint).hostname}: "
                f"{str(exc)[:100]}"
            )

    raise RuntimeError(
        "All Overpass endpoints failed: "
        + "; ".join(failures)
    )


def extract_store(element, searched_state):
    if not isinstance(element, dict):
        return None

    tags = element.get("tags") or {}

    name = clean(tags.get("name"))

    if not name:
        return None

    category = clean(
        tags.get("shop")
    ).lower()

    description = " ".join([
        name,
        clean(tags.get("description")),
        clean(tags.get("product")),
        clean(tags.get("name:en")),
        category,
    ])

    if EXCLUDED.search(description):
        return None

    # Generic comic shops need specific gaming relevance.
    if category not in ("games", "collector"):
        if not STORE_TERMS.search(description):
            return None

    osm_type = element.get("type")
    osm_id = element.get("id")

    if osm_type not in (
        "node", "way", "relation"
    ):
        return None

    if not isinstance(osm_id, int):
        return None

    center = element.get("center") or {}

    lat = element.get(
        "lat", center.get("lat")
    )
    lon = element.get(
        "lon", center.get("lon")
    )

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return None

    if not (
        -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        return None

    country_tag = clean(
        tags.get("addr:country")
    ).upper()

    if country_tag and country_tag not in (
        "US", "USA", "UNITED STATES"
    ):
        return None

    state_tag = clean(
        tags.get("addr:state")
    ).upper()

    # The administrative-area search supplies the
    # state when individual OSM address tags omit it.
    state = state_tag or searched_state

    street = " ".join(filter(None, [
        clean(tags.get("addr:housenumber")),
        clean(tags.get("addr:street")),
    ]))

    website = safe_url(
        tags.get("website")
        or tags.get("contact:website")
    )

    osm_url = (
        "https://www.openstreetmap.org/"
        f"{osm_type}/{osm_id}"
    )

    return {
        "id": f"osm-{osm_type}-{osm_id}",
        "name": name,
        "url": website,
        "city": clean(tags.get("addr:city")),
        "state": state,
        "country": "US",
        "address": clean(street),
        "lat": lat,
        "lon": lon,
        "games": [],
        "category": (
            category or "possible_tcg_shop"
        ),
        "source": "OpenStreetMap",
        "source_url": osm_url,
        "discovery_status": (
            "OSM-listed candidate"
        ),
        "inventory_status": "Unknown",
        "last_discovered": timestamp(),
        "discovery_version": "8.2",
    }


def merge_store(existing, discovered):
    # Preserve existing fields, including any
    # independently verified information.
    merged = dict(existing)

    for field, value in discovered.items():
        if field in (
            "games",
            "inventory_status",
            "owner_verified",
            "verified_at",
            "inventory_evidence",
            "stock_status",
        ):
            if field not in merged:
                merged[field] = value
            continue

        if field in ("city", "state", "address", "url"):
            if not merged.get(field) and value:
                merged[field] = value
            continue

        if value not in ("", None, []):
            merged[field] = value

    return merged


def run():
    DATA.mkdir(parents=True, exist_ok=True)

    existing = read_json(
        STORES_FILE, []
    )

    progress = read_json(
        STATE_FILE, {}
    )

    if not isinstance(existing, list):
        raise ValueError(
            "stores.json must contain a list"
        )

    if not isinstance(progress, dict):
        raise ValueError(
            "discovery_state.json must be an object"
        )

    by_id = {}

    for store in existing:
        if (
            isinstance(store, dict)
            and store.get("id")
        ):
            by_id[str(store["id"])] = dict(store)

    # V8.1's cursor is not reused because
    # V8.2 has a different geographic search order.
    cursor = int(
        progress.get("v82_cursor", 0)
    ) % len(SEARCH_ORDER)

    state = SEARCH_ORDER[cursor]

    print("=== POKESTOCK V8.2 ===")
    print("Searching state:", state)
    print("Existing stores:", len(by_id))

    progress["version"] = "8.2"
    progress["v82_last_attempt"] = timestamp()
    progress["v82_last_state"] = state
    progress["v82_regions_configured"] = len(
        SEARCH_ORDER
    )

    try:
        elements = query_state(state)

    except Exception as exc:
        progress["v82_last_error"] = (
            str(exc)[:500]
        )

        # Preserve the cursor so failed states
        # can be retried on the next run.
        write_json(STATE_FILE, progress)

        print("Discovery failed:", exc)
        print("Existing stores preserved.")
        return

    added = 0
    updated = 0
    candidates = 0

    for element in elements:
        store = extract_store(
            element, state
        )

        if store is None:
            continue

        candidates += 1
        sid = store["id"]

        if sid in by_id:
            by_id[sid] = merge_store(
                by_id[sid], store
            )
            updated += 1
        else:
            by_id[sid] = store
            added += 1

    # Do not discard stores from previous runs.
    directory = sorted(
        by_id.values(),
        key=lambda s: (
            str(s.get("state", "")),
            str(s.get("city", "")),
            str(s.get("name", "")),
        )
    )

    write_json(
        STORES_FILE, directory
    )

    completed = progress.get(
        "v82_completed_states", []
    )

    if not isinstance(completed, list):
        completed = []

    if state not in completed:
        completed.append(state)

    progress.update({
        "version": "8.2",
        "v82_cursor": (
            cursor + 1
        ) % len(SEARCH_ORDER),
        "v82_last_state": state,
        "v82_last_success": timestamp(),
        "v82_last_error": None,
        "v82_last_candidates": candidates,
        "v82_last_new_stores": added,
        "v82_last_updated_stores": updated,
        "v82_total_stores": len(directory),
        "v82_completed_states": completed,
        "v82_completed_count": len(completed),
        "v82_regions_configured": len(
            SEARCH_ORDER
        ),
        "v82_inventory_claims_created": 0,
    })

    write_json(
        STATE_FILE, progress
    )

    print("State completed:", state)
    print("Candidates found:", candidates)
    print("New stores:", added)
    print("Existing stores updated:", updated)
    print("Total stored:", len(directory))
    print(
        "States/district completed:",
        len(completed),
        "/",
        len(SEARCH_ORDER)
    )
    print("No inventory claims created.")


if __name__ == "__main__":
    run()
