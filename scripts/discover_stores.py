
#!/usr/bin/env python3
"""PokeStock V8.2.1: Resumable 50-state rural discovery.

One geographic tile per run. Existing data is preserved.
OpenStreetMap listings are candidates, never stock proof.
"""

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORES = DATA / "stores.json"
STATE_FILE = DATA / "discovery_state.json"

STATES = {
    "AL": "Alabama", "AK": "Alaska",
    "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}

ORDER = [
    "VA", "WV", "MD", "NC", "PA", "TN", "DC"
] + [
    s for s in STATES
    if s not in (
        "VA", "WV", "MD", "NC", "PA", "TN"
    )
]

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

HEADERS = {
    "User-Agent": (
        "PokeStock/8.2.1 "
        "(https://github.com/failordie2002-bit/PokeStocking)"
    )
}

KEYWORDS = re.compile(
    r"trading[\s-]*cards?|collectible[\s-]*cards?|"
    r"card[\s-]*games?|pok[eé]mon|tabletop|"
    r"hobby[\s-]*games?|game[\s-]*store|"
    r"\btcg\b|\bccg\b",
    re.I,
)

EXCLUDE = re.compile(
    r"casino|gambling|sports.betting|"
    r"arcade.only|video.games?.only",
    re.I,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def safe_url(value):
    try:
        p = urlparse(clean(value))
        if (
            p.scheme == "https"
            and p.hostname
            and not p.username
            and not p.password
        ):
            return p.geturl()
    except ValueError:
        pass
    return ""


def state_bounds(code):
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": STATES[code] + ", United States",
            "format": "json",
            "limit": 5,
            "countrycodes": "us",
        },
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    results = response.json()
    expected = STATES[code].lower()

    for item in results:
        if (
            item.get("type") == "administrative"
            and expected in item.get(
                "display_name", ""
            ).lower()
        ):
            south, north, west, east = map(
                float, item["boundingbox"]
            )
            return [south, west, north, east]

    raise RuntimeError(
        "State boundary lookup unsuccessful: " + code
    )


def make_tiles(bounds, code):
    south, west, north, east = bounds

    # Small tiles reduce Overpass timeouts.
    # Alaska uses larger tiles because of its size.
    step = 1.5 if code == "AK" else 0.65

    rows = max(1, math.ceil((north - south) / step))
    cols = max(1, math.ceil((east - west) / step))

    tiles = []

    for row in range(rows):
        for col in range(cols):
            a = south + row * step
            b = west + col * step
            c = min(north, a + step)
            d = min(east, b + step)
            tiles.append([
                round(a, 5), round(b, 5),
                round(c, 5), round(d, 5)
            ])

    return tiles


def query_tile(code, tile):
    south, west, north, east = tile

    bbox = (
        f"({south},{west},{north},{east})"
    )

    # Both the state area and geographic tile
    # must match for a result to be returned.
    query = f"""
[out:json][timeout:35];
area["ISO3166-2"="US-{code}"]
["boundary"="administrative"]->.state;
(
  nwr["shop"="games"]{bbox}(area.state);
  nwr["shop"="collector"]{bbox}(area.state);
  nwr["shop"="comic"]{bbox}(area.state);
  nwr["name"~"Trading Card|Card Shop|Card Game|TCG|Game Store",i]{bbox}(area.state);
  nwr["description"~"trading card|card game|pokemon|pokémon|TCG",i]{bbox}(area.state);
);
out center tags;
"""

    errors = []

    for endpoint in ENDPOINTS:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=HEADERS,
                timeout=55,
            )
            response.raise_for_status()

            result = response.json()

            if not isinstance(
                result.get("elements"), list
            ):
                raise ValueError("Invalid result")

            if result.get("remark"):
                raise RuntimeError(
                    str(result["remark"])[:200]
                )

            return result["elements"]

        except (
            requests.RequestException,
            ValueError,
            RuntimeError
        ) as exc:
            errors.append(str(exc)[:150])

    raise RuntimeError("; ".join(errors))


