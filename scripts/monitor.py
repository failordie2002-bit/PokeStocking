
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path("data/status.json")

SOURCES = {
    "pokemon": "https://press.pokemon.com/en/Items/Schedule?period=All&sortAsc=False&sortBy=Date",
    "union_arena": "https://www.unionarena-tcg.com/na/products/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokeStockMonitor/1.0)"
}

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
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def find_date(text):
    patterns = [
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return ""


def find_msrp(text):
    match = re.search(
        r"(?:MSRP|SRP|Retail Price)[:\s]*\$?\s*(\d+(?:\.\d{2})?)",
        text,
        re.IGNORECASE,
    )
    return "$" + match.group(1) if match else ""


def product_type(name, context=""):
    text = (name + " " + context).lower()

    if "booster box" in text or "booster display" in text:
        return "Booster Box"
    if "booster bundle" in text:
        return "Booster Bundle"
    if "booster pack" in text:
        return "Booster Pack"
    if "elite trainer box" in text or " etb" in text:
        return "Elite Trainer Box"
    if "collection" in text:
        return "Collection Box"
    if "starter deck" in text:
        return "Starter Deck"
    if "advanced deck" in text:
        return "Advanced Deck"
    if "structure deck" in text:
        return "Structure Deck"
    if "special booster" in text:
        return "Booster Box"
    return "Other"


def make_product(name, game, url, context=""):
    name = clean_text(name)
    context = clean_text(context)

    if not name or len(name) < 5:
        return None

    date = find_date(context) or find_date(name)
    msrp = find_msrp(context) or find_msrp(name)
    kind = product_type(name, context)

    return {
        "name": name,
        "game": game,
        "type": kind,
        "set": "",
        "stock_status": "Not checked",
        "image": "",
        "msrp": msrp,
        "market_price": "",
        "release_date": date,
        "sku": "",
        "url": url,
    }


def scrape_pokemon():
    products = []

    try:
        soup = get_page(SOURCES["pokemon"])

        for link in soup.find_all("a", href=True):
            name = clean_text(link.get_text(" ", strip=True))
            context = clean_text(link.parent.get_text(" ", strip=True))

            if not re.search(r"Pok[eé]mon\s+TCG", name, re.IGNORECASE):
                continue

            url = urljoin(SOURCES["pokemon"], link["href"])

            item = make_product(
                name=name,
                game="Pokémon",
                url=url,
                context=context,
            )

            if item:
                products.append(item)

    except Exception as error:
        print("Pokémon source error:", error)

    return products


def scrape_union_arena():
    products = []

    try:
        soup = get_page(SOURCES["union_arena"])

        for link in soup.find_all("a", href=True):
            name = clean_text(link.get_text(" ", strip=True))
            context = clean_text(link.parent.get_text(" ", strip=True))
            combined = (name + " " + context).lower()

            if not any(word in combined for word in [
                "booster pack",
                "booster box",
                "special booster",
                "starter deck",
                "advanced deck",
            ]):
                continue

            if len(name) < 5:
                continue

            url = urljoin(SOURCES["union_arena"], link["href"])

            item = make_product(
                name=name,
                game="Union Arena",
                url=url,
                context=context,
            )

            if item:
                products.append(item)

    except Exception as error:
        print("Union Arena source error:", error)

    return products


def remove_duplicates(items):
    unique = {}

    for item in items:
        key = (
            item["game"].lower(),
            item["name"].lower(),
            item["url"].lower(),
        )
        unique[key] = item

    return list(unique.values())


def main():
    print("Starting PokeStock monitor...")

    data = load_data()
    errors = []

    pokemon = scrape_pokemon()
    union_arena = scrape_union_arena()

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
    print("Pokémon products found:", len(pokemon))
    print("Union Arena products found:", len(union_arena))
    print("Total products:", len(products))
    print("Release entries:", len(releases))


if __name__ == "__main__":
    main()
