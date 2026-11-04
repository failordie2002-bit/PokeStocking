import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit, urljoin
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ROOT = Path('data')
ROOT.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)
UA = (
    'PokeStockPublicMonitor/1.0 '
    '(https://github.com/failordie2002-bit/PokeStocking)'
)

HTTP = requests.Session()
HTTP.headers.update({
    'User-Agent': UA,
    'Accept': (
        'text/html,application/rss+xml,'
        'application/atom+xml,application/xml;q=0.9,'
        '*/*;q=0.5'
    )
})

robots = {}
diagnostics = {}
attempts = 0

def load(file, default):
    try:
        a = json.loads(
            (ROOT / file).read_text(encoding='utf-8')
        )
        return a if isinstance(
            a, type(default)
        ) else default
    except (OSError, ValueError):
        return default

def dump(file, obj):
    (ROOT / file).write_text(
        json.dumps(
            obj, ensure_ascii=False, indent=2
        ) + '\n',
        encoding='utf-8'
    )

def clean(x, n=220):
    return ' '.join(str(x or '').split())[:n]

def norm(x):
    return re.sub(
        r'[^a-z0-9]+', ' ',
        unicodedata.normalize(
            'NFKD', clean(x, 500)
        ).encode('ascii', 'ignore').decode().lower()
    ).strip()

def valid(url):
    try:
        u = urlsplit(str(url))
        return (
            u.scheme == 'https'
            and bool(u.hostname)
            and not u.username
            and not u.password
        )
    except ValueError:
        return False

def fetch(url):
    global attempts
    if not valid(url):
        return None, 'invalid_url'

    host = urlsplit(url).hostname

    if host not in robots:
        try:
            r = HTTP.get(
                'https://' + host + '/robots.txt',
                timeout=8
            )

            if r.status_code in (401, 403, 429):
                robots[host] = (None, False)

            elif r.status_code == 200:
                p = RobotFileParser()
                p.parse(r.text.splitlines())
                robots[host] = (p, True)

            elif r.status_code == 404:
                robots[host] = (None, True)

            else:
                robots[host] = (None, False)

        except requests.RequestException:
            robots[host] = (None, False)

    p, ok = robots[host]

    if not ok or (
        p and not p.can_fetch(UA, url)
    ):
        return None, 'robots_unavailable_or_disallow'

    attempts += 1
    if attempts > 1:
        time.sleep(0.45)

    try:
        r = HTTP.get(
            url, timeout=14, allow_redirects=True
        )

        if r.status_code in (401, 403, 429):
            return (
                None,
                'access_restricted_' + str(r.status_code)
            )

        if r.status_code != 200:
            return None, 'http_' + str(r.status_code)

        if not valid(r.url) or len(r.content) > 2600000:
            return None, 'unexpected_response'

        content_type = r.headers.get(
            'Content-Type', ''
        ).lower()

        if not any(
            t in content_type
            for t in ('html', 'xml', 'rss', 'atom')
        ):
            return None, 'not_document'

        if re.search(
            'captcha|verify you are human|access denied',
            r.text[:3000], re.I
        ):
            return None, 'human_challenge'

        return r.text, 'ok'

    except requests.RequestException:
        return None, 'network_unavailable'

def sha(x):
    return hashlib.sha256(
        str(x).encode()
    ).hexdigest()[:18]

def published(s):
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)

        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)

        return d.astimezone(
            timezone.utc
        ).isoformat()

    except (ValueError, TypeError, IndexError):
        return ''

