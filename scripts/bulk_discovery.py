#!/usr/bin/env python3
"""PokeStock V8.3 nationwide bulk discovery.

Uses Geofabrik OpenStreetMap state extracts.
Preserves existing stores, products, releases,
shipments and previous discovery progress.

Store candidates are NOT verified inventory.
"""

import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import osmium

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORES = DATA / "stores.json"
STATE = DATA / "discovery_state.json"

BASE = (
    "https://download.geofabrik.de/"
    "north-america/us/"
)

# Nearby states first, then nationwide.
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
    ("WY", "wyoming")
]

HEADERS = {
    "User-Agent": (
        "PokeStock/8.3 "
        "(https://github.com/"
        "failordie2002-bit/PokeStocking)"
    )
}

MAX_BYTES = 1200 * 1024 * 1024
DOWNLOAD_SECONDS = 850

KEYWORDS = re.compile(
    r"trading[\s-]*cards?|"
    r"collectible[\s-]*cards?|"
    r"card[\s-]*games?|"
    r"pok[eé]mon|"
    r"tabletop|"
    r"hobby[\s-]*games?|"
    r"game[\s-]*store|"
    r"\btcg\b|\bccg\b",
    re.I
)

EXCLUDED = re.compile(
    r"casino|gambling|sports.betting|"
    r"arcade.only|video.games?.only",
    re.I
)


def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def load(path, default):
    if not path.exists():
        return default

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save(path, value):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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


def safe_url(value):
    try:
        parsed = urlparse(
            str(value or "").strip()
        )

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


def clean(value):
    return " ".join(
        str(value or "").split()
    )


def download(url, destination):
    start = time.monotonic()
    received = 0

    with requests.get(
        url,
        headers=HEADERS,
        stream=True,
        timeout=(20, 60)
    ) as response:

        response.raise_for_status()

        size = int(
            response.headers.get(
                "Content-Length", 0
            )
        )

        if size > MAX_BYTES:
            raise RuntimeError(
                "State extract exceeds size limit"
            )

        with open(destination, "wb") as file:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if not chunk:
                    continue

                received += len(chunk)

                if received > MAX_BYTES:
                    raise RuntimeError(
                        "Download exceeded size limit"
                    )

                if (
                    time.monotonic() - start
                    > DOWNLOAD_SECONDS
                ):
                    raise RuntimeError(
                        "Download time budget exceeded"
                    )

                file.write(chunk)

    if received == 0:
        raise RuntimeError(
            "Empty state extract"
        )

    return received


