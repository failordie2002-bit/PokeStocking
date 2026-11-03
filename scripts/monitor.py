
#!/usr/bin/env python3
"""
POKESTOCK V7.1
Official catalogue + retailer discovery + verified local inventory.

Dependencies:
    requests
    beautifulsoup4

Compatible with existing GitHub Actions workflow.

Safety:
- Never invent inventory.
- Never treat online stock as physical store stock.
- Never treat missing inventory as out of stock.
- Never carry expired stock confirmations forward.
- Preserve existing products, releases and historical data.
"""

import json
import re
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import (
    urljoin, urlparse, quote_plus, parse_qs
)
from concurrent.futures import (
    ThreadPoolExecutor, as_completed
)

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

VERSION = "7.1"

DATA_FILE = Path("data/status.json")
SOURCES_FILE = Path("data/retailer_sources.json")

PRESS_URL = (
    "https://press.pokemon.com/en/Items/Schedule"
    "?period=All&types=3&sortAsc=False&sortBy=Date"
)

UNION_URL = (
    "https://www.unionarena-tcg.com/na/products/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

RETAILERS = {
    "walmart.com": "Walmart",
    "target.com": "Target",
    "bestbuy.com": "Best Buy",
    "gamestop.com": "GameStop",
    "pokemoncenter.com": "Pokémon Center",
}

SEALED_WORDS = (
    "booster",
    "elite trainer",
    "collection",
    "bundle",
    "tin",
    "blister",
    "deck",
    "battle academy",
    "build & battle",
    "build and battle",
    "premium",
    "display",
    "chest",
    "battle stadium",
)

EXCLUDED_WORDS = (
    "sleeves",
    "binder",
    "playmat",
    "portfolio",
    "deck box",
    "plush",
    "shirt",
    "apparel",
    "tcg pocket",
)

DATE_PATTERN = (
    r"(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|"
    r"December)\s+\d{1,2},?\s+\d{4}"
)

MAX_DISCOVERY_SEARCHES = 8
MAX_RETAIL_CHECKS = 12
MAX_STORE_CHECKS = 12

STOCK_TTL_HOURS = 6
TIMEOUT = (8, 18)

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

NOW = datetime.now(timezone.utc)

SOURCE_STATUS = {}
ERRORS = []


# ============================================================
# GENERAL HELPERS
# ============================================================

def timestamp():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return re.sub(
        r"\s+", " ", str(value or "")
    ).strip()


def normalize(value):
    value = clean(value).casefold()
    value = value.replace("pokémon", "pokemon")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return clean(value)


def date_from(value):
    match = re.search(
        DATE_PATTERN, str(value or ""), re.I
    )

    if not match:
        return ""

    try:
        return datetime.strptime(
            match.group().replace(",", ""),
            "%B %d %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def stable_id(value):
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:16]


def hostname(url):
    try:
        return (
            urlparse(url).hostname or ""
        ).lower()
    except Exception:
        return ""


def retailer_name(url):
    host = hostname(url)

    for domain, name in RETAILERS.items():
        if host == domain or host.endswith(
            "." + domain
        ):
            return name

    return ""


def valid_https(url):
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except Exception:
        return False


def is_sealed(name):
    name = normalize(name)

    if not any(
        word in name
        for word in ("pokemon", "union arena")
    ):
        return False

    return (
        any(
            normalize(word) in name
            for word in SEALED_WORDS
        )
        and not any(
            normalize(word) in name
            for word in EXCLUDED_WORDS
        )
    )


def product_type(name):
    name = normalize(name)

    if "elite trainer" in name:
        return "Elite Trainer Box"

    if "booster box" in name:
        return "Booster Box"

    if "booster bundle" in name:
        return "Booster Bundle"

    if "booster" in name:
        return "Booster Pack"

    if "blister" in name:
        return "Blister"

    if "tin" in name:
        return "Tin"

    if "deck" in name:
        return "Deck"

    if "collection" in name:
        return "Collection Box"

    return "Other Sealed"


def fetch(url):
    if not valid_https(url):
        raise ValueError("Invalid HTTPS URL")

    last_error = None

    for attempt in range(2):
        try:
            response = SESSION.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            response.raise_for_status()

            if not response.content:
                raise ValueError("Empty response")

            return response

        except (
            requests.RequestException,
            ValueError
        ) as exc:
            last_error = exc

            if attempt == 0:
                time.sleep(1)

    raise last_error


def soup_from(url):
    response = fetch(url)

    return (
        BeautifulSoup(
            response.text, "html.parser"
        ),
        response.url
    )


def record_source(name, function):
    checked = timestamp()

    try:
        result = function()

        SOURCE_STATUS[name] = {
            "status": (
                "ok" if result else "no_results"
            ),
            "products_found": len(result),
            "checked_at": checked,
        }

        return result

    except Exception as exc:
        message = clean(str(exc))[:300]

        SOURCE_STATUS[name] = {
            "status": "error",
            "error": message,
            "checked_at": checked,
        }

        ERRORS.append(
            name + ": " + message
        )

        return []


def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)

    elif isinstance(value, dict):
        yield value

        for item in value.values():
            if isinstance(item, (list, dict)):
                yield from walk_json(item)