def game_set():
    names = [
        'Pokémon',
        'Union Arena',
        'Gundam',
        'One Piece',
        'Yu-Gi-Oh!',
        'Magic: The Gathering',
        'Disney Lorcana',
        'Digimon',
        'Dragon Ball Super',
        'Riftbound',
        'Star Wars: Unlimited',
        'Weiß Schwarz',
        'Cardfight!! Vanguard',
        'Flesh and Blood',
        'Battle Spirits Saga',
        'Shadowverse: Evolve',
        'Grand Archive',
        'Altered',
        'Sorcery: Contested Realm',
        'Final Fantasy TCG',
        'Kayou'
    ]

    games = {norm(x): x for x in names}

    for name in (
        'v31_product_catalogue.json',
        'unified_online_39.json'
    ):
        for x in load(name, []):
            if isinstance(x, dict):
                g = clean(x.get('game'), 75)
                if g and norm(g) and norm(g) != 'unknown':
                    games[norm(g)] = g

    return sorted(
        games.values(), key=str.casefold
    )

def classify(title, games):
    n = norm(title)

    aliases = {
        'Pokémon': ['pokemon', 'pokmon'],
        'Yu-Gi-Oh!': ['yu gi oh', 'yugioh'],
        'Magic: The Gathering': [
            'magic the gathering', 'mtg'
        ],
        'Disney Lorcana': ['lorcana'],
        'Star Wars: Unlimited': [
            'star wars unlimited'
        ],
        'Gundam': ['gundam'],
        'Union Arena': ['union arena']
    }

    for g in games:
        terms = aliases.get(g, [norm(g)])

        if any(
            t and (' ' + t + ' ') in (' ' + n + ' ')
            for t in terms
        ):
            return g

    return ''

def sealed(title):
    n = norm(title)

    include = re.search(
        r'booster|elite trainer|starter deck|'
        r'trial deck|collection|premium box|'
        r'card game|trading cards|mini tins?|'
        r'display box|battle deck|tcg|blister|sealed',
        n
    )

    exclude = re.search(
        r'\b(singles?|sleeves?|binders?|playmats?|'
        r'storage|card holder|graded|psa|'
        r'protectors?|top loader)\b',
        n
    )

    return bool(include) and not bool(exclude)

def official(link):
    try:
        u = urlsplit(link)
        h = (
            u.hostname or ''
        ).lower().removeprefix('www.')

        if u.scheme != 'https':
            return ''

        if (
            h == 'lowes.com'
            and u.path.startswith('/pd/')
        ):
            return "Lowe's"

        if (
            h == 'samsclub.com'
            and u.path.startswith('/ip/')
        ):
            return "Sam's Club"

        if h == 'costco.com' and (
            u.path.startswith('/p/')
            or u.path.endswith('.html')
        ):
            return 'Costco'

    except ValueError:
        pass

    return ''

def discover(games):
    prev = load('universal45.json', {})

    leads = {
        x['url']: x
        for x in prev.get(
            'retailer_listing_leads', []
        )
        if isinstance(x, dict)
        and valid(x.get('url'))
    }

    state = load('universal45_state.json', {})
    cursor = int(
        state.get('cursor', 0)
    ) % len(games)

    # Rotate through four games each run.
    chosen = [
        games[(cursor + i) % len(games)]
        for i in range(min(4, len(games)))
    ]

    searches = []

    for game in chosen:
        q = quote(game + ' trading card game')

        searches.extend([
            (
                'Costco',
                'https://www.costco.com/s?keyword=' + q
            ),
            (
                "Sam's Club",
                'https://www.samsclub.com/s/' + q
            ),
            (
                "Lowe's",
                'https://www.lowes.com/search?searchTerm=' + q
            )
        ])

    searches.append((
        "Lowe's",
        'https://www.lowes.com/ple/pokemon'
    ))

    results = {}

    for brand, url in searches:
        page, status = fetch(url)
        results[brand + ' | ' + url] = status

        if not page:
            continue

        soup = BeautifulSoup(page, 'html.parser')

        for a in soup.select('a[href]')[:1600]:
            target = urljoin(
                url, a.get('href', '')
            )

            b = official(target)
            if b != brand:
                continue

            title = clean(
                a.get_text(' ', strip=True)
                or a.get('aria-label')
                or a.get('title'),
                190
            )

            game = classify(title, games)

            if not game or not sealed(title):
                continue

            product_url = target.split(
                '#'
            )[0].split('?')[0]

            leads[product_url] = {
                'retailer': b,
                'game': game,
                'title': title,
                'url': product_url,
                'inventory_scope': 'listing_only',
                'shipping_verified': False,
                'store_stock_verified': False,
                'first_seen': leads.get(
                    product_url, {}
                ).get(
                    'first_seen', NOW.isoformat()
                ),
                'last_seen': NOW.isoformat(),
                'source_type': 'official_search_page'
            }

    items = sorted(
        leads.values(),
        key=lambda x: x.get('last_seen', ''),
        reverse=True
    )[:500]

    dump('universal45.json', {
        'version': '45',
        'checked_at': NOW.isoformat(),
        'games': games,
        'retailer_listing_leads': items,
        'last_batch_games': chosen,
        'source_diagnostics': results,
        'note': (
            'Official listing links only. '
            'Availability and pickup remain unknown '
            'without explicit observed evidence.'
        )
    })

    dump('universal45_state.json', {
        'cursor': (cursor + 4) % len(games),
        'last_batch_games': chosen,
        'checked_at': NOW.isoformat()
    })

    return len(items)

