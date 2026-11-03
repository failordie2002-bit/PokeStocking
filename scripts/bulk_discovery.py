
#!/usr/bin/env python3
"""PokeStock V8.4 - Nationwide Retail Discovery.

Discovers:
- Independent TCG, game, comic and hobby stores
- Major retail chains and discount stores
- Rural and small-town OSM-listed candidates

Supports future tracking of:
Pokemon, Union Arena, Gundam and One Piece.

Store discovery does NOT prove TCG availability
or current inventory. Existing records are kept.
"""

import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import osmium
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORES = DATA / "stores.json"
STATE = DATA / "discovery_state.json"

BASE = "https://download.geofabrik.de/north-america/us/"

STATES = [
    ("VA", "virginia"),
    ("WV", "west-virginia"),
    ("MD", "maryland"),
    ("NC", "north-carolina"),
    ("PA", "pennsylvania"),
    ("TN", "tennessee"),
    ("DC", "district-of-columbia"),
    ("AL", "alabama"),
    ("AK", "alaska"),
    ("AZ", "arizona"),
    ("AR", "arkansas"),
    ("CA", "california"),
    ("CO", "colorado"),
    ("CT", "connecticut"),
    ("DE", "delaware"),
    ("FL", "florida"),
    ("GA", "georgia"),
    ("HI", "hawaii"),
    ("ID", "idaho"),
    ("IL", "illinois"),
    ("IN", "indiana"),
    ("IA", "iowa"),
    ("KS", "kansas"),
    ("KY", "kentucky"),
    ("LA", "louisiana"),
    ("ME", "maine"),
    ("MA", "massachusetts"),
    ("MI", "michigan"),
    ("MN", "minnesota"),
    ("MS", "mississippi"),
    ("MO", "missouri"),
    ("MT", "montana"),
    ("NE", "nebraska"),
    ("NV", "nevada"),
    ("NH", "new-hampshire"),
    ("NJ", "new-jersey"),
    ("NM", "new-mexico"),
    ("NY", "new-york"),
    ("ND", "north-dakota"),
    ("OH", "ohio"),
    ("OK", "oklahoma"),
    ("OR", "oregon"),
    ("RI", "rhode-island"),
    ("SC", "south-carolina"),
    ("SD", "south-dakota"),
    ("TX", "texas"),
    ("UT", "utah"),
    ("VT", "vermont"),
    ("WA", "washington"),
    ("WI", "wisconsin"),
    ("WY", "wyoming"),
]

TRACKED_GAMES = [
    "Pokémon",
    "Union Arena",
    "Gundam",
    "One Piece",
]

# These are potential retailers, not guarantees
# that any particular branch sells TCG products.
CHAINS = {
    "Walmart": [
        "walmart",
        "walmart supercenter",
        "walmart neighborhood market",
    ],
    "Target": ["target"],
    "GameStop": ["gamestop", "game stop"],
    "Best Buy": ["best buy"],
    "Barnes & Noble": ["barnes & noble", "barnes and noble"],
    "Books-A-Million": ["books-a-million", "books a million"],
    "Five Below": ["five below"],
    "Dollar General": ["dollar general"],
    "Dollar Tree": ["dollar tree"],
    "Family Dollar": ["family dollar"],
    "Walgreens": ["walgreens"],
    "CVS": ["cvs", "cvs pharmacy"],
    "Costco": ["costco", "costco wholesale"],
    "Sam's Club": ["sam's club", "sams club"],
    "BJ's Wholesale Club": [
        "bj's wholesale club",
        "bjs wholesale club",
    ],
    "Kroger": ["kroger"],
    "Safeway": ["safeway"],
    "Meijer": ["meijer"],
    "Fred Meyer": ["fred meyer"],
    "Ross": ["ross dress for less", "ross"],
    "Burlington": ["burlington", "burlington stores"],
    "TJ Maxx": ["tj maxx", "tjmaxx"],
    "Marshalls": ["marshalls"],
    "Ollie's": ["ollie's bargain outlet", "ollies bargain outlet"],
    "Big Lots": ["big lots"],
    "Michaels": ["michaels"],
    "Hobby Lobby": ["hobby lobby"],
    "Newbury Comics": ["newbury comics"],
    "Hot Topic": ["hot topic"],
    "BoxLunch": ["boxlunch"],
}

INDEPENDENT = re.compile(
    r"trading[\s-]*cards?|"
    r"collectible[\s-]*cards?|"
    r"card[\s-]*games?|"
    r"pok[eé]mon|"
    r"tabletop|"
    r"hobby[\s-]*games?|"
    r"game[\s-]*store|"
    r"comic[\s-]*shop|"
    r"\btcg\b|\bccg\b",
    re.I,
)

