
#!/usr/bin/env python3
"""PokeStock V8.2.2 - Reliable nationwide discovery.

Searches small geographic tiles across all 50 US states
and Washington DC.

Primary: OpenStreetMap Overpass API.
Fallback: OpenStreetMap Nominatim search.

Only source-backed candidate stores are recorded.
No stock, shipment or product claims are invented.
Existing data is preserved.
"""

import json
import math
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

USER_AGENT = (
    "PokeStock/8.2.2 "
    "(https://github.com/failordie2002-bit/PokeStocking)"
)

HEADERS = {"User-Agent": USER_AGENT}

OVERPASS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

NOMINATIM = (
    "https://nominatim.openstreetmap.org"
)

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
    code for code in STATES
    if code not in (
        "VA", "WV", "MD", "NC", "PA", "TN", "DC"
    )
]

KEYWORDS = re.compile(
    r"trading[\s-]*cards?|collectible[\s-]*cards?|"
    r"card[\s-]*games?|pok[eé]mon|tabletop|"
    r"hobby[\s-]*games?|game[\s-]*store|"
    r"\btcg\b|\bccg\b",
    re.I,
)

EXCLUDED = re.compile(
    r"casino|gambling|sports.betting|"
    r"arcade.only|video.games?.only",
    re.I,
)

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path, default):
    if not path.exists():
        return default

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(path)


def clean(value):
    return " ".join(
        str(value or "").split()
    )


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


def state_bounds(code):
    response = SESSION.get(
        NOMINATIM + "/search",
        params={
            "q": STATES[code] + ", USA",
            "format": "json",
            "limit": 10,
            "countrycodes": "us",
        },
        timeout=25,
    )

    response.raise_for_status()

    results = response.json()

    for item in results:
        if (
            item.get("type") == "administrative"
            and STATES[code].lower()
            in item.get(
                "display_name", ""
            ).lower()
        ):
            south, north, west, east = map(
                float,
                item["boundingbox"]
            )

            return [
                south, west, north, east
            ]

    raise RuntimeError(
        "Unable to resolve state boundary: " + code
    )


def tiles_for(bounds, code):
    south, west, north, east = bounds

    # 0.25 degrees gives much smaller requests.
    # Larger Alaska tiles reduce total requests.
    step = 1.0 if code == "AK" else 0.25

    rows = max(
        1,
        math.ceil((north - south) / step)
    )

    cols = max(
        1,
        math.ceil((east - west) / step)
    )

    tiles = []

    for row in range(rows):
        for col in range(cols):
            a = south + row * step
            b = west + col * step

            tiles.append([
                round(a, 5),
                round(b, 5),
                round(min(north, a + step), 5),
                round(min(east, b + step), 5),
            ])

    return tiles


def overpass_query(code, tile):
    south, west, north, east = tile

    bbox = (
        f"({south},{west},{north},{east})"
    )

    return f"""
[out:json][timeout:25];
area["ISO3166-2"="US-{code}"]
["boundary"="administrative"]->.state;
(
  nwr["shop"="games"]{bbox}(area.state);
  nwr["shop"="collector"]{bbox}(area.state);
  nwr["shop"="comic"]{bbox}(area.state);
  nwr["name"~"Trading Card|Card Shop|Card Game|TCG|Game Store",i]{bbox}(area.state);
);
out center tags;
"""


def try_overpass(code, tile):
    query = overpass_query(code, tile)
    errors = []

    for endpoint in OVERPASS:
        for attempt in range(2):
            try:
                response = SESSION.post(
                    endpoint,
                    data={"data": query},
                    timeout=38,
                )

                response.raise_for_status()
                result = response.json()

                if result.get("remark"):
                    raise RuntimeError(
                        str(result["remark"])[:160]
                    )

                elements = result.get("elements")

                if not isinstance(elements, list):
                    raise ValueError(
                        "Invalid Overpass response"
                    )

                return elements, endpoint

            except (
                requests.RequestException,
                ValueError,
                RuntimeError
            ) as exc:
                errors.append(
                    str(exc)[:140]
                )

                if attempt == 0:
                    time.sleep(2)

    raise RuntimeError(
        "Overpass unavailable: "
        + "; ".join(errors[-3:])
    )


