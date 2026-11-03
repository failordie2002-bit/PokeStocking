
#!/usr/bin/env python3
"""PokeStock V9.2 — Universal Catalogue.

Repairs Kayou discovery using official Shoplazza
collection pages rather than Shopify JSON.

Preserves previous products, releases, images,
verified inventory, and historical fields.

Automatically checks Gundam, Kayou and two
additional publisher sources per run.

Never fabricates stock availability.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import (
    urljoin, urlparse, urldefrag, urlencode
)

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "status.json"
STAMP = datetime.now(timezone.utc).isoformat()

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "PokeStock/9.2 "
        "(https://github.com/"
        "failordie2002-bit/PokeStocking)"
    )
})

GUNDAM = (
    "https://www.gundam-gcg.com/"
    "en/products/list.php"
)

KAYOU = "https://shop.kayouofficial.com"

OTHER_SOURCES = [
    (
        "Union Arena",
        "https://www.unionarena-tcg.com/na/products/",
        "/na/products/"
    ),
    (
        "One Piece",
        "https://en.onepiece-cardgame.com/products/",
        "/products/"
    ),
    (
        "Yu-Gi-Oh!",
        "https://www.yugioh-card.com/en/products/",
        "/en/products/"
    ),
    (
        "Magic: The Gathering",
        "https://magic.wizards.com/en/products",
        "/en/products/"
    ),
    (
        "Digimon",
        "https://world.digimoncard.com/products/",
        "/products/"
    ),
    (
        "Weiß Schwarz",
        "https://en.ws-tcg.com/products/",
        "/products/"
    ),
    (
        "Cardfight!! Vanguard",
        "https://en.cf-vanguard.com/products/",
        "/products/"
    ),
    (
        "Shadowverse: Evolve",
        "https://en.shadowverse-evolve.com/products/",
        "/products/"
    ),
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
    r"battle deck|collection|collectible|card set|"
    r"bundle|sealed|display|tin|"
    r"collector box|gift box|blister|"
    r"trading cards|card game|card pack|"
    r"packs box|boxes case",
    re.I,
)

ACCESSORIES = re.compile(
    r"card sleeves?|playmat|binder|"
    r"deck case|deck box|dice|"
    r"damage counter|acrylic stand|"
    r"keychain|t-shirt|plush toy",
    re.I,
)

SPORTS = re.compile(
    r"\b(?:baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl|"
    r"nascar|motorsport)\b",
    re.I,
)

CODE = re.compile(
    r"\[([A-Z]{2,5}-?\d{1,3}[A-Z]?)\]",
    re.I,
)

DATE = re.compile(
    r"Release Date\s*"
    r"([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.I,
)


def clean(value):
    return " ".join(
        str(value or "").split()
    )


def norm(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        clean(value).lower()
        .replace("é", "e")
        .replace("ß", "ss")
    ).strip()


def safe_url(value):
    try:
        parsed = urlparse(
            str(value or "")
        )
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
        raise ValueError(
            "HTTPS URL required"
        )

    response = SESSION.get(
        url,
        timeout=(15, 35),
        allow_redirects=True,
    )

    response.raise_for_status()

    if not safe_url(response.url):
        raise ValueError(
            "Unsafe redirect"
        )

    if len(response.content) > 8_000_000:
        raise ValueError(
            "Response too large"
        )

    return response


def load():
    data = json.loads(
        STATUS.read_text(
            encoding="utf-8"
        )
    )

    if (
        not isinstance(data, dict)
        or not isinstance(
            data.get("products"), list
        )
        or not isinstance(
            data.get("releases"), list
        )
    ):
        raise ValueError(
            "Invalid catalogue; "
            "refusing overwrite"
        )

    return data


def save(data):
    temp = STATUS.with_suffix(
        ".json.tmp"
    )

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(STATUS)


def classify(name, code=""):
    n = norm(name)
    code = code.upper()

    if (
        "booster bundle display case" in n
        or "booster bundle case" in n
        or "booster bundle display" in n
    ):
        return "Booster bundle display case"

    if (
        "sealed case" in n
        or "boxes case" in n
        or "booster box case" in n
    ):
        return "Factory-sealed case"

    if "booster bundle" in n:
        return "Booster bundle"

    if (
        "booster box" in n
        or "booster display" in n
        or re.search(
            r"\d+ (?:foil |blister )?"
            r"packs box", n
        )
    ):
        return "Booster box"

    if "elite trainer box" in n:
        return "Elite Trainer Box"

    if (
        "starter deck" in n
        or code.startswith("ST")
    ):
        return "Starter deck"

    if "trial deck" in n:
        return "Trial deck"

    if "structure deck" in n:
        return "Structure deck"

    if "battle deck" in n:
        return "Battle deck"

    if (
        "booster pack" in n
        or code.startswith(
            ("GD", "EB", "BT")
        )
    ):
        return "Booster pack"

    if "booster" in n:
        return "Booster product"

    if (
        "collector box" in n
        or "collection" in n
    ):
        return "Collection"

    if re.search(r"\btin\b", n):
        return "Tin"

    if "deck" in n:
        return "Deck"

    if "card set" in n:
        return "Card set"

    return "Official card product"


def candidate_image(element, base):
    image = element.find("img")

    if not image:
        return ""

    src = (
        image.get("data-src")
        or image.get("data-original")
        or image.get("src")
        or ""
    )

    if (
        not src
        and image.get("srcset")
    ):
        src = (
            image["srcset"]
            .split(",")[0]
            .strip()
            .split(" ")[0]
        )

    url = urljoin(base, src)

    if (
        not safe_url(url)
        or re.search(
            r"logo|favicon|placeholder|sprite",
            url,
            re.I
        )
    ):
        return ""

    return url


def make_product(
    game,
    name,
    url,
    code="",
    image="",
    source="Official catalogue",
):
    result = {
        "name": clean(name),
        "game": game,
        "type": classify(name, code),
        "url": url,
        "source": source,
        "stock_status": "Not checked",
        "catalogue_checked_at": STAMP,
    }

    if code:
        result["sku"] = code

    if image:
        result["image"] = image
        result["image_review_status"] = (
            "unverified_candidate"
        )

    return result


def gundam_products():
    products = {}
    errors = []

    for page in range(1, 6):
        url = GUNDAM + "?page=" + str(page)

        try:
            soup = BeautifulSoup(
                fetch(url).text,
                "html.parser"
            )

            for anchor in soup.select(
                "a[href]"
            ):
                href = urldefrag(
                    urljoin(
                        url,
                        anchor["href"]
                    )
                )[0]

                parsed = urlparse(href)

                if (
                    parsed.hostname
                    != "www.gundam-gcg.com"
                    or not re.fullmatch(
                        r"/en/products/"
                        r"[A-Za-z0-9_-]+\.html",
                        parsed.path
                    )
                ):
                    continue

                raw = clean(
                    anchor.get_text(
                        " ", strip=True
                    )
                )

                if len(raw) < 8:
                    continue

                if (
                    ACCESSORIES.search(raw)
                    and not re.search(
                        r"bundle|card set|collection",
                        raw, re.I
                    )
                ):
                    continue

                match = CODE.search(raw)
                code = (
                    match.group(1)
                    if match else ""
                )

                slug = (
                    parsed.path
                    .split("/")[-1]
                    .replace(".html", "")
                    .upper()
                )

                if not code and re.match(
                    r"^(ST|GD|EB)\d+",
                    slug
                ):
                    code = slug

                if not (
                    code
                    or PRODUCT_TERMS.search(raw)
                    or re.search(
                        r"anniversary|edition beta",
                        raw, re.I
                    )
                ):
                    continue

                name = re.split(
                    r"\bRelease Date\b|\bMSRP\b",
                    raw,
                    maxsplit=1,
                    flags=re.I
                )[0].strip()

                if not name:
                    continue

                result = make_product(
                    "Gundam",
                    name,
                    href,
                    code,
                    candidate_image(
                        anchor, url
                    )
                )

                date_match = DATE.search(
                    raw
                )

                if date_match:
                    try:
                        result["release_date"] = (
                            datetime.strptime(
                                date_match.group(1),
                                "%B %d, %Y"
                            ).date().isoformat()
                        )
                    except ValueError:
                        pass

                products[href] = result

        except Exception as error:
            errors.append(
                f"Page {page}: "
                f"{type(error).__name__}: "
                f"{str(error)[:100]}"
            )

    if not products:
        raise RuntimeError(
            "No Gundam products found. "
            + "; ".join(errors)
        )

    return list(products.values()), errors


def kayou_line(name):
    n = norm(name)

    for line in KAYOU_LINES:
        if norm(line) in n:
            return line

    return "Other Kayou"


def kayou_collections():
    """Find collection URLs from the official shop."""
    soup = BeautifulSoup(
        fetch(KAYOU + "/").text,
        "html.parser"
    )

    results = {
        KAYOU + "/collections/all-items"
    }

    for anchor in soup.select(
        'a[href*="/collections/"]'
    ):
        url = urljoin(
            KAYOU,
            anchor.get("href", "")
        )

        parsed = urlparse(url)

        if (
            parsed.hostname
            != "shop.kayouofficial.com"
            or not re.fullmatch(
                r"/collections/[A-Za-z0-9_-]+/?",
                parsed.path
            )
        ):
            continue

        results.add(
            KAYOU + parsed.path.rstrip("/")
        )

    # Limit work and avoid hammering the store.
    return sorted(results)[:16]


def kayou_name(anchor):
    """Extract a real title, never a price or button."""
    candidates = []

    text = clean(
        anchor.get_text(
            " ", strip=True
        )
    )

    if text:
        candidates.append(text)

    title = clean(
        anchor.get("title")
    )

    if title:
        candidates.append(title)

    image = anchor.find("img")

    if image:
        alt = clean(image.get("alt"))
        if alt:
            candidates.append(alt)

    # Some themes put title and photo in
    # separate anchors within one product card.
    parent = anchor.parent

    for _ in range(3):
        if not parent:
            break

        heading = parent.find(
            ["h2", "h3", "h4"]
        )

        if heading:
            candidates.append(
                clean(
                    heading.get_text(
                        " ", strip=True
                    )
                )
            )

        parent = parent.parent

    candidates = [
        candidate
        for candidate in candidates
        if (
            8 <= len(candidate) <= 220
            and PRODUCT_TERMS.search(
                candidate
            )
            and not SPORTS.search(
                candidate
            )
            and not ACCESSORIES.search(
                candidate
            )
        )
    ]

    if not candidates:
        return ""

    # Prefer informative product titles.
    candidates.sort(
        key=lambda value: (
            bool(re.search(
                r"naruto|pony|demon|winx|"
                r"tokidoki|collector",
                value, re.I
            )),
            len(value)
        ),
        reverse=True
    )

    return candidates[0]


def kayou_products():
    """Discover actual Kayou Shoplazza product pages."""
    products = {}
    errors = []
    collections = kayou_collections()
    successful_pages = 0

    for collection in collections:
        try:
            soup = BeautifulSoup(
                fetch(collection).text,
                "html.parser"
            )
            successful_pages += 1

            for anchor in soup.select(
                'a[href*="/products/"]'
            ):
                href = urljoin(
                    collection,
                    anchor.get("href", "")
                )

                parsed = urlparse(href)

                if (
                    parsed.hostname
                    != "shop.kayouofficial.com"
                    or not re.fullmatch(
                        r"/products/"
                        r"[A-Za-z0-9_-]+/?",
                        parsed.path
                    )
                ):
                    continue

                href = (
                    KAYOU
                    + parsed.path.rstrip("/")
                )

                name = kayou_name(anchor)

                if not name:
                    continue

                image = candidate_image(
                    anchor, collection
                )

                entry = make_product(
                    "Kayou",
                    name,
                    href,
                    image=image,
                    source="Official Kayou US store"
                )

                entry["publisher"] = "Kayou"
                entry["franchise"] = (
                    kayou_line(name)
                )
                entry["catalogue_method"] = (
                    "Official Shoplazza collection"
                )

                # A separate sealed-case listing
                # is a distinct product.
                if re.search(
                    r"sealed case|boxes case",
                    name, re.I
                ):
                    entry["type"] = (
                        "Factory-sealed case"
                    )

                old = products.get(href)

                if not old:
                    products[href] = entry

                elif (
                    not old.get("image")
                    and image
                ):
                    old["image"] = image
                    old["image_review_status"] = (
                        "unverified_candidate"
                    )

        except Exception as error:
            errors.append(
                collection
                + ": "
                + type(error).__name__
                + ": "
                + str(error)[:100]
            )

    if not products:
        raise RuntimeError(
            "Kayou catalogue returned "
            "no product links. "
            + "; ".join(errors[:3])
        )

    if successful_pages == 0:
        raise RuntimeError(
            "No Kayou collection pages loaded"
        )

    return list(products.values()), errors


def generic_products(game, root, prefix):
    soup = BeautifulSoup(
        fetch(root).text,
        "html.parser"
    )

    hostname = urlparse(root).hostname
    results = {}

    for anchor in soup.select(
        "a[href]"
    ):
        href = urldefrag(
            urljoin(
                root,
                anchor.get("href", "")
            )
        )[0]

        parsed = urlparse(href)

        if (
            not safe_url(href)
            or parsed.hostname != hostname
            or not parsed.path.startswith(
                prefix
            )
        ):
            continue

        if (
            href.rstrip("/")
            == root.rstrip("/")
            or parsed.path.rstrip("/")
            == prefix.rstrip("/")
            or re.search(
                r"/(?:list|category|search|tag)/",
                parsed.path, re.I
            )
        ):
            continue

        name = clean(
            anchor.get_text(
                " ", strip=True
            )
        )

        if not name:
            image = anchor.find("img")
            name = clean(
                image.get("alt")
                if image else ""
            )

        if not (
            8 <= len(name) <= 180
        ):
            continue

        if (
            SPORTS.search(name)
            or ACCESSORIES.search(name)
            or not PRODUCT_TERMS.search(
                name
            )
        ):
            continue

        results[href] = make_product(
            game,
            name,
            href,
            image=candidate_image(
                anchor, root
            )
        )

    return list(results.values()), []


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

    before = len(output)
    updated = 0

    for product in incoming:
        key = product_key(product)

        if key not in output:
            output[key] = {
                **product,
                "first_seen": STAMP
            }
            continue

        old = output[key]
        changed = False

        protected = {
            "first_seen",
            "product_image",
            "online_stock_status",
            "store_inventory",
            "image_review_status",
        }

        for field, value in product.items():
            if field in protected:
                continue

            if (
                field == "image"
                and old.get("image")
            ):
                continue

            if (
                value not in ("", None, [])
                and old.get(field) != value
            ):
                old[field] = value
                changed = True

        if changed:
            updated += 1

    return (
        list(output.values()),
        len(output) - before,
        updated
    )


def check(game, function):
    try:
        products, errors = function()

        report = {
            "game": game,
            "status": (
                "partial"
                if errors
                else "ok"
                if products
                else "no_matching_products"
            ),
            "products_found": len(products),
            "errors": errors[:8],
            "checked_at": STAMP,
        }

        return products, report

    except Exception as error:
        return [], {
            "game": game,
            "status": "error",
            "products_found": 0,
            "error": (
                type(error).__name__
                + ": "
                + str(error)[:180]
            ),
            "checked_at": STAMP,
        }


def main():
    db = load()

    before = len(db["products"])
    releases_before = len(
        db["releases"]
    )

    discovered = []
    reports = []

    # These two catalogues are checked
    # on every run.
    for game, function in [
        ("Gundam", gundam_products),
        ("Kayou", kayou_products),
    ]:
        products, report = check(
            game, function
        )

        discovered.extend(products)
        reports.append(report)

    # Rotate through other publishers.
    cursor = int(
        db.get("v91_source_cursor", 0)
    )

    for offset in range(2):
        game, root, prefix = (
            OTHER_SOURCES[
                (cursor + offset)
                % len(OTHER_SOURCES)
            ]
        )

        products, report = check(
            game,
            lambda g=game, r=root, p=prefix:
                generic_products(g, r, p)
        )

        discovered.extend(products)
        reports.append(report)

    merged, added, updated = (
        merge_products(
            db["products"],
            discovered
        )
    )

    if len(merged) < before:
        raise RuntimeError(
            "Product loss detected"
        )

    if len(
        db["releases"]
    ) < releases_before:
        raise RuntimeError(
            "Release loss detected"
        )

    db["products"] = merged

    db["v91_source_cursor"] = (
        cursor + 2
    ) % len(OTHER_SOURCES)

    db["v9_catalogue"] = {
        "version": "9.2",
        "updated_at": STAMP,
        "games_registered": ALL_GAMES,
        "kayou_lines": KAYOU_LINES,
        "sports_cards_excluded": True,
        "source_checks": reports,
        "products_discovered_this_run": (
            len(discovered)
        ),
        "products_added_this_run": added,
        "products_updated_this_run": updated,
        "total_products": len(merged),
        "total_releases": len(
            db["releases"]
        ),
        "stock_claims_created": 0,
    }

    save(db)

    print("=== POKESTOCK V9.2 ===")
    print("Products before:", before)
    print("Products after:", len(merged))
    print("New products:", added)
    print("Updated products:", updated)
    print(
        "Releases preserved:",
        len(db["releases"])
    )

    for report in reports:
        print(
            report["game"],
            report["status"],
            report["products_found"],
            flush=True
        )


if __name__ == "__main__":
    main()
