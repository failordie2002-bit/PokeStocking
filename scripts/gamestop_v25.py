
#!/usr/bin/env python3
"""PokéStock V26: GameStop product discovery and evidence-only store monitoring.

Drop-in replacement for scripts/gamestop_v25.py, compatible with V25 workflow.
Never equates online availability, HTTP failures, or missing responses with shelf stock.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
BASE = "https://www.gamestop.com"
CATALOG = DATA / "gamestop_products.json"
OUTPUT = DATA / "gamestop_store_inventory.json"
REPORT = DATA / "gamestop_v25_report.json"
NOW = datetime.now(timezone.utc)
STAMP = NOW.isoformat()
MAX_PRODUCTS = max(1, min(100, int(os.getenv("POKESTOCK_MAX_PRODUCTS", "18"))))
MAX_AGE = timedelta(hours=8)
SEARCHES = [
    "pokemon trading card", "union arena", "one piece trading card",
    "yu gi oh cards", "magic the gathering", "lorcana",
    "gundam card game", "digimon card game", "dragon ball super cards",
    "star wars unlimited",
]
CARD = re.compile(
    r"pokemon|pokémon|union arena|one piece|yu[ -]?gi[ -]?oh|magic.{0,5}gathering|"
    r"lorcana|gundam|digimon|dragon ball|star wars unlimited|weiss schwarz|"
    r"cardfight|flesh and blood|riftbound|shadowverse|battle spirits|booster|"
    r"elite trainer box|trading card", re.I,
)
EXCLUDE = re.compile(
    r"funko|plush|t-shirt|hoodie|controller|headset|video game|figurine|"
    r"keychain|poster|gift card|storage box only", re.I,
)
STORE_MARKER = "Stores-ProductDetailStoreAvailability"
VARIATION_MARKER = "Product-Variation"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def tidy(value):
    return " ".join(str(value or "").split())


def valid_url(url):
    if not isinstance(url, str):
        return False
    try:
        p = urlparse(url)
        return (p.scheme == "https" and p.hostname in
                {"gamestop.com", "www.gamestop.com"} and
                p.path.lower().endswith(".html") and not p.username and not p.password)
    except ValueError:
        return False


def game(name):
    for label, pattern in [
        ("Pokémon", r"pokemon|pokémon"), ("Union Arena", r"union arena"),
        ("One Piece", r"one piece"), ("Yu-Gi-Oh!", r"yu[ -]?gi[ -]?oh"),
        ("Magic: The Gathering", r"magic.{0,5}gathering"),
        ("Disney Lorcana", r"lorcana"), ("Gundam", r"gundam"),
        ("Digimon", r"digimon"), ("Dragon Ball Super", r"dragon ball"),
        ("Star Wars Unlimited", r"star wars unlimited"),
        ("Weiß Schwarz", r"weiss schwarz"), ("Cardfight Vanguard", r"cardfight"),
        ("Flesh and Blood", r"flesh and blood"), ("Riftbound", r"riftbound"),
        ("Shadowverse", r"shadowverse"), ("Battle Spirits Saga", r"battle spirits"),
    ]:
        if re.search(pattern, name, re.I):
            return label
    return "Other TCG"


def product(name, url, origin):
    name, url = tidy(name), tidy(url)
    if not valid_url(url) or not CARD.search(name) or EXCLUDE.search(name):
        return None
    return {"retailer": "GameStop", "product_name": name, "game": game(name),
            "product_url": url, "discovered_at": STAMP, "discovery_source": origin}


def seed_catalog():
    """Use known GameStop product links; never reinterpret other retailers' stock."""
    found = {}
    for row in load(CATALOG, []):
        if isinstance(row, dict):
            p = product(row.get("product_name"), row.get("product_url"), "prior_catalog")
            if p:
                found[p["product_url"]] = p
    for filename in ("online_offers.json", "status.json"):
        source = load(DATA / filename, [])
        if isinstance(source, dict):
            source = source.get("products", [])
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            p = product(row.get("product_name") or row.get("name"),
                        row.get("product_url") or row.get("url"), filename)
            if p:
                found.setdefault(p["product_url"], p)
    return found


