
#!/usr/bin/env python3
"""PokéStock V10.2 — Evidence-backed retailer stock.

Checks real public Shopify availability and Kayou
product-page offers. Results represent ONLINE
availability, never physical shelf inventory.
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NOW = datetime.now(timezone.utc)
STAMP = NOW.isoformat()

STATUS = DATA / "status.json"
OFFERS = DATA / "online_offers.json"
REPORT = DATA / "online_inventory_report.json"
RETAILERS = DATA / "online_retailers.json"

MAX_AGE = timedelta(hours=8)
KAYOU_BATCH = 20
SHOP_BATCH = 15
SHOP_PAGE_SIZE = 250

DEFAULT_SHOPS = [
    {
        "name": "PixelThat TCG",
        "base": "https://www.pixelthattcg.com",
    },
    {
        "name": "KnaveTCG",
        "base": "https://knavetcg.com",
    },
]

GAMES = [
    ("Pokémon", r"pok[eé]mon"),
    ("Union Arena", r"union[\s-]*arena"),
    ("Gundam", r"gundam"),
    ("One Piece", r"one[\s-]*piece"),
    ("Yu-Gi-Oh!", r"yu[\s-]*gi[\s-]*oh|yugioh"),
    ("Magic: The Gathering",
     r"magic[\s:.-]*the[\s-]*gathering|\bmtg\b"),
    ("Disney Lorcana", r"lorcana"),
    ("Digimon", r"digimon"),
    ("Dragon Ball Super", r"dragon[\s-]*ball"),
    ("Star Wars: Unlimited",
     r"star[\s-]*wars[\s:.-]*unlimited"),
    ("Weiß Schwarz", r"wei(?:ss|ß)[\s-]*schwarz"),
    ("Cardfight!! Vanguard", r"cardfight|vanguard"),
    ("Battle Spirits Saga", r"battle[\s-]*spirits"),
    ("Shadowverse: Evolve", r"shadowverse"),
    ("Riftbound", r"riftbound"),
    ("Flesh and Blood", r"flesh[\s-]*and[\s-]*blood"),
    ("Altered", r"altered[\s-]*tcg"),
    ("Grand Archive", r"grand[\s-]*archive"),
    ("Final Fantasy TCG", r"final[\s-]*fantasy"),
    ("Sorcery: Contested Realm",
     r"sorcery[\s:.-]*contested"),
    ("Kayou",
     r"kayou|naruto|demon[\s-]*slayer|"
     r"my[\s-]*little[\s-]*pony|"
     r"kpop[\s-]*demon[\s-]*hunters|"
     r"winx[\s-]*club|tokidoki"),
]

SEALED = re.compile(
    r"booster|bundle|display|sealed|"
    r"starter[\s-]*deck|trial[\s-]*deck|"
    r"structure[\s-]*deck|battle[\s-]*deck|"
    r"elite[\s-]*trainer|\betb\b|"
    r"collector[\s-]*box|collection[\s-]*box|"
    r"gift[\s-]*box|blister|"
    r"trading[\s-]*card[\s-]*pack|"
    r"\b(?:tin|case)\b",
    re.I,
)

EXCLUDE = re.compile(
    r"single[\s-]*card|graded|slab|"
    r"sleeves|playmat|binder|toploader|"
    r"deck[\s-]*box|dice|figurine|"
    r"\bfigure\b|plush|keychain|acrylic|"
    r"poster|hoodie|shirt|mug|"
    r"blind[\s-]*box|storage[\s-]*box|"
    r"baseball|basketball|football|"
    r"hockey|soccer|\bnfl\b|\bnba\b|"
    r"\bmlb\b|\bnhl\b",
    re.I,
)

PREORDER = re.compile(
    r"pre[\s-]?order|pre[\s-]?sale|"
    r"presale|coming[\s-]*soon",
    re.I,
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "PokeStock/10.2",
    "Accept": "application/json,text/html",
})


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


def host(url):
    try:
        u = urlparse(url)
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
        ):
            return ""
        return u.hostname.lower()
    except (TypeError, ValueError):
        return ""


def fetch(url, expected_host):
    if host(url) != expected_host:
        raise ValueError("Unexpected request host")

    response = SESSION.get(
        url, timeout=(8, 20),
        allow_redirects=False,
    )
    response.raise_for_status()

    if len(response.content) > 8_000_000:
        raise ValueError("Response too large")

    return response


def game_of(title, metadata=""):
    text = title + " " + metadata

    for name, pattern in GAMES:
        if re.search(pattern, text, re.I):
            return name

    return ""


def product_format(title):
    text = clean(title).lower()

    if re.search(
        r"booster bundle.*(?:display|case)|"
        r"(?:display|case).*booster bundle",
        text,
    ):
        return "Booster bundle display case"

    if re.search(
        r"sealed case|factory.sealed case|"
        r"booster box case|case of \d+",
        text,
    ):
        return "Factory-sealed case"

    if "booster bundle" in text:
        return "Booster bundle"

    if re.search(
        r"booster box|booster display",
        text,
    ):
        return "Booster box"

    if "elite trainer" in text:
        return "Elite Trainer Box"

    if "booster pack" in text:
        return "Booster pack"

    if "deck" in text:
        return "Deck"

    if "collection" in text:
        return "Collection"

    return "Sealed TCG product"


def fresh(row):
    try:
        dt = datetime.fromisoformat(
            row["checked_at"].replace("Z", "+00:00")
        )
        return timedelta(0) <= NOW - dt <= MAX_AGE
    except (KeyError, ValueError, TypeError):
        return False


def eligible(title, metadata=""):
    return bool(
        game_of(title, metadata)
        and SEALED.search(title)
        and not EXCLUDE.search(title)
    )


def shop_list():
    configured = load(RETAILERS, [])
    if not isinstance(configured, list):
        raise ValueError("Invalid retailer configuration")

    result = {}
    for item in DEFAULT_SHOPS + configured:
        if not isinstance(item, dict):
            continue

        name = clean(item.get("name"))
        base = clean(item.get("base")).rstrip("/")
        domain = host(base)

        if name and domain:
            result[domain] = {
                "name": name,
                "base": "https://" + domain,
                "host": domain,
            }

    return sorted(
        result.values(),
        key=lambda x: x["host"],
    )


def shopify_check(shop, page):
    url = (
        shop["base"]
        + "/products.json?limit="
        + str(SHOP_PAGE_SIZE)
        + "&page=" + str(page)
    )

    response = fetch(url, shop["host"])
    payload = response.json()
    products = payload.get("products")

    if not isinstance(products, list):
        raise ValueError("No public Shopify products list")

    observations = []
    checked_products = set()
    matching = 0

    for item in products:
        if not isinstance(item, dict):
            continue

        title = clean(item.get("title"))
        tags = item.get("tags") or ""

        if isinstance(tags, list):
            tags = " ".join(map(str, tags))

        metadata = " ".join([
            clean(tags),
            clean(item.get("vendor")),
            clean(item.get("product_type")),
        ])

        if not eligible(title, metadata):
            continue

        handle = clean(item.get("handle"))

        if not re.fullmatch(
            r"[A-Za-z0-9_-]+", handle
        ):
            continue

        game = game_of(title, metadata)
        product_url = (
            shop["base"]
            + "/products/"
            + quote(handle)
        )

        variants = item.get("variants", [])

        if not isinstance(variants, list):
            continue

        matching += 1
        checked_products.add(product_url)

        images = item.get("images") or []
        picture = ""

        if (
            isinstance(images, list)
            and images
            and isinstance(images[0], dict)
        ):
            picture = clean(images[0].get("src"))

        for variant in variants:
            if not isinstance(variant, dict):
                continue

            available = variant.get("available")

            if not isinstance(available, bool):
                continue

            variant_name = clean(
                variant.get("title")
            )

            if variant_name.lower() == "default title":
                variant_name = "Product listing"

            combined = title + " " + variant_name

            # Preorder listings are never labeled
            # immediately available.
            if PREORDER.search(combined):
                availability = (
                    "Preorder" if available
                    else "Out of stock"
                )
            else:
                availability = (
                    "In stock" if available
                    else "Out of stock"
                )

            row = {
                "product_url": product_url,
                "product_name": title,
                "game": game,
                "retailer": shop["name"],
                "inventory_scope": "online",
                "availability": availability,
                "variant": (
                    variant_name or "Product listing"
                ),
                "sku": clean(variant.get("sku")),
                "format": product_format(combined),
                "evidence_type":
                    "shopify_public_variant",
                "evidence_url": product_url,
                "checked_at": STAMP,
            }

            if host(picture):
                row["image_candidate"] = picture
                row["image_review_status"] = (
                    "unverified_candidate"
                )

            price = variant.get("price")
            if price not in (None, ""):
                row["price"] = str(price)
                # Shopify public products feeds do not
                # independently prove store currency.
                row["currency"] = "Unverified"

            observations.append(row)

    return (
        observations,
        len(products),
        matching,
        checked_products,
    )


def product_nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from product_nodes(child)
        return

    if not isinstance(value, dict):
        return

    types = value.get("@type", [])
    if isinstance(types, str):
        types = [types]

    if any(
        str(t).split("/")[-1].lower() == "product"
        for t in types
    ):
        yield value

    for key in ("@graph", "mainEntity", "hasVariant"):
        if key in value:
            yield from product_nodes(value[key])


def kayou_check(product):
    url = product["url"]
    soup = BeautifulSoup(
        fetch(url, "shop.kayouofficial.com").text,
        "html.parser",
    )

    # Do not attach a catalogue name to a
    # different product page. The JSON-LD
    # product name must match sufficiently.
    slug = urlparse(url).path.split("/")[-1]
    expected = clean(product.get("name"))
    observations = []

    for tag in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            payload = json.loads(
                tag.string or tag.get_text()
            )
        except (ValueError, TypeError):
            continue

        for node in product_nodes(payload):
            actual = clean(node.get("name"))

            if not actual:
                continue

            def tokens(value):
                return set(
                    re.findall(
                        r"[a-z0-9]+",
                        value.lower(),
                    )
                )

            a = tokens(actual)
            b = tokens(expected)
            overlap = len(a & b) / max(
                1, len(a | b)
            )

            # Avoid mismatched catalogue records.
            if overlap < 0.35:
                continue

            if not eligible(actual, "Kayou"):
                continue

            offers = node.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                if (
                    str(offer.get("@type", "")).lower()
                    == "aggregateoffer"
                ):
                    continue

                state = str(
                    offer.get("availability") or ""
                ).split("/")[-1].lower()

                availability = {
                    "instock": "In stock",
                    "outofstock": "Out of stock",
                    "preorder": "Preorder",
                    "backorder": "Backorder",
                }.get(state)

                if not availability:
                    continue

                image = node.get("image")
                if isinstance(image, list):
                    image = next(
                        (
                            x for x in image
                            if isinstance(x, str)
                        ),
                        "",
                    )
                elif isinstance(image, dict):
                    image = image.get("url", "")

                row = {
                    "product_url": url,
                    "product_name": actual,
                    "game": "Kayou",
                    "retailer": "Kayou Official Store",
                    "inventory_scope": "online",
                    "availability": availability,
                    "variant": clean(
                        offer.get("name")
                        or offer.get("sku")
                        or "Product listing"
                    ),
                    "sku": clean(
                        offer.get("sku")
                        or node.get("sku")
                    ),
                    "format": product_format(actual),
                    "evidence_type": "schema_org_offer",
                    "evidence_url": url,
                    "checked_at": STAMP,
                }

                if isinstance(image, str) and host(image):
                    row["image_candidate"] = image
                    row["image_review_status"] = (
                        "unverified_candidate"
                    )

                if (
                    offer.get("price") not in (None, "")
                    and offer.get("priceCurrency")
                ):
                    row["price"] = str(
                        offer["price"]
                    )
                    row["currency"] = str(
                        offer["priceCurrency"]
                    )

                observations.append(row)

    return observations


def key(row):
    return (
        row.get("retailer"),
        row.get("product_url"),
        row.get("variant"),
        row.get("sku"),
    )


def main():
    catalogue = load(STATUS, {})
    products = catalogue.get("products", [])

    if not isinstance(products, list):
        raise ValueError("Invalid product catalogue")

    kayou = sorted(
        [
            p for p in products
            if (
                isinstance(p, dict)
                and host(p.get("url"))
                == "shop.kayouofficial.com"
                and p.get("name")
            )
        ],
        key=lambda p: p["url"],
    )

    old_offers = load(OFFERS, [])
    old_report = load(REPORT, {})

    if not isinstance(old_offers, list):
        raise ValueError("Invalid previous offers")

    if not isinstance(old_report, dict):
        old_report = {}

    cursor = int(old_report.get("next_cursor", 0))
    chosen = [
        kayou[(cursor + i) % len(kayou)]
        for i in range(min(KAYOU_BATCH, len(kayou)))
    ] if kayou else []

    observations = []
    checks = []
    checked_products = set()

    for product in chosen:
        url = product["url"]

        try:
            rows = kayou_check(product)
            observations.extend(rows)
            checked_products.add(
                ("Kayou Official Store", url)
            )

            checks.append({
                "retailer": "Kayou Official Store",
                "status": (
                    "verified_online_evidence"
                    if rows else "no_explicit_evidence"
                ),
                "product": product["name"],
                "offers": len(rows),
            })

        except Exception as error:
            checks.append({
                "retailer": "Kayou Official Store",
                "status": "error",
                "product": product["name"],
                "reason": str(error)[:140],
            })

    shops = shop_list()
    pages = old_report.get("shop_next_pages", {})

    if not isinstance(pages, dict):
        pages = {}

    new_pages = dict(pages)

    # Rotate retailer selection so the configured
    # retailer list can grow beyond 15 shops.
    shop_cursor = int(
        old_report.get("shop_cursor", 0)
    )

    selected = [
        shops[(shop_cursor + i) % len(shops)]
        for i in range(min(SHOP_BATCH, len(shops)))
    ] if shops else []

    for shop in selected:
        domain = shop["host"]
        page = max(1, int(pages.get(domain, 1)))

        try:
            rows, count, matched, checked = (
                shopify_check(shop, page)
            )

            observations.extend(rows)

            for url in checked:
                checked_products.add(
                    (shop["name"], url)
                )

            new_pages[domain] = (
                page + 1
                if count == SHOP_PAGE_SIZE
                else 1
            )

            checks.append({
                "retailer": shop["name"],
                "status": "ok",
                "page": page,
                "feed_items": count,
                "matching_products": matched,
                "offers": len(rows),
            })

        except Exception as error:
            checks.append({
                "retailer": shop["name"],
                "status": "error",
                "page": page,
                "reason": str(error)[:140],
            })

    combined = {}

    for row in old_offers:
        if (
            isinstance(row, dict)
            and fresh(row)
            and row.get("inventory_scope") == "online"
            and (
                row.get("retailer"),
                row.get("product_url"),
            ) not in checked_products
            and eligible(
                clean(row.get("product_name")),
                clean(row.get("game")),
            )
        ):
            combined[key(row)] = row

    for row in observations:
        combined[key(row)] = row

    final = sorted(
        combined.values(),
        key=lambda x: (
            x.get("retailer", ""),
            x.get("product_name", ""),
        ),
    )

    report = {
        "version": "10.2",
        "checked_at": STAMP,
        "candidate_products": len(kayou),
        "checked_this_run": len(chosen),
        "retailers_integrated": [
            "Kayou Official Store"
        ] + [s["name"] for s in selected],
        "retailers_checked_this_run": len(selected),
        "retailers_configured": len(shops),
        "offers_with_explicit_evidence":
            len(observations),
        "total_fresh_offers": len(final),
        "next_cursor": (
            (cursor + len(chosen)) % len(kayou)
            if kayou else 0
        ),
        "shop_cursor": (
            (shop_cursor + len(selected)) % len(shops)
            if shops else 0
        ),
        "shop_next_pages": new_pages,
        "checks": checks,
        "physical_store_stock_claims": 0,
    }

    save(OFFERS, final)
    save(REPORT, report)

    print("=== POKESTOCK V10.2 ===")
    print("Retailers configured:", len(shops))
    print("Retailers checked:", len(selected))
    print("Kayou pages checked:", len(chosen))
    print("New online observations:", len(observations))
    print("Fresh online offers:", len(final))

    for check in checks:
        print(
            check["retailer"],
            check["status"],
            check.get("offers", 0),
            check.get("reason", ""),
            flush=True,
        )


if __name__ == "__main__":
    main()
