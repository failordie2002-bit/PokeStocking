#!/usr/bin/env python3
"""PokéStock V21 — Free physical inventory discovery.

Builds a store-monitoring directory and identifies
which retailers require a store-specific stock adapter.

Does not scrape protected endpoints or invent stock.
Does not alter online inventory data.
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

STORES = DATA / "stores.json"
ONLINE = DATA / "online_retailers.json"
OUTPUT = DATA / "physical_inventory_sources.json"
REPORT = DATA / "physical_inventory_report.json"

STAMP = datetime.now(timezone.utc).isoformat()

CHAINS = {
    "Walmart": r"\bwalmart\b",
    "Target": r"\btarget\b",
    "GameStop": r"\bgame[\s-]*stop\b",
    "Best Buy": r"\bbest[\s-]*buy\b",
    "Barnes & Noble": r"barnes\s*(?:&|and)\s*noble",
    "Five Below": r"\bfive[\s-]*below\b",
    "Walgreens": r"\bwalgreens\b",
    "CVS": r"\bcvs\b",
    "Dollar General": r"\bdollar[\s-]*general\b",
}

TCG_STORE = re.compile(
    r"card|game|comic|hobby|collectib|"
    r"anime|trading|toy|tcg",
    re.I,
)

LOCAL_CITIES = {
    "staunton",
    "waynesboro",
    "harrisonburg",
    "charlottesville",
}

LOCAL_ZIPS = {
    "24401", "22980", "22801", "22802",
    "22901", "22902", "22903", "22911",
}

PUBLIC_RETAILER_URLS = {
    "Walmart": "https://www.walmart.com/",
    "Target": "https://www.target.com/",
    "GameStop": "https://www.gamestop.com/",
    "Best Buy": "https://www.bestbuy.com/",
    "Barnes & Noble": "https://www.barnesandnoble.com/",
    "Five Below": "https://www.fivebelow.com/",
    "Walgreens": "https://www.walgreens.com/",
    "CVS": "https://www.cvs.com/",
    "Dollar General": "https://www.dollargeneral.com/",
}


def load(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def first(store, *keys):
    for key in keys:
        value = store.get(key)
        if value not in (None, ""):
            return clean(value)
    return ""


def normalize_site(value):
    value = clean(value)

    if not value:
        return ""

    if value.startswith("http://"):
        value = "https://" + value[7:]

    if "://" not in value:
        value = "https://" + value

    try:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return ""

        hostname = parsed.hostname.lower()

        if hostname in ("localhost",):
            return ""

        if "." not in hostname:
            return ""

        return "https://" + hostname

    except ValueError:
        return ""


def chain_of(name):
    for chain, pattern in CHAINS.items():
        if re.search(pattern, name, re.I):
            return chain
    return ""


def store_location(store):
    address = first(
        store, "address", "street_address",
        "addr:street",
    )
    city = first(
        store, "city", "town",
        "addr:city",
    )
    state = first(
        store, "state", "region",
        "addr:state",
    )
    postal = first(
        store, "zip", "zipcode",
        "postal_code", "postcode",
        "addr:postcode",
    )

    location = store.get("location")
    if isinstance(location, dict):
        city = city or clean(location.get("city"))
        state = state or clean(location.get("state"))
        postal = postal or clean(
            location.get("postal_code")
        )

    return address, city, state, postal


def local_priority(city, postal):
    zip5 = postal[:5]

    return (
        city.lower() in LOCAL_CITIES
        or zip5 in LOCAL_ZIPS
    )


def retailer_sites():
    rows = load(ONLINE, [])

    if not isinstance(rows, list):
        return set()

    domains = set()

    for item in rows:
        if not isinstance(item, dict):
            continue

        base = normalize_site(item.get("base"))
        if base:
            domains.add(urlparse(base).hostname)

    return domains


def main():
    stores = load(STORES, [])

    if not isinstance(stores, list):
        raise ValueError(
            "data/stores.json must contain a list"
        )

    known_online = retailer_sites()

    sources = []
    seen = set()
    categories = Counter()
    local_count = 0

    for index, store in enumerate(stores):
        if not isinstance(store, dict):
            continue

        name = first(store, "name", "store_name")

        if not name:
            continue

        chain = chain_of(name)

        category = first(
            store, "category", "shop",
            "shop_type", "retailer_type",
        )

        if not chain and not TCG_STORE.search(
            name + " " + category
        ):
            continue

        address, city, state, postal = (
            store_location(store)
        )

        website = ""
        for key in (
            "website", "website_url",
            "contact_website", "shop_url",
        ):
            website = normalize_site(
                store.get(key)
            )
            if website:
                break

        if not website and chain:
            website = PUBLIC_RETAILER_URLS.get(
                chain, ""
            )

        domain = (
            urlparse(website).hostname
            if website else ""
        )

        online_feed_known = (
            domain in known_online
        )

        is_local = local_priority(
            city, postal
        )

        if is_local:
            local_count += 1

        # The original store directory may
        # contain candidate businesses rather
        # than verified TCG sellers.
        evidence_status = (
            "candidate_store_unverified"
        )

        if chain:
            source_type = "major_retailer"
        elif online_feed_known:
            source_type = "independent_online_feed"
        else:
            source_type = "independent_store"

        # A Shopify feed describes online
        # availability, not a particular shelf.
        physical_status = "Unknown"

        key = (
            name.lower(),
            address.lower(),
            city.lower(),
            postal[:5],
        )

        if key in seen:
            continue

        seen.add(key)

        row = {
            "source_id": "store-" + str(index),
            "name": name,
            "chain": chain or None,
            "category": category,
            "source_type": source_type,
            "address": address,
            "city": city,
            "state": state,
            "postal_code": postal,
            "website": website,
            "priority_area": (
                "Staunton region"
                if is_local else "Nationwide"
            ),
            "online_feed_known":
                online_feed_known,
            "physical_inventory_status":
                physical_status,
            "physical_inventory_verified": False,
            "store_identity_status":
                evidence_status,
            "stock_evidence_url": None,
            "stock_checked_at": None,
            "last_discovered_at": STAMP,
            "integration_status":
                "needs_store_specific_source",
        }

        sources.append(row)
        categories[source_type] += 1

    sources.sort(
        key=lambda x: (
            x["priority_area"] != "Staunton region",
            x["state"],
            x["city"],
            x["name"],
        )
    )

    report = {
        "version": "21.0",
        "generated_at": STAMP,
        "store_records_scanned": len(stores),
        "candidate_sources": len(sources),
        "local_candidate_sources": sum(
            row["priority_area"] == "Staunton region"
            for row in sources
        ),
        "source_types": dict(categories),
        "verified_physical_stock_observations": 0,
        "verified_physical_out_of_stock": 0,
        "inventory_scope": "physical_store",
        "status": "discovery_only",
        "next_step":
            "Integrate authorized store-specific "
            "availability sources.",
        "limitations": [
            "Candidate stores are not confirmed TCG sellers.",
            "Online availability does not prove shelf stock.",
            "Unknown is not equivalent to out of stock.",
            "No public physical-stock API is assumed.",
        ],
    }

    save(OUTPUT, sources)
    save(REPORT, report)

    print("=== POKESTOCK V21 ===")
    print("Store records:", len(stores))
    print("Candidate sources:", len(sources))
    print(
        "Staunton-region candidates:",
        report["local_candidate_sources"],
    )
    print(
        "Known online-feed locations:",
        sum(
            x["online_feed_known"]
            for x in sources
        ),
    )
    print("Verified physical stock: 0")
    print(
        "All physical stock remains UNKNOWN "
        "until store-specific evidence exists."
    )


if __name__ == "__main__":
    main()
