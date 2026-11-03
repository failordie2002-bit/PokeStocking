
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path("data/status.json")

SOURCES = {
    "pokemon_press": "https://press.pokemon.com/en/Items/Schedule?period=All&types=3&sortAsc=False&sortBy=Date",
    "best_buy": "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+trading+cards",
    "target": "https://www.target.com/s?searchTerm=pokemon%20trading%20cards",
    "walmart": "https://www.walmart.com/search?q=pokemon%20trading%20cards",
    "pokemon_center": "https://www.pokemoncenter.com/search/pokemon-trading-card-game",
    "union_arena": "https://www.unionarena-tcg.com/na/products/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

SEALED_TERMS = (
    "booster", "elite trainer", "etb", "collection",
    "tin", "blister", "battle deck", "battle academy",
    "premium", "build & battle", "build and battle",
    "chest", "trainer toolkit", "trainer's toolkit",
    "deck", "bundle", "display", "sealed box",
)

EXCLUDED_TERMS = (
    "plush", "funko", "figure", "shirt", "apparel",
    "sleeve", "binder", "portfolio", "playmat",
    "deck box", "costume", "model kit",
)

MONTH_DATE = (
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}"
)


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(
                DATA_FILE.read_text(encoding="utf-8")
            )
        except Exception as error:
            print("Previous data read error:", error)

    return {
        "products": [],
        "releases": [],
        "drawings": [],
        "history": [],
    }


def get_page(url, attempts=2):
    last_error = None

    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=(10, 20),
            )
            response.raise_for_status()

            return BeautifulSoup(
                response.text,
                "html.parser",
            )

        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2)

    raise last_error


