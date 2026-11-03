#!/usr/bin/env python3
"""PokéStock V22 — Public Shopify pickup monitoring.

Checks public product-variant pickup sections.
Does not require API keys or report shelf quantities.

Outputs:
  data/store_pickup_observations.json
  data/store_pickup_report.json
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

OFFERS = DATA / "online_offers.json"
RETAILERS = DATA / "online_retailers.json"
RESULTS = DATA / "store_pickup_observations.json"
REPORT = DATA / "store_pickup_report.json"

NOW = datetime.now(timezone.utc).isoformat()
MAX_CHECKS = 30
DELAY = 0.4

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "PokeStock/22 (public pickup availability)",
    "Accept": "text/html,application/json",
})

SECTIONS = (
    "pickup-availability",
    "store-availability",
)

AVAILABLE = re.compile(
    r"^(?:available|in stock|"
    r"pickup available|available for pickup)$",
    re.I,
)

UNAVAILABLE = re.compile(
    r"^(?:unavailable|out of stock|"
    r"pickup unavailable|"
    r"not available for pickup)$",
    re.I,
)


def read(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def tidy(value):
    return " ".join(str(value or "").split())


def safe_base(value):
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        return None
    return "https://" + parsed.hostname.lower()


def fetch(url, json_expected=False):
    # Only HTTPS, no redirects, bounded responses.
    response = SESSION.get(
        url,
        timeout=(7, 16),
        allow_redirects=False,
    )

    if response.status_code != 200:
        return None

    if len(response.content) > 1_500_000:
        return None

    time.sleep(DELAY)

    if json_expected:
        try:
            return response.json()
        except ValueError:
            return None

    return response.text


def product_handle(url, allowed_domains):
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return None

    if parsed.hostname not in allowed_domains:
        return None

    match = re.match(
        r"^/products/([a-zA-Z0-9_-]+)",
        parsed.path,
    )

    return match.group(1) if match else None


def choose_variant(product, offer):
    variants = product.get("variants", [])

    if not isinstance(variants, list):
        return None

    sku = tidy(offer.get("sku"))
    title = tidy(offer.get("variant"))

    if sku:
        for variant in variants:
            if tidy(variant.get("sku")) == sku:
                return variant

    if title and title.lower() != "product listing":
        for variant in variants:
            if tidy(variant.get("title")) == title:
                return variant

    # Only use a fallback when there is
    # exactly one possible variant.
    if len(variants) == 1:
        return variants[0]

    return None


def class_names(tag):
    return " ".join(tag.get("class", []))


def pickup_rows(html, evidence_url, offer, variant):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Shopify Dawn-compatible markup.
    # Other themes are left unverified rather
    # than guessed from arbitrary page text.
    items = soup.select(
        ".pickup-availability-list__item"
    )

    for item in items:
        heading = item.find(
            ["h2", "h3", "h4", "strong"]
        )

        if heading is None:
            continue

        location = tidy(heading.get_text(" ", strip=True))

        if not location:
            continue

        classes = class_names(item).lower()

        # The icon class is a common explicit
        # status signal in Shopify themes.
        has_positive_icon = bool(
            item.select_one(
                ".icon-in-stock, .icon-checkmark, "
                ".icon-check"
            )
        )

        has_negative_icon = bool(
            item.select_one(
                ".icon-out-of-stock, .icon-close, "
                ".icon-error"
            )
        )

        # If both or neither appear, status is
        # ambiguous; do not publish a claim.
        if has_positive_icon == has_negative_icon:
            continue

        status = (
            "Pickup available"
            if has_positive_icon
            else "Pickup unavailable"
        )

        rows.append({
            "retailer": offer.get("retailer"),
            "product_name": offer.get("product_name"),
            "product_url": offer.get("product_url"),
            "game": offer.get("game"),
            "variant_id": str(variant.get("id")),
            "variant": tidy(variant.get("title")),
            "location_name": location,
            "availability": status,
            "inventory_scope": "store_pickup",
            "shelf_stock_confirmed": False,
            "exact_quantity": None,
            "evidence_type":
                "public_shopify_pickup_section",
            "evidence_url": evidence_url,
            "checked_at": NOW,
        })

    return rows


def main():
    offers = read(OFFERS, [])
    retailers = read(RETAILERS, [])
    previous = read(REPORT, {})

    if not isinstance(offers, list):
        raise ValueError("Invalid online offers")

    if not isinstance(retailers, list):
        raise ValueError("Invalid retailer list")

    allowed = {}

    for retailer in retailers:
        if not isinstance(retailer, dict):
            continue

        base = safe_base(
            tidy(retailer.get("base"))
        )

        if base:
            allowed[
                tidy(retailer.get("name"))
            ] = base

    candidates = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        retailer = tidy(offer.get("retailer"))
        base = allowed.get(retailer)

        if not base:
            continue

        domain = urlparse(base).hostname
        handle = product_handle(
            tidy(offer.get("product_url")),
            {domain},
        )

        if handle:
            candidates.append((offer, base, handle))

    # Stable ordering + rotating cursor.
    candidates.sort(
        key=lambda entry: (
            entry[0].get("retailer", ""),
            entry[2],
            entry[0].get("sku", ""),
        )
    )

    cursor = int(previous.get("next_cursor", 0))
    if candidates:
        cursor %= len(candidates)

    batch = []

    for offset in range(
        min(MAX_CHECKS, len(candidates))
    ):
        batch.append(
            candidates[
                (cursor + offset) % len(candidates)
            ]
        )

    observations = []
    checks = []
    product_cache = {}

    for offer, base, handle in batch:
        cache_key = (base, handle)

        try:
            if cache_key not in product_cache:
                product_cache[cache_key] = fetch(
                    base + "/products/"
                    + quote(handle) + ".js",
                    json_expected=True,
                )

            product = product_cache[cache_key]

            if not isinstance(product, dict):
                checks.append({
                    "retailer": offer.get("retailer"),
                    "product": handle,
                    "status": "product_data_unavailable",
                })
                continue

            variant = choose_variant(product, offer)

            if not variant or not variant.get("id"):
                checks.append({
                    "retailer": offer.get("retailer"),
                    "product": handle,
                    "status": "variant_unresolved",
                })
                continue

            found = []
            section_worked = False

            for section in SECTIONS:
                url = (
                    base + "/variants/"
                    + str(variant["id"])
                    + "/?section_id=" + section
                )

                html = fetch(url)

                if html is None:
                    continue

                if "pickup-availability" not in html.lower():
                    continue

                section_worked = True
                found = pickup_rows(
                    html, url, offer, variant
                )

                if found:
                    break

            observations.extend(found)

            checks.append({
                "retailer": offer.get("retailer"),
                "product": handle,
                "status": (
                    "verified_pickup_rows"
                    if found else
                    "no_parseable_pickup_evidence"
                ),
                "pickup_rows": len(found),
                "section_retrieved": section_worked,
            })

        except (requests.RequestException,
                ValueError, TypeError) as exc:
            checks.append({
                "retailer": offer.get("retailer"),
                "product": handle,
                "status": "error",
                "error": type(exc).__name__,
            })

    # Avoid publishing duplicate observations.
    unique = {}

    for row in observations:
        key = (
            row["retailer"],
            row["variant_id"],
            row["location_name"],
        )
        unique[key] = row

    observations = list(unique.values())

    report = {
        "version": "22.0",
        "checked_at": NOW,
        "candidate_online_offers": len(candidates),
        "checked_this_run": len(batch),
        "next_cursor": (
            (cursor + len(batch)) % len(candidates)
            if candidates else 0
        ),
        "verified_pickup_observations":
            len(observations),
        "pickup_available": sum(
            r["availability"] == "Pickup available"
            for r in observations
        ),
        "pickup_unavailable": sum(
            r["availability"] == "Pickup unavailable"
            for r in observations
        ),
        "verified_shelf_quantities": 0,
        "checks": checks,
        "limitations": [
            "Only compatible public Shopify themes.",
            "Pickup availability may involve transfers.",
            "No observation means Unknown, not out of stock.",
            "No Walmart, Target or GameStop inventory claims.",
        ],
    }

    write(RESULTS, observations)
    write(REPORT, report)

    print("=== POKESTOCK V22 ===")
    print("Candidates:", len(candidates))
    print("Checked:", len(batch))
    print("Pickup observations:", len(observations))
    print(
        "Available for pickup:",
        report["pickup_available"],
    )
    print(
        "Unavailable for pickup:",
        report["pickup_unavailable"],
    )
    print("Confirmed shelf quantities: 0")


if __name__ == "__main__":
    main()