EXCLUDED = re.compile(
    r"casino|gambling|sports.betting|"
    r"arcade.only|video.games?.only",
    re.I,
)

CHAIN_EXCLUDED = re.compile(
    r"optical|vision center|photo center|"
    r"gas station|fuel center|distribution center|"
    r"warehouse depot",
    re.I,
)

ALLOWED_CHAIN_SHOPS = {
    "",
    "supermarket",
    "department_store",
    "variety_store",
    "discount",
    "convenience",
    "general",
    "books",
    "electronics",
    "games",
    "collector",
    "chemist",
    "beauty",
    "mall",
    "wholesale",
    "warehouse",
    "gift",
    "clothes",
    "toys",
    "hobby",
}

HEADERS = {
    "User-Agent": (
        "PokeStock/8.4 "
        "(https://github.com/"
        "failordie2002-bit/PokeStocking)"
    )
}

MAX_BYTES = 1200 * 1024 * 1024
MAX_SECONDS = 850


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return " ".join(str(value or "").split())


def normalized(value):
    value = clean(value).lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


NORMALIZED_CHAINS = {
    name: {normalized(alias) for alias in aliases}
    for name, aliases in CHAINS.items()
}


def identify_chain(name, brand, operator):
    for value in (name, brand, operator):
        candidate = normalized(value)
        if not candidate:
            continue

        for chain, aliases in NORMALIZED_CHAINS.items():
            if candidate in aliases:
                return chain

            for alias in aliases:
                if candidate.startswith(alias + " "):
                    return chain

    return None


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


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def download(url, destination):
    size = 0
    start = time.monotonic()

    with requests.get(
        url,
        headers=HEADERS,
        stream=True,
        timeout=(20, 60),
    ) as response:
        response.raise_for_status()

        declared = int(
            response.headers.get("Content-Length") or 0
        )
        if declared > MAX_BYTES:
            raise RuntimeError("State extract too large")

        with open(destination, "wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    raise RuntimeError("Download size limit exceeded")
                if time.monotonic() - start > MAX_SECONDS:
                    raise RuntimeError("Download timeout")
                output.write(chunk)

    if not size:
        raise RuntimeError("State extract was empty")

    print("Downloaded bytes:", size, flush=True)
    return size


class RetailCollector(osmium.SimpleHandler):
    def __init__(self, state_code):
        super().__init__()
        self.state_code = state_code
        self.found = {}
        self.chain_count = 0
        self.independent_count = 0

    def collect(self, kind, item, lat, lon):
        tags = {tag.k: tag.v for tag in item.tags}

        name = clean(tags.get("name"))
        if not name:
            return

        shop = clean(tags.get("shop")).lower()
        brand = clean(tags.get("brand"))
        operator = clean(tags.get("operator"))

        details = " ".join([
            name,
            shop,
            clean(tags.get("description")),
        ])

        if EXCLUDED.search(details):
            return

        chain = identify_chain(name, brand, operator)

        if chain:
            if shop not in ALLOWED_CHAIN_SHOPS:
                return
            if CHAIN_EXCLUDED.search(name):
                return
            category = "major_retailer"
            retailer_type = "chain"
        elif shop in ("games", "collector", "comic", "toys", "hobby"):
            category = shop
            retailer_type = "independent_candidate"
        elif INDEPENDENT.search(details):
            category = shop or "possible_tcg_shop"
            retailer_type = "independent_candidate"
        else:
            return

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return

        identifier = f"osm-{kind}-{item.id}"

        street = clean(" ".join(filter(None, [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
        ])))

        url = (
            tags.get("website")
            or tags.get("contact:website")
            or ""
        )

        record = {
            "id": identifier,
            "name": name,
            "url": safe_url(url),
            "city": clean(tags.get("addr:city")),
            "state": self.state_code,
            "country": "US",
            "address": street,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "games": [],
            "category": category,
            "retailer_type": retailer_type,
            "retailer_chain": chain or "",
            "source": "OpenStreetMap",
            "source_url": (
                f"https://www.openstreetmap.org/{kind}/{item.id}"
            ),
            "discovery_method": "Geofabrik state extract",
            "discovery_status": "OSM-listed candidate",
            "inventory_status": "Unknown",
            "discovery_version": "8.4",
            "last_discovered": now(),
        }

        self.found[identifier] = record

        if chain:
            self.chain_count += 1
        else:
            self.independent_count += 1

    def node(self, item):
        if item.location.valid():
            self.collect(
                "node",
                item,
                item.location.lat,
                item.location.lon,
            )

    def way(self, item):
        points = [
            (node.location.lat, node.location.lon)
            for node in item.nodes
            if node.location.valid()
        ]

        if not points:
            return

        lat = sum(point[0] for point in points) / len(points)
        lon = sum(point[1] for point in points) / len(points)

        self.collect("way", item, lat, lon)


def merge_stores(existing, incoming):
    merged = {
        str(store["id"]): dict(store)
        for store in existing
        if isinstance(store, dict) and store.get("id")
    }

    added = 0

    for store in incoming:
        identifier = str(store["id"])

        if identifier not in merged:
            merged[identifier] = store
            added += 1
            continue

        previous = merged[identifier]

        # Add missing metadata, preserving previous
        # inventory claims and curated information.
        for key, value in store.items():
            if (
                key not in previous
                or previous[key] in (None, "", [])
            ):
                previous[key] = value

    return list(merged.values()), added


def main():
    state = load(STATE, {})
    stores = load(STORES, [])

    if not isinstance(state, dict):
        raise ValueError("Invalid discovery state")
    if not isinstance(stores, list):
        raise ValueError("Invalid store directory")

    # V8.4 gets its own completion list so Virginia
    # and earlier states can be scanned again with
    # the expanded retailer rules.
    completed = state.get("v84_retail_completed_states", [])
    if not isinstance(completed, list):
        completed = []

    completed = list(dict.fromkeys(
        code for code in completed
        if code in {entry[0] for entry in STATES}
    ))

    pending = [
        entry for entry in STATES
        if entry[0] not in completed
    ]

    if not pending:
        print("All V8.4 state imports complete.")
        return

    code, slug = pending[0]

    state["v83_bulk_status"] = "running"
    state["v83_bulk_last_state"] = code
    state["v83_bulk_last_attempt"] = now()
    state["v83_bulk_last_error"] = None
    state["v84_retail_status"] = "running"
    state["v84_tracked_games"] = TRACKED_GAMES
    save(STATE, state)

    url = BASE + slug + "-latest.osm.pbf"

    print("=== V8.4 RETAIL DISCOVERY ===", flush=True)
    print("State:", code, flush=True)
    print("Source:", url, flush=True)
    print("Tracking:", ", ".join(TRACKED_GAMES), flush=True)

    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.osm.pbf"
            download(url, path)

            collector = RetailCollector(code)
            collector.apply_file(
                str(path),
                locations=True,
            )

            incoming = list(collector.found.values())

        updated, added = merge_stores(stores, incoming)

        # Data is saved before completion is recorded.
        save(STORES, updated)

        completed.append(code)

        # Preserve previous V8.3 completion progress.
        old_completed = state.get(
            "v83_bulk_completed_states", []
        )
        if not isinstance(old_completed, list):
            old_completed = []

        old_completed = list(dict.fromkeys(
            old_completed + [code]
        ))

        state.update({
            "v83_bulk_status": "success",
            "v83_bulk_last_state": code,
            "v83_bulk_last_error": None,
            "v83_bulk_last_success": now(),
            "v83_bulk_last_candidates": len(incoming),
            "v83_bulk_last_new_stores": added,
            "v83_bulk_total_stores": len(updated),
            "v83_bulk_completed_states": old_completed,
            "v83_bulk_completed_count": len(old_completed),
            "v83_bulk_total_states": len(STATES),
            "v83_bulk_inventory_claims_created": 0,
            "v84_retail_status": "success",
            "v84_retail_last_state": code,
            "v84_retail_last_new_stores": added,
            "v84_retail_last_candidates": len(incoming),
            "v84_retail_chain_candidates": collector.chain_count,
            "v84_retail_independent_candidates": (
                collector.independent_count
            ),
            "v84_retail_completed_states": completed,
            "v84_retail_completed_count": len(completed),
            "v84_retail_total_states": len(STATES),
            "v84_retail_last_success": now(),
            "v84_retail_last_error": None,
            "v84_tracked_games": TRACKED_GAMES,
        })

        save(STATE, state)

        print("=== RETAIL DISCOVERY SUCCESS ===")
        print("State:", code)
        print("Chain candidates:", collector.chain_count)
        print(
            "Independent candidates:",
            collector.independent_count,
        )
        print("New stores:", added)
        print("Total stores:", len(updated))
        print(
            "V8.4 completed:",
            len(completed),
            "/",
            len(STATES),
        )
        print("Verified inventory created: 0")

    except Exception as error:
        message = (
            type(error).__name__ + ": " + str(error)[:250]
        )

        state["v83_bulk_status"] = "failed"
        state["v83_bulk_last_error"] = message
        state["v84_retail_status"] = "failed"
        state["v84_retail_last_error"] = message
        state["v84_retail_last_failure"] = now()
        save(STATE, state)

        print("RETAIL DISCOVERY FAILED:", message, flush=True)
        raise


if __name__ == "__main__":
    main()