def try_nominatim(code, tile):
    # Nominatim is a limited fallback, not a
    # comprehensive replacement for Overpass.
    south, west, north, east = tile

    response = SESSION.get(
        NOMINATIM + "/search",
        params={
            "q": "trading card shop",
            "format": "json",
            "addressdetails": 1,
            "extratags": 1,
            "bounded": 1,
            "viewbox": (
                f"{west},{north},{east},{south}"
            ),
            "limit": 30,
        },
        timeout=30,
    )

    response.raise_for_status()

    items = response.json()

    if not isinstance(items, list):
        raise ValueError(
            "Invalid Nominatim response"
        )

    converted = []

    for item in items:
        address = item.get("address") or {}

        country = clean(
            address.get("country_code")
        ).lower()

        if country != "us":
            continue

        kind = item.get("osm_type")
        oid = item.get("osm_id")

        if kind not in (
            "node", "way", "relation"
        ):
            continue

        try:
            oid = int(oid)
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (
            TypeError, ValueError, KeyError
        ):
            continue

        if not (
            south <= lat <= north
            and west <= lon <= east
        ):
            continue

        extras = item.get("extratags") or {}

        name = clean(
            item.get("name")
            or item.get("display_name", "").split(",")[0]
        )

        if not name:
            continue

        tags = {
            "name": name,
            "shop": item.get("type", ""),
            "description": extras.get(
                "description", ""
            ),
            "website": extras.get(
                "website", ""
            ),
            "addr:city": (
                address.get("city")
                or address.get("town")
                or address.get("village")
                or ""
            ),
            "addr:state": code,
            "addr:street": address.get(
                "road", ""
            ),
            "addr:housenumber": address.get(
                "house_number", ""
            ),
        }

        converted.append({
            "type": kind,
            "id": oid,
            "lat": lat,
            "lon": lon,
            "tags": tags,
        })

    return converted


def discover(code, tile):
    try:
        elements, endpoint = try_overpass(
            code, tile
        )

        return elements, "Overpass", endpoint

    except Exception as primary_error:
        print(
            "Primary discovery failed:",
            str(primary_error)[:250]
        )

    # One Nominatim request per failed tile.
    # Do not retry rapidly against public servers.
    time.sleep(1)

    elements = try_nominatim(
        code, tile
    )

    return (
        elements,
        "Nominatim fallback",
        NOMINATIM
    )


