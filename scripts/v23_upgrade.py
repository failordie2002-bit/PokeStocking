
#!/usr/bin/env python3
"""PokéStock V23: pickup checks + website enhancement.

No API keys. No invented store inventory.
Preserves the existing PokéStock website and datasets.
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
HTML = ROOT / "index.html"

OFFERS = DATA / "online_offers.json"
RETAILERS = DATA / "online_retailers.json"
RESULTS = DATA / "v23_pickup_observations.json"
REPORT = DATA / "v23_pickup_report.json"

NOW = datetime.now(timezone.utc).isoformat()
MAX_CHECKS = 36

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "PokeStock/23 public product checker",
    "Accept": "text/html,application/json",
})

POSITIVE = re.compile(
    r"\b(ready for pickup|available for pickup|"
    r"pickup available|pick up today|"
    r"available to pick up)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(unavailable for pickup|"
    r"not available for pickup|"
    r"pickup unavailable|"
    r"not ready for pickup|"
    r"out of stock)\b",
    re.I,
)


def read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp.replace(path)


def clean(value):
    return " ".join(str(value or "").split())


def origin(url):
    try:
        p = urlparse(url)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username
            or p.password
            or p.port not in (None, 443)
        ):
            return None
        return "https://" + p.hostname.lower()
    except ValueError:
        return None


def get(url, as_json=False):
    try:
        response = SESSION.get(
            url,
            timeout=(7, 14),
            allow_redirects=False,
        )
        if response.status_code != 200:
            return None
        if len(response.content) > 1500000:
            return None
        time.sleep(0.25)
        return (
            response.json()
            if as_json else response.text
        )
    except (requests.RequestException, ValueError):
        return None


def candidates():
    offers = read(OFFERS, [])
    retailers = read(RETAILERS, [])

    domains = {}

    for retailer in retailers:
        if not isinstance(retailer, dict):
            continue
        base = origin(retailer.get("base", ""))
        if base:
            domains[retailer.get("name")] = base

    rows = []
    seen = set()

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        name = offer.get("retailer")
        base = domains.get(name)

        if not base:
            continue

        url = offer.get("product_url", "")
        if origin(url) != base:
            continue

        match = re.match(
            r"^/products/([a-zA-Z0-9_-]+)",
            urlparse(url).path,
        )

        if not match:
            continue

        handle = match.group(1)
        key = (base, handle, str(offer.get("sku", "")))

        if key in seen:
            continue

        seen.add(key)
        rows.append((offer, base, handle))

    return sorted(
        rows,
        key=lambda x: (
            x[0].get("retailer", ""),
            x[2],
            str(x[0].get("sku", "")),
        ),
    )


def select_variant(product, offer):
    variants = product.get("variants", [])

    if not isinstance(variants, list):
        return None

    sku = clean(offer.get("sku"))
    title = clean(offer.get("variant"))

    if sku:
        matches = [
            v for v in variants
            if clean(v.get("sku")) == sku
        ]
        if len(matches) == 1:
            return matches[0]

    if title and title != "Product listing":
        matches = [
            v for v in variants
            if clean(v.get("title")) == title
        ]
        if len(matches) == 1:
            return matches[0]

    if len(variants) == 1:
        return variants[0]

    return None


def extract_pickup(html, offer, variant, url):
    soup = BeautifulSoup(html, "html.parser")
    output = []

    # Shopify Dawn-style pickup location cards.
    items = soup.select(
        ".pickup-availability-list__item"
    )

    for item in items:
        heading = item.select_one(
            "h3, h4, .pickup-availability-list__item-title"
        )

        if heading is None:
            continue

        location = clean(
            heading.get_text(" ", strip=True)
        )

        if not location:
            continue

        # Only evaluate the availability text
        # belonging to this particular location.
        info = item.select_one(
            ".pickup-availability-list__item-info"
        )

        if info is None:
            continue

        status_text = clean(
            info.get_text(" ", strip=True)
        )

        positive = bool(POSITIVE.search(status_text))
        negative = bool(NEGATIVE.search(status_text))

        # Do not interpret ambiguous markup.
        if positive == negative:
            continue

        status = (
            "Pickup available"
            if positive else "Pickup unavailable"
        )

        output.append({
            "retailer": offer.get("retailer"),
            "game": offer.get("game"),
            "product_name": offer.get("product_name"),
            "product_url": offer.get("product_url"),
            "location_name": location,
            "variant_id": str(variant["id"]),
            "variant": clean(variant.get("title")),
            "availability": status,
            "inventory_scope": "store_pickup",
            "shelf_stock_confirmed": False,
            "exact_quantity": None,
            "evidence_type":
                "explicit_public_pickup_location_text",
            "evidence_url": url,
            "checked_at": NOW,
        })

    return output


def check_pickup():
    rows = candidates()
    previous = read(REPORT, {})

    cursor = int(previous.get("next_cursor", 0))

    if rows:
        cursor %= len(rows)

    count = min(MAX_CHECKS, len(rows))
    batch = [
        rows[(cursor + i) % len(rows)]
        for i in range(count)
    ]

    observations = []
    checks = []
    cache = {}

    for offer, base, handle in batch:
        key = (base, handle)

        if key not in cache:
            url = (
                base + "/products/"
                + quote(handle) + ".js"
            )
            cache[key] = get(url, as_json=True)

        product = cache[key]

        if not isinstance(product, dict):
            checks.append({
                "retailer": offer.get("retailer"),
                "product": handle,
                "status": "public_product_endpoint_unavailable",
            })
            continue

        variant = select_variant(product, offer)

        if not variant or not variant.get("id"):
            checks.append({
                "retailer": offer.get("retailer"),
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
                base + "/variants/"
                + quote(str(variant["id"]))
                + "/?section_id=" + section
            )

            html = get(url)

            if not html:
                continue

            found = extract_pickup(
                html, offer, variant, url
            )

            if found:
                break

        observations.extend(found)

        checks.append({
            "retailer": offer.get("retailer"),
            "product": handle,
            "status": (
                "verified_pickup_text"
                if found else
                "no_explicit_pickup_evidence"
            ),
            "observations": len(found),
        })

    unique = {}

    for row in observations:
        key = (
            row["retailer"],
            row["variant_id"],
            row["location_name"],
        )
        unique[key] = row

    observations = list(unique.values())

    report = {
        "version": "23.0",
        "checked_at": NOW,
        "candidate_offers": len(rows),
        "checked_this_run": count,
        "next_cursor": (
            (cursor + count) % len(rows)
            if rows else 0
        ),
        "verified_pickup_observations":
            len(observations),
        "pickup_available": sum(
            x["availability"] == "Pickup available"
            for x in observations
        ),
        "pickup_unavailable": sum(
            x["availability"] == "Pickup unavailable"
            for x in observations
        ),
        "physical_shelf_stock_confirmed": 0,
        "checks": checks,
    }

    save(RESULTS, observations)
    save(REPORT, report)

    print(
        "Products checked:", count,
        "| Pickup observations:", len(observations),
    )


DASHBOARD = r"""
<section id="pickup" class="panel">
  <div class="section-label">Store-specific evidence</div>
  <h2>Pickup Availability</h2>
  <p class="muted">
    Only explicit public pickup-location observations
    appear here. Pickup does not guarantee items
    are physically on a shelf. Missing results mean
    Unknown, not Out of Stock.
  </p>
  <div class="controls">
    <input id="v23Search"
      placeholder="Search products, stores, games">
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
  <p id="v23Info" class="muted">Loading pickup data...</p>
  <div id="v23Grid" class="grid"></div>
