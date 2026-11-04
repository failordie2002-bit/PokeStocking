#!/usr/bin/env python3
"""PokéStock 37: in-house alert radar + honest ONLINE restock forecaster.

Reads Script 36's public delayed alert archive; optionally reads a GitHub
repository_dispatch notification payload forwarded with the owner's consent.
Does not assert actual present availability, pickup, or shelf stock.
"""
import hashlib
import html
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

DATA = Path('data')
DATA.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)
EASTERN = ZoneInfo('America/New_York')
LOOKBACK_DAYS = 90
CUTOFF = NOW - timedelta(days=LOOKBACK_DAYS)

RETAILERS = [
    ('Best Buy', r'\bbest\s*buy\b', ('bestbuy.com',)),
    ('Walmart', r'\bwalmart\b', ('walmart.com',)),
    ('Target', r'\btarget\b', ('target.com',)),
    ('GameStop', r'\bgame\s*stop\b', ('gamestop.com',)),
    ('Barnes & Noble', r'\bbarnes\s*(?:&|and)\s*noble\b', ('barnesandnoble.com',)),
    ('Five Below', r'\bfive\s*below\b', ('fivebelow.com',)),
    ('Costco', r'\bcostco\b', ('costco.com',)),
    ('Sam\'s Club', r'\bsam\s*[\'’]?s\s*club\b', ('samsclub.com',)),
    ('Pokémon Center', r'\bpok[eé]mon\s*center\b', ('pokemoncenter.com',)),
    ('Amazon', r'\bamazon\b', ('amazon.com',)),
    ('CVS', r'\bcvs\b', ('cvs.com',)),
    ('Walgreens', r'\bwalgreens\b', ('walgreens.com',)),
]

GAME_RULES = [
    ('Pokémon', r'pok[eé]mon|pokemon|\bprismatic evolutions\b|\bdelta reign\b|\bscarlet\s*(?:&|and)\s*violet\b|\b151\s*(?:mini\s*tin|booster)\b|\bascended heroes\b|\bphantasmal flames\b'),
    ('Union Arena', r'union arena|\bue\d\d\s*bt\b'),
    ('One Piece', r'one piece|\bop[-\s]?\d{2}\b'),
    ('Magic: The Gathering', r'magic.the.gathering|\bmtg\b'),
    ('Disney Lorcana', r'\blorcana\b'),
    ('Yu-Gi-Oh!', r'yu[-\s]?gi[-\s]?oh'),
    ('Gundam', r'\bgundam\b'),
    ('Digimon', r'\bdigimon\b'),
    ('Dragon Ball Super', r'dragon ball'),
    ('Riftbound', r'\briftbound\b'),
    ('Weiß Schwarz', r'wei(?:ss|ß) schwarz'),
    ('Flesh and Blood', r'flesh.and.blood'),
]

SEALED = re.compile(
    r'\bbooster\b|\belite\s*trainer\s*box\b|\betb\b|\btin\b|'
    r'\bblister\b|\bcollection\b|\bstarter\s*deck\b|'
    r'\btrainer\s*box\b|\btrading\s*card\b|\btcg\b|\bpok[eé]mon\b', re.I
)
BAD = re.compile(
    r'\b(?:psa|bgs|cgc)\s*\d|\bsingles?\b|near[ -]?mint|'
    r'\bplaymat\b|\bsleeves?\b|\bbinders?\b|\bplush\b|'
    r'\bproxy\b|\bfigurines?\b|\bcode\s*card\b|'
    r'\bvirtual\s*card\b|\bgraded\b', re.I
)
ORDER = re.compile(r'\b(?:restock(?:ed)?|back\s*in\s*stock|in\s*stock|available|drop|alert)\b', re.I)
URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)
PRICE_RE = re.compile(r'(?<!\d)\$\s*(\d{1,5}(?:\.\d{1,2})?)(?!\d)')
APP_ALLOW = {'poketify', 'pokerestock', 'pok[eé]stock notifications', 'pokemon alerts', 'pokémon alerts', 'pkmn alerts'}
DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']