SAMS = [
    (
        '2026-09-21',
        'https://restockd.app/blog/ascended-heroes-focused-fighters-sams-club-wave-2-inventory'
    ),
    (
        '2026-07-15',
        'https://restockd.app/blog/ascended-heroes-focused-fighters-at-sam-s-club-inventory-by-location'
    )
]

def allocations():
    old = load('sams_allocations_45.json', {})

    records = {
        x['key']: x
        for x in old.get('records', [])
        if isinstance(x, dict) and x.get('key')
    }

    for date, url in SAMS:
        html, status = fetch(url)
        diagnostics[
            'Sam allocations ' + date
        ] = status

        if not html:
            continue

        soup = BeautifulSoup(
            html, 'html.parser'
        )

        state = ''

        for tag in soup.find_all([
            'h2', 'h3', 'li'
        ]):
            if tag.name in ('h2', 'h3'):
                m = re.search(
                    r'\(([A-Z]{2})\)\s*$',
                    tag.get_text(' ', strip=True)
                )
                state = m.group(1) if m else ''
                continue

            if not state:
                continue

            row = clean(
                tag.get_text(' ', strip=True), 260
            )

            m = re.match(
                r'(.{2,90}?)'
                r'(?:\s+\(Club\s*#(\d{3,5})\))?'
                r':\s*([\d,]+)\s+on\s+hand'
                r'(?:,\s*([\d,]+)\s+on\s+order)?',
                row,
                re.I
            )

            if not m:
                continue

            city = clean(m.group(1), 100)
            club = m.group(2) or ''

            key = sha(
                url + '|' + state + '|'
                + city + '|' + club
            )

            records[key] = {
                'key': key,
                'retailer': "Sam's Club",
                'game': 'Pokémon',
                'product': (
                    'Ascended Heroes Focused Fighters '
                    'Premium Collection'
                ),
                'city': city,
                'state': state,
                'club_number': club,
                'reported_on_hand': int(
                    m.group(3).replace(',', '')
                ),
                'reported_on_order': (
                    int(
                        m.group(4).replace(',', '')
                    )
                    if m.group(4) else None
                ),
                'report_date': date,
                'source_url': url,
                'source_kind': (
                    'independent_historical_allocation'
                ),
                'verified_shelf_stock': False,
                'note': (
                    'Third-party historical snapshot; '
                    'quantities and locations are '
                    'not independently verified.'
                )
            }

    dump('sams_allocations_45.json', {
        'version': '45',
        'checked_at': NOW.isoformat(),
        'records': list(records.values())[:1100],
        'sources': [x[1] for x in SAMS],
        'note': (
            'July and September 2026 snapshots, '
            'not current inventory. '
            'Never sum different snapshots.'
        )
    })

    return len(records)

