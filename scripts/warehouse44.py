"""Public TCG listings and sourced Costco allocations; never guesses shelf stock."""
import json, re, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

NOW = datetime.now(timezone.utc)
DATA = Path('data')
DATA.mkdir(exist_ok=True)
UA = 'PokeStockPublicResearch/1.0 (+https://github.com/failordie2002-bit/PokeStocking)'
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5'
})
ALLOCATION = 'https://restockd.app/pokemon-in-store?allocation=costco-30th'

SEEDS = {
    "Sam's Club": [
        'https://www.samsclub.com/ip/seort/17210852415',
        'https://www.samsclub.com/ip/pokemon-tcg-charizard-ex-super-premium-collection/15488968285'
    ],
    'Costco': [
        'https://www.costco.com/p/-/pokmon-5-pack-mini-tins-galar-pals-plus-4-promo-cards/4000092043',
        'https://www.costco.com/p/-/pokmon-5-pack-mini-tins-sinnoh-stars-plus-4-promo-cards/4000092037',
        'https://www.costco.com/p/-/pokmon-collectors-chest--great-ball--ultra-ball--3-eevee-promo-cards/100791463'
    ]
}
DISCOVERY = {
    "Sam's Club": [
        'https://www.samsclub.com/s/pokemon%20trading%20cards',
        'https://www.samsclub.com/s/pokemon%20elite%20trainer'
    ],
    'Costco': [
        'https://www.costco.com/s?keyword=pokemon%20trading%20cards',
        'https://www.costco.com/s?keyword=pokemon%20booster'
    ]
}

REPORT = {
    'checked_at': NOW.isoformat(),
    'sources': {},
    'robots': {},
    'notes': [],
    'explicit_shipping_available': 0,
    'explicit_shipping_unavailable': 0,
    'status_unknown': 0,
    'access_restricted': 0,
    'official_products_checked': 0,
    'third_party_allocation_rows': 0
}
ROBOTS = {}
CHECKED = 0

def load(name, default):
    try:
        x = json.loads(
            (DATA / name).read_text(encoding='utf-8')
        )
        return x if isinstance(x, type(default)) else default
    except (OSError, ValueError):
        return default

def norm(s):
    return (
        unicodedata.normalize('NFKD', str(s or ''))
        .encode('ascii', 'ignore')
        .decode().lower()
    )

def tcg(title):
    s = norm(title)
    game = bool(re.search(
        r'pokemon|union arena|lorcana|one piece|gundam|digimon|yu.gi.oh|magic the gathering|riftbound|dragon ball|weiss schwarz|cardfight',
        s
    ))
    sealed = bool(re.search(
        r'booster|trading cards?|card game|tcg|elite trainer|\betb\b|mini tins?|pok[e]? ball|collector.s chest|premium collection|starter deck|trading card box',
        s
    ))
    return game and sealed

def retailer(url):
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower().removeprefix('www.')
        if p.scheme != 'https':
            return None
        if host == 'costco.com' and (
            p.path.startswith('/p/') or
            p.path.endswith('.html')
        ):
            return 'Costco'
        if host == 'samsclub.com' and p.path.startswith('/ip/'):
            return "Sam's Club"
    except ValueError:
        pass
    return None

def canonical(url):
    try:
        p = urlsplit(url)
        return urlunsplit((
            'https', p.netloc.lower(),
            p.path.rstrip('/'), '', ''
        ))
    except (TypeError, ValueError):
        return ''

def allowed(url):
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False, 'invalid_url'
    if not host:
        return False, 'invalid_host'

    if host not in ROBOTS:
        base = 'https://' + host + '/robots.txt'
        try:
            res = SESSION.get(base, timeout=9)
            if res.status_code in (401, 403):
                ROBOTS[host] = (None, 'robots_disallow')
            elif res.status_code == 200:
                rp = RobotFileParser()
                rp.parse(res.text.splitlines())
                ROBOTS[host] = (rp, 'robots_checked')
            elif res.status_code == 404:
                ROBOTS[host] = (None, 'robots_absent')
            else:
                ROBOTS[host] = (None, 'robots_unavailable')
        except requests.RequestException:
            ROBOTS[host] = (None, 'robots_unavailable')
        REPORT['robots'][host] = ROBOTS[host][1]

    rp, state = ROBOTS[host]
    if state in (
        'robots_disallow', 'robots_unavailable'
    ):
        return False, state
    if rp and not rp.can_fetch(UA, url):
        return False, 'robots_disallow_path'
    return True, 'allowed'

