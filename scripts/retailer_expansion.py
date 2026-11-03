#!/usr/bin/env python3
"""PokéStock V11 — Nationwide Retailer Discovery.

Discovers public Shopify catalogues from websites
already associated with nationwide store records.

Writes:
  data/online_retailers.json
  data/retailer_discovery_report.json

Does NOT:
  - modify product catalogue
  - claim physical-store inventory
  - fabricate stock
  - treat every discovered store as a TCG retailer

Designed for periodic GitHub Actions execution.
"""

import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

STORES_FILE = DATA / "stores.json"
RETAILERS_FILE = DATA / "online_retailers.json"
REPORT_FILE = DATA / "retailer_discovery_report.json"

NOW = datetime.now(timezone.utc).isoformat()

# Limit work to avoid excessive requests.
MAX_CANDIDATES_PER_RUN = 20
MAX_REGISTERED = 500
TIMEOUT = (5, 12)

# Avoid probing known major retailer websites
# that do not use the Shopify adapter.
SKIP_DOMAINS = {
    "walmart.com",
    "target.com",
    "gamestop.com",
    "bestbuy.com",
    "amazon.com",
    "ebay.com",
    "costco.com",
    "samsclub.com",
    "walgreens.com",
    "cvs.com",
    "dollargeneral.com",
    "dollartree.com",
    "fivebelow.com",
    "barnesandnoble.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "google.com",
    "maps.google.com",
    "linktr.ee",
    "discord.gg",
}

SPORTS = re.compile(
    r"\b(baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl|"
    r"nascar|sports cards?)\b",
    re.I,
)

TCG = re.compile(
    r"pokemon|pokémon|union arena|gundam|"
    r"one piece|yugioh|yu.gi.oh|"
    r"magic.the.gathering|lorcana|"
    r"digimon|dragon ball|star wars unlimited|"
    r"weiss schwarz|weiß schwarz|"
    r"cardfight|battle spirits|shadowverse|"
    r"riftbound|flesh and blood|"
    r"grand archive|final fantasy tcg|"
    r"sorcery contested realm|"
    r"booster box|booster pack|"
    r"booster bundle|trading card game|"
    r"tcg|sealed card",
    re.I,
)

SEALED = re.compile(
    r"booster|bundle|display|sealed|"
    r"starter deck|trial deck|"
    r"structure deck|elite trainer|"
    r"collection box|collector box|"
    r"blister|card pack|battle deck|"
    r"trading card",
    re.I,
)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "PokeStock/11.0 Retailer Discovery",
    "Accept": "application/json",
})


def load(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def normalize_url(value):
    value = clean(value)

    if not value:
        return ""

    if value.startswith("http://"):
        value = "https://" + value[7:]

    if "://" not in value:
        value = "https://" + value

    try:
        parsed = urlparse(value)
        host = parsed.hostname

        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return ""

        host = host.lower().rstrip(".")

        if (
            host == "localhost"
            or host.endswith(".local")
            or host.endswith(".internal")
            or "." not in host
        ):
            return ""

        try:
            ipaddress.ip_address(host)
            return ""
        except ValueError:
            pass

        if any(
            host == domain
            or host.endswith("." + domain)
            for domain in SKIP_DOMAINS
        ):
            return ""

        return "https://" + host

    except ValueError:
        return ""


def public_dns(host):
    """Reject private/reserved network targets."""
    try:
        records = socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM
        )

        if not records:
            return False

        for record in records:
            address = record[4][0]
            ip = ipaddress.ip_address(address)

            if not ip.is_global:
                return False

        return True

    except (OSError, ValueError):
        return False


def store_site(store):
    for key in (
        "website",
        "url",
        "website_url",
        "contact_website",
    ):
        url = normalize_url(store.get(key))
        if url:
            return url

    return ""


def likely_store(store):
    name = clean(store.get("name"))
    category = clean(
        " ".join(str(store.get(k) or "") for k in (
            "category",
            "shop",
            "shop_type",
            "retailer_type",
            "description",
        ))
    )

    combined = name + " " + category

    if SPORTS.search(combined) and not TCG.search(combined):
        return False

    return bool(
        re.search(
            r"card|game|hobby|collectib|"
            r"comic|toy|tcg|anime",
            combined,
            re.I,
        )
    )


def candidates(stores):
    found = {}

    for store in stores:
        if not isinstance(store, dict):
            continue

        if not likely_store(store):
            continue

        url = store_site(store)

        if not url:
            continue

        host = urlparse(url).hostname

        if host not in found:
            found[host] = {
                "name": clean(
                    store.get("name") or host
                ),
                "base": url,
                "host": host,
            }

    return sorted(
        found.values(),
        key=lambda row: row["host"],
    )