# One local hearsay claim; NOT an observation.
SEED = {
    'id': 'collector-20261104-walmart-staunton-thu',
    'retailer': 'Walmart',
    'city': 'Staunton',
    'state': 'VA',
    'game': 'Pokémon',
    'weekday': 'Thursday',
    'period': 'early morning',
    'scope': 'city_retailer',
    'source_kind': 'local_collector_hearsay',
    'source_url': '',
    'reported_at': '2026-11-04',
    'title': (
        'Rumor: Staunton Walmart Pokémon '
        'restocks Thursday early morning'
    ),
    'note': (
        'A local collector heard this pattern. '
        'Branch, vendor schedule and stock have not '
        'been verified. One hearsay report, '
        'not weekly observations.'
    ),
    'evidence_count': 1,
    'confidence': 'Low',
    'shelf_stock_verified': False
}

FEEDS = [
    (
        'Reddit PokemonRestocks',
        'https://www.reddit.com/r/PokemonRestocks/new/.rss'
    ),
    (
        'Reddit PokemonTCG',
        'https://www.reddit.com/r/PokemonTCG/new/.rss'
    ),
    (
        'Google News local',
        'https://news.google.com/rss/search?q='
        + quote(
            'Pokemon TCG restock Staunton '
            'Virginia when:30d'
        )
        + '&hl=en-US&gl=US&ceid=US:en'
    ),
    (
        'Google News general',
        'https://news.google.com/rss/search?q='
        + quote(
            'trading card game Walmart '
            'restock Thursday when:7d'
        )
        + '&hl=en-US&gl=US&ceid=US:en'
    )
]

CHAINS = [
    'Walmart', 'Target', 'Best Buy',
    'GameStop', 'Costco', "Sam's Club",
    "Lowe's", 'Dollar General',
    'Walgreens', 'CVS', 'Five Below'
]

WEEK = [
    'Monday', 'Tuesday', 'Wednesday',
    'Thursday', 'Friday', 'Saturday',
    'Sunday'
]