def extract(element, code, method):
    tags = element.get("tags") or {}

    name = clean(tags.get("name"))

    if not name:
        return None

    category = clean(
        tags.get("shop")
    ).lower()

    description = " ".join([
        name,
        category,
        clean(tags.get("description")),
    ])

    if EXCLUDED.search(description):
        return None

    if category not in (
        "games", "collector"
    ) and not KEYWORDS.search(description):
        return None

    kind = element.get("type")
    oid = element.get("id")

    if kind not in (
        "node", "way", "relation"
    ):
        return None

    if not isinstance(oid, int):
        return None

    center = element.get("center") or {}

    try:
        lat = float(
            element.get(
                "lat", center.get("lat")
            )
        )

        lon = float(
            element.get(
                "lon", center.get("lon")
            )
        )

    except (TypeError, ValueError):
        return None

    if not (
        -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        return None

    street = clean(" ".join(filter(None, [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
    ])))

    return {
        "id": f"osm-{kind}-{oid}",
        "name": name,
        "url": safe_url(
            tags.get("website")
        ),
        "city": clean(
            tags.get("addr:city")
        ),
        "state": code,
        "country": "US",
        "address": street,
        "lat": lat,
        "lon": lon,
        "games": [],
        "category": (
            category or "possible_tcg_shop"
        ),
        "source": "OpenStreetMap",
        "source_url": (
            "https://www.openstreetmap.org/"
            f"{kind}/{oid}"
        ),
        "discovery_method": method,
        "discovery_status": (
            "OSM-listed candidate"
        ),
        "inventory_status": "Unknown",
        "last_discovered": now(),
        "discovery_version": "8.2.2",
    }


def merge(old, new):
    merged = dict(old)

    protected = {
        "games",
        "inventory_status",
        "stock_status",
        "owner_verified",
        "verified_at",
        "inventory_evidence",
    }

    for key, value in new.items():
        if key in protected and key in merged:
            continue

        if key in (
            "city", "state", "address", "url"
        ) and merged.get(key):
            continue

        if value not in (
            "", None, []
        ):
            merged[key] = value

    return merged


def main():
    DATA.mkdir(
        parents=True, exist_ok=True
    )

    existing = load(STORES, [])
    progress = load(STATE, {})

    if not isinstance(existing, list):
        raise ValueError(
            "Invalid stores.json"
        )

    if not isinstance(progress, dict):
        raise ValueError(
            "Invalid discovery_state.json"
        )

    by_id = {
        str(s["id"]): dict(s)
        for s in existing
        if isinstance(s, dict) and s.get("id")
    }

    cursor = int(
        progress.get("v822_state_cursor", 0)
    ) % len(ORDER)

    code = ORDER[cursor]

    progress.update({
        "version": "8.2.2",
        "v822_last_attempt": now(),
        "v822_last_state": code,
        "v822_status": "running",
    })

    print("=== POKESTOCK V8.2.2 ===")
    print("State:", code)
    print("Existing stores:", len(by_id))

    try:
        bounds_cache = progress.get(
            "v822_bounds", {}
        )

        if not isinstance(
            bounds_cache, dict
        ):
            bounds_cache = {}

        if code not in bounds_cache:
            bounds_cache[code] = (
                state_bounds(code)
            )

        bounds = bounds_cache[code]
        tiles = tiles_for(bounds, code)

        tile_index = int(
            progress.get(
                "v822_tile_cursor", 0
            )
        )

        if tile_index >= len(tiles):
            tile_index = 0

        tile = tiles[tile_index]

        print(
            "Tile",
            tile_index + 1,
            "of",
            len(tiles)
        )

        elements, method, endpoint = (
            discover(code, tile)
        )

        # A fallback search cannot establish that
        # a tile was comprehensively searched.
        complete = method == "Overpass"

        added = 0
        candidates = 0

        for element in elements:
            store = extract(
                element, code, method
            )

            if store is None:
                continue

            candidates += 1
            sid = store["id"]

            if sid in by_id:
                by_id[sid] = merge(
                    by_id[sid], store
                )
            else:
                by_id[sid] = store
                added += 1

        save(
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
            "v822_completed_states", []
        )

        if not isinstance(
            completed, list
        ):
            completed = []

        next_tile = tile_index
        next_state = cursor

        if complete:
            next_tile += 1

            if next_tile >= len(tiles):
                next_tile = 0

                if code not in completed:
                    completed.append(code)

                next_state = (
                    cursor + 1
                ) % len(ORDER)

        progress.update({
            "version": "8.2.2",
            "v822_status": (
                "success" if complete
                else "partial_fallback"
            ),
            "v822_last_error": None,
            "v822_last_state": code,
            "v822_last_tile": tile_index + 1,
            "v822_tiles_in_state": len(tiles),
            "v822_last_method": method,
            "v822_last_endpoint": endpoint,
            "v822_last_candidates": candidates,
            "v822_last_new_stores": added,
            "v822_total_stores": len(by_id),
            "v822_last_success": now(),
            "v822_bounds": bounds_cache,
            "v822_state_cursor": next_state,
            "v822_tile_cursor": next_tile,
            "v822_completed_states": completed,
            "v822_completed_count": len(completed),
            "v822_inventory_claims_created": 0,
        })

        save(STATE, progress)

        print("Method:", method)
        print("New stores:", added)
        print("Total stores:", len(by_id))
        print("Status:", progress["v822_status"])
        print("No inventory claims created.")

        if not complete:
            raise RuntimeError(
                "Fallback returned candidates, "
                "but tile remains incomplete. "
                "Retry required."
            )

    except Exception as exc:
        progress = load(STATE, progress)

        if progress.get(
            "v822_status"
        ) != "partial_fallback":
            progress["v822_status"] = "failed"

        progress["v822_last_error"] = (
            str(exc)[:500]
        )

        save(STATE, progress)

        print(
            "DISCOVERY FAILED:",
            progress["v822_last_error"]
        )

        # Exit nonzero so GitHub Actions can
        # report discovery failures correctly.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
