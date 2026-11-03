
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

# POKESTOCK V5
# Official catalogue and release discovery.
# Does not claim real-time retail inventory.

DATA_FILE = Path("data/status.json")

SOURCES = {
    "Pokemon Press":
        "https://press.pokemon.com/en/Items/Schedule?period=All&types=3&sortAsc=False&sortBy=Date",
    "Pokemon News":
        "https://www.pokemon.com/us/pokemon-news",
    "Union Arena":
        "https://www.unionarena-tcg.com/na/products/",
}

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (compatible; PokeStockCatalog/5.0)",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTHS = (
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December"
)

DATE_PATTERN = (
    r"(?:%s)\s+\d{1,2},?\s+\d{4}" % MONTHS
)

SEALED_WORDS = (
    "booster", "elite trainer", "collection",
    "battle deck", "starter deck", "advanced deck",
    "premium", "bundle", "tin", "blister",
    "battle academy", "toolkit", "chest",
    "build & battle", "build and battle",
    "display", "battle box",
)

EXCLUDED_WORDS = (
    "sleeve", "binder", "playmat", "plush",
    "figure", "portfolio", "deck box",
    "costume", "apparel", "shirt",
    "video game", "tcg pocket",
)

session = requests.Session()
session.headers.update(HEADERS)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return re.sub(
        r"\s+", " ", str(value or "")
    ).strip()


def load_database():
    if not DATA_FILE.exists():
        return {
            "products": [],
            "releases": [],
            "drawings": [],
            "history": [],
        }

    try:
        return json.loads(
            DATA_FILE.read_text(encoding="utf-8")
        )
    except Exception as error:
        print("Database error:", error)
        raise


def fetch(url):
    error = None

    for attempt in range(2):
        try:
            response = session.get(
                url,
                timeout=(10, 20),
            )
            response.raise_for_status()

            if not response.text.strip():
                raise ValueError("Empty response")

            return BeautifulSoup(
                response.text,
                "html.parser",
            )

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            error = exc

            if attempt == 0:
                time.sleep(2)

    raise error


