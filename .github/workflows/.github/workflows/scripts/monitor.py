import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "status.json"

POKEMON_URL = (
    "https://press.pokemon.com/en/Items/Schedule"
    "?period=All&sortAsc=False&sortBy=Date"
)
UNION_URL = "https://www.unionarena-tcg.com/na/products/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokeStockMonitor/1.0)"
}


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def load_existing():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "products": [],
        "releases": [],
        "drawings": [],
        "history": []
    }


def pokemon_releases():
    soup = get_page(POKEMON_URL)
    results = []

    for item in soup.select("a"):
        title = clean(item.get_text(" ", strip=True))
        href = item.get("href", "")

        if not title or not href:
            continue

        if not re.search(r"pokemon|tcg|trading card", title, re.I):
            continue

        if href.startswith("/"):
            href = "https://press.pokemon.com" + href

        results.append({
            "name": title,
            "game": "Pokemon",
            "url": href,
            "source": "Pokemon official press schedule",
            "stock_status": "Not checked"
        })

    return results


def union_releases():
    soup = get_page(UNION_URL)
    results = []

    text = clean(soup.get_text(" ", strip=True))

    # Capture product names and nearby release information
    for item in soup.select("a"):
        title = clean(item.get_text(" ", strip=True))
        href = item.get("href", "")

        if not title or len(title) < 4:
            continue

        if not re.search(
            r"booster|starter|advanced deck|union arena|precious",
            title,
            re.I
        ):
            continue

        if href.startswith("/"):
            href = "https://www.unionarena-tcg.com" + href

        results.append({
            "name": title,
            "game": "Union Arena",
            "url": href or UNION_URL,
            "source": "Bandai official product catalogue",
            "stock_status": "Not checked"
        })

    return results


def main():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = load_existing()

    releases = []
    errors = []

    for name, function in [
        ("Pokemon", pokemon_releases),
        ("Union Arena", union_releases)
    ]:
        try:
            releases.extend(function())
            print(f"{name}: source checked successfully")
        except Exception as error:
            errors.append(f"{name}: {error}")
            print(f"{name}: source check failed: {error}")

    # Remove duplicate products by name and URL
    unique = {}
    for item in releases:
        key = (item["game"], item["name"], item["url"])
        unique[key] = item

    data["releases"] = list(unique.values())
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["check_interval_minutes"] = 5
    data["release_sources"] = [
        POKEMON_URL,
        UNION_URL
    ]
    data["retailer_stock_checks"] = "not_connected"
    data["monitor_errors"] = errors

    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Saved {len(data['releases'])} release entries.")


if __name__ == "__main__":
    main()