def jsonld(soup):
    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        try:
            data = json.loads(
                script.string
                or script.get_text()
            )

            yield from walk_json(data)

        except (
            ValueError,
            TypeError
        ):
            continue


def schema_type(node, expected):
    value = node.get("@type", "")

    if isinstance(value, str):
        value = [value]

    return any(
        str(item).split("/")[-1] == expected
        for item in value
    )


def image_url(value, base):
    if isinstance(value, list):
        value = next(
            (x for x in value if x),
            ""
        )

    if isinstance(value, dict):
        value = (
            value.get("url")
            or value.get("contentUrl")
        )

    if not isinstance(value, str):
        return ""

    url = urljoin(base, value)

    return url if valid_https(url) else ""


def blank_product(
    name, game, url, category
):
    return {
        "name": clean(name),
        "game": game,
        "type": category,
        "set": "",
        "stock_status": "Not checked",
        "image": "",
        "image_source": "",
        "msrp": "",
        "market_price": "",
        "retailer_price": "",
        "retailer": "",
        "source": "",
        "release_date": "",
        "sku": "",
        "url": url,
    }


# ============================================================
# LOAD AND PRESERVE EXISTING DATABASE
# ============================================================

def load_database():
    if not DATA_FILE.exists():
        return {
            "products": [],
            "releases": [],
        }

    data = json.loads(
        DATA_FILE.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, dict):
        raise ValueError(
            "Existing database is not an object"
        )

    if not isinstance(
        data.get("products"), list
    ):
        raise ValueError(
            "Existing products are invalid"
        )

    if not isinstance(
        data.get("releases"), list
    ):
        raise ValueError(
            "Existing releases are invalid"
        )

    return data


def merge_products(previous, incoming):
    merged = {}
    added = 0

    for p in previous:
        if not isinstance(p, dict):
            continue

        key = (
            p.get("game", ""),
            p.get("url", "").rstrip("/")
        )

        if key[1]:
            merged[key] = p.copy()

    for p in incoming:
        key = (
            p.get("game", ""),
            p.get("url", "").rstrip("/")
        )

        if not key[1]:
            continue

        if key not in merged:
            p["first_seen"] = timestamp()
            merged[key] = p.copy()
            added += 1

        else:
            existing = merged[key]

            for field, value in p.items():
                if (
                    value
                    and field not in (
                        "first_seen",
                        "stock_status",
                        "retailer_stock_check",
                    )
                ):
                    existing[field] = value

        merged[key]["last_seen"] = timestamp()

    return list(merged.values()), added