def parse_date(text):
    match = re.search(
        DATE_PATTERN,
        text or "",
        flags=re.I,
    )

    if not match:
        return ""

    try:
        return datetime.strptime(
            match.group().replace(",", ""),
            "%B %d %Y",
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_msrp(text):
    match = re.search(
        r"MSRP\s*:?\s*\$?\s*(\d+(?:\.\d{1,2})?)",
        text or "",
        re.I,
    )

    if match:
        return "$" + match.group(1)

    return ""


def classify(name, game):
    value = name.lower()

    if game == "Union Arena":
        if "advanced deck" in value:
            return "Advanced Deck"
        if "starter deck" in value:
            return "Starter Deck"
        return "Booster Pack"

    if "elite trainer" in value:
        return "Elite Trainer Box"
    if "booster box" in value or "booster display" in value:
        return "Booster Box"
    if "booster bundle" in value:
        return "Booster Bundle"
    if "booster" in value:
        return "Booster Pack"
    if "tin" in value:
        return "Tin"
    if "blister" in value:
        return "Blister"
    if "deck" in value:
        return "Starter Deck"
    if "collection" in value:
        return "Collection Box"
    if "premium" in value:
        return "Premium Box"

    return "Other Sealed"


def sealed_title(name):
    value = clean(name).lower()

    if not (
        "pokemon" in value
        or "pokémon" in value
    ):
        return False

    if any(
        word in value
        for word in EXCLUDED_WORDS
    ):
        return False

    return any(
        word in value
        for word in SEALED_WORDS
    )


def new_product(name, game, url, kind):
    return {
        "name": clean(name),
        "game": game,
        "type": kind,
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


def valid_image(src, base):
    if not src:
        return ""

    url = urljoin(base, str(src))

    if not url.startswith(
        ("http://", "https://")
    ):
        return ""

    lower = url.lower()

    if any(
        word in lower
        for word in (
            "placeholder",
            "favicon",
            "sprite",
            "logo",
        )
    ):
        return ""

    return url


def extract_image(soup, base):
    # Prefer product photography.
    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
        )

        url = valid_image(src, base)

        if url and any(
            word in url.lower()
            for word in (
                "product",
                "packaging",
                "booster",
                "deck",
            )
        ):
            return url

    # Fallback to page preview artwork.
    for meta in soup.find_all("meta"):
        if meta.get("property") in (
            "og:image",
            "og:image:secure_url",
        ):
            return valid_image(
                meta.get("content"),
                base,
            )

    return ""


def surrounding_text(link):
    node = link

    for _ in range(5):
        if node.parent is None:
            break

        node = node.parent
        text = clean(
            node.get_text(" ", strip=True)
        )

        if parse_date(text):
            return text

    return clean(
        link.get_text(" ", strip=True)
    )


def discover_pokemon_press():
    url = SOURCES["Pokemon Press"]
    soup = fetch(url)

    releases = []
    seen = set()

    for link in soup.find_all(
        "a", href=True
    ):
        name = clean(
            link.get_text(" ", strip=True)
        )

        href = link["href"]

        if not re.search(
            r"Pok[eé]mon\s+TCG\s*:",
            name,
            re.I,
        ):
            continue

        if "/products/" not in href:
            continue

        target = urljoin(url, href)

        if target in seen:
            continue

        seen.add(target)

        releases.append({
            "name": name,
            "game": "Pokémon",
            "type": "Set Release",
            "date": parse_date(
                surrounding_text(link)
            ),
            "msrp": "",
            "url": target,
        })

    if not releases:
        raise RuntimeError(
            "No official Pokémon release entries parsed"
        )

    return releases


def discover_pokemon_news():
    # News is a discovery signal, not proof
    # of an individual retail SKU.
    url = SOURCES["Pokemon News"]
    soup = fetch(url)

    candidates = []
    seen = set()

    for link in soup.find_all(
        "a", href=True
    ):
        title = clean(
            link.get_text(" ", strip=True)
        )

        if not sealed_title(title):
            continue

        target = urljoin(
            url, link["href"]
        )

        if urlparse(target).netloc not in (
            "www.pokemon.com",
            "pokemon.com",
        ):
            continue

        if target in seen:
            continue

        seen.add(target)

        candidates.append({
            "name": title,
            "url": target,
            "source": "Pokemon News",
        })

    # Empty is a valid response from a
    # general news page. Do not invent items.
    return candidates


def discover_union_arena():
    url = SOURCES["Union Arena"]
    soup = fetch(url)

    products = []
    seen = set()

    for link in soup.find_all(
        "a", href=True
    ):
        href = link["href"]

        is_booster = (
            "/products/boosters/" in href
        )
        is_deck = (
            "/products/decks/" in href
        )

        if not (
            is_booster or is_deck
        ):
            continue

        target = urljoin(url, href)

        if target in seen:
            continue

        seen.add(target)

        raw_name = clean(
            link.get_text(" ", strip=True)
        )

        if not raw_name:
            continue

        name = re.sub(
            r"^(BOOSTERS|PRECONSTRUCTED DECKS)\s+",
            "",
            raw_name,
            flags=re.I,
        )

        kind = (
            "Booster Pack"
            if is_booster
            else "Starter Deck"
        )

        if "advanced deck" in name.lower():
            kind = "Advanced Deck"

        product = new_product(
            name,
            "Union Arena",
            target,
            kind,
        )

        product["source"] = (
            "Union Arena official catalogue"
        )

        context = surrounding_text(link)

        product["release_date"] = (
            parse_date(context)
        )
        product["msrp"] = (
            parse_msrp(context)
        )

        node = link

        for _ in range(4):
            if node.parent is None:
                break

            node = node.parent

            for img in node.find_all("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                )

                image = valid_image(
                    src, url
                )

                if (
                    image
                    and "/images/products/"
                    in image.lower()
                ):
                    product["image"] = image
                    product["image_source"] = (
                        "Union Arena official catalogue"
                    )
                    break

            if product["image"]:
                break

        products.append(product)

    if not products:
        raise RuntimeError(
            "No official Union Arena products parsed"
        )

    return products


def refresh_image(product):
    url = product.get("url", "")

    if not url.startswith(
        ("https://", "http://")
    ):
        return ""

    try:
        soup = fetch(url)
        return extract_image(soup, url)
    except Exception as error:
        print(
            "Image lookup failed:",
            url,
            str(error)[:100],
        )
        return ""


def merge_products(previous, discovered):
    # URL-based identity avoids accidentally
    # merging different sealed formats.
    merged = {}

    for item in previous:
        url = item.get("url", "")

        if not url:
            continue

        # Remove only the known, unverified
        # hardcoded Valentine's Box fallback.
        if (
            item.get("sku") == "20038675"
            and "valentine" in
            item.get("name", "").lower()
        ):
            continue

        key = (
            item.get("game", ""),
            url.rstrip("/"),
        )

        merged[key] = item.copy()

    for item in discovered:
        url = item.get("url", "")

        if not url:
            continue

        key = (
            item.get("game", ""),
            url.rstrip("/"),
        )

        if key in merged:
            old = merged[key]

            for field, value in item.items():
                if value and field not in (
                    "stock_status",
                    "first_seen",
                    "last_seen",
                ):
                    old[field] = value

            old["last_seen"] = timestamp()
        else:
            fresh = item.copy()
            fresh["first_seen"] = timestamp()
            fresh["last_seen"] = timestamp()
            merged[key] = fresh

    products = list(merged.values())

    # No inventory source is connected.
    for product in products:
        product["stock_status"] = "Not checked"

    return products


def make_releases(
    press_releases,
    products,
    previous_releases,
):
    releases = {}
    
    for item in previous_releases:
        if item.get("url"):
            key = (
                item.get("game", ""),
                item["url"],
            )
            releases[key] = item.copy()

    for item in press_releases:
        key = (
            item["game"],
            item["url"],
        )

        if key in releases:
            old = releases[key]

            for field, value in item.items():
                if value:
                    old[field] = value
        else:
            releases[key] = item.copy()

    for product in products:
        date = product.get(
            "release_date", ""
        )

        if not date:
            continue

        key = (
            product.get("game", ""),
            product.get("url", ""),
        )

        if key in releases:
            continue

        releases[key] = {
            "name": product["name"],
            "game": product["game"],
            "type": product["type"],
            "date": date,
            "msrp": product.get(
                "msrp", ""
            ),
            "url": product["url"],
        }

    return list(releases.values())


def main():
    print("Starting PokeStock V5")

    data = load_database()

    previous = data.get(
        "products", []
    )

    discovered = []
    press_releases = []
    errors = []
    statuses = {}

    def run_source(name, function):
        checked = timestamp()

        try:
            result = function()

            statuses[name] = {
                "status": (
                    "ok" if result
                    else "no_results"
                ),
                "products_found": len(result),
                "checked_at": checked,
            }

            print(
                name,
                "results:",
                len(result),
            )

            return result

        except Exception as error:
            message = str(error)[:300]

            statuses[name] = {
                "status": "error",
                "error": message,
                "checked_at": checked,
            }

            errors.append(
                name + ": " + message
            )

            print(
                name,
                "ERROR:",
                message,
            )

            return []

    press_releases = run_source(
        "Pokemon Press",
        discover_pokemon_press,
    )

    news = run_source(
        "Pokemon News",
        discover_pokemon_news,
    )

    union = run_source(
        "Union Arena",
        discover_union_arena,
    )

    discovered.extend(union)

    # News links are retained as discovery
    # candidates, not as verified SKUs.
    data["discovery_candidates"] = news

    # Preserve all previous verified and
    # previously collected product records.
    products = merge_products(
        previous,
        discovered,
    )

    # Retry only a small number of missing
    # images per run to avoid timeouts.
    missing = [
        product
        for product in products
        if not product.get("image")
    ][:6]

    with ThreadPoolExecutor(
        max_workers=3
    ) as executor:
        images = list(
            executor.map(
                refresh_image,
                missing,
            )
        )

    for product, image in zip(
        missing, images
    ):
        if image:
            product["image"] = image
            product["image_source"] = (
                "Product detail page"
            )

    releases = make_releases(
        press_releases,
        products,
        data.get("releases", []),
    )

    old_urls = {
        p.get("url")
        for p in previous
    }

    new_products = [
        p for p in discovered
        if p.get("url") not in old_urls
    ]

    data["products"] = products
    data["releases"] = releases
    data["last_updated"] = timestamp()
    data["check_interval_minutes"] = 5
    data["release_sources"] = list(
        SOURCES.values()
    )
    data["catalogue_source_status"] = (
        statuses
    )
    data["monitor_errors"] = errors
    data["retailer_stock_checks"] = (
        "not_connected"
    )

    data["discovery_summary"] = {
        "new_products_this_run": len(
            new_products
        ),
        "total_products": len(
            products
        ),
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
        "source_errors": len(errors),
        "updated_at": timestamp(),
    }

    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    DATA_FILE.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("PokeStock V5 finished")
    print(
        json.dumps(
            data["discovery_summary"],
            indent=2,
        )
    )

    if errors:
        print("Source failures:")
        for error in errors:
            print("-", error)


if __name__ == "__main__":
    main()
