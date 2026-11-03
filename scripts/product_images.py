#!/usr/bin/env python3
"""PokeStock V8.3 - Product image enrichment.

Find product-specific images on existing source pages.
Never invent product records or stock information.
Preserve the existing catalogue and its metadata.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "status.json"

HEADERS = {
    "User-Agent": (
        "PokeStock/8.3 "
        "(public product metadata enrichment)"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

MAX_PRODUCTS_PER_RUN = 12

BAD_IMAGE = re.compile(
    r"logo|favicon|sprite|avatar|"
    r"banner|placeholder|social-icon|"
    r"payment|newsletter",
    re.I
)

PRODUCT_WORDS = re.compile(
    r"booster|bundle|elite trainer|"
    r"collection|starter|deck|"
    r"premium|display|tin|pack",
    re.I
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def valid_url(value):
    try:
        parsed = urlparse(str(value or ""))
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def read_data():
    data = json.loads(
        STATUS.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise ValueError("Invalid status.json")

    if not isinstance(data.get("products"), list):
        raise ValueError("Invalid products")

    if not isinstance(data.get("releases"), list):
        raise ValueError("Invalid releases")

    return data


def save_data(data):
    temp = STATUS.with_suffix(".json.tmp")

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(STATUS)


def normalize(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value or "").lower()
    ).strip()


def product_terms(name):
    words = normalize(name).split()

    stopwords = {
        "pokemon", "pokémon", "tcg",
        "the", "and", "for", "with",
        "card", "cards", "game",
        "official", "new", "set",
        "booster", "box", "pack",
        "bundle", "collection",
        "elite", "trainer", "deck",
        "premium", "starter"
    }

    return {
        word for word in words
        if len(word) >= 4
        and word not in stopwords
    }


def image_candidates(soup, base):
    candidates = []

    for selector in (
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'meta[property="twitter:image"]'
    ):
        tag = soup.select_one(selector)

        if tag:
            candidates.append(
                tag.get("content", "")
            )

    for img in soup.select("img"):
        candidates.append(
            img.get("data-src")
            or img.get("data-original")
            or img.get("src")
            or ""
        )

    result = []
    seen = set()

    for raw in candidates:
        url = urljoin(base, raw)

        if not valid_url(url):
            continue

        if BAD_IMAGE.search(
            urlparse(url).path
        ):
            continue

        if url in seen:
            continue

        seen.add(url)
        result.append(url)

    return result


def find_image(product):
    page = product.get("url", "")
    name = product.get("name", "")

    if not valid_url(page):
        return None

    if not PRODUCT_WORDS.search(name):
        return None

    response = SESSION.get(
        page,
        timeout=18,
        allow_redirects=True
    )

    response.raise_for_status()

    if not valid_url(response.url):
        raise ValueError("Invalid redirect")

    content_type = response.headers.get(
        "Content-Type", ""
    ).lower()

    if "text/html" not in content_type:
        raise ValueError("Not an HTML page")

    if len(response.content) > 4000000:
        raise ValueError("Page too large")

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    page_title = " ".join(
        [
            soup.title.get_text(" ", strip=True)
            if soup.title else "",
            (
                soup.select_one(
                    'meta[property="og:title"]'
                ) or {}
            ).get("content", "")
        ]
    )

    terms = product_terms(name)
    title_words = set(
        normalize(page_title).split()
    )

    # Require a meaningful product-name match.
    if not terms:
        return None

    overlap = len(
        terms.intersection(title_words)
    )

    if overlap < min(2, len(terms)):
        return None

    candidates = image_candidates(
        soup, response.url
    )

    if not candidates:
        return None

    # Only accept metadata images explicitly
    # supplied by the matching product page.
    metadata = []

    for selector in (
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'meta[property="twitter:image"]'
    ):
        tag = soup.select_one(selector)

        if not tag:
            continue

        url = urljoin(
            response.url,
            tag.get("content", "")
        )

        if (
            url in candidates
            and not BAD_IMAGE.search(
                urlparse(url).path
            )
        ):
            metadata.append(url)

    if not metadata:
        return None

    return {
        "image": metadata[0],
        "image_source_url": response.url,
        "image_checked_at": timestamp(),
        "image_method": "product_page_metadata",
        "image_review_status": "automatic_candidate"
    }


def main():
    data = read_data()
    products = data["products"]

    before = len(products)
    releases_before = len(data["releases"])

    cursor = int(
        data.get("v83_image_cursor", 0)
    )

    if not products:
        print("No products to inspect.")
        return

    updated = 0
    inspected = 0
    errors = []

    for offset in range(
        min(MAX_PRODUCTS_PER_RUN, len(products))
    ):
        index = (
            cursor + offset
        ) % len(products)

        product = products[index]

        if not isinstance(product, dict):
            continue

        inspected += 1

        # Keep existing images unchanged.
        if (
            valid_url(product.get("product_image"))
            or valid_url(product.get("image"))
        ):
            continue

        try:
            result = find_image(product)

            if result:
                product.update(result)
                product["product_image"] = (
                    result["image"]
                )
                updated += 1

        except Exception as exc:
            errors.append(
                str(product.get("name", ""))[:60]
                + ": "
                + str(exc)[:120]
            )

        time.sleep(0.4)

    data["v83_image_cursor"] = (
        cursor + min(
            MAX_PRODUCTS_PER_RUN,
            len(products)
        )
    ) % len(products)

    data["v83_image_enrichment"] = {
        "version": "8.3",
        "checked_at": timestamp(),
        "products_inspected": inspected,
        "images_added": updated,
        "total_products": len(products),
        "errors": errors[:15]
    }

    if len(data["products"]) != before:
        raise RuntimeError(
            "Product count changed unexpectedly"
        )

    if len(data["releases"]) != releases_before:
        raise RuntimeError(
            "Release count changed unexpectedly"
        )

    save_data(data)

    print("=== POKESTOCK V8.3 IMAGES ===")
    print("Products:", before)
    print("Inspected:", inspected)
    print("Images added:", updated)
    print("Errors:", len(errors))
    print("Existing data preserved.")


if __name__ == "__main__":
    main()
