
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path("data/status.json")

SOURCES = {
    "pokemon": (
        "https://press.pokemon.com/en/Items/Schedule"
        "?period=All&types=3&sortAsc=False&sortBy=Date"
    ),
    "union_arena": "https://www.unionarena-tcg.com/na/products/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokeStockMonitor/1.0)"
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


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_date(text):
    if not text:
        return ""

    quarter = re.search(
        r"\bQ([1-4])\s+(\d{4})\b", text, re.IGNORECASE
    )

    if quarter:
        return f"Q{quarter.group(1)} {quarter.group(2)}"

    match = re.search(MONTH_DATE, text, re.IGNORECASE)

    if not match:
        return ""

    value = match.group(0).replace(",", "")

    try:
        return datetime.strptime(
            value, "%B %d %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def find_date(text):
    return normalize_date(text)


def find_msrp(text):
    match = re.search(
        r"(?:MSRP|SRP|Retail Price)[:\s]*\$?\s*(\d+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    return "$" + match.group(1) if match else ""


def pokemon_type(name):
    text = name.lower()

    if "battle deck" in text:
        return "Battle Deck"
    if "battle academy" in text:
        return "Battle Academy"
    if "collection" in text:
        return "Collection"
    if "trick or trade" in text:
        return "Booster Bundle"
    if "mega evolution" in text or "scarlet & violet" in text:
        return "Expansion"

    return "Other"


def make_product(name, game, url, kind, release_date="", msrp=""):
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
        "release_date": release_date,
        "sku": "",
        "url": url,
    }


def pokemon_image(url):
    """Find a product image on an individual Pokémon press page."""
    try:
        soup = get_page(url)

        # Prefer page-level image metadata.
        for meta in soup.find_all("meta"):
            key = meta.get("property", "").lower()
            name = meta.get("name", "").lower()

            if key in ("og:image", "og:image:secure_url") or name == "twitter:image":
                content = meta.get("content", "").strip()
                if content:
                    return urljoin(url, content)

        # Fallback to product-shot images.
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")

            if not src:
                continue

            candidate = urljoin(url, src)
            marker = candidate.lower()

            if any(word in marker for word in (
                "product", "shot", "press"
            )):
                return candidate

    except Exception as error:
        print("Pokémon image lookup failed:", url, error)

    return ""


def scrape_pokemon():
    products = []
    soup = get_page(SOURCES["pokemon"])

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

        url = urljoin(SOURCES["pokemon"], link["href"])

        context = ""
        node = link

        for _ in range(5):
            if node.parent is None:
                break

            node = node.parent
            candidate = clean_text(node.get_text(" ", strip=True))

            if find_date(candidate):
                context = candidate
                break

        release_date = find_date(context)

        if "battle deck" in name.lower():
            release_date = ""

        products.append(
            make_product(
                name=name,
                game="Pokémon",
                url=url,
                kind=pokemon_type(name),
                release_date=release_date,
            )
        )

    return products


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
    """Find a thumbnail belonging to this Union Arena product card."""
    nodes = [link]
    node = link

    # Product images are sometimes inside the link and sometimes
    # inside its immediate card container.
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
                and ("/boosters/" in lower or "/decks/" in lower)
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
            candidate = clean_text(node.get_text(" ", strip=True))

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
            link, SOURCES["union_arena"]
        )

        if product["image"]:
            product["image_source"] = "Union Arena official catalogue"

        products.append(product)

    return products


def remove_duplicates(items):
    unique = {}

    for item in items:
        key = (
            item["game"].lower(),
            item["url"].lower(),
        )
        unique[key] = item

    return list(unique.values())


def main():
    print("Starting PokeStock monitor...")

    data = load_data()
    old_products = data.get("products", [])
    errors = []

    old_by_url = {
        item.get("url", ""): item
        for item in old_products
        if item.get("url")
    }

    try:
        pokemon = scrape_pokemon()
        print("Pokémon source entries:", len(pokemon))

        # Reuse cached images; retrieve missing ones.
        missing = [
            item for item in pokemon
            if not old_by_url.get(item["url"], {}).get("image")
        ]

        print("Pokémon images to retrieve:", len(missing))

        with ThreadPoolExecutor(max_workers=8) as executor:
            images = list(
                executor.map(
                    lambda item: pokemon_image(item["url"]),
                    missing,
                )
            )

        for item, image_url in zip(missing, images):
            item["image"] = image_url
            if image_url:
                item["image_source"] = "Pokémon official press page"

    except Exception as error:
        pokemon = [
            item for item in old_products
            if item.get("game") == "Pokémon"
        ]
        errors.append("Pokémon: " + str(error))
        print(errors[-1])

    try:
        union_arena = scrape_union_arena()
        print("Union Arena source entries:", len(union_arena))

    except Exception as error:
        union_arena = [
            item for item in old_products
            if item.get("game") == "Union Arena"
        ]
        errors.append("Union Arena: " + str(error))
        print(errors[-1])

    products = remove_duplicates(pokemon + union_arena)

    # Preserve previously retrieved images and other existing fields.
    for item in products:
        old = old_by_url.get(item["url"], {})

        for field in ("image", "image_source", "sku", "set", "market_price"):
            if not item.get(field) and old.get(field):
                item[field] = old[field]

    releases = []

    for item in products:
        if item.get("release_date"):
            releases.append({
                "name": item["name"],
                "game": item["game"],
                "type": item["type"],
                "date": item["release_date"],
                "msrp": item["msrp"],
                "url": item["url"],
            })

    data["products"] = products
    data["releases"] = releases
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["check_interval_minutes"] = 5
    data["release_sources"] = list(SOURCES.values())
    data["retailer_stock_checks"] = "not_connected"
    data["monitor_errors"] = errors

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pokemon_images = sum(
        bool(p.get("image")) for p in products
        if p.get("game") == "Pokémon"
    )
    union_images = sum(
        bool(p.get("image")) for p in products
        if p.get("game") == "Union Arena"
    )

    print("Monitor finished.")
    print("Pokémon products:", sum(p["game"] == "Pokémon" for p in products))
    print("Union Arena products:", sum(p["game"] == "Union Arena" for p in products))
    print("Pokémon images:", pokemon_images)
    print("Union Arena images:", union_images)
    print("Total products:", len(products))
    print("Release entries:", len(releases))
    print("Errors:", len(errors))


if __name__ == "__main__":
    main()