def inspect_shopify(shop):
    """Inspect a public Shopify products feed.

    A successful response alone is not enough:
    at least one recognizable TCG product must
    appear before registering the retailer.
    """
    if not public_dns(shop["host"]):
        raise ValueError(
            "Domain did not resolve to public IPs"
        )

    url = shop["base"] + "/products.json?limit=100"

    response = SESSION.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=False,
    )

    if 300 <= response.status_code < 400:
        raise ValueError(
            "Redirect not followed"
        )

    response.raise_for_status()

    if len(response.content) > 5_000_000:
        raise ValueError(
            "Catalogue response too large"
        )

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            "Invalid Shopify response"
        )

    products = payload.get("products")

    if not isinstance(products, list):
        raise ValueError(
            "No Shopify products array"
        )

    matched = []

    for product in products:
        if not isinstance(product, dict):
            continue

        title = clean(product.get("title"))
        tags = product.get("tags") or ""

        if isinstance(tags, list):
            tags = " ".join(map(str, tags))

        text = title + " " + clean(tags)

        if (
            TCG.search(text)
            and SEALED.search(text)
            and not (
                SPORTS.search(text)
                and not TCG.search(title)
            )
        ):
            matched.append(title)

    if not matched:
        return {
            "supported": False,
            "reason": "No matching sealed TCG products",
            "feed_products": len(products),
        }

    return {
        "supported": True,
        "feed_products": len(products),
        "matching_products": len(matched),
        "examples": matched[:3],
    }


def main():
    stores = load(STORES_FILE, [])

    if not isinstance(stores, list):
        raise ValueError(
            "Store directory must be a list"
        )

    existing = load(RETAILERS_FILE, [])

    if not isinstance(existing, list):
        raise ValueError(
            "Retailer configuration must be a list"
        )

    previous = load(REPORT_FILE, {})
    cursor = int(previous.get("next_cursor", 0))

    pool = candidates(stores)

    selected = []

    if pool:
        for i in range(
            min(MAX_CANDIDATES_PER_RUN, len(pool))
        ):
            selected.append(
                pool[(cursor + i) % len(pool)]
            )

    registered = {}

    for shop in existing:
        if not isinstance(shop, dict):
            continue

        base = normalize_url(shop.get("base"))

        if not base:
            continue

        domain = urlparse(base).hostname

        registered[domain] = {
            "name": clean(
                shop.get("name") or domain
            ),
            "base": base,
        }

    checks = []
    added = 0

    for shop in selected:
        if shop["host"] in registered:
            checks.append({
                "name": shop["name"],
                "status": "already_registered",
            })
            continue

        try:
            result = inspect_shopify(shop)

            if (
                result["supported"]
                and len(registered) < MAX_REGISTERED
            ):
                registered[shop["host"]] = {
                    "name": shop["name"],
                    "base": shop["base"],
                }

                added += 1
                status = "registered"
            else:
                status = "not_eligible"

            checks.append({
                "name": shop["name"],
                "host": shop["host"],
                "status": status,
                **result,
            })

        except Exception as error:
            checks.append({
                "name": shop["name"],
                "host": shop["host"],
                "status": "error",
                "reason": (
                    type(error).__name__
                    + ": "
                    + str(error)[:120]
                ),
            })

    next_cursor = (
        (cursor + len(selected)) % len(pool)
        if pool else 0
    )

    result = sorted(
        registered.values(),
        key=lambda x: x["name"].lower(),
    )

    report = {
        "version": "11.0",
        "checked_at": NOW,
        "total_store_records": len(stores),
        "candidate_retailer_websites": len(pool),
        "checked_this_run": len(selected),
        "new_retailers_registered": added,
        "total_registered_retailers": len(result),
        "next_cursor": next_cursor,
        "checks": checks,
        "inventory_scope": "online_only",
        "physical_store_stock_claims": 0,
    }

    save(RETAILERS_FILE, result)
    save(REPORT_FILE, report)

    print("=== POKESTOCK V11 ===")
    print("Store records:", len(stores))
    print("Candidate websites:", len(pool))
    print("Websites checked:", len(selected))
    print("New retailers:", added)
    print("Total registered:", len(result))

    for check in checks:
        print(
            check["status"],
            check["name"],
            check.get("matching_products", ""),
            check.get("reason", ""),
            flush=True,
        )


if __name__ == "__main__":
    main()
