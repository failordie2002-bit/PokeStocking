
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DATA = Path('data/status.json')
PRESS = 'https://press.pokemon.com/en/Items/Schedule?period=All&types=3&sortAsc=False&sortBy=Date'
UNION = 'https://www.unionarena-tcg.com/na/products/'
NEWS = 'https://www.pokemon.com/us/pokemon-news'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept-Language': 'en-US,en;q=0.9'}
RETAIL_DOMAINS = ('bestbuy.com', 'target.com', 'walmart.com', 'gamestop.com', 'pokemoncenter.com')
SEALED = ('booster', 'elite trainer', 'collection', 'tin', 'blister', 'battle deck', 'starter deck', 'advanced deck', 'bundle', 'premium', 'battle academy', 'build & battle', 'build and battle', 'toolkit', 'chest', 'display', 'battle box', 'battle kit', 'battle stadium')
EXCLUDE = ('sleeves', 'binder', 'playmat', 'plush', 'figure', 'portfolio', 'deck box', 'costume', 'apparel', 'shirt', 'video game', 'tcg pocket')
DATE_RE = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def date_from(s):
    m = re.search(DATE_RE, s or '', re.I)
    if not m:
        return ''
    try:
        return datetime.strptime(m.group().replace(',', ''), '%B %d %Y').strftime('%Y-%m-%d')
    except ValueError:
        return ''


def fetch(url):
    error = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(8, 16), allow_redirects=True)
            r.raise_for_status()
            if not r.text.strip():
                raise ValueError('Empty page')
            return BeautifulSoup(r.text, 'html.parser'), r.url
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt == 0:
                time.sleep(1)
    raise error


def nodes(value):
    if isinstance(value, list):
        for x in value:
            yield from nodes(x)
    elif isinstance(value, dict):
        yield value
        for x in value.values():
            if isinstance(x, (dict, list)):
                yield from nodes(x)