def read(name, fallback):
    try:
        return json.loads((DATA/name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def write(name, data):
    dest = DATA/name
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    temp.replace(dest)


def clean(value, limit=350):
    s = html.unescape(str(value or ''))
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:limit]


def norm(value):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', str(value or '').lower()).encode('ascii','ignore').decode('ascii'))


def parsed_at(s):
    try:
        d = datetime.fromisoformat(str(s).replace('Z','+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(timezone.utc)
        return d if CUTOFF <= d <= NOW + timedelta(minutes=8) else None
    except (ValueError, TypeError):
        return None


def safe_link(text):
    """Keep HTTPS URL and a minimal set of nontracking purchase identifiers."""
    try:
        src = urlsplit(str(text).rstrip('.,;)]'))
        if src.scheme != 'https' or not src.hostname or src.username or src.password:
            return ''
        if len(src.netloc)>160 or len(src.path)>600:
            return ''
        retain = {'skuId','skuID','variant','tcin','id','asin'}
        qs = [(k,v) for k,v in parse_qsl(src.query, keep_blank_values=False) if k in retain and len(v)<100]
        return urlunsplit(('https',src.netloc.lower(),src.path,urlencode(qs),''))
    except ValueError:
        return ''


def retailer_from(text, url=''):
    h = urlsplit(url).hostname or '' if url else ''
    for retailer, pattern, domains in RETAILERS:
        if any(h == d or h.endswith('.'+d) for d in domains):
            return retailer
    for retailer, pattern, _ in RETAILERS:
        if re.search(pattern, text, re.I):
            return retailer
    return ''


def game_from(text):
    for name, p in GAME_RULES:
        if re.search(p,text,re.I):
            return name
    return 'Other TCG'


def sealed(text):
    return bool(SEALED.search(text) and not BAD.search(text))


def stable_id(prefix, *parts):
    return prefix + hashlib.sha256('|'.join(map(str,parts)).encode('utf-8')).hexdigest()[:22]


def normalize_external(x):
    """Only the finite, dated restock history from Script 36. No live stock claim."""
    if not isinstance(x,dict):
        return None
    when = parsed_at(x.get('reported_at'))
    product = clean(x.get('product_name'),230)
    retailer = clean(x.get('retailer'),65)
    if not when or not retailer or not sealed(product):
        return None
    url = safe_link(x.get('retailer_url'))
    source = safe_link(x.get('source_url'))
    if not source:
        return None
    price = str(x.get('price_reported') or '').strip()
    if not re.fullmatch(r'\d{1,5}(?:\.\d{1,2})?',price):
        price = ''
    return {
        'id': stable_id('delayed-',x.get('id') or '',source,url,product,when.isoformat()),
        'product_name': product,
        'game': game_from(product),
        'retailer': retailer,
        'price_reported': price,
        'reported_at': when.isoformat(),
        'source': 'Public delayed restock history',
        'source_kind': 'external_delayed_alert',
        'source_url': source,
        'retailer_url': url,
        'availability': 'Restock reported — not verified now',
        'stock_verified_now': False,
        'physical_store_verified': False,
        'inventory_scope': 'online_restock_signal',
        'location_name': None,
        'store_id': None,
    }


def parse_notification(raw):
    """Future opt-in Android forwarding input, received via repository_dispatch.

    No raw notification text is ever committed; only accepted product metadata.
    """
    if not isinstance(raw,dict):
        return None, 'no_dispatch_payload'
    app = clean(raw.get('app'),70)
    if norm(app) not in {norm(a) for a in APP_ALLOW}:
        return None, 'unsupported_notification_app'
    title = clean(raw.get('title'),250)
    body = clean(raw.get('text'),700)
    whole = clean(title+' '+body,900)
    if not whole or not ORDER.search(whole):
        return None, 'not_a_stock_alert'
    # Never record personal notification contents. Ignore unknown hosts.
    urls = [safe_link(m.group(0)) for m in URL_RE.finditer(whole)]
    urls = [u for u in urls if u]
    retailer = retailer_from(whole, next((u for u in urls if retailer_from('',u)),''))
    if not retailer:
        return None, 'unknown_retailer'
    product = title if title and re.search(r'pokemon|pok[eé]mon|booster|union arena|tcg|\betb\b',title,re.I) else body
    product = URL_RE.sub('',product)
    product = re.sub(r'(?i)\b(?:best buy|walmart|target|gamestop)\b[:\-]?',' ',product)
    product = re.sub(r'(?i)\b(?:is|just|now|back|in stock|restocked|available|alert|drop|buy now)\b',' ',product)
    product = PRICE_RE.sub(' ',product)
    product = clean(product.strip(' -:,.!'),230)
    if not sealed(product):
        return None, 'no_recognizable_sealed_product'
    when = parsed_at(raw.get('received_at')) or NOW
    price_match = PRICE_RE.search(whole)
    price = price_match.group(1) if price_match else ''
    purchase_url = next((u for u in urls if retailer_from('',u)==retailer),'')
    identity = (retailer,norm(product),when.replace(second=0,microsecond=0).isoformat())
    return {
        'id': stable_id('phone-',*identity),
        'product_name': product,
        'game': game_from(product),
        'retailer': retailer,
        'price_reported': price,
        'reported_at': when.isoformat(),
        'source': app + ' notification (authorized forwarding)',
        'source_kind': 'user_forwarded_notification',
        'source_url': '',
        'retailer_url': purchase_url,
        'availability': 'Notification reported a restock — verify before purchase',
        'stock_verified_now': False,
        'physical_store_verified': False,
        'inventory_scope': 'online_restock_signal',
        'location_name': None,
        'store_id': None,
    }, 'accepted'


def next_weekday(day):
    today = NOW.astimezone(EASTERN).date()
    ahead = (day - today.weekday()) % 7
    return (today + timedelta(days=ahead if ahead else 7)).isoformat()


def forecasts(rows):
    """Count unique observation *dates*, not report volume. Never call them probabilities."""
    by_retailer = defaultdict(list)
    by_product = defaultdict(list)
    for row in rows:
        d = parsed_at(row.get('reported_at'))
        if not d:
            continue
        loc = d.astimezone(EASTERN)
        if row.get('inventory_scope') != 'online_restock_signal':
            continue
        by_retailer[row['retailer']].append(loc)
        key = (row['retailer'], norm(row['product_name']))
        by_product[key].append((row['product_name'], loc))

    ret = []
    for retailer, dates in sorted(by_retailer.items()):
        unique_days = sorted({d.date() for d in dates})
        counts = Counter(d.weekday() for d in unique_days)
        span = (unique_days[-1]-unique_days[0]).days if len(unique_days)>1 else 0
        good = len(unique_days)>=6 and span>=21
        ranked=sorted(counts.items(),key=lambda item:(-item[1],item[0]))
        signals = len(dates)
        ret.append({
            'retailer': retailer,
            'signal_count': signals,
            'distinct_observation_dates': len(unique_days),
            'date_span_days': span,
            'confidence': 'Limited historical signal' if good else 'Insufficient evidence',
            'forecast_status': 'historical_watch_window' if good else 'insufficient_history',
            'weekday_counts': [{'day':DAYS[i],'count':counts.get(i,0)} for i in range(7)],
            'watch_windows': [
                {'weekday':DAYS[i], 'historical_dates':n, 'next_matching_date':next_weekday(i),
                 'share_of_observed_dates_pct':round(n*100/len(unique_days))}
                for i,n in ranked[:2]
            ] if good else [],
            'interpretation': 'Weekday distribution of dated ONLINE restock alerts, not stock likelihood or a delivery promise.'
        })

    prod = []
    for (retailer, key), events in by_product.items():
        days = sorted({d.date() for _,d in events})
        span = (days[-1]-days[0]).days if len(days)>1 else 0
        if len(days)<4 or span<14:
            continue
        counts = Counter(d.weekday() for d in days)
        top = counts.most_common(1)[0]
        prod.append({'retailer':retailer,'product_name':events[-1][0],
                     'observations':len(events),'distinct_dates':len(days),
                     'preferred_weekday':DAYS[top[0]],
                     'next_matching_date':next_weekday(top[0]),
                     'interpretation':'Historical online watch window only; no stock guarantee.'})
    prod.sort(key=lambda x:(-x['distinct_dates'],x['retailer']))
    return {
        'version':'37.0',
        'updated_at':NOW.isoformat(),
        'inventory_scope':'online_restock_signal',
        'lookback_days':LOOKBACK_DAYS,
        'weekday_timezone':'America/New_York',
        'source_count':len(rows),
        'retailer_patterns': ret,
        'product_patterns': prod[:100],
        'method':'Counts distinct dates with alerts, never store inventory; requires 6 distinct dates across 21 days before a retailer-level watch window.',
        'excluded_from_shipment_forecaster':True,
        'store_level_inventory_confirmed':0,
    }


def main():
    previous = read('alert_events_37.json',[])
    prior_phone = [x for x in previous if isinstance(x,dict) and x.get('source_kind')=='user_forwarded_notification'] if isinstance(previous,list) else []
    external = read('external_alerts_36.json',[])
    if not isinstance(external,list):
        external=[]
    delayed = [x for x in (normalize_external(r) for r in external) if x]
    incoming = os.getenv('POKESTOCK_ALERT_PAYLOAD','null')
    try:
        payload=json.loads(incoming)
        if isinstance(payload,dict) and len(incoming)<13000:
            forwarded,reason=parse_notification(payload)
        else:
            forwarded,reason=None,'no_dispatch_payload'
    except ValueError:
        forwarded,reason=None,'invalid_dispatch_json'

    combined = {x['id']:x for x in prior_phone+delayed if isinstance(x,dict) and x.get('id') and parsed_at(x.get('reported_at'))}
    if forwarded:
        combined[forwarded['id']]=forwarded
    rows = sorted(combined.values(),key=lambda x:x['reported_at'],reverse=True)[:2500]
    write('alert_events_37.json',rows)
    f=forecasts(rows)
    write('online_forecaster_37.json',f)
    counts=Counter(x.get('retailer') for x in rows)
    report={
        'version':'37.0','updated_at':NOW.isoformat(),
        'external_delayed_alerts':len(delayed),
        'user_forwarded_notifications':sum(x.get('source_kind')=='user_forwarded_notification' for x in rows),
        'new_notification_status':reason,
        'new_notification_recorded':bool(forwarded),
        'total_90d_alerts':len(rows),
        'retailers':dict(sorted(counts.items())),
        'best_buy_24h':sum(x.get('retailer')=='Best Buy' and parsed_at(x['reported_at'])>=NOW-timedelta(hours=24) for x in rows),
        'retailers_with_forecast_watch_window':sum(x['forecast_status']=='historical_watch_window' for x in f['retailer_patterns']),
        'verified_online_stock_from_these_alerts':0,
        'verified_in_store_stock_from_these_alerts':0,
        'notes':['Data shown in-house. External purchase/source links are optional.',
                 'Third-party restock alerts are historical evidence, not current inventory.',
                 'Online restocks are never added to physical shipment events.',
                 'Live Android forwarding requires an authorized one-time setup.'],
    }
    write('alert_bridge_report_37.json',report)
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
