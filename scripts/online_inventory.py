
#!/usr/bin/env python3
"""PokeStock V10.1 - Multi-retailer online inventory.

Checks Kayou product pages and public Shopify
catalogues for selected independent TCG retailers.

Results are ONLINE offers only, not store shelves.
Does not alter status.json or existing catalogue.
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

KAYOU_HOST = "shop.kayouofficial.com"

# Initial independent-retailer integrations.
# Public feed availability is tested each run.
SHOPS = [
    {
        "name": "KnaveTCG",
        "base": "https://knavetcg.com",
    },
    {
        "name": "PixelThat TCG",
        "base": "https://www.pixelthattcg.com",
    },
]

# Keep additional retailer feeds configurable
# without changing the monitoring logic.
SHOP_FILE = DATA / "online_retailers.json"

GAMES = [
    ("Pokémon", [
        "pokemon", "pokémon"
    ]),
    ("Union Arena", [
        "union arena"
    ]),
    ("Gundam", [
        "gundam"
    ]),
    ("One Piece", [
        "one piece"
    ]),
    ("Yu-Gi-Oh!", [
        "yu gi oh", "yugioh"
    ]),
    ("Magic: The Gathering", [
        "magic the gathering", "mtg"
    ]),
    ("Disney Lorcana", [
        "lorcana"
    ]),
    ("Digimon", [
        "digimon"
    ]),
    ("Dragon Ball Super", [
        "dragon ball"
    ]),
    ("Star Wars: Unlimited", [
        "star wars unlimited"
    ]),
    ("Weiß Schwarz", [
        "weiss schwarz", "weiß schwarz"
    ]),
    ("Cardfight!! Vanguard", [
        "cardfight vanguard", "cardfight!! vanguard"
    ]),
    ("Battle Spirits Saga", [
        "battle spirits saga"
    ]),
    ("Shadowverse: Evolve", [
        "shadowverse"
    ]),
    ("Riftbound", [
        "riftbound", "league of legends tcg"
    ]),
    ("Flesh and Blood", [
        "flesh and blood"
    ]),
    ("Altered", [
        "altered tcg"
    ]),
    ("Grand Archive", [
        "grand archive"
    ]),
    ("Final Fantasy TCG", [
        "final fantasy tcg"
    ]),
    ("Sorcery: Contested Realm", [
        "sorcery contested realm"
    ]),
    ("Kayou", [
        "kayou", "naruto collectible",
        "kpop demon hunters collectible",
        "my little pony collectible",
    ]),
]

SEALED = re.compile(
    r"booster|bundle|display|sealed|"
    r"starter deck|trial deck|structure deck|"
    r"elite trainer|etb|collection|"
    r"collector box|gift box|"
    r"blister|tin|card pack|"
    r"battle deck|double pack|"
    r"deck build box|case",
    re.I
)

EXCLUDE = re.compile(
    r"\b(single card|single cards|graded|"
    r"slab|sleeves|playmat|binder|"
    r"toploader|deck box|dice|"
    r"baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl)\b",
    re.I
)

PREORDER = re.compile(
    r"pre[\s-]?order|presale|pre[\s-]?sale|"
    r"coming soon|not yet released",
    re.I
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "PokeStock/10.1 "
        "(public product availability monitor)"
    ),
    "Accept": "application/json,text/html",
})

MAX_AGE = timedelta(hours=8)
KAYOU_BATCH = 25
SHOP_PAGE_SIZE = 100


def read(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write(path, value):
    path.parent.mkdir(
        parents=True, exist_ok=True
    )
    temp = path.with_suffix(
        path.suffix + ".tmp"
    )
    temp.write_text(
        json.dumps(
            value, indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )
    temp.replace(path)


def clean(value):
    return " ".join(
        str(value or "").split()
    )


def norm(value):
    s = clean(value).lower()
    s = s.replace("é", "e").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


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


def get(url, expected_host):
    if host(url) != expected_host:
        raise ValueError("Untrusted request host")

    r = SESSION.get(
        url, timeout=(12, 30),
        allow_redirects=True
    )
    r.raise_for_status()

    if host(r.url) != expected_host:
        raise ValueError("Untrusted redirect")

    if len(r.content) > 8_000_000:
        raise ValueError("Response too large")

    return r


def game_of(title, tags="", vendor=""):
    words = norm(
        " ".join([title, tags, vendor])
    )
    padded = " " + words + " "

    for game, aliases in GAMES:
        for alias in aliases:
            token = " " + norm(alias) + " "
            if token in padded:
                return game

    return ""


def fmt(title):
    n = norm(title)

    if (
        "booster bundle display" in n
        or "booster bundle case" in n
    ):
        return "Booster bundle display case"

    if "booster box case" in n or (
        "sealed case" in n
    ):
        return "Factory-sealed case"

    if "booster bundle" in n:
        return "Booster bundle"

    if (
        "booster box" in n
        or "booster display" in n
    ):
        return "Booster box"

    if "elite trainer box" in n:
        return "Elite Trainer Box"

    if "starter deck" in n:
        return "Starter deck"

    if "booster pack" in n:
        return "Booster pack"

    if "tin" in n.split():
        return "Tin"

    if "collection" in n:
        return "Collection"

    return "Sealed TCG product"


def fresh(row):
    try:
        date = datetime.fromisoformat(
            row["checked_at"].replace(
                "Z", "+00:00"
            )
        )
        return (
            timedelta(0)
            <= NOW - date
            <= MAX_AGE
        )
    except (
        TypeError, KeyError, ValueError
    ):
        return False


def schema_nodes(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from schema_nodes(item)
        return

    if not isinstance(payload, dict):
        return

    kind = payload.get("@type", [])
    kinds = (
        kind if isinstance(kind, list)
        else [kind]
    )

    if any(
        str(x).split("/")[-1].lower()
        == "product" for x in kinds
    ):
        yield payload

    for name in (
        "@graph", "mainEntity", "hasVariant"
    ):
        if name in payload:
            yield from schema_nodes(
                payload[name]
            )


def schema_state(value):
    key = str(value or "").split("/")[-1].lower()
    return {
        "instock": "In stock",
        "outofstock": "Out of stock",
        "soldout": "Out of stock",
        "preorder": "Preorder",
        "backorder": "Backorder",
    }.get(key, "Unknown")


def kayou_check(product):
    url = product["url"]
    soup = BeautifulSoup(
        get(url, KAYOU_HOST).text,
        "html.parser"
    )

    found = []

    for tag in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            payload = json.loads(
                tag.string or tag.get_text()
            )
        except (ValueError, TypeError):
            continue

        for node in schema_nodes(payload):
            offers = node.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                if (
                    str(offer.get("@type", ""))
                    .lower() == "aggregateoffer"
                ):
                    continue

                state = schema_state(
                    offer.get("availability")
                )

                if state == "Unknown":
                    continue

                sku = clean(
                    offer.get("sku")
                    or node.get("sku")
                )
                variant = clean(
                    offer.get("name")
                    or offer.get("sku")
                )

                # A single Product-level offer does
                # not prove individual option stock.
                if len(offers) > 1 and not variant:
                    continue

                image = node.get("image")
                if isinstance(image, list):
                    image = next(
                        (
                            x for x in image
                            if isinstance(x, str)
                        ),
                        ""
                    )
                if isinstance(image, dict):
                    image = image.get("url", "")

                if not (
                    isinstance(image, str)
                    and host(image)
                ):
                    meta = soup.find(
                        "meta",
                        attrs={
                            "property": "og:image"
                        }
                    )
                    image = (
                        meta.get("content", "")
                        if meta else ""
                    )

                row = {
                    "product_url": url,
                    "product_name": product["name"],
                    "game": "Kayou",
                    "retailer": "Kayou Official Store",
                    "inventory_scope": "online",
                    "availability": state,
                    "variant": (
                        variant or "Product listing"
                    ),
                    "sku": sku,
                    "format": fmt(product["name"]),
                    "evidence_type":
                        "schema_org_offer",
                    "evidence_url": url,
                    "checked_at": STAMP,
                }

                if isinstance(image, str) and host(image):
                    row["image_candidate"] = image
                    row["image_review_status"] = (
                        "unverified_candidate"
                    )

                if (
                    offer.get("price") not in ("", None)
                    and offer.get("priceCurrency")
                ):
                    row["price"] = str(
                        offer["price"]
                    )
                    row["currency"] = str(
                        offer["priceCurrency"]
                    )

                found.append(row)

    # Prevent duplicates within one product.
    unique = {}
    conflicts = set()

    for row in found:
        key = (
            row["product_url"],
            row["variant"],
            row["sku"],
        )

        if key in unique and (
            unique[key]["availability"]
            != row["availability"]
        ):
            conflicts.add(key)
        else:
            unique[key] = row

    return [
        row for key, row in unique.items()
        if key not in conflicts
    ]


def configured_shops():
    extra = read(SHOP_FILE, [])
    if not isinstance(extra, list):
        raise ValueError(
            "online_retailers.json must be a list"
        )

    result = []
    seen = set()

    for shop in SHOPS + extra:
        if not isinstance(shop, dict):
            continue

        base = clean(
            shop.get("base")
        ).rstrip("/")
        name = clean(shop.get("name"))

        domain = host(base)

        if (
            not domain
            or not name
            or domain in seen
        ):
            continue

        seen.add(domain)
        result.append({
            "name": name,
            "base": base,
            "host": domain,
        })

    return result


def shopify_check(shop, page):
    # Public Shopify catalogue feed.
    # A failure is recorded, not treated as
    # proof that the store has no stock.
    url = (
        shop["base"]
        + "/products.json?limit="
        + str(SHOP_PAGE_SIZE)
        + "&page=" + str(page)
    )

    payload = get(
        url, shop["host"]
    ).json()

    items = (
        payload.get("products")
        if isinstance(payload, dict)
        else None
    )

    if not isinstance(items, list):
        raise ValueError(
            "Not a supported Shopify feed"
        )

    rows = []
    matched = 0

    for item in items:
        title = clean(
            item.get("title")
        )
        tags = item.get("tags", "")
        if isinstance(tags, list):
            tags = " ".join(
                str(x) for x in tags
            )

        vendor = clean(
            item.get("vendor")
        )

        game = game_of(
            title, str(tags), vendor
        )

        if (
            not game
            or not SEALED.search(title)
            or EXCLUDE.search(title)
        ):
            continue

        handle = clean(
            item.get("handle")
        )

        if not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            handle
        ):
            continue

        matched += 1
        product_url = (
            shop["base"]
            + "/products/"
            + quote(handle)
        )

        variants = item.get("variants", [])
        if not isinstance(variants, list):
            continue

        image = (
            item.get("images") or []
        )
        picture = ""

        if (
            isinstance(image, list)
            and image
            and isinstance(image[0], dict)
        ):
            picture = clean(
                image[0].get("src")
            )

        for variant in variants:
            if not isinstance(variant, dict):
                continue

            available = variant.get(
                "available"
            )

            # No guess when Shopify does not
            # explicitly supply availability.
            if not isinstance(available, bool):
                continue

            variant_name = clean(
                variant.get("title")
            )

            if variant_name.lower() == "default title":
                variant_name = "Product listing"

            combined_name = (
                title + " " + variant_name
            )

            # Available preorders must never
            # appear as immediately in stock.
            state = (
                "Preorder"
                if PREORDER.search(combined_name)
                else "In stock"
                if available
                else "Out of stock"
            )

            row = {
                "product_url": product_url,
                "product_name": title,
                "game": game,
                "retailer": shop["name"],
                "inventory_scope": "online",
                "availability": state,
                "variant": (
                    variant_name
                    or "Product listing"
                ),
                "sku": clean(
                    variant.get("sku")
                ),
                "format": fmt(combined_name),
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
                row["currency"] = "USD"

            rows.append(row)

    return rows, len(items), matched


def offer_key(row):
    return (
        row.get("retailer"),
        row.get("product_url"),
        row.get("variant"),
        row.get("sku"),
    )


def main():
    catalogue = read(STATUS, {})
    products = catalogue.get("products", [])

    if not isinstance(products, list):
        raise ValueError(
            "Invalid existing catalogue"
        )

    candidates = sorted(
        [
            p for p in products
            if (
                isinstance(p, dict)
                and host(p.get("url"))
                == KAYOU_HOST
                and p.get("name")
            )
        ],
        key=lambda x: x["url"]
    )

    previous = read(OFFERS, [])
    if not isinstance(previous, list):
        raise ValueError(
            "Invalid previous offer file"
        )

    old_report = read(REPORT, {})
    cursor = int(
        old_report.get("next_cursor", 0)
    )

    chosen = [
        candidates[
            (cursor + i) % len(candidates)
        ]
        for i in range(
            min(KAYOU_BATCH, len(candidates))
        )
    ] if candidates else []

    observations = []
    checks = []
    checked_urls = set()

    for product in chosen:
        url = product["url"]
        checked_urls.add(
            ("Kayou Official Store", url)
        )

        try:
            rows = kayou_check(product)
            observations.extend(rows)
            checks.append({
                "retailer": "Kayou Official Store",
                "status": (
                    "verified_online_evidence"
                    if rows
                    else "no_explicit_evidence"
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

    shops = configured_shops()

    # Check one public catalogue page per shop
    # on each scheduled execution.
    pages = old_report.get(
        "shop_next_pages", {}
    )
    if not isinstance(pages, dict):
        pages = {}

    new_pages = {}

    for shop in shops[:15]:
        name = shop["name"]
        page = max(
            1, int(
                pages.get(
                    shop["host"], 1
                )
            )
        )

        try:
            rows, count, matched = (
                shopify_check(shop, page)
            )

            observations.extend(rows)

            # Only clear earlier records for
            # products that appeared in this feed.
            for row in rows:
                checked_urls.add((
                    name, row["product_url"]
                ))

            new_pages[shop["host"]] = (
                page + 1
                if count == SHOP_PAGE_SIZE
                else 1
            )

            checks.append({
                "retailer": name,
                "status": "ok",
                "page": page,
                "feed_items": count,
                "matching_products": matched,
                "offers": len(rows),
            })
        except Exception as error:
            new_pages[shop["host"]] = page
            checks.append({
                "retailer": name,
                "status": "error",
                "page": page,
                "reason": str(error)[:140],
            })

    combined = {}

    for row in previous:
        if (
            not isinstance(row, dict)
            or not fresh(row)
            or (
                row.get("retailer"),
                row.get("product_url")
            ) in checked_urls
        ):
            continue

        combined[offer_key(row)] = row

    for row in observations:
        combined[offer_key(row)] = row

    final = list(combined.values())

    next_cursor = (
        (cursor + len(chosen))
        % len(candidates)
        if candidates else 0
    )

    report = {
        "version": "10.1",
        "checked_at": STAMP,
        "candidate_products": len(candidates),
        "checked_this_run": len(chosen),
        "retailers_integrated": [
            "Kayou Official Store"
        ] + [
            s["name"] for s in shops[:15]
        ],
        "offers_with_explicit_evidence":
            len(observations),
        "total_fresh_offers": len(final),
        "next_cursor": next_cursor,
        "shop_next_pages": new_pages,
        "checks": checks,
        "physical_store_stock_claims": 0,
    }

    write(OFFERS, final)
    write(REPORT, report)

    print("=== POKESTOCK V10.1 ===")
    print("Kayou pages:", len(chosen))
    print("Retailers attempted:", len(shops))
    print("New offers:", len(observations))
    print("Fresh offers:", len(final))

    for item in checks:
        print(
            item["retailer"],
            item["status"],
            item.get("offers", 0),
            item.get("reason", ""),
            flush=True,
        )


if __name__ == "__main__":
    main()