</section>
"""

JS = r"""
<script>
(function(){
  "use strict";

  const esc = value => String(value ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&":"&amp;",
      "<":"&lt;",
      ">":"&gt;",
      '"':"&quot;",
      "'":"&#39;"
    }[c])
  );

  let rows = [];
  let report = {};

  function safeLink(url,label){
    try{
      const parsed = new URL(url);
      if(parsed.protocol !== "https:") return "";
      return `<a class="action" target="_blank"
        rel="noopener noreferrer"
        href="${esc(parsed.href)}">${esc(label)}</a>`;
    }catch{
      return "";
    }
  }

  function render(){
    const search = document.getElementById("v23Search")
      .value.toLowerCase().trim();

    const state = document.getElementById("v23State")
      .value;

    const fresh = rows.filter(r=>{
      const age = Date.now() - Date.parse(r.checked_at);
      return Number.isFinite(age)
        && age >= 0
        && age <= 8 * 3600000
        && r.inventory_scope === "store_pickup"
        && r.shelf_stock_confirmed === false
        && [
          "Pickup available",
          "Pickup unavailable"
        ].includes(r.availability)
        && r.location_name
        && r.evidence_url;
    });

    const matched = fresh.filter(r=>{
      const text = [
        r.product_name,
        r.retailer,
        r.location_name,
        r.game
      ].join(" ").toLowerCase();

      return (!search || text.includes(search))
        && (!state || r.availability === state);
    });

    document.getElementById("v23Info").textContent =
      matched.length + " matching fresh pickup observations. " +
      "Checked: " + (report.checked_at || "Unknown") +
      ". Physical shelf quantities: unverified.";

    document.getElementById("v23Grid").innerHTML =
      matched.map(r=>`
        <article class="tile">
          <h3>${esc(r.product_name)}</h3>
          <p><strong>${esc(r.retailer)}</strong></p>
          <p>Pickup location: ${esc(r.location_name)}</p>
          <p>${esc(r.game || "Trading cards")}</p>
          <span class="pill ${
            r.availability === "Pickup available"
              ? "in" : "out"
          }">${esc(r.availability)}</span>
          <p class="muted">
            Store pickup only; shelf stock not confirmed.
          </p>
          <p class="muted">
            Checked: ${esc(
              new Date(r.checked_at).toLocaleString()
            )}
          </p>
          ${safeLink(r.product_url,"View product")}
          ${safeLink(r.evidence_url,"Pickup evidence")}
        </article>
      `).join("") ||
      `<div class="empty">
        No verified pickup observations match.
        This does not mean the products are sold out.
      </div>`;
  }

  async function load(){
    try{
      const [a,b] = await Promise.all([
        fetch(
          "data/v23_pickup_observations.json?v=" +
          Date.now(),
          {cache:"no-store"}
        ),
        fetch(
          "data/v23_pickup_report.json?v=" +
          Date.now(),
          {cache:"no-store"}
        )
      ]);

      if(!a.ok || !b.ok) throw Error("Data unavailable");

      rows = await a.json();
      report = await b.json();

      if(!Array.isArray(rows)) rows = [];

    }catch(error){
      rows = [];
      report = {};
      console.warn("V23 pickup data:",error);
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


def patch_website():
    if not HTML.exists():
        raise FileNotFoundError("index.html not found")

    html = HTML.read_text(encoding="utf-8")

    if 'id="pickup"' in html:
        print("V23 dashboard already installed")
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
            "Website structure changed; "
            "refusing unsafe HTML modification"
        )

    html = html.replace(
        nav_anchor,
        '<button data-tab="pickup">📍 Pickup</button>\n    '
        + nav_anchor,
        1,
    )

    html = html.replace(
        section_anchor,
        DASHBOARD + "\n" + section_anchor,
        1,
    )

    html = html.replace(
        "</body>",
        JS + "\n</body>",
        1,
    )

    HTML.write_text(html, encoding="utf-8")
    print("V23 dashboard installed successfully")


if __name__ == "__main__":
    check_pickup()
    patch_website()
