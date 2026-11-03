#!/usr/bin/env python3
"""PokéStock V24: verified store-specific inventory join and diagnostics.

Reads current local pickup and inventory observations, matches only uniquely
identified physical stores, and publishes map-ready records. Does not invent
retailer inventory or treat online stock as local stock.
"""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
NOW = datetime.now(timezone.utc)
MAX_AGE_HOURS = 8


def load(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save(name, value):
    target = DATA / name
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(target)


def norm(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).split())


def fresh(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        age = (NOW - stamp.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= MAX_AGE_HOURS * 3600
    except (TypeError, ValueError):
        return False


def valid_url(value):
    try:
        p = urlparse(str(value))
        return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def main():
    stores = load('stores.json', [])
    pickups = load('v23_pickup_observations.json', [])
    status = load('status.json', {})
    inventory = status.get('store_inventory', []) if isinstance(status, dict) else []
    stores = stores if isinstance(stores, list) else []
    pickups = pickups if isinstance(pickups, list) else []
    inventory = inventory if isinstance(inventory, list) else []

    by_id = {str(s.get('id')): s for s in stores if isinstance(s, dict) and s.get('id')}
    by_name = {}
    for s in stores:
        if not isinstance(s, dict) or not s.get('id'):
            continue
        key = norm(s.get('name'))
        if key:
            by_name.setdefault(key, []).append(s)

    confirmed = []
    unresolved = Counter()
    seen = set()

    def add(store, record, availability, kind, evidence):
        key = (str(store['id']), str(record.get('product_name')), str(record.get('variant_id', '')), availability, kind)
        if key in seen:
            return
        seen.add(key)
        confirmed.append({
            'store_id': str(store['id']),
            'store_name': store.get('name'),
            'store_city': store.get('city') or None,
            'store_state': store.get('state') or None,
            'lat': store.get('lat'), 'lon': store.get('lon'),
            'product_name': record.get('product_name'),
            'game': record.get('game'),
            'availability': availability,
            'inventory_scope': kind,
            'shelf_stock_confirmed': kind == 'physical_store',
            'evidence_url': evidence,
            'checked_at': record.get('checked_at') or record.get('verified_at'),
        })

    for p in pickups:
        if not isinstance(p, dict):
            continue
        if p.get('inventory_scope') != 'store_pickup' or not fresh(p.get('checked_at')):
            continue
        if p.get('availability') not in ('Pickup available', 'Pickup unavailable'):
            continue
        if not valid_url(p.get('evidence_url')):
            continue
        location = norm(p.get('location_name'))
        retailer = norm(p.get('retailer'))
        # Exact location identity only; fuzzy matches can label the wrong branch.
        matches = by_name.get(location, [])
        if len(matches) != 1:
            unresolved['pickup_location_not_uniquely_matched'] += 1
            continue
        store = matches[0]
        # The location must match retailer name, unless the record explicitly
        # provides the canonical store id (future compatible field).
        if retailer and retailer not in norm(store.get('name')) and norm(store.get('name')) not in retailer:
            unresolved['retailer_identity_unverified'] += 1
            continue
        add(store, p, p['availability'], 'store_pickup', p['evidence_url'])

    for r in inventory:
        if not isinstance(r, dict) or not r.get('store_id'):
            continue
        store = by_id.get(str(r['store_id']))
        if not store:
            unresolved['store_id_not_found'] += 1
            continue
        if not fresh(r.get('verified_at')) or not valid_url(r.get('source_url')):
            unresolved['stale_or_missing_evidence'] += 1
            continue
        if r.get('status') not in ('In stock', 'Out of stock'):
            unresolved['unsupported_status'] += 1
            continue
        # Do not elevate unknown provenance to verified physical shelf stock.
        if r.get('inventory_scope') != 'physical_store' or r.get('physical_inventory_verified') is not True:
            unresolved['physical_provenance_unverified'] += 1
            continue
        add(store, r, r['status'], 'physical_store', r['source_url'])

    report = {
        'version': '24.0', 'checked_at': NOW.isoformat(),
        'store_candidates': len(stores),
        'pickup_observations_input': len(pickups),
        'physical_observations_input': len(inventory),
        'verified_store_specific_records': len(confirmed),
        'pickup_available': sum(x['availability'] == 'Pickup available' for x in confirmed),
        'physical_in_stock': sum(x['availability'] == 'In stock' for x in confirmed),
        'unresolved': dict(unresolved),
        'chain_integrations': {
            'Walmart': 'not_connected',
            'Target': 'not_connected',
            'GameStop': 'not_connected',
            'Best Buy': 'not_connected',
        },
        'note': 'No store-specific stock is inferred from online offers or store candidates.',
    }
    save('verified_local_stock.json', confirmed)
    save('verified_local_stock_report.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