# ============================================================
# OFFICIAL POKEMON RELEASE DISCOVERY
# ============================================================

def discover_pokemon():
    soup, base = soup_from(PRESS_URL)

    found = {}

    for link in soup.find_all(
        "a", href=True
    ):
        name = clean(
            link.get_text(
                " ", strip=True
            )
        )

        if not re.search(
            r"Pok[eé]mon\s+TCG\s*:",
            name, re.I
        ):
            continue

        if "/products/" not in link["href"]:
            continue

        url = urljoin(
            base, link["href"]
        )

        parent = link

        for _ in range(4):
            if parent.parent is None:
                break

            parent = parent.parent

            if date_from(
                parent.get_text(
                    " ", strip=True
                )
            ):
                break

        found[url] = {
            "name": name,
            "game": "Pokémon",
            "type": "Set Release",
            "date": date_from(
                parent.get_text(
                    " ", strip=True
                )
            ),
            "msrp": "",
            "url": url,
        }

    if not found:
        raise RuntimeError(
            "No official Pokémon releases parsed"
        )

    return list(found.values())


# ============================================================
# OFFICIAL UNION ARENA DISCOVERY
# ============================================================

def discover_union():
    soup, base = soup_from(UNION_URL)

    found = {}

    for link in soup.find_all(
        "a", href=True
    ):
        href = link["href"]

        if not any(
            part in href
            for part in (
                "/products/boosters/",
                "/products/decks/",
            )
        ):
            continue

        name = clean(
            link.get_text(
                " ", strip=True
            )
        )

        if not name:
            continue

        name = re.sub(
            r"^(BOOSTERS|PRECONSTRUCTED DECKS)\s+",
            "",
            name,
            flags=re.I,
        )

        url = urljoin(base, href)

        category = (
            "Starter Deck"
            if "/decks/" in href
            else "Booster Pack"
        )

        p = blank_product(
            name,
            "Union Arena",
            url,
            category,
        )

        p["source"] = (
            "Union Arena official catalogue"
        )

        parent = link

        for _ in range(4):
            if parent.parent is None:
                break

            parent = parent.parent

            content = clean(
                parent.get_text(
                    " ", strip=True
                )
            )

            if date_from(content):
                p["release_date"] = (
                    date_from(content)
                )

            for img in parent.find_all(
                "img"
            ):
                src = (
                    img.get("src")
                    or img.get("data-src")
                )

                url_image = image_url(
                    src, base
                )

                if (
                    url_image
                    and "/images/products/"
                    in url_image.lower()
                ):
                    p["image"] = url_image
                    p["image_source"] = (
                        "Union Arena official catalogue"
                    )
                    break

            if p["image"]:
                break

        found[url] = p

    if not found:
        raise RuntimeError(
            "No Union Arena products parsed"
        )

    return list(found.values())


# ============================================================
# RETAILER PRODUCT DISCOVERY
# ============================================================

def search_queries(products, cursor):
    pokemon = [
        p for p in products
        if p.get("game") == "Pokémon"
    ]

    if not pokemon:
        return [], cursor

    chosen = [
        pokemon[
            (cursor + i) % len(pokemon)
        ]
        for i in range(
            min(
                MAX_DISCOVERY_SEARCHES,
                len(pokemon)
            )
        )
    ]

    queries = []

    for p in chosen:
        name = clean(p.get("name"))

        if name:
            queries.append(name)

    new_cursor = (
        cursor + len(chosen)
    ) % len(pokemon)

    return queries, new_cursor