def get(url):
    global CHECKED
    permit, why = allowed(url)
    if not permit:
        return None, why

    try:
        if CHECKED:
            time.sleep(0.7)
        CHECKED += 1
        r = SESSION.get(
            url, timeout=16, allow_redirects=True
        )
        if r.status_code in (401, 403, 429):
            return None, 'access_restricted_' + str(r.status_code)
        if r.status_code in (404, 410):
            return None, 'not_found'
        if r.status_code != 200:
            return None, 'http_' + str(r.status_code)
        if not (
            r.url.startswith('https://') and
            len(r.content) < 3_000_000
        ):
            return None, 'unexpected_response'
        content_type = r.headers.get('Content-Type', '').lower()
        if 'html' not in content_type and 'xml' not in content_type:
            return None, 'not_html'
        s = r.text
        if re.search(
            r'captcha|verify you are human|unusual traffic|access denied',
            s[:4000], re.I
        ):
            return None, 'access_challenge'
        return s, 'ok'
    except requests.RequestException:
        return None, 'network_unavailable'

def offer_ld(soup, title):
    states = []
    prices = []
    for tag in soup.find_all(
        'script', type='application/ld+json'
    )[:30]:
        try:
            tree = json.loads(
                tag.string or tag.get_text() or '{}'
            )
        except (ValueError, TypeError):
            continue
        stack = [tree]
        for _ in range(120):
            if not stack:
                break
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            stack.extend(
                v for k, v in item.items()
                if k in (
                    '@graph', 'mainEntity', 'itemListElement'
                ) and isinstance(v, (dict, list))
            )
            typ = item.get('@type', [])
            types = typ if isinstance(typ, list) else [typ]
            if not any(
                str(t).lower() == 'product'
                for t in types
            ):
                continue
            ldname = norm(item.get('name', ''))
            if ldname and title and not (
                ldname[:18] in norm(title) or
                norm(title)[:18] in ldname
            ):
                continue
            off = item.get('offers', [])
            off = off if isinstance(off, list) else [off]
            for v in off:
                if not isinstance(v, dict):
                    continue
                a = str(
                    v.get('availability', '')
                ).lower().split('/')[-1]
                if a in ('instock', 'outofstock'):
                    states.append(a)
                pr = v.get('price')
                if pr is not None and re.fullmatch(
                    r'\d+(?:\.\d{1,2})?', str(pr)
                ):
                    prices.append(str(pr))
    state = (
        states[0]
        if len(set(states)) == 1 and states
        else None
    )
    return state, (prices[0] if prices else None)

