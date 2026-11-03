
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path("data/status.json")

SOURCES = {
    "pokemon": "https://press.pokemon.com/en/Items/Schedule?period=All&types=3",
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

    return {"products": [], "releases": [], "drawings": [], "history": []}


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_date(text):
    if not text:
        return ""

    match = re.search(MONTH_DATE, text, re.IGNORECASE)
    if not match:
        return ""

    value = match.group(0).replace(",", "")
    try:
        return datetime.strptime(value, "%B %d %Y").strftime("%Y-%m-%d")
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


def pokemon_set_name(name):
    if ":" in name:
        return name.split(":", 1)[1].strip()
    return name


def pokemon_type(name):
    text = name.lower()

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
        "msrp": msrp,
        "market_price": "",
        "release_date": release_date,
        "sku": "",
        "url": url,
    }


def scrape_pokemon():
    products = []
    soup = get_page(SOURCES["pokemon"])

    for link in soup.find_all("a", href=True):
        name = clean_text(link.get_text(" ", strip=True))

        if not re.search(r"Pok[eé]mon\s+TCG\s*:", name, re.IGNORECASE):
            continue

        if "/products/" not in link["href"]:
            continue

        url = urljoin(SOURCES["pokemon"], link["href"])

        # Search nearby schedule containers for the official release date.
        context = ""
        node = link

        for _ in range(5):
            if node.parent is None:
                break
            node = node.parent
            context = clean_text(node.get_text(" ", strip=True))

            if normalize_date(context):
                break

        release_date = find_date(context)

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


def clean_union_name(raw, kind):
    text = clean_text(raw)

    # Remove the website's section heading.
    text = re.sub(
        r"^(BOOSTERS|PRECONSTRUCTED DECKS|OTHER)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove the product type prefix.
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

    # Remove release-date and MSRP information.
    text = re.split(
        r"\s+Release Date\b|\s+MSRP\b",
        text,
        flags=re.IGNORECASE,
    )[0]

    return clean_text(text)


def scrape_union_arena():
    products = []
    soup = get_page(SOURCES["union_arena"])

    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Only accept actual booster and deck product pages.
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

        name = clean_union_name(raw, kind)

        if len(name) < 3:
            continue

        url = urljoin(SOURCES["union_arena"], href)

        context = ""
        node = link

        for _ in range(4):
            if node.parent is None:
                break
            node = node.parent
            context = clean_text(node.get_text(" ", strip=True))

            if normalize_date(context) and find_msrp(context):
                break

        release_date = find_date(context)
        msrp = find_msrp(context)

        products.append(
            make_product(
                name=name,
                game="Union Arena",
                url=url,
                kind=kind,
                release_date=release_date,
                msrp=msrp,
            )
        )

    return products


def remove_duplicates(items):
    unique = {}

    for item in items:
        key = (item["game"].lower(), item["url"].lower())
        unique[key] = item

    return list(unique.values())


def main():
    print("Starting PokeStock monitor...")

    data = load_data()
    errors = []

    pokemon = []
    union_arena = []

    try:
        pokemon = scrape_pokemon()
    except Exception as error:
        errors.append("Pokémon: " + str(error))
        print(errors[-1])

    try:
        union_arena = scrape_union_arena()
    except Exception as error:
        errors.append("Union Arena: " + str(error))
        print(errors[-1])

    products = remove_duplicates(pokemon + union_arena)

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

    print("Monitor finished.")
    print("Pokémon products:", len(pokemon))
    print("Union Arena products:", len(union_arena))
    print("Total products:", len(products))
    print("Release entries:", len(releases))
    print("Errors:", len(errors))


if __name__ == "__main__":
    main()