def discover(page):
    found, diagnostics = {}, []
    for query in SEARCHES:
        url = BASE + "/search/?q=" + quote(query)
        diag = {"query": query, "search_url": url, "product_links": 0,
                "tiles": 0, "accepted": 0}
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1700)
            soup = BeautifulSoup(page.content(), "html.parser")
            diag["http_status"] = response.status if response else None
            diag["final_url"] = page.url
            diag["page_title"] = tidy(soup.title.get_text(" ", strip=True))[:140] if soup.title else ""
            tiles = soup.select("[data-pid]")
            links = soup.select('a[href*=".html"]')
            diag["tiles"] = len(tiles)
            diag["product_links"] = len(links)
            for tile in tiles:
                name = (tile.get("data-cnstrc-item-name") or
                        tile.get("data-name") or tile.get("title"))
                anchor = tile.select_one('a[href*=".html"]')
                if anchor is None:
                    continue
                if not name:
                    name = anchor.get("title") or anchor.get_text(" ", strip=True)
                p = product(name, urljoin(BASE, anchor.get("href", "")), "gamestop_search")
                if p:
                    found[p["product_url"]] = p
                    diag["accepted"] += 1
            # Conservative fallback for changed tile markup.
            for anchor in links:
                name = anchor.get("title") or anchor.get("aria-label") or anchor.get_text(" ", strip=True)
                p = product(name, urljoin(BASE, anchor.get("href", "")), "gamestop_search_link")
                if p:
                    found.setdefault(p["product_url"], p)
            diag["total_accepted_after_fallback"] = len(found)
        except PlaywrightError as exc:
            diag["error"] = str(exc)[:200]
        diagnostics.append(diag)
        print("SEARCH", json.dumps(diag, ensure_ascii=False))
    return found, diagnostics


def parse_store(payload, item, evidence_url):
    if not isinstance(payload, dict):
        return []
    store_id = tidy(payload.get("storeId"))
    store_name = tidy(payload.get("storeName"))
    address = tidy(payload.get("storeDetails"))
    entries = payload.get("products")
    if not all((store_id, store_name, address)) or not isinstance(entries, list):
        return []
    rows = []
    for entry in entries:
        if not isinstance(entry, dict) or type(entry.get("inStock")) is not bool:
            continue
        rows.append({
            "retailer": "GameStop", "store_id": store_id, "store_name": store_name,
            "store_address": address, "product_name": item["product_name"],
            "product_url": item["product_url"], "game": item["game"],
            "availability": "In stock" if entry["inStock"] else "Out of stock",
            "inventory_scope": "store_specific", "pickup_confirmed": False,
            "shelf_stock_confirmed": False,
            "evidence_type": "gamestop_store_availability_response",
            "evidence_url": evidence_url, "checked_at": STAMP,
        })
    return rows


def inspect(context, item):
    page = context.new_page()
    captured = {"store": [], "variation": 0, "http_status": None, "error": None}

    def on_response(response):
        url = response.url
        if STORE_MARKER not in url and VARIATION_MARKER not in url:
            return
        if response.status != 200:
            return
        if VARIATION_MARKER in url:
            captured["variation"] += 1
        if STORE_MARKER in url:
            try:
                captured["store"].append((response.json(), url))
            except (ValueError, PlaywrightError):
                pass

    page.on("response", on_response)
    try:
        response = page.goto(item["product_url"], wait_until="domcontentloaded", timeout=30000)
        captured["http_status"] = response.status if response else None
        page.wait_for_timeout(4500)
    except PlaywrightError as exc:
        captured["error"] = str(exc)[:200]
    finally:
        page.close()
    rows = []
    for payload, url in captured["store"]:
        rows.extend(parse_store(payload, item, url))
    return {"observations": rows, "store_responses": len(captured["store"]),
            "variation_responses": captured["variation"],
            "http_status": captured["http_status"], "error": captured["error"]}