def discover_search_candidates(query):
    """
    Bing HTML discovery is best-effort only.
    Search hits are candidates, never verified
    retailer listings or stock confirmations.
    """

    search_url = (
        "https://www.bing.com/search?q="
        + quote_plus(
            query + (
                " site:walmart.com OR "
                "site:target.com OR "
                "site:bestbuy.com OR "
                "site:gamestop.com"
            )
        )
    )

    soup, _ = soup_from(search_url)

    candidates = []

    for link in soup.select(
        "li.b_algo h2 a[href]"
    ):
        url = link.get("href", "")

        retailer = retailer_name(url)

        if not retailer:
            continue

        if not valid_https(url):
            continue

        candidates.append({
            "query": query,
            "retailer": retailer,
            "url": url,
            "title": clean(
                link.get_text(
                    " ", strip=True
                )
            ),
            "discovered_at": timestamp(),
            "verification": "candidate_only",
        })

    return candidates


def match_product_name(
    expected, actual
):
    a = normalize(expected)
    b = normalize(actual)

    if not a or not b:
        return False

    if a == b:
        return True

    # Require a substantial title match.
    # Avoid matching only "Pokemon" or
    # generic words such as "booster".
    shorter = min(
        (a, b),
        key=len
    )

    return (
        len(shorter) >= 22
        and (
            a in b
            or b in a
        )
    )


def validate_retailer_page(candidate):
    url = candidate["url"]

    result = {
        **candidate,
        "verification": "unverified",
        "checked_at": timestamp(),
        "availability": "Unknown",
    }

    try:
        soup, final_url = soup_from(url)

        if retailer_name(
            final_url
        ) != candidate["retailer"]:
            raise ValueError(
                "Redirected outside expected retailer"
            )

        products = []

        for node in jsonld(soup):
            if not schema_type(
                node, "Product"
            ):
                continue

            name = clean(
                node.get("name")
            )

            if not name:
                continue

            products.append({
                "name": name,
                "sku": clean(
                    node.get("sku")
                ),
                "image": image_url(
                    node.get("image"),
                    final_url
                ),
            })

        matching = [
            p for p in products
            if match_product_name(
                candidate["query"],
                p["name"]
            )
            and is_sealed(p["name"])
        ]

        if not matching:
            result["reason"] = (
                "No matching structured sealed product"
            )
            return result

        match = matching[0]

        result.update({
            "verification": (
                "verified_product_listing"
            ),
            "product_name": match["name"],
            "sku": match["sku"],
            "image": match["image"],
            "url": final_url,
            "reason": (
                "Matching structured Product metadata"
            ),
        })

        # No stock inference from search snippets,
        # generic page text, or availability badges.

    except Exception as exc:
        result["verification"] = "error"
        result["reason"] = (
            clean(str(exc))[:250]
        )

    return result


# ============================================================
# OPTIONAL STORE-LEVEL INVENTORY SOURCES
# ============================================================

def load_retailer_sources():
    """
    Optional data/retailer_sources.json.

    The file must contain independently
    established retailer product/store sources.

    A store source requires:
      store_id
      store_name
      lat
      lon
      game
      product_name
      source_url
      evidence_url

    evidence_url must return JSON with:
      store_id
      product_name
      availability

    Accepted availability:
      InStock
      OutOfStock
      PreOrder
      BackOrder

    The evidence must refer to the exact store.
    Online inventory alone is insufficient.
    """

    if not SOURCES_FILE.exists():
        return []

    data = json.loads(
        SOURCES_FILE.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, list):
        raise ValueError(
            "retailer_sources.json must be a list"
        )

    return data


def canonical_availability(value):
    value = str(value or "").strip()
    value = value.rstrip("/").split("/")[-1]

    statuses = {
        "InStock": "In stock",
        "OutOfStock": "Out of stock",
        "PreOrder": "Preorder",
        "BackOrder": "Backorder",
    }

    return statuses.get(value, "Unknown")