def structured(soup):
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            yield from nodes(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def is_product(node):
    t = node.get('@type', '')
    return 'Product' in (t if isinstance(t, list) else [t])


def is_sealed(name):
    s = clean(name).lower()
    return ('pokemon' in s or 'pokémon' in s) and any(x in s for x in SEALED) and not any(x in s for x in EXCLUDE)


def kind(name):
    s = name.lower()
    if 'elite trainer' in s: return 'Elite Trainer Box'
    if 'booster box' in s or 'booster display' in s: return 'Booster Box'
    if 'booster bundle' in s: return 'Booster Bundle'
    if 'booster' in s: return 'Booster Pack'
    if 'blister' in s: return 'Blister'
    if 'tin' in s: return 'Tin'
    if 'build & battle' in s or 'build and battle' in s: return 'Build & Battle'
    if 'deck' in s: return 'Starter Deck'
    if 'collection' in s or 'chest' in s: return 'Collection Box'
    if 'premium' in s: return 'Premium Box'
    return 'Other Sealed'


def product(name, game, url, type_name):
    return {'name': clean(name), 'game': game, 'type': type_name, 'set': '', 'stock_status': 'Not checked', 'image': '', 'image_source': '', 'msrp': '', 'market_price': '', 'retailer_price': '', 'retailer': '', 'source': '', 'release_date': '', 'sku': '', 'url': url}


def image(value, base):
    if isinstance(value, list): value = next((v for v in value if v), '')
    if isinstance(value, dict): value = value.get('url') or value.get('contentUrl')
    if not isinstance(value, str) or not value: return ''
    u = urljoin(base, value)
    if not u.startswith(('https://', 'http://')) or any(x in u.lower() for x in ('sprite', 'favicon', 'placeholder', 'logo')): return ''
    return u


def page_image(soup, base):
    for n in soup.find_all('img'):
        src = n.get('src') or n.get('data-src') or n.get('data-lazy-src')
        u = image(src, base)
        if u and any(t in u.lower() for t in ('product', 'booster', 'deck', 'packaging')):
            return u
    for n in soup.find_all('meta'):
        if n.get('property') in ('og:image', 'og:image:secure_url'):
            return image(n.get('content'), base)
    return ''


def context(link):
    node = link
    for _ in range(5):
        if node.parent is None: break
        node = node.parent
        txt = clean(node.get_text(' ', strip=True))
        if date_from(txt) and len(txt) < 1500: return txt
    return clean(link.get_text(' ', strip=True))


def press_discovery():
    soup, _ = fetch(PRESS)
    found = {}
    for a in soup.find_all('a', href=True):
        name = clean(a.get_text(' ', strip=True))
        if not re.search(r'Pok[eé]mon\s+TCG\s*:', name, re.I) or '/products/' not in a['href']: continue
        url = urljoin(PRESS, a['href'])
        found[url] = {'name': name, 'game': 'Pokémon', 'type': 'Set Release', 'date': date_from(context(a)), 'msrp': '', 'url': url}
    if not found: raise RuntimeError('No Pokémon Press release entries parsed')
    return list(found.values())


def press_detail(release):
    soup, url = fetch(release['url'])
    # Official product detail pages can describe multiple formats. Keep each
    # named format as an announcement, never as a retailer stock listing.
    found = []
    seen = set()
    for node in structured(soup):
        if not is_product(node): continue
        name = clean(node.get('name'))
        if not is_sealed(name): continue
        key = name.casefold()
        if key in seen: continue
        seen.add(key)
        p = product(name, 'Pokémon', url + '#product-' + str(len(found)+1), kind(name))
        p['source'] = 'Pokémon Press product detail'
        p['release_date'] = release.get('date', '')
        p['image'] = image(node.get('image'), url)
        p['image_source'] = 'Pokémon Press' if p['image'] else ''
        p['discovery_confidence'] = 'official_structured_product'
        found.append(p)
    # Some official detail pages are announcements for one sealed format.
    if not found and is_sealed(release['name']):
        p = product(release['name'], 'Pokémon', url, kind(release['name']))
        p['source'] = 'Pokémon Press product announcement'
        p['release_date'] = release.get('date', '')
        p['image'] = page_image(soup, url)
        p['image_source'] = 'Pokémon Press' if p['image'] else ''
        p['discovery_confidence'] = 'official_announcement'
        found.append(p)
    return found


def union_discovery():
    soup, _ = fetch(UNION)
    found = {}
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/products/boosters/' not in href and '/products/decks/' not in href: continue
        name = clean(a.get_text(' ', strip=True))
        if not name: continue
        name = re.sub(r'^(BOOSTERS|PRECONSTRUCTED DECKS)\s+', '', name, flags=re.I)
        url = urljoin(UNION, href)
        k = 'Advanced Deck' if 'advanced deck' in name.lower() else ('Starter Deck' if '/decks/' in href else 'Booster Pack')
        p = product(name, 'Union Arena', url, k)
        p['source'] = 'Union Arena official catalogue'
        txt = context(a)
        p['release_date'] = date_from(txt)
        m = re.search(r'MSRP\s*:?\s*\$?\s*(\d+(?:\.\d{1,2})?)', txt, re.I)
        if m: p['msrp'] = '$' + m.group(1)
        node = a
        for _ in range(4):
            if node.parent is None: break
            node = node.parent
            for img in node.find_all('img'):
                u = image(img.get('src') or img.get('data-src'), UNION)
                if u and '/images/products/' in u.lower():
                    p['image'], p['image_source'] = u, 'Union Arena official catalogue'
                    break
            if p['image']: break
        found[url] = p
    if not found: raise RuntimeError('No Union Arena catalogue products parsed')
    return list(found.values())


def host(url):
    return (urlparse(url).hostname or '').lower()


def retailer_name(url):
    domain = host(url)
    for domain_suffix, name in (('bestbuy.com', 'Best Buy'), ('target.com', 'Target'), ('walmart.com', 'Walmart'), ('gamestop.com', 'GameStop'), ('pokemoncenter.com', 'Pokémon Center')):
        if domain == domain_suffix or domain.endswith('.' + domain_suffix): return name
    return ''


def normalize_availability(value):
    if not isinstance(value, str): return ''
    token = value.rstrip('/').split('/')[-1].lower()
    if token == 'instock': return 'In stock'
    if token in ('outofstock', 'soldout'): return 'Out of stock'
    if token == 'preorder': return 'Preorder'
    if token == 'backorder': return 'Backorder'
    return ''


def offer_records(value):
    if isinstance(value, list):
        for v in value: yield from offer_records(v)
    elif isinstance(value, dict):
        yield value
        for v in value.get('offers', []) if isinstance(value.get('offers'), list) else []:
            yield from offer_records(v)


def check_retailer(p):
    url = p.get('url', '')
    retailer = retailer_name(url)
    if not retailer: return None
    result = {'retailer': retailer, 'url': url, 'checked_at': now(), 'status': 'Unknown', 'method': 'JSON-LD Product offers', 'reason': ''}
    try:
        soup, final_url = fetch(url)
        if retailer_name(final_url) != retailer:
            raise ValueError('Unexpected redirect outside retailer domain')
        matches = []
        for node in structured(soup):
            if not is_product(node): continue
            name = clean(node.get('name'))
            # Require title evidence that this is the product, not a related item.
            expected = clean(p.get('name', '')).casefold()
            actual = name.casefold()
            if not name or not expected or (expected not in actual and actual not in expected): continue
            for offer in offer_records(node.get('offers')):
                availability = normalize_availability(offer.get('availability'))
                if availability: matches.append(availability)
        distinct = set(matches)
        if len(distinct) == 1:
            result['status'] = distinct.pop()
            result['reason'] = 'Explicit structured offer availability on matching product page'
        elif len(distinct) > 1:
            result['reason'] = 'Conflicting offer availability values'
        else:
            result['reason'] = 'No matching structured Product offer availability'
    except Exception as exc:
        result['reason'] = str(exc)[:240]
        result['check_failed'] = True
    return result


def merge(old, fresh):
    combined = {}
    for p in old:
        url = p.get('url', '')
        if not url: continue
        if p.get('sku') == '20038675' and 'valentine' in p.get('name', '').lower(): continue
        combined[(p.get('game', ''), url.rstrip('/'))] = p.copy()
    new_count = 0
    for p in fresh:
        key = (p.get('game', ''), p.get('url', '').rstrip('/'))
        if not key[1]: continue
        if key not in combined:
            p['first_seen'] = now()
            new_count += 1
            combined[key] = p.copy()
        else:
            existing = combined[key]
            for field, val in p.items():
                if val and field not in ('stock_status', 'first_seen', 'last_seen'):
                    existing[field] = val
        combined[key]['last_seen'] = now()
    return list(combined.values()), new_count


def main():
    old = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {'products': [], 'releases': []}
    old_products = old.get('products', [])
    statuses, errors, discovered = {}, [], []

    def source(name, fn):
        try:
            records = fn()
            statuses[name] = {'status': 'ok' if records else 'no_results', 'products_found': len(records), 'checked_at': now()}
            print(name, len(records))
            return records
        except Exception as exc:
            msg = str(exc)[:250]
            statuses[name] = {'status': 'error', 'error': msg, 'checked_at': now()}
            errors.append(name + ': ' + msg)
            print(name, 'ERROR', msg)
            return []

    press = source('Pokemon Press', press_discovery)
    discovered.extend(source('Union Arena', union_discovery))

    # Scan a bounded number of official detail pages per run.
    # Rotate through pages across runs, so later pages are not starved.
    cursor = int(old.get('v6_press_cursor', 0))
    if press:
        count = min(12, len(press))
        selected = [press[(cursor + i) % len(press)] for i in range(count)]
        old['v6_press_cursor'] = (cursor + count) % len(press)
        details_ok, details_fail = 0, 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(press_detail, r): r for r in selected}
            for future in as_completed(futures):
                try:
                    discovered.extend(future.result())
                    details_ok += 1
                except Exception as exc:
                    details_fail += 1
                    errors.append('Press detail: ' + str(exc)[:150])
        statuses['Pokemon Press detail pages'] = {'status': 'ok' if not details_fail else 'partial_error', 'pages_checked': count, 'pages_succeeded': details_ok, 'pages_failed': details_fail, 'checked_at': now()}

    products, new_count = merge(old_products, discovered)

    # Check only genuine, previously discovered retailer product URLs.
    # No general search-page availability or invented per-store claims.
    retailer_items = [p for p in products if retailer_name(p.get('url', ''))]
    stock_cursor = int(old.get('v6_stock_cursor', 0))
    selected_stock = [retailer_items[(stock_cursor + i) % len(retailer_items)] for i in range(min(10, len(retailer_items)))] if retailer_items else []
    if retailer_items:
        old['v6_stock_cursor'] = (stock_cursor + len(selected_stock)) % len(retailer_items)
    checks = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(check_retailer, p): p for p in selected_stock}
        for future in as_completed(futures):
            result = future.result()
            if result: checks.append(result)

    by_url = {c['url']: c for c in checks}
    for p in products:
        check = by_url.get(p.get('url', ''))
        if check:
            p['retailer_stock_check'] = check
            p['stock_status'] = check['status']
        else:
            # Never carry forward an old in-stock assertion as current.
            p['stock_status'] = 'Not checked'

    releases = {(r.get('game', ''), r.get('url', '')): r.copy() for r in old.get('releases', []) if r.get('url')}
    for r in press:
        key = (r['game'], r['url'])
        if key in releases:
            releases[key].update({k: v for k, v in r.items() if v})
        else:
            releases[key] = r
    for p in products:
        if not p.get('release_date'): continue
        key = (p.get('game', ''), p.get('url', ''))
        if key not in releases:
            releases[key] = {'name': p['name'], 'game': p['game'], 'type': p['type'], 'date': p['release_date'], 'msrp': p.get('msrp', ''), 'url': p['url']}

    old['products'] = products
    old['releases'] = list(releases.values())
    old['last_updated'] = now()
    old['check_interval_minutes'] = 5
    old['catalogue_source_status'] = statuses
    old['monitor_errors'] = errors
    old['retailer_stock_checks'] = 'partial_product_page_checks' if retailer_items else 'not_connected'
    old['v6_stock_checks'] = checks
    old['discovery_summary'] = {
        'new_products_this_run': new_count,
        'total_products': len(products),
        'pokemon_products': sum(p.get('game') == 'Pokémon' for p in products),
        'union_arena_products': sum(p.get('game') == 'Union Arena' for p in products),
        'products_with_images': sum(bool(p.get('image')) for p in products),
        'retailer_urls_available': len(retailer_items),
        'retailer_urls_checked_this_run': len(checks),
        'confirmed_availability_signals': sum(c['status'] != 'Unknown' for c in checks),
        'source_errors': len(errors),
        'updated_at': now(),
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding='utf-8')
    print('PokéStock V6 finished')
    print(json.dumps(old['discovery_summary'], indent=2))
    if errors:
        print('Errors:', *errors, sep='\n- ')


if __name__ == '__main__':
    main()
