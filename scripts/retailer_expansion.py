
#!/usr/bin/env python3
"""PokéStock V11.2 — Expanded TCG Retailer Discovery.

Discovers compatible public Shopify feeds from
store websites already in PokéStock's directory.

Supports:
- More website field formats
- More TCG franchises
- Sealed booster boxes, bundles, cases and decks
- Rotating scans across multiple runs
- Persistent registered retailer list
- Evidence-based retailer qualification

Does not verify physical-store inventory.
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

STORES = DATA / "stores.json"
RETAILERS = DATA / "online_retailers.json"
REPORT = DATA / "retailer_discovery_report.json"

STAMP = datetime.now(timezone.utc).isoformat()

MAX_CHECKS = 30
MAX_REGISTERED = 500
MAX_FEED_PRODUCTS = 250
TIMEOUT = (5, 10)

SKIP_DOMAINS = {
    "walmart.com", "target.com",
    "gamestop.com", "bestbuy.com",
    "amazon.com", "ebay.com",
    "costco.com", "samsclub.com",
    "walgreens.com", "cvs.com",
    "dollargeneral.com", "dollartree.com",
    "fivebelow.com", "barnesandnoble.com",
    "facebook.com", "instagram.com",
    "tiktok.com", "x.com", "twitter.com",
    "google.com", "business.site",
    "linktr.ee", "discord.gg",
    "wordpress.com", "wixsite.com",
}

GAME_PATTERNS = [
    r"pok[eé]mon",
    r"union[\s-]*arena",
    r"gundam",
    r"one[\s-]*piece",
    r"yu[\s-]*gi[\s-]*oh",
    r"magic[\s:.-]*the[\s-]*gathering",
    r"\bmtg\b",
    r"lorcana",
    r"digimon",
    r"dragon[\s-]*ball",
    r"star[\s-]*wars[\s:.-]*unlimited",
    r"wei(?:ss|ß)[\s-]*schwarz",
    r"cardfight",
    r"vanguard",
    r"battle[\s-]*spirits",
    r"shadowverse",
    r"riftbound",
    r"flesh[\s-]*and[\s-]*blood",
    r"altered[\s-]*tcg",
    r"grand[\s-]*archive",
    r"final[\s-]*fantasy",
    r"sorcery[\s:.-]*contested",
    r"naruto",
    r"demon[\s-]*slayer",
    r"my[\s-]*little[\s-]*pony",
    r"kpop[\s-]*demon[\s-]*hunters",
    r"winx[\s-]*club",
    r"tokidoki",
    r"\bkayou\b",
]

GAME = re.compile(
    "|".join(GAME_PATTERNS), re.I
)

SEALED = re.compile(
    r"booster[\s-]*(box|pack|bundle|display|case)"
    r"|booster"
    r"|display[\s-]*case"
    r"|factory[\s-]*sealed"
    r"|sealed[\s-]*case"
    r"|starter[\s-]*deck"
    r"|trial[\s-]*deck"
    r"|structure[\s-]*deck"
    r"|battle[\s-]*deck"
    r"|elite[\s-]*trainer"
    r"|collector[\s-]*box"
    r"|collection[\s-]*box"
    r"|trading[\s-]*card[\s-]*pack"
    r"|card[\s-]*box",
    re.I,
)

NON_CARDS = re.compile(
    r"\b(figurine|figure|plush|keychain|"
    r"acrylic|sleeves|binder|playmat|"
    r"poster|shirt|hoodie|mug|"
    r"blind[\s-]*box|storage[\s-]*box)\b",
    re.I,
)

SPORTS = re.compile(
    r"\b(baseball|basketball|football|"
    r"hockey|soccer|nfl|nba|mlb|nhl|"
    r"nascar|sports[\s-]*cards?)\b",
    re.I,
)

STORE_TERMS = re.compile(
    r"card|game|hobby|collectib|comic|"
    r"anime|toy|tcg|trading",
    re.I,
)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "PokeStock/11.2 (+public TCG discovery)",
    "Accept": "application/json",
})


def read_json(path, fallback):
    if not path.exists():
        return fallback
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            data, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def normalize_url(raw):
    value = clean(raw)

    if not value:
        return ""

    if re.search(r"[\s,;]", value):
        return ""

    if value.startswith("http://"):
        value = "https://" + value[7:]

    if "://" not in value:
        value = "https://" + value

    try:
        u = urlparse(value)
        host = (u.hostname or "").lower().rstrip(".")

        if (
            u.scheme != "https"
            or not host
            or u.username
            or u.password
            or u.port not in (None, 443)
        ):
            return ""

        if "." not in host or host == "localhost":
            return ""

        try:
            ipaddress.ip_address(host)
            return ""
        except ValueError:
            pass

        if host.endswith((".local", ".internal")):
            return ""

        for blocked in SKIP_DOMAINS:
            if host == blocked or host.endswith("." + blocked):
                return ""

        return "https://" + host

    except ValueError:
        return ""


def public_dns(host):
    try:
        results = socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM
        )
        if not results:
            return False

        return all(
            ipaddress.ip_address(item[4][0]).is_global
            for item in results
        )
    except (OSError, ValueError):
        return False


def extract_websites(store):
    keys = (
        "website", "url", "website_url",
        "contact_website", "shop_url",
        "online_store", "homepage",
    )

    found = set()

    for key in keys:
        raw = store.get(key)

        if isinstance(raw, list):
            values = raw
        else:
            values = [raw]

        for value in values:
            if not isinstance(value, str):
                continue

            url = normalize_url(value)

            if url:
                found.add(url)

    return sorted(found)


def likely_store(store):
    values = [
        store.get("name"),
        store.get("category"),
        store.get("shop"),
        store.get("shop_type"),
        store.get("retailer_type"),
        store.get("description"),
    ]

    text = " ".join(clean(x) for x in values)

    if SPORTS.search(text) and not GAME.search(text):
        return False

    return bool(STORE_TERMS.search(text))


def candidates(stores):
    found = {}

    for store in stores:
        if not isinstance(store, dict):
            continue

        if not likely_store(store):
            continue

        for base in extract_websites(store):
            host = urlparse(base).hostname

            if host not in found:
                found[host] = {
                    "name": clean(
                        store.get("name") or host
                    ),
                    "base": base,
                    "host": host,
                }

    return sorted(
        found.values(),
        key=lambda x: x["host"],
    )


def qualifies(product):
    if not isinstance(product, dict):
        return False

    title = clean(product.get("title"))
    tags = product.get("tags") or ""
    product_type = clean(product.get("product_type"))

    if isinstance(tags, list):
        tags = " ".join(map(str, tags))

    text = " ".join([
        title, clean(tags), product_type
    ])

    # Require a recognizable game in product metadata
    # and a sealed-card format in the title.
    if not GAME.search(text):
        return False

    if not SEALED.search(title):
        return False

    if NON_CARDS.search(title):
        return False

    if SPORTS.search(title) and not GAME.search(title):
        return False

    return True


def inspect(shop):
    host = shop["host"]

    if not public_dns(host):
        raise ValueError("Not a public DNS destination")

    endpoint = (
        shop["base"]
        + "/products.json?limit="
        + str(MAX_FEED_PRODUCTS)
    )

    response = SESSION.get(
        endpoint,
        timeout=TIMEOUT,
        allow_redirects=False,
        stream=True,
    )

    try:
        if 300 <= response.status_code < 400:
            raise ValueError("Redirect not followed")

        response.raise_for_status()

        chunks = []
        size = 0

        for chunk in response.iter_content(65536):
            size += len(chunk)

            if size > 6_000_000:
                raise ValueError("Feed too large")

            chunks.append(chunk)

        payload = json.loads(b"".join(chunks))

    finally:
        response.close()

    if not isinstance(payload, dict):
        raise ValueError("Invalid Shopify response")

    products = payload.get("products")

    if not isinstance(products, list):
        raise ValueError("Missing products list")

    matches = [
        clean(p.get("title"))
        for p in products
        if qualifies(p)
    ]

    return {
        "supported": bool(matches),
        "feed_products": len(products),
        "matching_products": len(matches),
        "examples": matches[:3],
    }


def main():
    stores = read_json(STORES, [])

    if not isinstance(stores, list):
        raise ValueError("stores.json must be a list")

    existing = read_json(RETAILERS, [])

    if not isinstance(existing, list):
        raise ValueError(
            "online_retailers.json must be a list"
        )

    previous = read_json(REPORT, {})
    pool = candidates(stores)

    cursor = int(previous.get("next_cursor", 0))
    selected = []

    for offset in range(min(MAX_CHECKS, len(pool))):
        selected.append(
            pool[(cursor + offset) % len(pool)]
        )

    registered = {}

    for item in existing:
        if not isinstance(item, dict):
            continue

        base = normalize_url(item.get("base"))

        if not base:
            continue

        host = urlparse(base).hostname

        registered[host] = {
            "name": clean(item.get("name") or host),
            "base": base,
        }

    checks = []
    added = 0

    for shop in selected:
        host = shop["host"]

        if host in registered:
            checks.append({
                "name": shop["name"],
                "status": "already_registered",
            })
            continue

        try:
            result = inspect(shop)

            if (
                result["supported"]
                and len(registered) < MAX_REGISTERED
            ):
                registered[host] = {
                    "name": shop["name"],
                    "base": shop["base"],
                }

                added += 1
                status = "registered"

            else:
                status = "not_eligible"

            checks.append({
                "name": shop["name"],
                "host": host,
                "status": status,
                **result,
            })

        except Exception as error:
            checks.append({
                "name": shop["name"],
                "host": host,
                "status": "error",
                "reason": (
                    type(error).__name__
                    + ": " + str(error)[:130]
                ),
            })

    next_cursor = (
        (cursor + len(selected)) % len(pool)
        if pool else 0
    )

    output = sorted(
        registered.values(),
        key=lambda x: x["name"].lower(),
    )

    report = {
        "version": "11.2",
        "checked_at": STAMP,
        "total_store_records": len(stores),
        "candidate_retailer_websites": len(pool),
        "checked_this_run": len(selected),
        "new_retailers_registered": added,
        "total_registered_retailers": len(output),
        "next_cursor": next_cursor,
        "checks": checks,
        "inventory_scope": "online_only",
        "physical_store_stock_claims": 0,
    }

    write_json(RETAILERS, output)
    write_json(REPORT, report)

    print("=== POKESTOCK V11.2 ===")
    print("Store records:", len(stores))
    print("Candidate websites:", len(pool))
    print("Checked:", len(selected))
    print("New retailers:", added)
    print("Registered retailers:", len(output))

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
