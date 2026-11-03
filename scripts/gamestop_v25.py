#!/usr/bin/env python3
"""
PokéStock V25 — GameStop Store Inventory

Based on the publicly documented GameStop browser
checking approach from GianPokemonTracker.

Features:
- Discover GameStop TCG products automatically
- Monitor real product pages with Playwright
- Capture GameStop's own store availability response
- Record actual store identity and product availability
- Never substitute online stock for physical stock
- Preserve previously verified results until expiration
- Produce machine-readable data and diagnostics

No API key required.

IMPORTANT:
GameStop chooses the store returned by its own session.
This script does not claim that the selected store is
near the user unless the returned address proves it.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote

from bs4 import BeautifulSoup
from playwright.sync_api import (
    sync_playwright,
    Error as PlaywrightError,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

BASE = "https://www.gamestop.com"

SEARCHES = [
    "pokemon trading card",
    "union arena",
    "one piece trading card",
    "yu gi oh cards",
    "magic the gathering",
    "lorcana",
    "gundam card game",
    "digimon card game",
    "dragon ball super cards",
    "star wars unlimited",
]

MAX_PRODUCTS = int(
    os.environ.get("POKESTOCK_MAX_PRODUCTS", "18")
)

MAX_AGE_HOURS = 8

NOW = datetime.now(timezone.utc)
STAMP = NOW.isoformat()

OUTPUT = DATA / "gamestop_store_inventory.json"
REPORT = DATA / "gamestop_v25_report.json"
CATALOG = DATA / "gamestop_products.json"

VARIATION_MARKER = "Product-Variation"
STORE_MARKER = "Stores-ProductDetailStoreAvailability"

CARD_PATTERN = re.compile(
    r"pokemon|pokémon|union arena|one piece|"
    r"yu.gi.oh|magic.the.gathering|lorcana|"
    r"gundam|digimon|dragon ball|"
    r"star wars unlimited|weiss schwarz|"
    r"cardfight|flesh and blood|"
    r"riftbound|shadowverse|"
    r"battle spirits|booster|"
    r"elite trainer box|trading card",
    re.I,
)

EXCLUDED_PATTERN = re.compile(
    r"funko|plush|t-shirt|hoodie|"
    r"controller|headset|"
    r"video game|figurine|"
    r"keychain|poster|"
    r"gift card|"
    r"storage box only",
    re.I,
)


def read_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return default


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def game_for(name):
    text = name.lower()

    games = [
        ("Pokémon", r"pokemon|pokémon"),
        ("Union Arena", r"union arena"),
        ("One Piece", r"one piece"),
        ("Yu-Gi-Oh!", r"yu.gi.oh"),
        ("Magic: The Gathering", r"magic.the.gathering"),
        ("Disney Lorcana", r"lorcana"),
        ("Gundam", r"gundam"),
        ("Digimon", r"digimon"),
        ("Dragon Ball Super", r"dragon ball"),
        ("Star Wars Unlimited", r"star wars unlimited"),
        ("Weiß Schwarz", r"weiss schwarz"),
        ("Cardfight Vanguard", r"cardfight"),
        ("Flesh and Blood", r"flesh and blood"),
        ("Riftbound", r"riftbound"),
        ("Shadowverse", r"shadowverse"),
        ("Battle Spirits Saga", r"battle spirits"),
    ]

    for game, pattern in games:
        if re.search(pattern, text, re.I):
            return game

    return "Other TCG"


def valid_product_url(url):
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme == "https"
            and parsed.hostname in (
                "gamestop.com",
                "www.gamestop.com",
            )
            and parsed.path.endswith(".html")
        )
    except ValueError:
        return False


def discover(page):
    found = {}

    for query in SEARCHES:
        url = (
            BASE
            + "/search/?q="
            + quote(query)
        )

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(2200)

            soup = BeautifulSoup(
                page.content(),
                "html.parser",
            )

            for tile in soup.select("[data-pid]"):
                name = clean(
                    tile.get("data-cnstrc-item-name")
                )

                anchor = tile.select_one(
                    'a[href*=".html"]'
                )

                if not name or anchor is None:
                    continue

                if not CARD_PATTERN.search(name):
                    continue

                if EXCLUDED_PATTERN.search(name):
                    continue

                href = anchor.get("href", "")
                product_url = urljoin(BASE, href)

                if not valid_product_url(product_url):
                    continue

                found[product_url] = {
                    "retailer": "GameStop",
                    "product_name": name,
                    "game": game_for(name),
                    "product_url": product_url,
                    "discovered_at": STAMP,
                }

        except PlaywrightError as error:
            print(
                "Discovery unavailable:",
                query,
                str(error)[:160],
            )

    return list(found.values())


def parse_store_response(payload, product):
    if not isinstance(payload, dict):
        return []

    store_id = clean(payload.get("storeId"))
    store_name = clean(payload.get("storeName"))
    store_details = clean(
        payload.get("storeDetails")
    )

    products = payload.get("products")

    if not isinstance(products, list):
        return []

    if not store_id or not store_name or not store_details:
        return []

    observations = []

    for entry in products:
        if not isinstance(entry, dict):
            continue

        # A missing or non-boolean inStock field is UNKNOWN.
        # Never convert it to False.
        in_stock = entry.get("inStock")

        if type(in_stock) is not bool:
            continue

        observations.append({
            "retailer": "GameStop",
            "store_id": store_id,
            "store_name": store_name,
            "store_address": store_details,
            "product_name": product["product_name"],
            "product_url": product["product_url"],
            "game": product["game"],
            "availability": (
                "In stock"
                if in_stock
                else "Out of stock"
            ),
            "inventory_scope": "store_specific",
            "pickup_confirmed": False,
            "shelf_stock_confirmed": False,
            "evidence_type":
                "gamestop_store_availability_response",
            "checked_at": STAMP,
        })

    return observations


def inspect_product(context, product):
    page = context.new_page()

    captured = {
        "store": [],
        "variation": [],
    }

    def capture(response):
        url = response.url

        if (
            STORE_MARKER not in url
            and VARIATION_MARKER not in url
        ):
            return

        if response.status != 200:
            return

        try:
            payload = response.json()

            if STORE_MARKER in url:
                captured["store"].append(
                    (payload, url)
                )

            elif VARIATION_MARKER in url:
                captured["variation"].append(
                    (payload, url)
                )

        except Exception:
            pass

    page.on("response", capture)

    error_message = None

    try:
        page.goto(
            product["product_url"],
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_timeout(4500)

    except PlaywrightError as error:
        error_message = str(error)[:200]

    finally:
        page.close()

    observations = []

    for payload, evidence_url in captured["store"]:
        rows = parse_store_response(
            payload,
            product,
        )

        for row in rows:
            row["evidence_url"] = evidence_url

        observations.extend(rows)

    # Only a store-specific response can generate
    # store inventory observations.
    # Variation responses describe overall availability.
    return {
        "observations": observations,
        "store_responses": len(captured["store"]),
        "variation_responses": len(
            captured["variation"]
        ),
        "error": error_message,
    }


def fresh(record):
    try:
        dt = datetime.fromisoformat(
            record["checked_at"].replace(
                "Z",
                "+00:00",
            )
        )

        return (
            timedelta(0)
            <= NOW - dt.astimezone(timezone.utc)
            <= timedelta(hours=MAX_AGE_HOURS)
        )

    except (KeyError, ValueError, TypeError):
        return False


def main():
    previous_catalog = read_json(
        CATALOG,
        [],
    )

    previous_records = read_json(
        OUTPUT,
        [],
    )

    previous_report = read_json(
        REPORT,
        {},
    )

    report = {
        "version": "25.0",
        "checked_at": STAMP,
        "retailer": "GameStop",
        "searches_attempted": len(SEARCHES),
        "products_discovered_this_run": 0,
        "products_checked": 0,
        "store_responses": 0,
        "variation_responses": 0,
        "store_observations": 0,
        "in_stock": 0,
        "out_of_stock": 0,
        "near_staunton_confirmed": 0,
        "errors": [],
    }

    discoveries = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        try:
            context = browser.new_context(
                locale="en-US",
                viewport={
                    "width": 1280,
                    "height": 900,
                },
            )

            page = context.new_page()

            discoveries = discover(page)

            page.close()

            report[
                "products_discovered_this_run"
            ] = len(discoveries)

            merged = {}

            for product in previous_catalog:
                if isinstance(product, dict):
                    url = product.get("product_url")

                    if valid_product_url(url):
                        merged[url] = product

            for product in discoveries:
                merged[product["product_url"]] = product

            catalog = list(merged.values())

            write_json(CATALOG, catalog)

            if catalog:
                cursor = int(
                    previous_report.get(
                        "next_cursor",
                        0,
                    )
                ) % len(catalog)
            else:
                cursor = 0

            batch = [
                catalog[
                    (cursor + i) % len(catalog)
                ]
                for i in range(
                    min(MAX_PRODUCTS, len(catalog))
                )
            ]

            report["next_cursor"] = (
                (cursor + len(batch)) % len(catalog)
                if catalog
                else 0
            )

            new_records = []

            for product in batch:
                print(
                    "Checking:",
                    product["product_name"],
                )

                result = inspect_product(
                    context,
                    product,
                )

                report["products_checked"] += 1

                report["store_responses"] += (
                    result["store_responses"]
                )

                report["variation_responses"] += (
                    result["variation_responses"]
                )

                new_records.extend(
                    result["observations"]
                )

                if result["error"]:
                    report["errors"].append({
                        "product": product["product_name"],
                        "error": result["error"],
                    })

            combined = {}

            for row in previous_records + new_records:
                if not isinstance(row, dict):
                    continue

                if not fresh(row):
                    continue

                key = (
                    str(row.get("store_id")),
                    str(row.get("product_url")),
                )

                # New observations replace old ones.
                combined[key] = row

            records = list(combined.values())

            write_json(
                OUTPUT,
                records,
            )

            report["store_observations"] = len(
                records
            )

            report["in_stock"] = sum(
                r["availability"] == "In stock"
                for r in records
            )

            report["out_of_stock"] = sum(
                r["availability"] == "Out of stock"
                for r in records
            )

            # Address matching is deliberately strict.
            # No inferred proximity from runner IP.
            local_cities = (
                "staunton",
                "waynesboro",
                "harrisonburg",
                "charlottesville",
            )

            report["near_staunton_confirmed"] = sum(
                r["availability"] == "In stock"
                and any(
                    city in r["store_address"].lower()
                    for city in local_cities
                )
                and re.search(
                    r"\bVA\b|\bVirginia\b",
                    r["store_address"],
                    re.I,
                ) is not None
                for r in records
            )

            report["catalog_size"] = len(catalog)

            report["note"] = (
                "Availability is reported for the "
                "actual GameStop store returned by "
                "the website. Store-specific availability "
                "does not guarantee pickup or shelf "
                "quantity. Unknown results are omitted."
            )

            write_json(
                REPORT,
                report,
            )

            print(
                json.dumps(
                    report,
                    indent=2,
                )
            )

        finally:
            browser.close()


if __name__ == "__main__":
    main()