class StoreCollector(osmium.SimpleHandler):
    def __init__(self, state_code):
        super().__init__()
        self.state_code = state_code
        self.found = {}

    def collect(self, kind, item, lat, lon):
        tags = {
            tag.k: tag.v
            for tag in item.tags
        }

        name = clean(tags.get("name"))

        if not name:
            return

        category = clean(
            tags.get("shop")
        ).lower()

        description = " ".join([
            name,
            category,
            clean(tags.get("description"))
        ])

        if EXCLUDED.search(description):
            return

        if (
            category not in ("games", "collector")
            and not KEYWORDS.search(description)
        ):
            return

        if not (
            -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            return

        identifier = (
            f"osm-{kind}-{item.id}"
        )

        street = clean(" ".join(
            filter(None, [
                tags.get("addr:housenumber"),
                tags.get("addr:street")
            ])
        ))

        website = (
            tags.get("website")
            or tags.get("contact:website")
            or ""
        )

        self.found[identifier] = {
            "id": identifier,
            "name": name,
            "url": safe_url(website),
            "city": clean(
                tags.get("addr:city")
            ),
            "state": self.state_code,
            "country": "US",
            "address": street,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "games": [],
            "category": (
                category or "possible_tcg_shop"
            ),
            "source": "OpenStreetMap",
            "source_url": (
                "https://www.openstreetmap.org/"
                f"{kind}/{item.id}"
            ),
            "discovery_status": (
                "OSM-listed candidate"
            ),
            "inventory_status": "Unknown",
            "discovery_method": (
                "Geofabrik state extract"
            ),
            "discovery_version": "8.3",
            "last_discovered": now()
        }

    def node(self, item):
        if not item.location.valid():
            return

        self.collect(
            "node",
            item,
            item.location.lat,
            item.location.lon
        )

    def way(self, item):
        points = []

        for node in item.nodes:
            if node.location.valid():
                points.append((
                    node.location.lat,
                    node.location.lon
                ))

        if not points:
            return

        lat = sum(
            point[0] for point in points
        ) / len(points)

        lon = sum(
            point[1] for point in points
        ) / len(points)

        self.collect(
            "way",
            item,
            lat,
            lon
        )


def merge_stores(existing, incoming):
    merged = {}

    for store in existing:
        if (
            isinstance(store, dict)
            and store.get("id")
        ):
            merged[str(store["id"])] = dict(store)

    added = 0

    for store in incoming:
        identifier = str(store["id"])

        if identifier not in merged:
            merged[identifier] = store
            added += 1
            continue

        old = merged[identifier]

        # Preserve existing verified or
        # manually curated information.
        for field, value in store.items():
            if field not in old or old[field] in (
                None, "", []
            ):
                old[field] = value

    return list(merged.values()), added


def main():
    state = load(STATE, {})
    stores = load(STORES, [])

    if not isinstance(state, dict):
        raise ValueError(
            "Invalid discovery state"
        )

    if not isinstance(stores, list):
        raise ValueError(
            "Invalid store directory"
        )

    completed = state.get(
        "v83_bulk_completed_states", []
    )

    if not isinstance(completed, list):
        completed = []

    completed = [
        code for code in completed
        if code in {
            entry[0] for entry in STATES
        }
    ]

    pending = [
        item for item in STATES
        if item[0] not in completed
    ]

    if not pending:
        print(
            "All configured state extracts "
            "have been processed."
        )
        return

    code, slug = pending[0]

    state["v83_bulk_status"] = "running"
    state["v83_bulk_last_state"] = code
    state["v83_bulk_last_attempt"] = now()
    state["v83_bulk_last_error"] = None

    save(STATE, state)

    url = (
        BASE + slug + "-latest.osm.pbf"
    )

    print(
        "Downloading state extract:",
        code, url,
        flush=True
    )

    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.osm.pbf"

            size = download(url, path)

            print(
                "Downloaded bytes:",
                size,
                flush=True
            )

            collector = StoreCollector(code)

            collector.apply_file(
                str(path),
                locations=True
            )

            candidates = list(
                collector.found.values()
            )

        updated, added = merge_stores(
            stores,
            candidates
        )

        # Write stores before marking
        # the state as completed.
        save(STORES, updated)

        completed.append(code)

        state["v83_bulk_completed_states"] = completed
        state["v83_bulk_completed_count"] = len(completed)
        state["v83_bulk_total_states"] = len(STATES)
        state["v83_bulk_last_state"] = code
        state["v83_bulk_last_candidates"] = len(candidates)
        state["v83_bulk_last_new_stores"] = added
        state["v83_bulk_total_stores"] = len(updated)
        state["v83_bulk_last_success"] = now()
        state["v83_bulk_status"] = "success"
        state["v83_bulk_last_error"] = None
        state["v83_bulk_inventory_claims_created"] = 0

        save(STATE, state)

        print("=== BULK DISCOVERY SUCCESS ===")
        print("State:", code)
        print("Candidates:", len(candidates))
        print("New stores:", added)
        print("Total stores:", len(updated))
        print(
            "States completed:",
            len(completed),
            "/",
            len(STATES)
        )

    except Exception as exc:
        state["v83_bulk_status"] = "failed"
        state["v83_bulk_last_error"] = (
            type(exc).__name__
            + ": "
            + str(exc)[:250]
        )
        state["v83_bulk_last_failure"] = now()

        save(STATE, state)

        print(
            "BULK DISCOVERY FAILED:",
            state["v83_bulk_last_error"],
            flush=True
        )

        raise


if __name__ == "__main__":
    main()
