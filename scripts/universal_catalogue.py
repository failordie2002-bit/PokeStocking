#!/usr/bin/env python3
"""PokeStock V9 Universal Catalogue - Phase 1.

Preserves existing data and discovers source-backed
non-sports TCG and collectible card products.

Uses supported official website listings and the
official Kayou Shopify storefront.

Never invents products, stock, or packaging formats.
Additional publisher adapters are added progressively.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATUS = DATA / "status.json"

STAMP = datetime.now(timezone.utc).isoformat()

HEADERS = {
    "User-Agent": (
        "PokeStock/9.0 "
        "(https://github.com/"
        "failordie2002-bit/PokeStocking)"
    )
}

# Every requested game is registered.
# "pending" means that a reliable, tested
# product-specific adapter still needs building.
GAMES = {
    "Pokémon": "active",
    "Union Arena": "active",
    "Gundam": "active",
    "One Piece": "active",
    "Yu-Gi-Oh!": "active",
    "Magic: The Gathering": "active",
    "Disney Lorcana": "pending",
    "Digimon": "active",
    "Dragon Ball Super": "pending",
    "Star Wars: Unlimited": "pending",
    "Weiß Schwarz": "active",
    "Cardfight!! Vanguard": "active",
    "Battle Spirits Saga": "pending",
    "Shadowverse: Evolve": "active",
    "Riftbound": "pending",
    "Flesh and Blood": "pending",
    "Altered": "pending",
    "Grand Archive": "pending",
    "Final Fantasy TCG": "pending",
    "Sorcery: Contested Realm": "pending",
    "Kayou": "active",
}

KAYOU_LINES = [
    "Naruto",
    "Demon Slayer",
    "My Little Pony",
    "KPop Demon Hunters",
    "Winx Club",
    "tokidoki",
]

# URLs verified as official product-catalogue
# entry points. Only eligible product links
# are imported, not every anchor on a page.
SOURCES = [
    {
        "game": "Gundam",
        "url": "https://www.gundam-gcg.com/en/products/list.php",
        "pages": 5,
        "path": "/en/products/",
        "mode": "html",
    },
    {
        "game": "Union Arena",
        "url": "https://www.unionarena-tcg.com/na/products/",
        "pages": 1,
        "path": "/na/products/",
        "mode": "html",
    },
    {
        "game": "One Piece",
        "url": "https://en.onepiece-cardgame.com/products/",
        "pages": 1,
        "path": "/products/",
        "mode": "html",
    },
    {
        "game": "Yu-Gi-Oh!",
        "url": "https://www.yugioh-card.com/en/products/",
        "pages": 1,
        "path": "/en/products/",
        "mode": "html",
    },
    {
        "game": "Magic: The Gathering",
        "url": "https://magic.wizards.com/en/products",
        "pages": 1,
        "path": "/en/products/",
        "mode": "html",
    },
    {
        "game": "Digimon",
        "url": "https://world.digimoncard.com/products/",
        "pages": 1,
        "path": "/products/",
        "mode": "html",
    },
    {
        "game": "Weiß Schwarz",
        "url": "https://en.ws-tcg.com/products/",
        "pages": 1,
        "path": "/products/",
        "mode": "html",
    },
    {
        "game": "Cardfight!! Vanguard",
        "url": "https://en.cf-vanguard.com/products/",
        "pages": 1,
        "path": "/products/",
        "mode": "html",
    },
    {
        "game": "Shadowverse: Evolve",
        "url": "https://en.shadowverse-evolve.com/products/",
        "pages": 1,
        "path": "/products/",
        "mode": "html",
    },
    {
        "game": "Kayou",
        "url": "https://shop.kayouofficial.com/",
        "pages": 3,
        "mode": "kayou",
    },
]

PRODUCT_WORDS = re.compile(
    r"booster|starter|trial deck|structure deck|"
    r"battle deck|deck set|collector box|"
    r"collection|card set|premium set|"
    r"sealed|display|bundle|tin|"
    r"gift box|blister|card pack|"
    r"card game|trading cards",
    re.I,
)

ACCESSORIES = re.compile(
    r"playmat|card sleeve|deck box|"
    r"binder|storage case|"
    r"card case|dice|storage box|"
    r"accessories|merchandise",
    re.I,
)

SPORTS = re.compile(
    r"baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl|"
    r"formula one|nascar|motorsport",
    re.I,
)

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value):
    return " ".join(str(value or "").split())


def normal(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        clean(value).lower()
        .replace("é", "e")
        .replace("ß", "ss")
    ).strip()


def https(url):
    try:
        p = urlparse(str(url))
        return (
            p.scheme == "https"
            and bool(p.hostname)
            and not p.username
            and not p.password
        )
    except ValueError:
        return False


def load(path, default):
    if not path.exists():
        return default
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save(path, value):
    path.parent.mkdir(
        parents=True, exist_ok=True
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


def fetch(url):
    if not https(url):
        raise ValueError("HTTPS required")

    response = SESSION.get(
        url,
        timeout=(15, 35),
        allow_redirects=True
    )
    response.raise_for_status()

    if not https(response.url):
        raise ValueError("Unsafe redirect")

    if len(response.content) > 8_000_000:
        raise ValueError("Response too large")

    return response


def format_type(name):
    n = normal(name)

    formats = [
        ("booster bundle display case",
         "Booster bundle display case"),
        ("booster bundle display",
         "Booster bundle display case"),
        ("booster box case",
         "Booster box case"),
        ("booster display", "Booster box"),
        ("booster box", "Booster box"),
        ("booster bundle", "Booster bundle"),
        ("elite trainer box", "Elite Trainer Box"),
        ("starter deck", "Starter deck"),
        ("trial deck", "Trial deck"),
        ("structure deck", "Structure deck"),
        ("battle deck", "Battle deck"),
        ("booster pack", "Booster pack"),
        ("booster set", "Booster set"),
        ("collector box", "Collector box"),
        ("collection box", "Collection box"),
        ("gift box", "Gift box"),
        ("premium card collection", "Collection"),
        ("collection", "Collection"),
        ("blister", "Blister pack"),
        ("tin", "Tin"),
        ("display case", "Display case"),
        ("deck", "Deck"),
    ]

    for phrase, label in formats:
        if phrase in n:
            return label

    return "Official product listing"


def candidate_name(anchor):
    # Many official catalogues place product names
    # in image alt/title attributes rather than
    # directly inside anchor text.
    candidates = [
        clean(anchor.get_text(" ", strip=True)),
        clean(anchor.get("title")),
    ]

    image = anchor.find("img")
    if image:
        candidates.append(
            clean(image.get("alt"))
        )

    candidates = [
        name for name in candidates
        if 8 <= len(name) <= 200
    ]

    candidates.sort(
        key=lambda name: (
            bool(PRODUCT_WORDS.search(name)),
            len(name)
        ),
        reverse=True
    )

    return candidates[0] if candidates else ""


def image_candidate(anchor, base):
    image = anchor.find("img")
    if not image:
        return ""

    src = (
        image.get("data-src")
        or image.get("src")
        or ""
    )

    url = urljoin(base, src)

    if not https(url):
        return ""

    if re.search(
        r"logo|favicon|sprite|placeholder",
        url,
        re.I
    ):
        return ""

    return url


def html_products(source):
    found = {}
    root = source["url"]
    parsed_root = urlparse(root)

    for page in range(1, source["pages"] + 1):
        url = root

        if source["pages"] > 1:
            url += "?page=" + str(page)

        soup = BeautifulSoup(
            fetch(url).text,
            "html.parser"
        )

        for anchor in soup.select("a[href]"):
            href = urljoin(
                url,
                anchor.get("href", "")
            )
            href = urldefrag(href)[0]

            if not https(href):
                continue

            parsed = urlparse(href)

            if parsed.hostname != parsed_root.hostname:
                continue

            if not parsed.path.startswith(
                source["path"]
            ):
                continue

            if href.rstrip("/") == root.rstrip("/"):
                continue

            name = candidate_name(anchor)

            if not name:
                continue

            if ACCESSORIES.search(name):
                continue

            if SPORTS.search(name):
                continue

            # Specific catalogue links only.
            # Generic category/filter pages are
            # excluded unless named as a product.
            if not PRODUCT_WORDS.search(name):
                continue

            if re.search(
                r"/(category|list|search|news)/",
                parsed.path,
                re.I
            ):
                continue

            image = image_candidate(anchor, url)

            found[href] = {
                "name": name,
                "game": source["game"],
                "type": format_type(name),
                "url": href,
                "stock_status": "Not checked",
                "source": "Official catalogue",
                "catalogue_method":
                    "Official product link",
                "catalogue_checked_at": STAMP,
            }

            if image:
                found[href]["image"] = image
                found[href]["image_review_status"] = (
                    "unverified_candidate"
                )

    return list(found.values())


def kayou_game(name):
    n = normal(name)

    mappings = [
        ("naruto", "Naruto"),
        ("demon slayer", "Demon Slayer"),
        ("my little pony", "My Little Pony"),
        ("kpop demon hunters", "KPop Demon Hunters"),
        ("winx club", "Winx Club"),
        ("tokidoki", "tokidoki"),
    ]

    for token, label in mappings:
        if token in n:
            return label

    return "Other Kayou"


def kayou_products(source):
    base = source["url"].rstrip("/")
    found = {}

    for page in range(1, source["pages"] + 1):
        url = (
            base +
            "/products.json?limit=100&page=" +
            str(page)
        )

        payload = fetch(url).json()
        items = payload.get("products", [])

        if not isinstance(items, list):
            raise ValueError("Invalid Kayou response")

        if not items:
            break

        for item in items:
            title = clean(item.get("title"))

            if not title:
                continue

            if SPORTS.search(title):
                continue

            if ACCESSORIES.search(title):
                continue

            handle = clean(item.get("handle"))

            if not re.fullmatch(
                r"[a-zA-Z0-9_-]+",
                handle
            ):
                continue

            page_url = base + "/products/" + handle

            # Product existence can be established
            # without asserting its stock status.
            images = item.get("images") or []
            photo = ""

            if images and isinstance(images[0], dict):
                photo = clean(images[0].get("src"))

            variants = item.get("variants") or []

            if not variants:
                variants = [None]

            for variant in variants:
                variant = variant or {}

                options = [
                    clean(variant.get("option1")),
                    clean(variant.get("option2")),
                    clean(variant.get("option3")),
                ]

                option_name = " ".join(
                    x for x in options
                    if x and x.lower() != "default title"
                )

                name = (
                    title + " — " + option_name
                    if option_name
                    else title
                )

                if SPORTS.search(name):
                    continue

                if not PRODUCT_WORDS.search(name):
                    continue

                variant_id = variant.get("id")

                product_url = page_url
                if variant_id and str(variant_id).isdigit():
                    product_url += "?variant=" + str(
                        variant_id
                    )

                entry = {
                    "name": name,
                    "game": "Kayou",
                    "publisher": "Kayou",
                    "franchise": kayou_game(title),
                    "type": format_type(name),
                    "url": product_url,
                    "source": "Official Kayou store",
                    "catalogue_checked_at": STAMP,
                    "stock_status": "Not checked",
                    "catalogue_method":
                        "Official storefront product",
                }

                if https(photo):
                    entry["image"] = photo
                    entry["image_review_status"] = (
                        "unverified_candidate"
                    )

                found[product_url] = entry

    return list(found.values())


def record_key(item):
    return (
        normal(item.get("game")),
        item.get("url")
        or item.get("sku")
        or normal(item.get("name"))
    )


def merge_products(existing, incoming):
    merged = {
        record_key(item): dict(item)
        for item in existing
        if isinstance(item, dict)
    }

    new_count = 0

    for product in incoming:
        key = record_key(product)

        if key not in merged:
            product["first_seen"] = STAMP
            merged[key] = product
            new_count += 1
            continue

        old = merged[key]

        # Do not erase previously curated fields
        # or verified packaging photographs.
        protected = {
            "product_image",
            "image_review_status",
            "online_stock_status",
            "store_inventory",
            "first_seen",
        }

        for field, value in product.items():
            if field in protected:
                if field not in old:
                    old[field] = value
            elif value not in ("", None, []):
                if field == "image" and old.get("image"):
                    continue
                old[field] = value

    return list(merged.values()), new_count


def main():
    db = load(
        STATUS,
        {"products": [], "releases": []}
    )

    if not isinstance(db, dict):
        raise ValueError("Invalid status file")

    if not isinstance(db.get("products"), list):
        raise ValueError("Invalid existing products")

    if not isinstance(db.get("releases"), list):
        raise ValueError("Invalid existing releases")

    before = len(db["products"])
    release_before = len(db["releases"])

    # Rotate source checks so each run stays fast.
    cursor = int(db.get("v9_source_cursor", 0))
    batch_size = 3

    chosen = [
        SOURCES[(cursor + i) % len(SOURCES)]
        for i in range(min(batch_size, len(SOURCES)))
    ]

    discovered = []
    checks = []

    for source in chosen:
        game = source["game"]

        try:
            if source["mode"] == "kayou":
                products = kayou_products(source)
            else:
                products = html_products(source)

            discovered.extend(products)

            checks.append({
                "game": game,
                "status": (
                    "ok" if products
                    else "no_matching_products"
                ),
                "products_found": len(products),
                "checked_at": STAMP,
                "source_url": source["url"],
            })

            print(
                game,
                "products parsed:",
                len(products),
                flush=True
            )

        except Exception as error:
            checks.append({
                "game": game,
                "status": "error",
                "error": (
                    type(error).__name__
                    + ": "
                    + str(error)[:180]
                ),
                "checked_at": STAMP,
                "source_url": source["url"],
            })

            print(
                "SOURCE ERROR:",
                game,
                repr(error),
                flush=True
            )

    merged, added = merge_products(
        db["products"],
        discovered
    )

    if len(merged) < before:
        raise RuntimeError(
            "Catalogue shrink detected"
        )

    if len(db["releases"]) < release_before:
        raise RuntimeError(
            "Release data shrink detected"
        )

    db["products"] = merged

    db["v9_source_cursor"] = (
        cursor + len(chosen)
    ) % len(SOURCES)

    db["v9_catalogue"] = {
        "version": "9.0-phase-1",
        "updated_at": STAMP,
        "games_registered": list(GAMES),
        "game_adapter_status": GAMES,
        "kayou_lines": KAYOU_LINES,
        "additional_collectibles":
            "Non-sports licensed cards",
        "sports_cards_excluded": True,
        "source_checks": checks,
        "products_discovered_this_run":
            len(discovered),
        "products_added_this_run": added,
        "total_products": len(merged),
        "total_releases": len(db["releases"]),
        "stock_claims_created": 0,
    }

    save(STATUS, db)

    print("=== POKESTOCK V9 CATALOGUE ===")
    print("Products before:", before)
    print("Products after:", len(merged))
    print("New products:", added)
    print("Releases preserved:", len(db["releases"]))
    print("Verified stock claims created: 0")


if __name__ == "__main__":
    main()