def product_page(url, old):
    brand = retailer(url)
    if not brand:
        return None
    record = {
        'retailer': brand,
        'url': canonical(url),
        'title': old.get('title', ''),
        'shipping_status': 'unverified',
        'price': None,
        'currency': None,
        'checked_at': NOW.isoformat(),
        'last_accessible_at': old.get('last_accessible_at'),
        'evidence': 'Product listing; shipping not established',
        'member_club_required': True,
        'local_pickup_verified': False,
        'shelf_inventory_verified': False
    }
    page, outcome = get(url)
    record['access_result'] = outcome

    if page is None:
        record['shipping_status'] = 'access_unavailable'
        record['evidence'] = (
            'The public product page could not be confirmed '
            'during this scan; not a stock result'
        )
        return record

    soup = BeautifulSoup(page, 'html.parser')
    head = soup.find('h1')
    title = (
        head.get_text(' ', strip=True)
        if head else ''
    )
    if not title:
        mt = soup.find('meta', property='og:title')
        title = mt.get('content', '') if mt else ''
    title = ' '.join(title.split())[:180]

    if not tcg(title):
        record['shipping_status'] = 'access_unavailable'
        record['evidence'] = (
            'No trustworthy TCG product title in the page'
        )
        return record

    record['title'] = title
    record['last_accessible_at'] = NOW.isoformat()
    state, ldprice = offer_ld(soup, title)
    content = re.sub(
        r'\s+', ' ', ' '.join(soup.stripped_strings)
    )

    status = 'unverified'
    reason = (
        'The product page exists, but unscoped online '
        'shipping availability is not explicit'
    )

    if state == 'instock':
        status = 'shipping_available_observed'
        reason = (
            'Product structured data explicitly reported '
            'InStock; online offer only'
        )
    elif state == 'outofstock':
        status = 'shipping_unavailable_observed'
        reason = (
            'Product structured data explicitly reported '
            'OutOfStock'
        )
    elif brand == "Sam's Club":
        if re.search(
            r'\bShipping\s+Not available\b',
            content, re.I
        ):
            status = 'shipping_unavailable_observed'
            reason = (
                'Sam’s Club product page explicitly says '
                'Shipping Not available'
            )
        elif re.search(
            r'\bAvailable for Shipping\b',
            content, re.I
        ):
            status = 'shipping_available_observed'
            reason = (
                'Sam’s Club product page explicitly says '
                'Available for Shipping'
            )
    elif brand == 'Costco' and re.search(
        r'expected to be in stock and available for purchase soon',
        content, re.I
    ):
        status = 'shipping_unavailable_observed'
        reason = (
            'Costco product page says expected '
            'to be in stock soon'
        )

    record['shipping_status'] = status
    record['evidence'] = reason
    if ldprice:
        record['price'] = ldprice
        record['currency'] = 'USD'
    elif brand == "Sam's Club":
        m = re.search(
            r'Current price is USD\s*\$?\s*(\d+(?:\.\d{1,2})?)',
            content, re.I
        )
        if m:
            record['price'] = m.group(1)
            record['currency'] = 'USD'
    return record

def discover():
    urls = {
        canonical(x)
        for group in SEEDS.values() for x in group
    }
    previous = load('warehouse_watch_44.json', {})
    for old in previous.get('products', []):
        if isinstance(old, dict) and retailer(
            old.get('url', '')
        ):
            urls.add(canonical(old['url']))

    # Old alerts help find official URLs, never current stock.
    for x in load('alert_events_37.json', []):
        if not isinstance(x, dict):
            continue
        link = (
            x.get('retailer_url') or
            x.get('source_url') or ''
        )
        if retailer(link) and tcg(
            x.get('product_name', '')
        ):
            urls.add(canonical(link))

    # Public discovery; all blocked sources are skipped.
    for brand, searches in DISCOVERY.items():
        for url in searches:
            doc, result = get(url)
            REPORT['sources'][url] = result
            if not doc:
                continue
            s = BeautifulSoup(doc, 'html.parser')
            for a in s.find_all('a', href=True)[:2000]:
                link = requests.compat.urljoin(
                    url, a.get('href', '')
                )
                label = (
                    a.get_text(' ', strip=True) or
                    a.get('aria-label', '')
                )
                if retailer(link) == brand and tcg(label):
                    urls.add(canonical(link))

    if len(urls) < 55:
        for brand, domain in [
            ('Costco', 'costco.com'),
            ("Sam's Club", 'samsclub.com')
        ]:
            suffix = (
                ' /p/ pokemon trading cards'
                if brand == 'Costco'
                else ' /ip/ pokemon elite trainer box'
            )
            term = 'site:' + domain + suffix
            url = (
                'https://www.bing.com/search?q='
                + quote(term) + '&format=rss'
            )
            xml, result = get(url)
            REPORT['sources']['Bing RSS ' + brand] = result
            if not xml:
                continue
            try:
                tree = ET.fromstring(xml)
                for node in tree.findall('.//item')[:30]:
                    link = (
                        node.findtext('link') or ''
                    ).strip()
                    title = (
                        node.findtext('title') or ''
                    ).strip()
                    if retailer(link) == brand and tcg(title):
                        urls.add(canonical(link))
            except ET.ParseError:
                REPORT['sources']['Bing RSS ' + brand] = (
                    'unreadable_xml'
                )
    return sorted(
        u for u in urls if retailer(u)
    )[:55]