def rumors(games):
    old = load('rumor45.json', {})

    allrows = {
        x['id']: x
        for x in old.get('reports', [])
        if isinstance(x, dict) and x.get('id')
    }

    allrows[SEED['id']] = SEED
    statuses = {}

    recent_games = load(
        'universal45_state.json', {}
    ).get('last_batch_games', [])

    dynamic = [
        (
            'Google News ' + g,
            'https://news.google.com/rss/search?q='
            + quote(
                g + ' TCG restock retailer when:7d'
            )
            + '&hl=en-US&gl=US&ceid=US:en'
        )
        for g in recent_games[:4]
    ]

    cities = {
        (
            norm(x.get('city')),
            norm(x.get('state'))
        ): clean(x.get('city'), 90)
        for x in load('stores.json', [])
        if isinstance(x, dict)
        and x.get('city')
        and x.get('state')
    }

    for name, url in FEEDS + dynamic:
        xml, status = fetch(url)
        statuses[name] = status

        if not xml:
            continue

        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            statuses[name] = 'invalid_feed'
            continue

        items = (
            root.findall('.//item')
            + root.findall(
                './/{http://www.w3.org/2005/Atom}entry'
            )
        )

        for item in items[:70]:
            def tag(n):
                x = (
                    item.findtext(n)
                    or item.findtext(
                        '{http://www.w3.org/2005/Atom}'
                        + n
                    )
                )
                return clean(x, 650)

            title = tag('title')
            desc = (
                tag('description')
                or tag('summary')
            )

            textbody = BeautifulSoup(
                title + ' ' + desc,
                'html.parser'
            ).get_text(' ', strip=True)

            term = norm(textbody)

            if not re.search(
                r'restock|stocking|stocked|'
                r'shipment|delivery|cards arrived',
                term
            ):
                continue

            chain = next(
                (
                    c for c in CHAINS
                    if norm(c) in term
                ),
                None
            )

            weekday = next(
                (
                    w for w in WEEK
                    if norm(w) in term
                ),
                None
            )

            if not chain or not weekday:
                continue

            game = classify(textbody, games)

            if not game:
                continue

            link = tag('link')

            if not link:
                a = item.find(
                    '{http://www.w3.org/2005/Atom}link'
                )
                link = (
                    a.get('href', '')
                    if a is not None else ''
                )

            if not valid(link):
                continue

            date = (
                published(tag('pubDate'))
                or tag('published')
                or tag('updated')
            )

            try:
                d = datetime.fromisoformat(
                    date.replace('Z', '+00:00')
                )

                if d.tzinfo is None:
                    d = d.replace(
                        tzinfo=timezone.utc
                    )

                if NOW - d.astimezone(
                    timezone.utc
                ) > timedelta(days=45):
                    continue

            except (ValueError, TypeError):
                continue

            city = ''
            state = ''

            for m in re.finditer(
                r'\b([A-Z][a-z]+'
                r'(?:\s+[A-Z][a-z]+){0,2})'
                r'\s*,?\s+([A-Z]{2})\b',
                textbody
            ):
                k = (
                    norm(m.group(1)),
                    norm(m.group(2))
                )

                if k in cities:
                    city = cities[k]
                    state = m.group(2)
                    break

            if (
                not city
                and 'staunton' in term
                and re.search(
                    r'\b(va|virginia)\b', term
                )
            ):
                city = 'Staunton'
                state = 'VA'

            period = (
                'morning'
                if re.search(
                    r'\bmorning\b', term
                )
                else (
                    'evening'
                    if 'evening' in term
                    else 'unspecified'
                )
            )

            key = 'feed-' + sha(link)

            allrows[key] = {
                'id': key,
                'retailer': chain,
                'city': city,
                'state': state,
                'game': game,
                'weekday': weekday,
                'period': period,
                'scope': (
                    'city_retailer'
                    if city
                    else 'general_retailer'
                ),
                'source_kind': (
                    'public_rss_title_claim'
                ),
                'source_url': link,
                'reported_at': date,
                'title': title,
                'note': (
                    'Unverified public headline or '
                    'post. May be generic guidance '
                    'rather than a direct observation.'
                ),
                'evidence_count': 1,
                'confidence': 'Low',
                'shelf_stock_verified': False
            }

    active = {}

    for k, x in allrows.items():
        if k == SEED['id']:
            active[k] = x
            continue

        try:
            d = datetime.fromisoformat(
                str(
                    x.get('reported_at', '')
                ).replace('Z', '+00:00')
            )

            if (
                d.tzinfo
                and NOW - d.astimezone(
                    timezone.utc
                ) <= timedelta(days=90)
            ):
                active[k] = x

        except (ValueError, TypeError):
            pass

    rows = sorted(
        active.values(),
        key=lambda x: x.get(
            'reported_at', ''
        ),
        reverse=True
    )[:250]

    dump('rumor45.json', {
        'version': '45',
        'checked_at': NOW.isoformat(),
        'reports': rows,
        'sources': statuses,
        'rules': [
            'A source URL contributes one dated claim.',
            'General retailer rumors never verify a branch.',
            'Hearsay always retains low confidence.',
            'No private retailer data or vendor tracking.'
        ]
    })

    return len(rows)

if __name__ == '__main__':
    games = game_set()
    discovered = discover(games)
    a = allocations()
    rumors_count = rumors(games)

    dump('universal45_report.json', {
        'checked_at': NOW.isoformat(),
        'supported_games': len(games),
        'retailer_listing_leads': discovered,
        'sams_historical_allocation_entries': a,
        'rumor_claims': rumors_count,
        'allocation_source_diagnostics': diagnostics,
        'robots_hosts': {
            h: (
                'available'
                if x[1]
                else 'disallowed_or_unavailable'
            )
            for h, x in robots.items()
        },
        'limitations': (
            'No live shelf inventory. '
            'No CAPTCHA or rate-limit bypass. '
            'Rumors stay low confidence. '
            'Scheduled runs are not guaranteed exact.'
        )
    })

    print(
        'SCRIPT 45 SOURCE AUDIT:',
        json.dumps(
            load('universal45_report.json', {}),
            ensure_ascii=False
        )
    )