def find_date(text):
    match = re.search(MONTH_DATE, text or "", re.I)

    if not match:
        return ""

    try:
        return datetime.strptime(
            match.group(0).replace(",", ""),
            "%B %d %Y",
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def find_price(text):
    match = re.search(
        r"\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
        text or "",
    )
    return "$" + match.group(1) if match else ""


def product_type(name):
    name = name.lower()

    if "elite trainer" in name or "etb" in name:
        return "Elite Trainer Box"
    if "booster box" in name or "booster display" in name:
        return "Booster Box"
    if "booster bundle" in name:
        return "Booster Bundle"
    if "booster" in name:
        return "Booster Pack"
    if "blister" in name:
        return "Blister"
    if "tin" in name:
        return "Tin"
    if "build & battle" in name:
        return "Build & Battle"
    if "deck" in name:
        return "Starter Deck"
    if "collection" in name or "chest" in name:
        return "Collection Box"
    if "premium" in name:
        return "Premium Box"

    return "Other Sealed"


def is_sealed(name):
    lower = clean(name).lower()

    if not (
        "pokemon" in lower or "pokémon" in lower
    ):
        return False

    if any(x in lower for x in EXCLUDED_TERMS):
        return False

    return any(x in lower for x in SEALED_TERMS)


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


def image_url(value, base):
    if isinstance(value, list):
        value = value[0] if value else ""

    if isinstance(value, dict):
        value = value.get("url", "")

    if not isinstance(value, str) or not value:
        return ""

    result = urljoin(base, value)

    if not result.startswith(("https://", "http://")):
        return ""

    if any(
        x in result.lower()
        for x in ("placeholder", "sprite", "favicon")
    ):
        return ""

    return result


def walk_json(value):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_jsonld(soup, base, retailer):
    products = []

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            payload = json.loads(
                script.string or script.get_text()
            )
        except Exception:
            continue

        for node in walk_json(payload):
            node_type = node.get("@type", "")
            types = (
                node_type
                if isinstance(node_type, list)
                else [node_type]
            )

            if not any(
                str(t).lower() == "product"
                for t in types
            ):
                continue

            name = clean(node.get("name"))

            if not is_sealed(name):
                continue

            url = node.get("url") or node.get("@id")

            if not isinstance(url, str):
                continue

            url = urljoin(base, url)

            if not url.startswith(("http://", "https://")):
                continue

            product = new_product(
                name,
                "Pokémon",
                url,
                product_type(name),
            )

            product["image"] = image_url(
                node.get("image"),
                base,
            )
            product["retailer"] = retailer
            product["source"] = retailer + " catalogue"

            offers = node.get("offers", {})

            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            if isinstance(offers, dict):
                price = offers.get("price")

                if price is not None:
                    product["retailer_price"] = "$" + str(
                        price
                    )

            sku = node.get("sku")

            if sku:
                product["sku"] = str(sku)

            if product["image"]:
                product["image_source"] = retailer

            products.append(product)

    return products


def parse_html_products(soup, base, retailer):
    products = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        lower = href.lower()

        if retailer == "Best Buy":
            valid = "/site/" in lower
        elif retailer == "Target":
            valid = "/p/" in lower
        elif retailer == "Walmart":
            valid = "/ip/" in lower
        else:
            valid = (
                "/product/" in lower
                or "/products/" in lower
            )

        if not valid:
            continue

        url = urljoin(base, href.split("?")[0])

        if url in seen:
            continue

        seen.add(url)

        node = link
        context = clean(link.get_text(" ", strip=True))

        for _ in range(5):
            if node.parent is None:
                break

            node = node.parent
            candidate = clean(
                node.get_text(" ", strip=True)
            )

            if 20 < len(candidate) < 1500:
                context = candidate
                if "$" in candidate:
                    break

        candidates = [
            link.get("aria-label", ""),
            link.get("title", ""),
            link.get_text(" ", strip=True),
        ]

        for img in link.find_all("img"):
            candidates.append(img.get("alt", ""))

        name = next(
            (
                clean(candidate)
                for candidate in candidates
                if is_sealed(candidate)
            ),
            "",
        )

        if not name:
            continue

        product = new_product(
            name,
            "Pokémon",
            url,
            product_type(name),
        )

        product["retailer"] = retailer
        product["source"] = retailer + " catalogue"
        product["retailer_price"] = find_price(context)
        product["release_date"] = find_date(context)

        for img in node.find_all("img"):
            candidate = image_url(
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src"),
                base,
            )

            if candidate:
                product["image"] = candidate
                product["image_source"] = retailer
                break

        products.append(product)

    return products


def deduplicate(products):
    unique = {}

    for product in products:
        url = product.get("url", "")

        if not url:
            continue

        key = (
            product.get("game", "").lower(),
            url.rstrip("/").lower(),
        )

        if key not in unique:
            unique[key] = product

    return list(unique.values())


def scrape_retailer(name, url):
    soup = get_page(url)

    products = parse_jsonld(soup, url, name)

    if not products:
        products = parse_html_products(
            soup,
            url,
            name,
        )

    return deduplicate(products)


def scrape_pokemon_press():
    products = []
    url = SOURCES["pokemon_press"]
    soup = get_page(url)

    for link in soup.find_all("a", href=True):
        name = clean(link.get_text(" ", strip=True))

        if not re.search(
            r"Pok[eé]mon\s+TCG\s*:",
            name,
            re.I,
        ):
            continue

        if "/products/" not in link["href"]:
            continue

        product_url = urljoin(url, link["href"])

        node = link
        date = ""

        for _ in range(5):
            if node.parent is None:
                break

            node = node.parent

            date = find_date(
                clean(node.get_text(" ", strip=True))
            )

            if date:
                break

        products.append({
            "name": name,
            "game": "Pokémon",
            "type": "Set Release",
            "date": date,
            "url": product_url,
        })

    return products


def fetch_product_image(url):
    try:
        soup = get_page(url)

        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            candidate = image_url(src, url)

            if candidate and any(
                word in candidate.lower()
                for word in (
                    "product",
                    "packaging",
                    "booster",
                )
            ):
                return candidate

        for meta in soup.find_all("meta"):
            if meta.get("property") == "og:image":
                return image_url(
                    meta.get("content"),
                    url,
                )

    except Exception as error:
        print("Image lookup error:", str(error)[:120])

    return ""


def scrape_union_arena():
    url = SOURCES["union_arena"]
    soup = get_page(url)
    products = []

    for link in soup.find_all("a", href=True):
        href = link["href"]

        booster = "/products/boosters/" in href
        deck = "/products/decks/" in href

        if not (booster or deck):
            continue

        name = clean(link.get_text(" ", strip=True))

        if not name:
            continue

        name = re.sub(
            r"^(BOOSTERS|PRECONSTRUCTED DECKS)\s+",
            "",
            name,
            flags=re.I,
        )

        kind = (
            "Booster Pack"
            if booster
            else "Starter Deck"
        )

        if "advanced deck" in name.lower():
            kind = "Advanced Deck"

        product = new_product(
            name,
            "Union Arena",
            urljoin(url, href),
            kind,
        )

        product["source"] = (
            "Union Arena official catalogue"
        )

        node = link

        for _ in range(4):
            if node.parent is None:
                break

            node = node.parent
            context = clean(
                node.get_text(" ", strip=True)
            )

            if not product["release_date"]:
                product["release_date"] = find_date(
                    context
                )

            if not product["msrp"]:
                match = re.search(
                    r"MSRP[:\s]*\$?\s*(\d+(?:\.\d{2})?)",
                    context,
                    re.I,
                )

                if match:
                    product["msrp"] = "$" + match.group(1)

            for img in node.find_all("img"):
                candidate = image_url(
                    img.get("src")
                    or img.get("data-src"),
                    url,
                )

                if (
                    candidate
                    and "/images/products/" in candidate.lower()
                ):
                    product["image"] = candidate
                    product["image_source"] = (
                        "Union Arena official catalogue"
                    )
                    break

            if product["image"]:
                break

        products.append(product)

    return deduplicate(products)


def main():
    print("Starting PokeStock V4...")

    data = load_data()
    previous = data.get("products", [])

    old_by_url = {
        p.get("url"): p
        for p in previous
        if p.get("url")
    }

    errors = []
    source_status = {}
    pokemon = []

    # Preserve earlier discoveries, but remove
    # the unverified Valentine's Box fallback.
    for product in previous:
        if product.get("game") != "Pokémon":
            continue

        if product.get("sku") == "20038675":
            continue

        if (
            "valentine" in
            product.get("name", "").lower()
        ):
            continue

        pokemon.append(product.copy())

    try:
        press = scrape_pokemon_press()

        source_status["Pokémon Press"] = {
            "status": "ok",
            "products_found": len(press),
            "checked_at": now(),
        }

        print("Pokémon release entries:", len(press))

    except Exception as error:
        press = []
        errors.append("Pokémon Press: " + str(error))

        source_status["Pokémon Press"] = {
            "status": "error",
            "error": str(error)[:250],
            "checked_at": now(),
        }

    retailers = [
        ("Best Buy", "best_buy"),
        ("Target", "target"),
        ("Walmart", "walmart"),
        ("Pokémon Center", "pokemon_center"),
    ]

    for retailer, key in retailers:
        try:
            found = scrape_retailer(
                retailer,
                SOURCES[key],
            )

            if not found:
                raise RuntimeError(
                    "No sealed products could be parsed"
                )

            pokemon.extend(found)

            source_status[retailer] = {
                "status": "ok",
                "products_found": len(found),
                "checked_at": now(),
            }

            print(
                retailer,
                "products discovered:",
                len(found),
            )

        except Exception as error:
            message = str(error)[:250]

            errors.append(
                retailer + ": " + message
            )

            source_status[retailer] = {
                "status": "error",
                "error": message,
                "checked_at": now(),
            }

            print(retailer, "error:", message)

    pokemon = deduplicate(pokemon)

    missing = [
        p for p in pokemon
        if not p.get("image")
        and p.get("url", "").startswith("http")
    ][:8]

    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(
            pool.map(
                lambda p: fetch_product_image(
                    p["url"]
                ),
                missing,
            )
        )

    for product, img in zip(missing, images):
        if img:
            product["image"] = img
            product["image_source"] = (
                "Product page"
            )

    try:
        union = scrape_union_arena()

        if not union:
            raise RuntimeError(
                "No Union Arena products found"
            )

        source_status["Union Arena"] = {
            "status": "ok",
            "products_found": len(union),
            "checked_at": now(),
        }

        print("Union Arena products:", len(union))

    except Exception as error:
        errors.append(
            "Union Arena: " + str(error)
        )

        union = [
            p.copy()
            for p in previous
            if p.get("game") == "Union Arena"
        ]

        source_status["Union Arena"] = {
            "status": "error",
            "error": str(error)[:250],
            "checked_at": now(),
        }

    products = deduplicate(pokemon + union)

    for product in products:
        old = old_by_url.get(
            product.get("url"),
            {},
        )

        for field in (
            "image",
            "image_source",
            "sku",
            "set",
            "market_price",
            "msrp",
            "retailer_price",
            "retailer",
            "first_seen",
        ):
            if (
                not product.get(field)
                and old.get(field)
            ):
                product[field] = old[field]

        if not product.get("first_seen"):
            product["first_seen"] = now()

        product["last_seen"] = now()

        # Never invent retailer inventory.
        product["stock_status"] = "Not checked"

    releases = []
    release_keys = set()

    for item in press:
        if not item.get("date"):
            continue

        key = (
            "Pokémon",
            item["url"],
        )

        if key in release_keys:
            continue

        release_keys.add(key)

        releases.append({
            "name": item["name"],
            "game": "Pokémon",
            "type": "Set Release",
            "date": item["date"],
            "msrp": "",
            "url": item["url"],
        })

    for product in products:
        if not product.get("release_date"):
            continue

        key = (
            product.get("game"),
            product.get("url"),
        )

        if key in release_keys:
            continue

        release_keys.add(key)

        releases.append({
            "name": product["name"],
            "game": product["game"],
            "type": product["type"],
            "date": product["release_date"],
            "msrp": product.get("msrp", ""),
            "url": product["url"],
        })

    if not press:
        for release in data.get("releases", []):
            if release.get("game") != "Pokémon":
                continue

            key = (
                "Pokémon",
                release.get("url"),
            )

            if key not in release_keys:
                releases.append(release)
                release_keys.add(key)

    data["products"] = products
    data["releases"] = releases
    data["last_updated"] = now()
    data["check_interval_minutes"] = 5
    data["release_sources"] = list(
        SOURCES.values()
    )
    data["catalogue_source_status"] = source_status
    data["retailer_stock_checks"] = "not_connected"
    data["monitor_errors"] = errors

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

    print("PokeStock V4 finished.")
    print(
        "Pokémon products:",
        sum(
            p.get("game") == "Pokémon"
            for p in products
        ),
    )
    print(
        "Union Arena products:",
        sum(
            p.get("game") == "Union Arena"
            for p in products
        ),
    )
    print("Total products:", len(products))
    print("Release entries:", len(releases))
    print("Errors:", len(errors))
    print(
        "Source status:",
        json.dumps(source_status),
    )


if __name__ == "__main__":
    main()
