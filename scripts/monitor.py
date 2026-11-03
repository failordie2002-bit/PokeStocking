import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path("data/status.json")

SOURCES = {
    "pokemon_press": (
        "https://press.pokemon.com/en/Items/Schedule"
        "?period=All&types=3&sortAsc=False&sortBy=Date"
    ),
    "pokemon_retail": (
        "https://www.gamestop.com/pokemon/new"
        "?prefn1=preorderAvailabilityDate"
        "&prefv1=-15%7C180%7C365"
    ),
    "union_arena": "https://www.unionarena-tcg.com/na/products/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    )
}

MONTH_DATE = (
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4}"
)


def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "products": [],
        "releases": [],
        "drawings": [],
        "history": [],
    }


def get_page(url, attempts=3, timeout=(10, 25)):
    last_error = None

    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")

        except requests.RequestException as error:
            last_error = error

            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))

    raise last_error


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_date(text):
    if not text:
        return ""

    quarter = re.search(
        r"\bQ([1-4])\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )

    if quarter:
        return f"Q{quarter.group(1)} {quarter.group(2)}"

    numeric = re.search(
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
        text,
    )

    if numeric:
        try:
            value = datetime.strptime(
                numeric.group(0),
                "%m/%d/%Y",
            )
            return value.strftime("%Y-%m-%d")
        except ValueError:
            pass

    match = re.search(MONTH_DATE, text, re.IGNORECASE)

    if not match:
        return ""

    value = match.group(0).replace(",", "")

    try:
        return datetime.strptime(
            value,
            "%B %d %Y",
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def find_date(text):
    return normalize_date(text)


def find_msrp(text):
    match = re.search(
        r"(?:MSRP|SRP|Retail Price)[:\s]*\$?\s*"
        r"(\d+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    return "$" + match.group(1) if match else ""


def find_retail_price(text):
    match = re.search(
        r"\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
        text,
    )

    if not match:
        return ""

    return "$" + match.group(1).replace(",", "")


def pokemon_type(name):
    text = name.lower()

    if "elite trainer box" in text:
        return "Elite Trainer Box"
    if "booster box" in text:
        return "Booster Box"
    if "booster bundle" in text:
        return "Booster Bundle"
    if "sleeved booster" in text or "booster pack" in text:
        return "Booster Pack"
    if "blister" in text:
        return "Blister"
    if "mini tin" in text or "tin" in text:
        return "Tin"
    if "build and battle" in text:
        return "Build & Battle"
    if "battle deck" in text or "battle academy" in text:
        return "Deck"
    if "valentine" in text:
        return "Special Box"
    if "premium tournament" in text:
        return "Premium Box"
    if "collection" in text or "binder" in text:
        return "Collection Box"
    if "box" in text:
        return "Collection Box"

    return "Other Sealed"


def make_product(
    name,
    game,
    url,
    kind,
    release_date="",
    msrp="",
):
    return {
        "name": clean_text(name),
        "game": game,
        "type": kind,
        "set": "",
        "stock_status": "Not checked",
        "image": "",
        "image_source": "",
        "msrp": msrp,
        "market_price": "",
        "retailer_price": "",
        "retailer": "",
        "source": "",
        "release_date": release_date,
        "sku": "",
        "url": url,
    }


# ---------------------------------------------------------
# POKÉMON: OFFICIAL RELEASE ANNOUNCEMENTS
# ---------------------------------------------------------

def scrape_pokemon_press():
    products = []
    soup = get_page(SOURCES["pokemon_press"])

    for link in soup.find_all("a", href=True):
        name = clean_text(link.get_text(" ", strip=True))

        if not re.search(
            r"Pok[eé]mon\s+TCG\s*:",
            name,
            re.IGNORECASE,
        ):
            continue

        if "/products/" not in link["href"]:
            continue

        url = urljoin(SOURCES["pokemon_press"], link["href"])

        context = ""
        node = link

        for _ in range(5):
            if node.parent is None:
                break

            node = node.parent
            candidate = clean_text(
                node.get_text(" ", strip=True)
            )

            if find_date(candidate):
                context = candidate
                break

        release_date = find_date(context)

        if "battle deck" in name.lower():
            release_date = ""

        products.append({
            "name": name,
            "game": "Pokémon",
            "type": "Set Release",
            "date": release_date,
            "url": url,
        })

    return products


# ---------------------------------------------------------
# POKÉMON: RETAILER SEALED-PRODUCT DISCOVERY
# ---------------------------------------------------------

def card_image(link):
    nodes = [link]
    node = link

    for _ in range(5):
        if node.parent is None:
            break
        node = node.parent
        nodes.append(node)

    for container in nodes:
        for img in container.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
            )

            if not src:
                continue

            candidate = urljoin(
                SOURCES["pokemon_retail"],
                src,
            )

            lower = candidate.lower()

            if any(word in lower for word in (
                "logo", "icon", "sprite", "placeholder"
            )):
                continue

            return candidate

    return ""


def scrape_gamestop():
    products = []
    soup = get_page(SOURCES["pokemon_retail"])

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if "/toys-games/trading-cards/products/" not in href:
            continue

        url = urljoin(SOURCES["pokemon_retail"], href)

        context = ""
        node = link

        for _ in range(6):
            if node.parent is None:
                break

            node = node.parent
            candidate = clean_text(
                node.get_text(" ", strip=True)
            )

            if (
                "pokemon trading card game" in candidate.lower()
                and len(candidate) < 1200
            ):
                context = candidate

                if "$" in candidate:
                    break

        candidates = [
            clean_text(link.get_text(" ", strip=True)),
            clean_text(link.get("aria-label", "")),
            clean_text(link.get("title", "")),
        ]

        for img in link.find_all("img"):
            candidates.append(
                clean_text(img.get("alt", ""))
            )

        candidates.append(context)

        name = ""

        for candidate in candidates:
            match = re.search(
                r"Pokemon Trading Card Game[^$]{0,180}",
                candidate,
                re.IGNORECASE,
            )

            if match:
                name = clean_text(match.group(0))
                break

        name = re.split(
            r"\s+\$|\s+Release Date\b|\s+Add to Cart\b",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        if (
            "pokemon" not in name.lower()
            or "trading card game" not in name.lower()
        ):
            continue

        product = make_product(
            name=name,
            game="Pokémon",
            url=url,
            kind=pokemon_type(name),
            release_date=find_date(context),
        )

        product["image"] = card_image(link)
        product["retailer"] = "GameStop"
        product["source"] = "GameStop product listing"
        product["retailer_price"] = find_retail_price(context)

        if product["image"]:
            product["image_source"] = "GameStop product image"

        sku_match = re.search(r"/(\d{6,})(?:\.html)?", url)

        if sku_match:
            product["sku"] = sku_match.group(1)

        products.append(product)

    return remove_duplicates(products)


def add_known_valentines_box(products):
    url = (
        "https://www.gamestop.com/toys-games/trading-cards/"
        "products/pokemon-trading-card-game-valentines-box/"
        "20038675.html"
    )

    if any("valentine" in p["name"].lower() for p in products):
        return products

    product = make_product(
        name="Pokémon TCG: Valentine's Box",
        game="Pokémon",
        url=url,
        kind="Special Box",
        release_date="2027-01-15",
        msrp="$14.99",
    )

    product["sku"] = "20038675"
    product["retailer"] = "GameStop"
    product["source"] = "Verified product listing"
    product["image"] = (
        "https://media.gamestop.com/i/gamestop/"
        "20038675?fmt=auto&h=768&w=768"
    )
    product["image_source"] = "GameStop product image"

    products.append(product)

    return products


# ---------------------------------------------------------
# POKÉMON: IMAGE LOOKUP WITH RETRIES
# ---------------------------------------------------------

def pokemon_image(url):
    try:
        soup = get_page(
            url,
            attempts=3,
            timeout=(8, 18),
        )

        # Prefer actual product/packaging images when available.
        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
            )

            if not src:
                continue

            candidate = urljoin(url, src)
            lower = candidate.lower()

            if (
                "product" in lower
                or "packaging" in lower
                or "product-shot" in lower
            ):
                return candidate

        for meta in soup.find_all("meta"):
            key = meta.get("property", "").lower()
            name = meta.get("name", "").lower()

            if (
                key in ("og:image", "og:image:secure_url")
                or name == "twitter:image"
            ):
                content = meta.get("content", "").strip()

                if content:
                    return urljoin(url, content)

    except Exception as error:
        print("Pokémon image lookup failed:", url, error)

    return ""


# ---------------------------------------------------------
# UNION ARENA: OFFICIAL CATALOGUE
# ---------------------------------------------------------

def clean_union_name(raw):
    text = clean_text(raw)

    text = re.sub(
        r"^(BOOSTERS|PRECONSTRUCTED DECKS|OTHER)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    prefixes = [
        "Special Booster Pack",
        "Precious Booster Pack",
        "Booster Pack",
        "Advanced Deck",
        "Starter Deck",
    ]

    for prefix in prefixes:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break

    text = re.split(
        r"\s+Release Date\b|\s+MSRP\b",
        text,
        flags=re.IGNORECASE,
    )[0]

    return clean_text(text)


def union_product_image(link, base_url):
    nodes = [link]
    node = link

    for _ in range(3):
        if node.parent is None:
            break
        node = node.parent
        nodes.append(node)

    for container in nodes:
        for img in container.find_all("img"):
            src = img.get("src") or img.get("data-src")

            if not src:
                continue

            candidate = urljoin(base_url, src)
            lower = candidate.lower()

            if (
                "/images/products/" in lower
                and (
                    "/boosters/" in lower
                    or "/decks/" in lower
                )
            ):
                return candidate

    return ""


def scrape_union_arena():
    products = []
    soup = get_page(SOURCES["union_arena"])

    for link in soup.find_all("a", href=True):
        href = link["href"]

        is_booster = "/products/boosters/" in href
        is_deck = "/products/decks/" in href

        if not (is_booster or is_deck):
            continue

        raw = clean_text(link.get_text(" ", strip=True))

        if not raw:
            continue

        kind = "Booster Pack" if is_booster else "Starter Deck"

        if "advanced deck" in raw.lower():
            kind = "Advanced Deck"

        name = clean_union_name(raw)

        if len(name) < 3:
            continue

        url = urljoin(SOURCES["union_arena"], href)

        context = ""
        node = link

        for _ in range(4):
            if node.parent is None:
                break

            node = node.parent
            candidate = clean_text(
                node.get_text(" ", strip=True)
            )

            if find_date(candidate) and find_msrp(candidate):
                context = candidate
                break

        product = make_product(
            name=name,
            game="Union Arena",
            url=url,
            kind=kind,
            release_date=find_date(context),
            msrp=find_msrp(context),
        )

        product["image"] = union_product_image(
            link,
            SOURCES["union_arena"],
        )

        product["source"] = "Union Arena official catalogue"

        if product["image"]:
            product["image_source"] = (
                "Union Arena official catalogue"
            )

        products.append(product)

    return remove_duplicates(products)


# ---------------------------------------------------------
# MERGING AND PUBLISHING
# ---------------------------------------------------------

def remove_duplicates(items):
    unique = {}

    for item in items:
        key = (
            item.get("game", "").lower(),
            item.get("url", "").lower(),
        )

        if key[1]:
            unique[key] = item

    return list(unique.values())


def main():
    print("Starting PokeStock monitor...")

    data = load_data()
    old_products = data.get("products", [])
    old_by_url = {
        item.get("url", ""): item
        for item in old_products
        if item.get("url")
    }

    errors = []
    image_failures = 0

    # Pokémon release announcements.
    try:
        pokemon_press = scrape_pokemon_press()
        print("Pokémon release announcements:", len(pokemon_press))

    except Exception as error:
        pokemon_press = []
        errors.append("Pokémon Press: " + str(error))
        print(errors[-1])

    # Pokémon individual sealed products.
    try:
        pokemon = scrape_gamestop()

        if not pokemon:
            raise RuntimeError(
                "No Pokémon sealed products were found on the listing page."
            )

        print("GameStop Pokémon products:", len(pokemon))

    except Exception as error:
        errors.append("GameStop catalogue: " + str(error))
        print(errors[-1])

        # Keep the previous catalogue rather than deleting it.
        pokemon = [
            item for item in old_products
            if item.get("game") == "Pokémon"
        ]

    pokemon = add_known_valentines_box(pokemon)

    # Retry missing Pokémon images.
    missing = [
        item for item in pokemon
        if not item.get("image")
    ]

    print("Pokémon images to retrieve:", len(missing))

    with ThreadPoolExecutor(max_workers=4) as executor:
        images = list(
            executor.map(
                lambda item: pokemon_image(item["url"]),
                missing,
            )
        )

    for item, image_url in zip(missing, images):
        if image_url:
            item["image"] = image_url
            item["image_source"] = "Product page image"
        else:
            image_failures += 1

    # Union Arena catalogue.
    try:
        union_arena = scrape_union_arena()
        print("Union Arena source entries:", len(union_arena))

        if not union_arena:
            raise RuntimeError("No Union Arena products were found.")

    except Exception as error:
        errors.append("Union Arena: " + str(error))
        print(errors[-1])

        union_arena = [
            item for item in old_products
            if item.get("game") == "Union Arena"
        ]

    products = remove_duplicates(pokemon + union_arena)

    # Preserve cached information from previous runs.
    for item in products:
        old = old_by_url.get(item.get("url", ""), {})

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
            if not item.get(field) and old.get(field):
                item[field] = old[field]

        if not item.get("first_seen"):
            item["first_seen"] = datetime.now(
                timezone.utc
            ).isoformat()

        item["last_seen"] = datetime.now(
            timezone.utc
        ).isoformat()

    # Release calendar combines set announcements and sealed products.
    releases = []
    release_keys = set()

    for item in pokemon_press:
        if not item.get("date"):
            continue

        key = ("Pokémon", item["url"])

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

    for item in products:
        if not item.get("release_date"):
            continue

        key = (
            item.get("game", ""),
            item.get("url", ""),
        )

        if key in release_keys:
            continue

        release_keys.add(key)

        releases.append({
            "name": item["name"],
            "game": item["game"],
            "type": item["type"],
            "date": item["release_date"],
            "msrp": item.get("msrp", ""),
            "url": item["url"],
        })

    # Keep older Pokémon release dates if the press site is unavailable.
    if not pokemon_press:
        for item in data.get("releases", []):
            if item.get("game") != "Pokémon":
                continue

            key = (
                "Pokémon",
                item.get("url", ""),
            )

            if key not in release_keys:
                releases.append(item)
                release_keys.add(key)

    data["products"] = products
    data["releases"] = releases
    data["last_updated"] = datetime.now(
        timezone.utc
    ).isoformat()
    data["check_interval_minutes"] = 5
    data["release_sources"] = list(SOURCES.values())
    data["retailer_stock_checks"] = "not_connected"
    data["monitor_errors"] = errors

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pokemon_count = sum(
        p.get("game") == "Pokémon" for p in products
    )

    union_count = sum(
        p.get("game") == "Union Arena" for p in products
    )

    pokemon_images = sum(
        bool(p.get("image"))
        for p in products
        if p.get("game") == "Pokémon"
    )

    union_images = sum(
        bool(p.get("image"))
        for p in products
        if p.get("game") == "Union Arena"
    )

    print("Monitor finished.")
    print("Pokémon products:", pokemon_count)
    print("Union Arena products:", union_count)
    print("Pokémon images:", pokemon_images)
    print("Union Arena images:", union_images)
    print("Image lookup failures:", image_failures)
    print("Total products:", len(products))
    print("Release entries:", len(releases))
    print("Errors:", len(errors))


if __name__ == "__main__":
    main()