def verify_store_source(source):
    """
    Strict, machine-readable store inventory.

    Only exact store_id and product_name matches
    can produce a map report.
    """

    result = {
        "status": "Unknown",
        "checked_at": timestamp(),
        "source_url": source.get(
            "source_url", ""
        ),
    }

    required = (
        "store_id",
        "store_name",
        "lat",
        "lon",
        "game",
        "product_name",
        "source_url",
        "evidence_url",
    )

    for field in required:
        if source.get(field) in (
            None, ""
        ):
            result["reason"] = (
                "Missing field: " + field
            )
            return result

    try:
        lat = float(source["lat"])
        lon = float(source["lon"])

        if (
            abs(lat) > 90
            or abs(lon) > 180
        ):
            raise ValueError(
                "Invalid store coordinates"
            )

        evidence_url = source["evidence_url"]
        source_url = source["source_url"]

        if not (
            valid_https(evidence_url)
            and valid_https(source_url)
        ):
            raise ValueError(
                "Source URLs must use HTTPS"
            )

        response = fetch(evidence_url)

        # JSON only. No guesswork from
        # retailer page text or search snippets.
        evidence = response.json()

        if not isinstance(evidence, dict):
            raise ValueError(
                "Inventory evidence is not an object"
            )

        if str(
            evidence.get("store_id", "")
        ) != str(source["store_id"]):
            raise ValueError(
                "Store ID mismatch"
            )

        if normalize(
            evidence.get("product_name")
        ) != normalize(
            source["product_name"]
        ):
            raise ValueError(
                "Product name mismatch"
            )

        # Require evidence explicitly indicating
        # this is store-level inventory.
        if evidence.get(
            "inventory_scope"
        ) != "physical_store":
            raise ValueError(
                "Evidence is not physical-store inventory"
            )

        availability = canonical_availability(
            evidence.get("availability")
        )

        result["status"] = availability

        if availability == "Unknown":
            result["reason"] = (
                "No recognized availability value"
            )
            return result

        result["reason"] = (
            "Explicit matching store-level JSON evidence"
        )

        if availability != "In stock":
            return result

        # Publish only a verified positive.
        # The verification time is the time
        # this source was successfully checked.
        result.update({
            "store_id": str(
                source["store_id"]
            ),
            "store_name": clean(
                source["store_name"]
            ),
            "product_name": clean(
                source["product_name"]
            ),
            "game": source["game"],
            "lat": lat,
            "lon": lon,
            "verified_at": timestamp(),
            "source_url": source_url,
            "evidence_url": evidence_url,
        })

        return result

    except Exception as exc:
        result["status"] = "Unknown"
        result["reason"] = (
            clean(str(exc))[:250]
        )
        result["check_failed"] = True

        return result


# ============================================================
# RELEASE PRESERVATION
# ============================================================

def merge_releases(previous, incoming):
    merged = {}

    for release in previous:
        if not isinstance(
            release, dict
        ):
            continue

        key = (
            release.get("game", ""),
            release.get("url", ""),
        )

        if key[1]:
            merged[key] = release.copy()

    for release in incoming:
        key = (
            release.get("game", ""),
            release.get("url", ""),
        )

        if not key[1]:
            continue

        if key not in merged:
            merged[key] = release.copy()

        else:
            for field, value in release.items():
                if value:
                    merged[key][field] = value

    return list(merged.values())


# ============================================================
# MAIN MONITOR
# ============================================================

