
#!/usr/bin/env python3
"""
PokéStock V23.1
Complete Shopify Pickup Monitor + Website Upgrade

- Corrects Shopify Dawn pickup selectors
- Checks publicly available product variants
- Detects explicit pickup availability by location
- Keeps online, pickup, and shelf stock separate
- Adds a Pickup tab to the existing website
- Rotates product checks between runs
- Requires no API key
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

OFFERS_FILE = DATA / "online_offers.json"
RETAILERS_FILE = DATA / "online_retailers.json"
RESULTS_FILE = DATA / "v23_pickup_observations.json"
REPORT_FILE = DATA / "v23_pickup_report.json"
HTML_FILE = ROOT / "index.html"

NOW = datetime.now(timezone.utc).isoformat()
MAX_CHECKS = 36

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "PokeStock/23.1 public availability checker",
    "Accept": "text/html,application/json",
})

POSITIVE = re.compile(
    r"\b(ready for pickup|available for pickup|"
    r"pickup available|pick up today|"
    r"available to pick up|pickup ready)\b",
    re.I,
)

NEGATIVE = re.compile(
    r"\b(unavailable for pickup|"
    r"not available for pickup|"
    r"pickup unavailable|"
    r"not ready for pickup|"
    r"out of stock|not available)\b",
    re.I,
)


def load_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def safe_origin(value):
    try:
        parsed = urlparse(value)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return None

        return "https://" + parsed.hostname.lower()

    except (ValueError, TypeError):
        return None


def fetch(url, as_json=False):
    try:
        response = SESSION.get(
            url,
            timeout=(7, 15),
            allow_redirects=False,
        )

        if response.status_code != 200:
            return None

        if len(response.content) > 1_500_000:
            return None

        time.sleep(0.3)

        return (
            response.json()
            if as_json
            else response.text
        )

    except (requests.RequestException, ValueError):
        return None


def discover_candidates():
    offers = load_json(OFFERS_FILE, [])
    retailers = load_json(RETAILERS_FILE, [])

    domains = {}

    for retailer in retailers:
        if not isinstance(retailer, dict):
            continue

        base = safe_origin(
            retailer.get("base", "")
        )

        if base:
            domains[retailer.get("name")] = base

    candidates = []
    seen = set()

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        retailer = offer.get("retailer")
        base = domains.get(retailer)

        if not base:
            continue

        url = offer.get("product_url", "")

        if safe_origin(url) != base:
            continue

        match = re.match(
            r"^/products/([a-zA-Z0-9_-]+)",
            urlparse(url).path,
        )

        if not match:
            continue

        handle = match.group(1)

        key = (
            base,
            handle,
            str(offer.get("sku", "")),
        )

        if key in seen:
            continue

        seen.add(key)

        candidates.append(
            (offer, base, handle)
        )

    candidates.sort(
        key=lambda item: (
            item[0].get("retailer", ""),
            item[2],
            str(item[0].get("sku", "")),
        )
    )

    return candidates


def select_variant(product, offer):
    variants = product.get("variants", [])

    if not isinstance(variants, list):
        return None

    sku = clean(offer.get("sku"))
    title = clean(offer.get("variant"))

    if sku:
        matches = [
            variant
            for variant in variants
            if clean(variant.get("sku")) == sku
        ]

        if len(matches) == 1:
            return matches[0]

    if title and title.lower() != "product listing":
        matches = [
            variant
            for variant in variants
            if clean(variant.get("title")) == title
        ]

        if len(matches) == 1:
            return matches[0]

    if len(variants) == 1:
        return variants[0]

    return None


def pickup_status(text):
    text = clean(text)

    positive = bool(POSITIVE.search(text))
    negative = bool(NEGATIVE.search(text))

    if positive and not negative:
        return "Pickup available"

    if negative and not positive:
        return "Pickup unavailable"

    return None


def parse_pickup(html, offer, variant, evidence_url):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    observations = []

    # Shopify Dawn and compatible themes.
    locations = soup.select(
        ".pickup-availability-list__item"
    )

    for item in locations:

        heading = item.select_one(
            ".pickup-availability-list__location, "
            ".pickup-availability-list__item-title, "
            "h3, h4"
        )

        if heading is None:
            continue

        location_name = clean(
            heading.get_text(" ", strip=True)
        )

        if not location_name:
            continue

        stock_element = item.select_one(
            ".pickup-availability-list__stock, "
            ".pickup-availability-list__item-info"
        )

        if stock_element is None:
            continue

        stock_text = clean(
            stock_element.get_text(
                " ",
                strip=True,
            )
        )

        status = pickup_status(stock_text)

        if status is None:
            continue

        observations.append({
            "retailer": offer.get("retailer"),
            "game": offer.get("game"),
            "product_name":
                offer.get("product_name"),
            "product_url":
                offer.get("product_url"),
            "location_name": location_name,
            "variant_id":
                str(variant.get("id")),
            "variant":
                clean(variant.get("title")),
            "availability": status,
            "inventory_scope": "store_pickup",
            "shelf_stock_confirmed": False,
            "exact_quantity": None,
            "evidence_type":
                "explicit_public_pickup_location_text",
            "evidence_url": evidence_url,
            "checked_at": NOW,
        })

    return observations


def run_monitor():
    candidates = discover_candidates()

    previous_report = load_json(
        REPORT_FILE,
        {},
    )

    cursor = int(
        previous_report.get("next_cursor", 0)
    )

    if candidates:
        cursor %= len(candidates)

    count = min(
        MAX_CHECKS,
        len(candidates),
    )

    batch = [
        candidates[
            (cursor + index) % len(candidates)
        ]
        for index in range(count)
    ]

    observations = []
    checks = []
    cache = {}

    for offer, base, handle in batch:

        key = (base, handle)

        if key not in cache:
            product_url = (
                base
                + "/products/"
                + quote(handle)
                + ".js"
            )

            cache[key] = fetch(
                product_url,
                as_json=True,
            )

        product = cache[key]

        if not isinstance(product, dict):
            checks.append({
                "retailer":
                    offer.get("retailer"),
                "product": handle,
                "status":
                    "public_product_endpoint_unavailable",
            })
            continue

        variant = select_variant(
            product,
            offer,
        )

        if not variant or not variant.get("id"):
            checks.append({
                "retailer":
                    offer.get("retailer"),
                "product": handle,
                "status": "variant_unresolved",
            })
            continue

        found = []

        for section in (
            "pickup-availability",
            "store-availability",
        ):

            url = (
                base
                + "/variants/"
                + quote(str(variant["id"]))
                + "/?section_id="
                + section
            )

            html = fetch(url)

            if not html:
                continue

            found = parse_pickup(
                html,
                offer,
                variant,
                url,
            )

            if found:
                break

        observations.extend(found)

        checks.append({
            "retailer":
                offer.get("retailer"),
            "product": handle,
            "status": (
                "verified_pickup_text"
                if found
                else "no_explicit_pickup_evidence"
            ),
            "observations": len(found),
        })

    unique = {}

    for observation in observations:
        key = (
            observation["retailer"],
            observation["variant_id"],
            observation["location_name"],
        )
        unique[key] = observation

    observations = list(unique.values())

    report = {
        "version": "23.1",
        "checked_at": NOW,
        "candidate_offers": len(candidates),
        "checked_this_run": count,
        "next_cursor": (
            (cursor + count) % len(candidates)
            if candidates
            else 0
        ),
        "verified_pickup_observations":
            len(observations),
        "pickup_available": sum(
            row["availability"]
            == "Pickup available"
            for row in observations
        ),
        "pickup_unavailable": sum(
            row["availability"]
            == "Pickup unavailable"
            for row in observations
        ),
        "physical_shelf_stock_confirmed": 0,
        "checks": checks,
    }

    save_json(
        RESULTS_FILE,
        observations,
    )

    save_json(
        REPORT_FILE,
        report,
    )

    print("PokéStock V23.1")
    print("Eligible offers:", len(candidates))
    print("Checked:", count)
    print(
        "Verified pickup observations:",
        len(observations),
    )
    print(
        "Available for pickup:",
        report["pickup_available"],
    )
    print(
        "Unavailable for pickup:",
        report["pickup_unavailable"],
    )


PICKUP_SECTION = """
<section id="pickup" class="panel">
  <div class="section-label">
    Verified pickup observations
  </div>

  <h2>Store Pickup Availability</h2>

  <p class="muted">
    Results require explicit pickup information
    for a named retail location.
    Pickup availability does not guarantee
    products are physically on a shelf.
    Missing information means Unknown.
  </p>

  <div class="controls">
    <input
      id="v23Search"
      placeholder="Search products or locations"
    >

    <select id="v23State">
      <option value="">All pickup statuses</option>
      <option value="Pickup available">
        Pickup available
      </option>
      <option value="Pickup unavailable">
        Pickup unavailable
      </option>
    </select>
  </div>

  <p id="v23Info" class="muted">
    Loading pickup observations...
  </p>

  <div id="v23Grid" class="grid"></div>