def fresh(row):
    try:
        dt = datetime.fromisoformat(row["checked_at"].replace("Z", "+00:00"))
        age = NOW - dt.astimezone(timezone.utc)
        return timedelta(0) <= age <= MAX_AGE
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def main():
    previous_report = load(REPORT, {})
    previous_rows = load(OUTPUT, [])
    if not isinstance(previous_report, dict):
        previous_report = {}
    if not isinstance(previous_rows, list):
        previous_rows = []
    report = {"version": "25.0", "engine_version": "26.0", "checked_at": STAMP,
              "retailer": "GameStop", "searches_attempted": len(SEARCHES),
              "products_discovered_this_run": 0, "products_checked": 0,
              "store_responses": 0, "variation_responses": 0,
              "store_observations": 0, "in_stock": 0, "out_of_stock": 0,
              "near_staunton_confirmed": 0, "errors": [], "checks": []}
    catalog = seed_catalog()
    report["catalog_seeded"] = len(catalog)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
            page = context.new_page()
            discovered, diagnostics = discover(page)
            page.close()
            report["discovery_diagnostics"] = diagnostics
            report["products_discovered_this_run"] = len(discovered)
            catalog.update(discovered)
            products = sorted(catalog.values(), key=lambda x: x["product_url"])
            save(CATALOG, products)
            cursor = int(previous_report.get("next_cursor", 0) or 0) % len(products) if products else 0
            batch = [products[(cursor + i) % len(products)]
                     for i in range(min(MAX_PRODUCTS, len(products)))]
            report["next_cursor"] = (cursor + len(batch)) % len(products) if products else 0
            new_rows = []
            for item in batch:
                result = inspect(context, item)
                report["products_checked"] += 1
                report["store_responses"] += result["store_responses"]
                report["variation_responses"] += result["variation_responses"]
                new_rows.extend(result["observations"])
                diag = {"product": item["product_name"], "url": item["product_url"],
                        "http_status": result["http_status"],
                        "store_responses": result["store_responses"],
                        "observations": len(result["observations"])}
                if result["error"]:
                    diag["error"] = result["error"]
                    report["errors"].append(diag)
                report["checks"].append(diag)
                print("CHECK", json.dumps(diag, ensure_ascii=False))
            merged = {}
            for row in previous_rows + new_rows:
                if not isinstance(row, dict) or not fresh(row):
                    continue
                if row.get("availability") not in {"In stock", "Out of stock"}:
                    continue
                if not all(row.get(k) for k in ("store_id", "store_name", "store_address", "product_url", "evidence_url")):
                    continue
                merged[(str(row["store_id"]), row["product_url"])] = row
            records = list(merged.values())
            save(OUTPUT, records)
            report["store_observations"] = len(records)
            report["in_stock"] = sum(r["availability"] == "In stock" for r in records)
            report["out_of_stock"] = sum(r["availability"] == "Out of stock" for r in records)
            report["near_staunton_confirmed"] = sum(
                r["availability"] == "In stock" and
                any(city in r["store_address"].lower() for city in
                    ("staunton", "waynesboro", "harrisonburg", "charlottesville")) and
                re.search(r"\bVA\b|\bVirginia\b", r["store_address"], re.I) is not None
                for r in records)
            report["catalog_size"] = len(products)
            report["integration_verified_this_run"] = report["store_responses"] > 0
            report["integration_status"] = (
                "store_response_captured" if report["integration_verified_this_run"]
                else "unverified_no_store_response")
            report["note"] = (
                "Store-specific availability is not proof of shelf quantity or pickup. "
                "Unknown responses are never converted to out of stock. "
                "A successful workflow is not proof of a working retailer integration.")
            save(REPORT, report)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