def main():
    print(
        "Starting PokéStock V" + VERSION
    )

    db = load_database()

    old_products = db["products"]
    old_releases = db["releases"]

    # ----------------------------------------
    # Official catalogue discovery
    # ----------------------------------------

    pokemon_releases = record_source(
        "Pokemon Press",
        discover_pokemon
    )

    union_products = record_source(
        "Union Arena",
        discover_union
    )

    products, new_count = merge_products(
        old_products,
        union_products
    )

    releases = merge_releases(
        old_releases,
        pokemon_releases
    )

    # ----------------------------------------
    # Retailer search discovery
    # ----------------------------------------

    cursor = int(
        db.get(
            "v71_discovery_cursor", 0
        )
    )

    queries, next_cursor = search_queries(
        products,
        cursor
    )

    db["v71_discovery_cursor"] = next_cursor

    previous_candidates = db.get(
        "retailer_discovery_candidates", []
    )

    if not isinstance(
        previous_candidates, list
    ):
        previous_candidates = []

    candidate_map = {
        c["url"]: c
        for c in previous_candidates
        if isinstance(c, dict)
        and c.get("url")
    }

    search_failures = 0
    search_successes = 0

    for query in queries:
        try:
            candidates = (
                discover_search_candidates(
                    query
                )
            )

            search_successes += 1

            for candidate in candidates:
                candidate_map[
                    candidate["url"]
                ] = candidate

        except Exception as exc:
            search_failures += 1

            ERRORS.append(
                "Retailer discovery: "
                + clean(str(exc))[:200]
            )

    SOURCE_STATUS[
        "Retailer search discovery"
    ] = {
        "status": (
            "partial_error"
            if search_failures
            and search_successes
            else "error"
            if search_failures
            else "ok"
            if candidate_map
            else "no_results"
        ),
        "searches_attempted": len(queries),
        "searches_succeeded": search_successes,
        "searches_failed": search_failures,
        "candidate_count": len(
            candidate_map
        ),
        "checked_at": timestamp(),
    }

    # ----------------------------------------
    # Verify discovered retailer pages
    # ----------------------------------------

    all_candidates = list(
        candidate_map.values()
    )

    retailer_cursor = int(
        db.get(
            "v71_retail_cursor", 0
        )
    )

    if all_candidates:
        selected = [
            all_candidates[
                (retailer_cursor + i)
                % len(all_candidates)
            ]
            for i in range(
                min(
                    MAX_RETAIL_CHECKS,
                    len(all_candidates)
                )
            )
        ]

        db["v71_retail_cursor"] = (
            retailer_cursor
            + len(selected)
        ) % len(all_candidates)

    else:
        selected = []

    with ThreadPoolExecutor(
        max_workers=3
    ) as executor:

        futures = [
            executor.submit(
                validate_retailer_page,
                candidate
            )
            for candidate in selected
        ]

        for future in as_completed(
            futures
        ):
            result = future.result()

            candidate_map[
                result["url"]
            ] = result

    verified_listings = [
        c for c in candidate_map.values()
        if c.get("verification")
        == "verified_product_listing"
    ]

    SOURCE_STATUS[
        "Retailer listing validation"
    ] = {
        "status": (
            "ok" if verified_listings
            else "no_results"
        ),
        "pages_checked_this_run": len(
            selected
        ),
        "verified_listing_count": len(
            verified_listings
        ),
        "checked_at": timestamp(),
    }

    # ----------------------------------------
    # Store-level inventory checks
    # ----------------------------------------

    try:
        store_sources = (
            load_retailer_sources()
        )

        SOURCE_STATUS[
            "Store inventory configuration"
        ] = {
            "status": (
                "ok"
                if store_sources
                else "not_configured"
            ),
            "sources": len(store_sources),
            "checked_at": timestamp(),
        }

    except Exception as exc:
        store_sources = []

        message = clean(str(exc))[:250]

        ERRORS.append(
            "Store inventory configuration: "
            + message
        )

        SOURCE_STATUS[
            "Store inventory configuration"
        ] = {
            "status": "error",
            "error": message,
            "checked_at": timestamp(),
        }

    store_cursor = int(
        db.get(
            "v71_store_cursor", 0
        )
    )

    if store_sources:
        chosen_stores = [
            store_sources[
                (store_cursor + i)
                % len(store_sources)
            ]
            for i in range(
                min(
                    MAX_STORE_CHECKS,
                    len(store_sources)
                )
            )
        ]

        db["v71_store_cursor"] = (
            store_cursor
            + len(chosen_stores)
        ) % len(store_sources)

    else:
        chosen_stores = []

    store_checks = []

    with ThreadPoolExecutor(
        max_workers=3
    ) as executor:

        futures = [
            executor.submit(
                verify_store_source,
                source
            )
            for source in chosen_stores
        ]

        for future in as_completed(
            futures
        ):
            store_checks.append(
                future.result()
            )

    # ----------------------------------------
    # Retain only recent verified stock
    # ----------------------------------------

    old_inventory = db.get(
        "store_inventory", []
    )

    if not isinstance(
        old_inventory, list
    ):
        old_inventory = []

    inventory = {}

    def recent(record):
        if record.get(
            "status"
        ) != "In stock":
            return False

        try:
            verified = datetime.fromisoformat(
                record["verified_at"]
                .replace("Z", "+00:00")
            )

            if verified.tzinfo is None:
                return False

            age = (
                NOW - verified
            ).total_seconds()

            return (
                0 <= age
                <= STOCK_TTL_HOURS * 3600
            )

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            return False

    # Preserve unexpired prior reports,
    # but never extend their verification time.
    for record in old_inventory:
        if (
            isinstance(record, dict)
            and recent(record)
        ):
            key = (
                str(
                    record.get(
                        "store_id", ""
                    )
                ),
                normalize(
                    record.get(
                        "product_name", ""
                    )
                ),
            )

            inventory[key] = record

    for result in store_checks:
        if not result.get(
            "store_id"
        ):
            continue

        key = (
            str(result["store_id"]),
            normalize(
                result["product_name"]
            ),
        )

        if (
            result["status"]
            == "In stock"
            and recent(result)
        ):
            inventory[key] = result

        else:
            inventory.pop(
                key, None
            )

    # An unavailable check is not a fresh
    # confirmation. Previously confirmed
    # records retain only their original TTL.

    # ----------------------------------------
    # Reset unverified product-level stock
    # ----------------------------------------

    for p in products:
        p["stock_status"] = (
            "Not checked"
        )

    # The map uses store_inventory,
    # not global product stock_status.

    # ----------------------------------------
    # Save output
    # ----------------------------------------

    db["products"] = products
    db["releases"] = releases

    db[
        "retailer_discovery_candidates"
    ] = list(candidate_map.values())

    db[
        "verified_retailer_listings"
    ] = verified_listings

    db[
        "store_inventory"
    ] = list(inventory.values())

    db[
        "v71_store_checks"
    ] = store_checks

    db[
        "catalogue_source_status"
    ] = SOURCE_STATUS

    db["monitor_errors"] = ERRORS

    db["monitor_version"] = VERSION
    db["last_updated"] = timestamp()

    db["retailer_stock_checks"] = (
        "store_sources_configured"
        if store_sources
        else "not_connected"
    )

    db["discovery_summary"] = {
        "new_products_this_run": new_count,
        "total_products": len(products),
        "pokemon_products": sum(
            p.get("game") == "Pokémon"
            for p in products
        ),
        "union_arena_products": sum(
            p.get("game") == "Union Arena"
            for p in products
        ),
        "products_with_images": sum(
            bool(p.get("image"))
            for p in products
        ),
        "retailer_candidates": len(
            candidate_map
        ),
        "verified_retailer_listings": len(
            verified_listings
        ),
        "store_sources_configured": len(
            store_sources
        ),
        "store_checks_this_run": len(
            store_checks
        ),
        "verified_in_stock_locations": len(
            inventory
        ),
        "source_errors": len(ERRORS),
        "updated_at": timestamp(),
    }

    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    DATA_FILE.write_text(
        json.dumps(
            db,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8",
    )

    print(
        "PokéStock V7.1 complete"
    )

    print(
        json.dumps(
            db["discovery_summary"],
            indent=2
        )
    )

    if ERRORS:
        print("Source errors:")

        for error in ERRORS:
            print("-", error)


if __name__ == "__main__":
    main()