</section>
"""

PICKUP_SCRIPT = r"""
<script>
(function(){
  "use strict";

  const escapeHTML = value =>
    String(value ?? "").replace(
      /[&<>"']/g,
      c => ({
        "&":"&amp;",
        "<":"&lt;",
        ">":"&gt;",
        '"':"&quot;",
        "'":"&#39;"
      }[c])
    );

  let observations = [];
  let report = {};

  function link(url,label){
    try{
      const u = new URL(url);

      if(u.protocol !== "https:"){
        return "";
      }

      return `<a class="action"
        href="${escapeHTML(u.href)}"
        target="_blank"
        rel="noopener noreferrer">
        ${escapeHTML(label)}
      </a>`;

    }catch{
      return "";
    }
  }

  function render(){
    const search = document
      .getElementById("v23Search")
      .value.trim().toLowerCase();

    const filter = document
      .getElementById("v23State")
      .value;

    const fresh = observations.filter(row=>{
      const checked = Date.parse(row.checked_at);
      const age = Date.now() - checked;

      return Number.isFinite(checked)
        && age >= 0
        && age <= 8 * 3600000
        && row.inventory_scope === "store_pickup"
        && row.shelf_stock_confirmed === false
        && [
          "Pickup available",
          "Pickup unavailable"
        ].includes(row.availability)
        && row.location_name
        && row.evidence_url;
    });

    const matched = fresh.filter(row=>{
      const text = [
        row.product_name,
        row.retailer,
        row.location_name,
        row.game
      ].join(" ").toLowerCase();

      return (!search || text.includes(search))
        && (!filter || row.availability === filter);
    });

    document.getElementById("v23Info")
      .textContent =
        matched.length
        + " fresh pickup observations. Last check: "
        + (report.checked_at || "Unknown")
        + ". Shelf stock not verified.";

    document.getElementById("v23Grid")
      .innerHTML =
        matched.map(row=>`
          <article class="tile">
            <h3>
              ${escapeHTML(row.product_name)}
            </h3>

            <p>
              ${escapeHTML(row.retailer)}
            </p>

            <p>
              Pickup location:
              ${escapeHTML(row.location_name)}
            </p>

            <p>
              ${escapeHTML(row.game || "TCG")}
            </p>

            <span class="pill ${
              row.availability === "Pickup available"
                ? "in" : "out"
            }">
              ${escapeHTML(row.availability)}
            </span>

            <p class="muted">
              Store pickup only.
              Shelf inventory not confirmed.
            </p>

            <p class="muted">
              Checked:
              ${escapeHTML(
                new Date(
                  row.checked_at
                ).toLocaleString()
              )}
            </p>

            ${link(
              row.product_url,
              "View product"
            )}

            ${link(
              row.evidence_url,
              "View evidence"
            )}
          </article>
        `).join("")
        || `<div class="empty">
          No verified pickup observations.
          This does not mean products
          are out of stock.
        </div>`;
  }

  async function load(){
    try{
      const [a,b] = await Promise.all([
        fetch(
          "data/v23_pickup_observations.json?v="
          + Date.now(),
          {cache:"no-store"}
        ),
        fetch(
          "data/v23_pickup_report.json?v="
          + Date.now(),
          {cache:"no-store"}
        )
      ]);

      if(!a.ok || !b.ok){
        throw Error("Data unavailable");
      }

      observations = await a.json();
      report = await b.json();

      if(!Array.isArray(observations)){
        observations = [];
      }

    }catch(error){
      console.warn(error);
      observations = [];
      report = {};
    }

    render();
  }

  document.getElementById("v23Search")
    .addEventListener("input",render);

  document.getElementById("v23State")
    .addEventListener("change",render);

  load();
})();
</script>
"""


def upgrade_website():
    if not HTML_FILE.exists():
        raise FileNotFoundError(
            "index.html is missing"
        )

    html = HTML_FILE.read_text(
        encoding="utf-8"
    )

    # V23 already installed the pickup tab.
    # Do not duplicate it.
    if 'id="pickup"' in html:
        print(
            "Pickup dashboard already installed."
        )
        return

    nav_anchor = (
        '<button data-tab="products">'
    )

    section_anchor = (
        '    <section id="products"'
    )

    if (
        nav_anchor not in html
        or section_anchor not in html
        or "</body>" not in html
    ):
        raise RuntimeError(
            "Website structure not recognized."
        )

    html = html.replace(
        nav_anchor,
        '<button data-tab="pickup">'
        '📍 Pickup</button>\n    '
        + nav_anchor,
        1,
    )

    html = html.replace(
        section_anchor,
        PICKUP_SECTION
        + "\n"
        + section_anchor,
        1,
    )

    html = html.replace(
        "</body>",
        PICKUP_SCRIPT
        + "\n</body>",
        1,
    )

    HTML_FILE.write_text(
        html,
        encoding="utf-8",
    )

    print("Pickup dashboard installed.")


def main():
    run_monitor()
    upgrade_website()


if __name__ == "__main__":
    main()