def store_from_osm(element, code):
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
        category,
    ])

    if EXCLUDE.search(description):
        return None

    if category not in ("games", "collector"):
        if not KEYWORDS.search(description):
            return None

    kind = element.get("type")
    oid = element.get("id")

    if kind not in ("node", "way", "relation"):
        return None

    if not isinstance(oid, int):
        return None

    center = element.get("center") or {}

    try:
        lat = float(
            element.get("lat", center.get("lat"))
        )
        lon = float(
            element.get("lon", center.get("lon"))
        )
    except (TypeError, ValueError):
        return None

    if not (
        -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        return None

    tagged_state = clean(
        tags.get("addr:state")
    )

    street = clean(" ".join(filter(None, [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
    ])))

    return {
        "id": f"osm-{kind}-{oid}",
        "name": name,
        "url": safe_url(
            tags.get("website")
            or tags.get("contact:website")
        ),
        "city": clean(tags.get("addr:city")),
        "state": tagged_state or code,
        "country": "US",
        "address": street,
        "lat": lat,
        "lon": lon,
        "games": [],
        "category": category or "possible_tcg_shop",
        "source": "OpenStreetMap",
        "source_url": (
            "https://www.openstreetmap.org/"
            f"{kind}/{oid}"
        ),
        "discovery_status": "OSM-listed candidate",
        "inventory_status": "Unknown",
        "last_discovered": now(),
        "discovery_version": "8.2.1",
    }


def merge(old, new):
    combined = dict(old)

    protected = {
        "games", "inventory_status",
        "owner_verified", "verified_at",
        "inventory_evidence", "stock_status",
    }

    for field, value in new.items():
        if field in protected and field in combined:
            continue

        if field in (
            "city", "state", "address", "url"
        ) and combined.get(field):
            continue

        if value not in ("", None, []):
            combined[field] = value

    return combined


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    existing = read(STORES, [])
    progress = read(STATE_FILE, {})

    if not isinstance(existing, list):
        raise ValueError("Invalid stores.json")

    if not isinstance(progress, dict):
        raise ValueError("Invalid discovery_state.json")

    by_id = {
        str(s["id"]): dict(s)
        for s in existing
        if isinstance(s, dict) and s.get("id")
    }

    cursor = int(
        progress.get("v821_state_cursor", 0)
    ) % len(ORDER)

    code = ORDER[cursor]

    print("=== POKESTOCK V8.2.1 ===")
    print("State:", code)
    print("Existing stores:", len(by_id))

    try:
        cached = progress.get("v821_bounds", {})

        if not isinstance(cached, dict):
            cached = {}

        if code in cached:
            bounds = cached[code]
        else:
            bounds = state_bounds(code)
            cached[code] = bounds

        tiles = make_tiles(bounds, code)

        tile_cursor = int(
            progress.get("v821_tile_cursor", 0)
        )

        if tile_cursor >= len(tiles):
            tile_cursor = 0

        tile = tiles[tile_cursor]

        print(
            "Tile:",
            tile_cursor + 1,
            "of",
            len(tiles)
        )

        elements = query_tile(code, tile)

    except Exception as exc:
        progress.update({
            "version": "8.2.1",
            "v821_last_state": code,
            "v821_last_error": str(exc)[:500],
            "v821_last_attempt": now(),
        })

        write(STATE_FILE, progress)

        print("Discovery error:", exc)
        print("Existing data preserved.")
        return

    added = 0
    candidates = 0

    for element in elements:
        store = store_from_osm(element, code)

        if store is None:
            continue

        candidates += 1
        sid = store["id"]

        if sid in by_id:
            by_id[sid] = merge(by_id[sid], store)
        else:
            by_id[sid] = store
            added += 1

    write(
        STORES,
        sorted(
            by_id.values(),
            key=lambda s: (
                str(s.get("state", "")),
                str(s.get("city", "")),
                str(s.get("name", "")),
            )
        )
    )

    completed = progress.get(
        "v821_completed_states", []
    )

    if not isinstance(completed, list):
        completed = []

    next_tile = tile_cursor + 1
    next_state = cursor

    if next_tile >= len(tiles):
        if code not in completed:
            completed.append(code)

        next_tile = 0
        next_state = (cursor + 1) % len(ORDER)

    progress.update({
        "version": "8.2.1",
        "v821_bounds": cached,
        "v821_state_cursor": next_state,
        "v821_tile_cursor": next_tile,
        "v821_last_state": code,
        "v821_last_tile": tile_cursor + 1,
        "v821_tiles_in_state": len(tiles),
        "v821_last_success": now(),
        "v821_last_error": None,
        "v821_last_candidates": candidates,
        "v821_last_new_stores": added,
        "v821_total_stores": len(by_id),
        "v821_completed_states": completed,
        "v821_completed_count": len(completed),
        "v821_inventory_claims_created": 0,
    })

    write(STATE_FILE, progress)

    print("New stores:", added)
    print("Total stores:", len(by_id))
    print("Next tile:", next_tile + 1)
    print("No inventory claims created.")


if __name__ == "__main__":
    main()