def parse_allocation():
    page, outcome = get(ALLOCATION)
    REPORT['sources'][
        'Costco independent allocation source'
    ] = outcome
    if not page:
        return [], None

    soup = BeautifulSoup(page, 'html.parser')
    title = soup.get_text(' ', strip=True)
    dated = re.search(
        r'Updated\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})',
        title, re.I
    )
    as_of = None
    if dated:
        try:
            as_of = datetime.strptime(
                dated.group(1) + ' ' +
                dated.group(2) + ' ' +
                str(NOW.year),
                '%B %d %Y'
            ).date().isoformat()
        except ValueError:
            pass

    rows = []
    for table in soup.find_all('table'):
        headings = ' '.join(
            x.get_text(' ', strip=True).lower()
            for x in table.find_all('th')
        )
        if not all(
            word in headings
            for word in (
                'on hand', 'on order', 'in transit'
            )
        ):
            continue

        for tr in table.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 6:
                continue
            names = [
                c.get_text(' ', strip=True)
                for c in cells[:6]
            ]
            try:
                hand, order, transit = [
                    int(re.sub(r'[^\d]', '', n))
                    for n in names[3:6]
                ]
            except ValueError:
                continue

            number = names[1].strip()
            if not re.fullmatch(r'\d{1,6}', number):
                continue

            rows.append({
                'name': names[0][:130],
                'warehouse_number': number,
                'address': names[2][:200],
                'reported_on_hand': hand,
                'reported_on_order': order,
                'reported_in_transit': transit,
                'product_name': (
                    'Pokémon 30th Celebration '
                    'ETB + Booster Bundle'
                ),
                'item_number': '2007496',
                'reported_as_of': as_of,
                'source_url': ALLOCATION,
                'evidence_class': (
                    'third_party_allocation_unverified'
                ),
                'shelf_stock_confirmed': False
            })
    return rows[:500], as_of

def main():
    previous = load('warehouse_watch_44.json', {})
    prev_by = {
        x.get('url'): x
        for x in previous.get('products', [])
        if isinstance(x, dict)
    }

    candidates = discover()
    products = []
    transitions = load('warehouse_changes_44.json', [])

    for url in candidates:
        previous_item = prev_by.get(url, {})
        x = product_page(url, previous_item)
        if not x:
            continue
        products.append(x)
        oldstate = previous_item.get('shipping_status')
        newstate = x['shipping_status']

        if (
            oldstate in (
                'shipping_available_observed',
                'shipping_unavailable_observed'
            )
            and newstate in (
                'shipping_available_observed',
                'shipping_unavailable_observed'
            )
            and oldstate != newstate
        ):
            transitions.append({
                'url': url,
                'retailer': x['retailer'],
                'product': x['title'],
                'previous': oldstate,
                'observed': newstate,
                'at': NOW.isoformat(),
                'evidence': x['evidence'],
                'note': (
                    'Observed storefront transition, '
                    'not a confirmed purchase'
                )
            })

    allocations, as_of = parse_allocation()
    REPORT['third_party_allocation_rows'] = len(allocations)
    REPORT['official_products_checked'] = len(products)

    for x in products:
        status = x['shipping_status']
        if status == 'shipping_available_observed':
            REPORT['explicit_shipping_available'] += 1
        elif status == 'shipping_unavailable_observed':
            REPORT['explicit_shipping_unavailable'] += 1
        elif status == 'access_unavailable':
            REPORT['access_restricted'] += 1
        else:
            REPORT['status_unknown'] += 1

    transitions = [
        x for x in transitions
        if isinstance(x, dict)
    ][-300:]

    payload = {
        'version': '44.0',
        'checked_at': NOW.isoformat(),
        'products': products,
        'allocations': allocations,
        'allocation_reported_as_of': as_of,
        'summary': REPORT,
        'limitations': [
            'Product listings and shipping do not establish store shelf inventory.',
            'Sam’s pickup depends on the shopper’s selected club; no generic scan verifies it.',
            'Costco third-party allocation figures are unverified, dated, and not guaranteed on shelves.',
            'Inaccessible pages are not considered sold out or in stock.'
        ]
    }

    for name, content in [
        ('warehouse_watch_44.json', payload),
        ('warehouse_changes_44.json', transitions)
    ]:
        (DATA / name).write_text(
            json.dumps(
                content, indent=2, ensure_ascii=False
            ) + '\n',
            encoding='utf-8'
        )

    print(json.dumps({
        k: v for k, v in REPORT.items()
        if k not in ('sources', 'robots')
    }, indent=2))
    print('Sources:', json.dumps(REPORT['sources']))

if __name__ == '__main__':
    main()
