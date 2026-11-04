#!/usr/bin/env python3
"""Merge Pokestock's existing independently collected online offers.

A product listed as in stock was observed at CHECK TIME only.
Never infer pickup, checkout success, or physical shelf inventory.
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path('data')
INPUTS = ('v34_inventory.json', 'online_offers.json')
OUTPUT = ROOT / 'unified_online_39.json'
REPORT = ROOT / 'unified_online_report_39.json'
STATES = {'In stock', 'Out of stock', 'Preorder', 'Backorder'}
NOW = datetime.now(timezone.utc)

def read(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []

def dt(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None

def uri(value):
    try:
        p = urlsplit(str(value))
        if p.scheme != 'https' or not p.hostname: return ''
        return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/'), '', ''))
    except (ValueError, TypeError):
        return ''

def clean(v, limit=400):
    return ' '.join(str(v or '').split())[:limit]

def save(path, value):
    data = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == data:
        return False
    path.write_text(data, encoding='utf-8')
    return True

def main():
    merged = {}
    counts = {}

    for source in INPUTS:
        rows = read(ROOT / source)
        counts[source] = len(rows)

        for row in rows:
            if not isinstance(row, dict): continue
            if row.get('inventory_scope') != 'online': continue
            if row.get('availability') not in STATES: continue

            stamp = dt(row.get('checked_at'))
            if not stamp or stamp > NOW + timedelta(minutes=10): continue
            if NOW - stamp > timedelta(hours=36): continue

            product = clean(row.get('product_name'), 300)
            retailer = clean(row.get('retailer'), 120)
            product_url = uri(row.get('product_url'))
            evidence_url = uri(row.get('evidence_url'))

            if not product or not retailer or not product_url or not evidence_url:
                continue

            normalized = dict(row)
            normalized['product_name'] = product
            normalized['retailer'] = retailer
            normalized['product_url'] = product_url
            normalized['evidence_url'] = evidence_url
            normalized['inventory_scope'] = 'online'
            normalized['checked_at'] = stamp.isoformat()
            normalized['evidence_summary'] = 'Observed at retailer check time; current stock not guaranteed'

            # Preserve different SKUs and product variants separately.
            key = (
                retailer.casefold(),
                product_url,
                clean(row.get('sku'), 100),
                clean(row.get('variant'), 100)
            )

            old = merged.get(key)
            old_stamp = dt(old['checked_at']) if old else None

            if not old_stamp or stamp > old_stamp:
                merged[key] = normalized

    offers = sorted(
        merged.values(),
        key=lambda v: (
            v['availability'] != 'In stock',
            -dt(v['checked_at']).timestamp(),
            v['retailer'].casefold(),
            v['product_name'].casefold()
        )
    )

    available = [
        x for x in offers if x['availability'] == 'In stock'
    ]

    report = {
        'version': '39.0',
        'source': 'Pokestock direct merchant observations',
        'sources': counts,
        'merged_offers': len(offers),
        'in_stock_at_last_observation': len(available),
        'retailers': dict(sorted(
            Counter(x['retailer'] for x in offers).items()
        )),
        'newest_observation': max(
            (x['checked_at'] for x in offers),
            default=None
        ),
        'confirmed_shelf_stock': 0,
        'confirmed_checkout_success': 0,
        'note': 'Availability is historical storefront evidence, not guaranteed live inventory.'
    }

    save(OUTPUT, offers)
    save(REPORT, report)
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
