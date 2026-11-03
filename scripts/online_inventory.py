#!/usr/bin/env python3
"""PokeStock V10 - Evidence-based online stock.

Phase 1 monitors official Kayou product pages.
Additional retailer adapters can be added later.

Outputs:
  data/online_offers.json
  data/online_inventory_report.json

Does not modify status.json or store_inventory.
Does not claim physical-store availability.
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NOW = datetime.now(timezone.utc)
STAMP = NOW.isoformat()

STATUS = DATA / "status.json"
OFFERS = DATA / "online_offers.json"
REPORT = DATA / "online_inventory_report.json"

HOSTS = {
    "shop.kayouofficial.com": "Kayou Official Store",
}

BATCH_SIZE = 25
MAX_AGE_HOURS = 8

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "PokeStock/10.0 "
        "(public product availability monitor)"
    ),
    "Accept": "text/html,application/xhtml+xml",
})


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def allowed(url):
    try:
        parsed = urlparse(str(url))
        return (
            parsed.scheme == "https"
            and parsed.hostname in HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.path.startswith("/products/")
        )
    except ValueError:
        return False


def fetch(url):
    if not allowed(url):
        raise ValueError("Unsupported storefront URL")

    response = SESSION.get(
        url,
        timeout=(12, 30),
        allow_redirects=True,
    )
    response.raise_for_status()

    if not allowed(response.url):
        raise ValueError("Untrusted redirect")

    if len(response.content) > 6_000_000:
        raise ValueError("Product page too large")

    return BeautifulSoup(response.text, "html.parser")


def product_nodes(value):
    """Find Product objects in JSON-LD, including graphs."""
    if isinstance(value, list):
        for item in value:
            yield from product_nodes(item)
        return

    if not isinstance(value, dict):
        return

    kind = value.get("@type", [])
    kinds = kind if isinstance(kind, list) else [kind]

    if any(
        str(k).split("/")[-1].lower() == "product"
        for k in kinds
    ):
        yield value

    for key in ("@graph", "mainEntity", "hasVariant"):
        if key in value:
            yield from product_nodes(value[key])


def schema_products(soup):
    result = []

    for tag in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            payload = json.loads(tag.string or tag.get_text())
            result.extend(product_nodes(payload))
        except (ValueError, TypeError):
            continue

    return result


def availability(value):
    """Only explicit Schema.org availability is accepted."""
    v = str(value or "").strip().split("/")[-1].lower()

    mapping = {
        "instock": "In stock",
        "outofstock": "Out of stock",
        "soldout": "Out of stock",
        "preorder": "Preorder",
        "presale": "Preorder",
        "backorder": "Backorder",
    }

    return mapping.get(v, "Unknown")


def image_candidate(soup, node):
    """Image candidate, not verified packaging artwork."""
    candidates = []

    for item in node.get("image", [] ) if isinstance(
        node.get("image"), list
    ) else [node.get("image")]:
        if isinstance(item, dict):
            candidates.append(item.get("url"))
        else:
            candidates.append(item)

    tag = soup.find(
        "meta", attrs={"property": "og:image"}
    )

    if tag:
        candidates.append(tag.get("content"))

    for url in candidates:
        if not isinstance(url, str):
            continue

        parsed = urlparse(url)

        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not re.search(
                r"logo|favicon|placeholder|sprite",
                url, re.I
            )
        ):
            return url

    return ""


def normalize_offers(node):
    raw = node.get("offers", [])

    if isinstance(raw, dict):
        if raw.get("@type") == "AggregateOffer":
            # Aggregate availability doesn't prove
            # each selectable variant is available.
            return []
        return [raw]

    if isinstance(raw, list):
        return [
            x for x in raw
            if isinstance(x, dict)
            and x.get("@type") != "AggregateOffer"
        ]

    return []


def parse_product(product, soup):
    nodes = schema_products(soup)
    retailer = HOSTS[urlparse(product["url"]).hostname]
    results = []

    # Do not infer stock from generic buttons,
    # page text, or marketing messages.
    for node in nodes:
        offers = normalize_offers(node)

        if not offers:
            continue

        for idx, offer in enumerate(offers):
            state = availability(
                offer.get("availability")
            )

            if state == "Unknown":
                continue

            sku = clean(
                offer.get("sku")
                or node.get("sku")
            )

            offer_name = clean(
                offer.get("name")
                or offer.get("sku")
            )

            # Multiple selectable offers must not
            # be represented as one blanket claim.
            if len(offers) > 1 and not (
                offer_name or sku
            ):
                continue

            variant = (
                offer_name or sku
                if len(offers) > 1
                else "Product listing"
            )

            record = {
                "product_url": product["url"],
                "product_name": product["name"],
                "game": product["game"],
                "retailer": retailer,
                "inventory_scope": "online",
                "availability": state,
                "variant": variant,
                "sku": sku,
                "evidence_type": "schema_org_offer",
                "evidence_url": product["url"],
                "checked_at": STAMP,
            }

            image = image_candidate(soup, node)

            if image:
                record["image_candidate"] = image
                record["image_review_status"] = (
                    "unverified_candidate"
                )

            price = offer.get("price")
            currency = offer.get("priceCurrency")

            if price not in (None, "") and currency:
                record["price"] = str(price)
                record["currency"] = str(currency)

            results.append(record)

    # Conflicting data on one variant is not
    # sufficient evidence of either stock state.
    unique = {}

    for row in results:
        key = (
            row["product_url"],
            row["variant"],
            row["sku"]
        )

        if key not in unique:
            unique[key] = row
        elif unique[key]["availability"] != row["availability"]:
            unique.pop(key, None)

    return list(unique.values())


def recent(row):
    try:
        timestamp = datetime.fromisoformat(
            row["checked_at"].replace("Z", "+00:00")
        )
        age = NOW - timestamp

        return (
            timedelta(0) <= age
            <= timedelta(hours=MAX_AGE_HOURS)
        )
    except (KeyError, TypeError, ValueError):
        return False


def main():
    catalogue = load(STATUS, {})
    products = catalogue.get("products", [])

    if not isinstance(products, list):
        raise ValueError("Invalid product catalogue")

    candidates = sorted(
        [
            p for p in products
            if isinstance(p, dict)
            and allowed(p.get("url"))
            and p.get("name")
            and p.get("game")
        ],
        key=lambda p: p["url"]
    )

    previous = load(OFFERS, [])
    if not isinstance(previous, list):
        raise ValueError("Invalid previous online offers")

    cursor = int(load(REPORT, {}).get("next_cursor", 0))

    if candidates:
        chosen = [
            candidates[(cursor + i) % len(candidates)]
            for i in range(
                min(BATCH_SIZE, len(candidates))
            )
        ]
    else:
        chosen = []

    new = []
    checks = []

    for product in chosen:
        try:
            soup = fetch(product["url"])
            offers = parse_product(product, soup)
            new.extend(offers)

            checks.append({
                "product": product["name"],
                "status": (
                    "verified_online_evidence"
                    if offers else "no_explicit_evidence"
                ),
                "offers": len(offers),
            })

        except Exception as error:
            checks.append({
                "product": product["name"],
                "status": "error",
                "reason": (
                    type(error).__name__
                    + ": " + str(error)[:120]
                )
            })

    checked_urls = {
        p["url"] for p in chosen
    }

    # Previously checked pages are replaced with
    # new observations, never stale positives.
    combined = [
        row for row in previous
        if (
            isinstance(row, dict)
            and recent(row)
            and row.get("product_url")
            not in checked_urls
        )
    ]

    combined.extend(new)

    save(OFFERS, combined)

    next_cursor = (
        (cursor + len(chosen)) % len(candidates)
        if candidates else 0
    )

    report = {
        "version": "10.0",
        "checked_at": STAMP,
        "retailers_integrated": list(
            HOSTS.values()
        ),
        "candidate_products": len(candidates),
        "checked_this_run": len(chosen),
        "offers_with_explicit_evidence": len(new),
        "total_fresh_offers": len(combined),
        "next_cursor": next_cursor,
        "checks": checks,
        "physical_store_stock_claims": 0,
    }

    save(REPORT, report)

    print("=== POKESTOCK V10 ONLINE INVENTORY ===")
    print("Candidates:", len(candidates))
    print("Checked:", len(chosen))
    print("Verified online offers:", len(new))
    print("Fresh offers:", len(combined))

    for item in checks:
        print(
            item["status"],
            item["product"][:90]
        )


if __name__ == "__main__":
    main()
