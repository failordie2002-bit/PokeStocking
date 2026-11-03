
#!/usr/bin/env python3
"""PokeStock V9.1 Universal TCG Catalogue.

- Gundam: all official catalogue pages
- Kayou: official storefront products
- Other TCGs: rotating official catalogue sources
- Preserves products, releases and inventory
- Never invents stock or sealed case formats
- Excludes sports cards
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "status.json"
STAMP = datetime.now(timezone.utc).isoformat()

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "PokeStock/9.1 "
        "(https://github.com/"
        "failordie2002-bit/PokeStocking)"
    )
})

GUNDAM = (
    "https://www.gundam-gcg.com/en/products/list.php"
)

KAYOU = "https://shop.kayouofficial.com"

OTHER_SOURCES = [
    ("Union Arena",
     "https://www.unionarena-tcg.com/na/products/",
     "/na/products/"),
    ("One Piece",
     "https://en.onepiece-cardgame.com/products/",
     "/products/"),
    ("Yu-Gi-Oh!",
     "https://www.yugioh-card.com/en/products/",
     "/en/products/"),
    ("Magic: The Gathering",
     "https://magic.wizards.com/en/products",
     "/en/products/"),
    ("Digimon",
     "https://world.digimoncard.com/products/",
     "/products/"),
    ("Weiß Schwarz",
     "https://en.ws-tcg.com/products/",
     "/products/"),
    ("Cardfight!! Vanguard",
     "https://en.cf-vanguard.com/products/",
     "/products/"),
    ("Shadowverse: Evolve",
     "https://en.shadowverse-evolve.com/products/",
     "/products/"),
]

ALL_GAMES = [
    "Pokémon",
    "Union Arena",
    "Gundam",
    "One Piece",
    "Yu-Gi-Oh!",
    "Magic: The Gathering",
    "Disney Lorcana",
    "Digimon",
    "Dragon Ball Super",
    "Star Wars: Unlimited",
    "Weiß Schwarz",
    "Cardfight!! Vanguard",
    "Battle Spirits Saga",
    "Shadowverse: Evolve",
    "Riftbound",
    "Flesh and Blood",
    "Altered",
    "Grand Archive",
    "Final Fantasy TCG",
    "Sorcery: Contested Realm",
    "Kayou",
]

KAYOU_LINES = [
    "Naruto",
    "Demon Slayer",
    "My Little Pony",
    "KPop Demon Hunters",
    "Winx Club",
    "tokidoki",
]

PRODUCT_TERMS = re.compile(
    r"booster|starter|trial deck|structure deck|"
    r"battle deck|collection|card set|"
    r"bundle|sealed|display|tin|"
    r"collector box|gift box|blister|"
    r"trading cards|card game",
    re.I
)

ACCESSORIES = re.compile(
    r"sleeves?|playmat|binder|storage case|"
    r"card case|deck box|dice|"
    r"damage counter|accessories",
    re.I
)

SPORTS = re.compile(
    r"\b(?:baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl|"
    r"nascar|motorsport)\b",
    re.I
)

DATE = re.compile(
    r"Release Date\s*"
    r"([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.I
)

CODE = re.compile(
    r"\[([A-Z]{2,5}[-]?\d{1,3}[A-Z]?)\]",
    re.I
)


def clean(value):
    return " ".join(str(value or "").split())


def norm(value):
    return re.sub(
        r"[^a-z0-9]+", " ",
        clean(value).lower().replace("é", "e")
    ).strip()


def safe_url(value):
    try:
        parsed = urlparse(str(value))
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def fetch(url):
    if not safe_url(url):
        raise ValueError("HTTPS URL required")

    response = SESSION.get(
        url, timeout=(15, 35)
    )
    response.raise_for_status()

    if not safe_url(response.url):
        raise ValueError("Unsafe redirect")

    if len(response.content) > 8000000:
        raise ValueError("Response too large")

    return response


def load():
    return json.loads(
        STATUS.read_text(encoding="utf-8")
    )


def save(value):
    temp = STATUS.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(
            value, ensure_ascii=False, indent=2
        ),
        encoding="utf-8"
    )
    temp.replace(STATUS)


def classify(name, code=""):
    n = norm(name)
    code = code.upper()

    if "booster bundle display" in n:
        return "Booster bundle display case"

    if "booster bundle case" in n:
        return "Booster bundle display case"

    if "booster box case" in n:
        return "Booster box case"

    if "booster bundle" in n:
        return "Booster bundle"

    if "booster box" in n or "booster display" in n:
        return "Booster box"

    if "elite trainer box" in n:
        return "Elite Trainer Box"

    if "starter deck" in n or code.startswith("ST"):
        return "Starter deck"

    if "trial deck" in n:
        return "Trial deck"

    if "structure deck" in n:
        return "Structure deck"

    if "battle deck" in n:
        return "Battle deck"

    if "booster pack" in n:
        return "Booster pack"

    if code.startswith(("GD", "EB", "BT")):
        return "Booster pack"

    if "booster" in n:
        return "Booster product"

    if "collection" in n:
        return "Collection"

    if re.search(r"\btin\b", n):
        return "Tin"

    if "deck" in n:
        return "Deck"

    if "card set" in n:
        return "Card set"

    return "Official product"


def image_from(anchor, base):
    image = anchor.find("img")

    if not image:
        return ""

    src = (
        image.get("data-src")
        or image.get("src")
        or ""
    )

    url = urljoin(base, src)

    if (
        not safe_url(url)
        or re.search(
            r"logo|favicon|sprite|placeholder",
            url, re.I
        )
    ):
        return ""

    return url


def new_product(game, name, url, code="",
                image="", source="Official catalogue"):
    entry = {
        "name": clean(name),
        "game": game,
        "type": classify(name, code),
        "url": url,
        "source": source,
        "stock_status": "Not checked",
        "catalogue_checked_at": STAMP,
    }

    if code:
        entry["sku"] = code

    if image:
        entry["image"] = image
        entry["image_review_status"] = (
            "unverified_candidate"
        )

    return entry


def gundam_products():
    results = {}
    errors = []

    # Include page 1 explicitly. Query pagination
    # on the official list.php catalogue.
    for page in range(1, 6):
        url = GUNDAM + "?page=" + str(page)

        try:
            soup = BeautifulSoup(
                fetch(url).text, "html.parser"
            )

            for anchor in soup.select("a[href]"):
                href = urldefrag(urljoin(
                    url, anchor.get("href", "")
                ))[0]

                parsed = urlparse(href)

                # Must be an actual product detail page,
                # never a filter or catalogue index.
                if (
                    parsed.hostname
                    != "www.gundam-gcg.com"
                    or not re.fullmatch(
                        r"/en/products/[A-Za-z0-9_-]+\.html",
                        parsed.path
                    )
                ):
                    continue

                raw = clean(
                    anchor.get_text(" ", strip=True)
                )

                if len(raw) < 8:
                    continue

                if ACCESSORIES.search(raw):
                    # Keep sealed bundles and card sets
                    # if they include actual cards.
                    if not re.search(
                        r"bundle|card set|collection",
                        raw, re.I
                    ):
                        continue

                match = CODE.search(raw)
                code = match.group(1) if match else ""

                slug = parsed.path.split("/")[-1]
                slug = slug.replace(".html", "").upper()

                if not code:
                    prefix = re.match(
                        r"^(ST|GD|EB)\d+",
                        slug
                    )
                    if prefix:
                        code = slug

                # Reject miscellaneous unrelated
                # catalogue entries.
                if not (
                    code
                    or PRODUCT_TERMS.search(raw)
                    or re.search(
                        r"anniversary|edition beta",
                        raw, re.I
                    )
                ):
                    continue

                # Text frequently includes date and MSRP.
                name = re.split(
                    r"\bRelease Date\b|\bMSRP\b",
                    raw, maxsplit=1,
                    flags=re.I
                )[0].strip()

                if not name:
                    continue

                entry = new_product(
                    "Gundam",
                    name,
                    href,
                    code,
                    image_from(anchor, url)
                )

                date_match = DATE.search(raw)

                if date_match:
                    try:
                        from datetime import datetime
                        entry["release_date"] = (
                            datetime.strptime(
                                date_match.group(1),
                                "%B %d, %Y"
                            ).date().isoformat()
                        )
                    except ValueError:
                        pass

                # Official category is supported by
                # Gundam's product-code prefixes.
                if code.upper().startswith("ST"):
                    entry["type"] = "Starter deck"
                elif code.upper().startswith(
                    ("GD", "EB")
                ):
                    entry["type"] = "Booster pack"

                results[href] = entry

        except Exception as error:
            errors.append(
                f"Page {page}: {type(error).__name__}: "
                f"{str(error)[:100]}"
            )

    if not results:
        raise RuntimeError(
            "No Gundam product pages found. "
            + "; ".join(errors)
        )

    return list(results.values()), errors


def generic_products(game, root, prefix):
    soup = BeautifulSoup(
        fetch(root).text, "html.parser"
    )

    hostname = urlparse(root).hostname
    results = {}

    for anchor in soup.select("a[href]"):
        href = urldefrag(urljoin(
            root, anchor.get("href", "")
        ))[0]

        parsed = urlparse(href)

        if (
            not safe_url(href)
            or parsed.hostname != hostname
            or not parsed.path.startswith(prefix)
        ):
            continue

        # Skip indexes, filters and category links.
        if (
            href.rstrip("/") == root.rstrip("/")
            or parsed.path.rstrip("/") == prefix.rstrip("/")
            or re.search(
                r"/(?:list|category|search|tag)/",
                parsed.path, re.I
            )
        ):
            continue

        name = clean(
            anchor.get_text(" ", strip=True)
        )

        if not name:
            img = anchor.find("img")
            name = clean(
                img.get("alt") if img else ""
            )

        if not (8 <= len(name) <= 180):
            continue

        if SPORTS.search(name) or ACCESSORIES.search(name):
            continue

        if not PRODUCT_TERMS.search(name):
            continue

        results[href] = new_product(
            game, name, href,
            image=image_from(anchor, root)
        )

    return list(results.values())


def kayou_line(name):
    n = norm(name)

    for line in KAYOU_LINES:
        if norm(line) in n:
            return line

    return "Other Kayou"


def kayou_products():
    results = {}

    for page in range(1, 4):
        url = (
            KAYOU
            + "/products.json?limit=100&page="
            + str(page)
        )

        payload = fetch(url).json()
        items = payload.get("products", [])

        if not isinstance(items, list):
            raise ValueError("Invalid Kayou response")

        if not items:
            break

        for item in items:
            name = clean(item.get("title"))
            handle = clean(item.get("handle"))

            if (
                not name
                or SPORTS.search(name)
                or ACCESSORIES.search(name)
                or not re.fullmatch(
                    r"[A-Za-z0-9_-]+", handle
                )
            ):
                continue

            if not PRODUCT_TERMS.search(name):
                continue

            url = (
                KAYOU + "/products/" + handle
            )

            entry = new_product(
                "Kayou", name, url,
                source="Official Kayou storefront"
            )

            entry["publisher"] = "Kayou"
            entry["franchise"] = kayou_line(name)

            images = item.get("images") or []

            if (
                images
                and isinstance(images[0], dict)
                and safe_url(images[0].get("src"))
            ):
                entry["image"] = images[0]["src"]
                entry["image_review_status"] = (
                    "unverified_candidate"
                )

            results[url] = entry

    return list(results.values())


def product_key(item):
    return (
        norm(item.get("game")),
        item.get("url")
        or item.get("sku")
        or norm(item.get("name"))
    )


def merge_products(existing, incoming):
    output = {
        product_key(item): dict(item)
        for item in existing
        if isinstance(item, dict)
    }

    added = 0
    updated = 0

    for item in incoming:
        key = product_key(item)

        if key not in output:
            output[key] = {
                **item,
                "first_seen": STAMP
            }
            added += 1
            continue

        old = output[key]

        # Prevent losing verified availability,
        # curated photographs and historical data.
        protected = {
            "first_seen",
            "product_image",
            "online_stock_status",
            "store_inventory",
            "image_review_status",
        }

        changed = False

        for field, value in item.items():
            if field in protected:
                continue

            if field == "image" and old.get("image"):
                continue

            if value not in ("", None, []):
                if old.get(field) != value:
                    old[field] = value
                    changed = True

        if changed:
            updated += 1

    return list(output.values()), added, updated


def check(label, function):
    try:
        products, errors = function()
        return products, {
            "game": label,
            "status": (
                "partial" if errors
                else "ok" if products
                else "no_matching_products"
            ),
            "products_found": len(products),
            "errors": errors,
            "checked_at": STAMP,
        }
    except Exception as error:
        return [], {
            "game": label,
            "status": "error",
            "products_found": 0,
            "error": (
                type(error).__name__
                + ": " + str(error)[:180]
            ),
            "checked_at": STAMP,
        }


def main():
    db = load()

    if (
        not isinstance(db, dict)
        or not isinstance(db.get("products"), list)
        or not isinstance(db.get("releases"), list)
    ):
        raise ValueError(
            "Invalid existing catalogue; refusing overwrite"
        )

    before = len(db["products"])
    releases_before = len(db["releases"])

    discovered = []
    reports = []

    # Always check Gundam and Kayou.
    for game, function in [
        ("Gundam", gundam_products),
        ("Kayou", lambda: (kayou_products(), [])),
    ]:
        products, report = check(game, function)
        discovered.extend(products)
        reports.append(report)

    # Rotate two additional publisher sources
    # per run to keep execution lightweight.
    cursor = int(db.get("v91_source_cursor", 0))

    for offset in range(2):
        game, root, prefix = OTHER_SOURCES[
            (cursor + offset) % len(OTHER_SOURCES)
        ]

        products, report = check(
            game,
            lambda g=game, r=root, p=prefix:
                (generic_products(g, r, p), [])
        )

        discovered.extend(products)
        reports.append(report)

    merged, added, updated = merge_products(
        db["products"], discovered
    )

    if len(merged) < before:
        raise RuntimeError("Product count decreased")

    if len(db["releases"]) < releases_before:
        raise RuntimeError("Release count decreased")

    db["products"] = merged
    db["v91_source_cursor"] = (
        cursor + 2
    ) % len(OTHER_SOURCES)

    db["v9_catalogue"] = {
        "version": "9.1",
        "updated_at": STAMP,
        "games_registered": ALL_GAMES,
        "kayou_lines": KAYOU_LINES,
        "sports_cards_excluded": True,
        "source_checks": reports,
        "products_discovered_this_run": len(discovered),
        "products_added_this_run": added,
        "products_updated_this_run": updated,
        "total_products": len(merged),
        "total_releases": len(db["releases"]),
        "stock_claims_created": 0,
    }

    save(db)

    print("=== POKESTOCK V9.1 ===")
    print("Products before:", before)
    print("Products after:", len(merged))
    print("New products:", added)
    print("Updated products:", updated)
    print("Releases preserved:", len(db["releases"]))

    for report in reports:
        print(
            report["game"],
            report["status"],
            report["products_found"]
        )


if __name__ == "__main__":
    main()
