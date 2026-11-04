import json
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

DATA = Path('data')
NOW = datetime.now(timezone.utc)

def read(name, fallback):
    try:
        result = json.loads(
            (DATA / name).read_text(encoding='utf-8')
        )
        return result if isinstance(
            result, type(fallback)
        ) else fallback
    except (OSError, ValueError):
        return fallback

def text(x, n=250):
    return ' '.join(str(x or '').split())[:n]

def norm(x):
    return re.sub(
        r'[^a-z0-9]', '', text(x).lower()
    )

def iso(x):
    try:
        d = datetime.fromisoformat(
            str(x).replace('Z', '+00:00')
        )
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None

def https(x):
    try:
        u = urlsplit(str(x))
        return str(x)[:900] if (
            u.scheme == 'https' and u.netloc
        ) else ''
    except ValueError:
        return ''

def point(row):
    try:
        a = float(row.get('lat'))
        b = float(
            row.get('lon', row.get('long'))
        )
        return (a, b) if (
            abs(a) <= 90 and abs(b) <= 180
        ) else None
    except (ValueError, TypeError):
        return None

stores = read('stores.json', [])
places = defaultdict(list)
by_id = {}

for s in stores:
    if not isinstance(s, dict):
        continue
    p = point(s)
    if p is None:
        continue

    sid = text(s.get('id'), 120)
    if sid:
        by_id[sid] = p

    if s.get('city') and s.get('state'):
        places[
            (norm(s['city']), norm(s['state']))
        ].append(p)

centers = {
    k: (
        median(z[0] for z in v),
        median(z[1] for z in v)
    )
    for k, v in places.items() if v
}

seen = set()
events = []

def add(event):
    if event['id'] in seen:
        return

    d = iso(event['reported_at'])
    if not d:
        return
    if d > NOW + timedelta(hours=1):
        return
    if NOW - d > timedelta(days=60):
        return
    if not https(event['source_url']):
        return
    if event['lat'] is None or event['lon'] is None:
        return

    seen.add(event['id'])
    events.append(event)

for row in read('v34_public_sightings.json', []):
    if not isinstance(row, dict):
        continue

    sid = text(row.get('store_id'), 120)
    city = text(row.get('city'), 90)
    state = text(row.get('state'), 20)

    p = by_id.get(sid) if (
        row.get('store_match_verified') is True
    ) else None

    p = p or centers.get(
        (norm(city), norm(state))
    )
    if not p:
        continue

    eid = text(row.get('event_id'), 130)
    if not eid:
        continue

    add({
        'id': 'sighting:' + eid,
        'kind': 'community_sighting',
        'title': text(
            row.get('product_name'), 230
        ),
        'retailer': text(
            row.get('retailer'), 90
        ),
        'game': text(row.get('game'), 80),
        'city': city,
        'state': state,
        'lat': p[0],
        'lon': p[1],
        'reported_at': text(
            row.get('reported_at_approx'), 60
        ),
        'source_url': https(
            row.get('source_url')
        ),
        'store_id': sid,
        'store_match_verified':
            row.get('store_match_verified') is True,
        'stock_verified_now': False,
        'location_precision':
            'exact_store' if (
                row.get('store_match_verified') is True
            ) else 'approximate_city'
    })

social = read('social_media_feed.json', {})

for row in social.get('posts', []):
    if not isinstance(row, dict):
        continue

    loc = row.get('location')
    if not isinstance(loc, dict):
        continue

    p = point(loc)
    if not p:
        continue

    signals = row.get('restock_signals') or []
    if not isinstance(signals, list) or not signals:
        continue

    eid = text(
        row.get('id') or row.get('url'), 150
    )
    if not eid:
        continue

    add({
        'id': 'social:' + eid,
        'kind': 'social_research_lead',
        'title': text(row.get('title'), 230),
        'retailer': ', '.join(
            text(x, 60)
            for x in (
                row.get('retailer_mentions') or []
            )[:3]
        ),
        'game': text(row.get('game'), 80),
        'city': text(loc.get('city'), 90),
        'state': text(loc.get('state'), 20),
        'lat': p[0],
        'lon': p[1],
        'reported_at': text(
            row.get('published_at'), 60
        ),
        'source_url': https(
            row.get('original_post_url')
            or row.get('url')
        ),
        'store_id': '',
        'store_match_verified': False,
        'stock_verified_now': False,
        'location_precision':
            'source_tagged_approximate'
    })

events.sort(
    key=lambda x: x['reported_at'],
    reverse=True
)

v34 = read('v34_report.json', {})

out = {
    'version': '43.0',
    'public_sighting_feed_checked': text(
        v34.get('checked_at'), 60
    ),
    'social_feed_checked': text(
        social.get('updated_at'), 60
    ),
    'events': events,
    'community_sighting_count': sum(
        x['kind'] == 'community_sighting'
        for x in events
    ),
    'location_tagged_social_leads': sum(
        x['kind'] == 'social_research_lead'
        for x in events
    ),
    'note': (
        'City locations are approximate; social posts '
        'and sightings do not prove shelf stock. '
        'Only repeated verified exact-store reports '
        'support weekday watch patterns.'
    )
}

path = DATA / 'forecast_activity_43.json'
encoded = json.dumps(
    out, ensure_ascii=False, indent=2
) + '\n'

if not path.exists() or (
    path.read_text(encoding='utf-8') != encoded
):
    path.write_text(
        encoded, encoding='utf-8'
    )

print(
    'Script 43 collected',
    len(events),
    'dated location-tagged research signals'
)
