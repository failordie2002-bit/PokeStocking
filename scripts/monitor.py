
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "status.json"

SOURCES = {
    "Pokemon": "https://press.pokemon.com/en/Items/Schedule?period=All&sortAsc=False&sortBy=Date",
    "Union Arena": "https://www.unionarena-tcg.com/na/products/"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PokeStockMonitor/1.0)"
}


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def check_source(game, url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.select("a[href]"):
        name = clean(link.get_text(" ", strip=True))
        href = link["href"]

        if not name or len(name) < 4:
            continue

        if game == "Pokemon":
            if not re.search(r"pokemon|tcg|trading card", name, re.I):
                continue
            base = "https://press.pokemon.com"
        else:
            if not re.search(
                r"booster|starter|advanced deck|union arena|precious",
                name,
                re.I
            ):
                continue
            base = "https://www.unionarena-tcg.com"

        if href.startswith("/"):
            href = base + href

        results.append({
            "name": name,
            "game": game,
            "url": href,
            "source": url,
            "stock_status": "Not checked"
        })

    return results


def main():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {
            "products": [],
            "releases": [],
            "drawings": [],
            "history": []
        }

    releases = []
    errors = []

    for game, url in SOURCES.items():
        try:
            found = check_source(game, url)
            releases.extend(found)
            print(f"{game}: checked successfully; found {len(found)} entries")
        except Exception as error:
            errors.append(f"{game}: {error}")
            print(f"{game}: check failed: {error}")

    unique = {}
    for item in releases:
        key = (item["game"], item["name"], item["url"])
        unique[key] = item

    data["releases"] = list(unique.values())
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["check_interval_minutes"] = 5
    data["release_sources"] = list(SOURCES.values())
    data["retailer_stock_checks"] = "not_connected"
    data["monitor_errors"] = errors

    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Saved {len(data['releases'])} release entries.")


if __name__ == "__main__":
    main()
