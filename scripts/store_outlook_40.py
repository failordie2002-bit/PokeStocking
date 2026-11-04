#!/usr/bin/env python3
"""Store research, regional chatter, and verified history remain separate."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path('data')
NOW = datetime.now(timezone.utc)

def read(name, default):
    try:
        v = json.loads((DATA/name).read_text(encoding='utf-8'))
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default

def clean(value, limit=180):
    return ' '.join(str(value or '').split())[:limit]

def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None

def key(value):
    return ''.join(x for x in clean(value).casefold() if x.isalnum())

def chain_of(row):
    value = clean(row.get('retailer_chain') or row.get('chain') or row.get('retailer'), 90)
    if value: return value
    name = clean(row.get('name') or row.get('store_name'), 150).casefold()
    for n in ('Walmart','Target','Best Buy','GameStop','Dollar General',
              'Five Below','Barnes & Noble','CVS','Walgreens','Costco',
              "Sam's Club",'Dollar Tree','Ross'):
        if n.casefold() in name: return n
    return 'Independent / other'

def store_row(raw):
    sid = clean(raw.get('id') or raw.get('store_id'), 100)
    if not sid: return None
    name = clean(raw.get('name') or raw.get('store_name'), 180)
    city = clean(raw.get('city'), 100)
    state = clean(raw.get('state'), 30)
    if not name: name = chain_of(raw) + (' — ' + city if city else '')
    zip_code = clean(raw.get('zip') or raw.get('zipcode') or raw.get('postal_code'), 16)
    return {'store_id':sid,'store_name':name,'chain':chain_of(raw),
            'city':city,'state':state,'zip':zip_code,
            'verified_store_sightings':0,'provisional_reports':[],
            'city_area_reports':[],'research_watch':False,
            'research_basis':'','research_source':'',
            'outlook':'No store-specific evidence',
            'confidence':'Insufficient evidence','watch_weekday':None,
            'last_reported_at':None}

def main():
    originals = read('stores.json', [])
    legacy = read('v30_restock_forecasts.json', [])
    shipments = read('shipments.json', {})
    sightings = read('v34_public_sightings.json', [])
    exact_events = read('restock_observations.json', [])
    releases = read('v30_release_watch.json', [])
    by_id = {}
    for raw in originals:
        if isinstance(raw, dict):
            s = store_row(raw)
            if s: by_id[s['store_id']] = s
    for raw in legacy:
        if not isinstance(raw, dict): continue
        s = store_row(raw)
        if s and s['store_id'] not in by_id: by_id[s['store_id']] = s

    research = {}
    for item in shipments.get('forecasts', []) if isinstance(shipments, dict) else []:
        if not isinstance(item, dict): continue
        sid = clean(item.get('store_id'),100)
        # Generic retailer guidance is NOT a store delivery prediction.
        if sid and item.get('delivery_confirmed') is False and item.get('confidence') == 'Research only':
            research[sid] = item

    reports = {}
    for r in sightings:
        if not isinstance(r, dict): continue
        t = stamp(r.get('reported_at_approx'))
        if not t or t > NOW+timedelta(hours=1) or NOW-t > timedelta(days=60): continue
        report_id = clean(r.get('event_id'), 100)
        if not report_id: continue
        reports[report_id] = {
            'id': report_id, 'store_id':clean(r.get('store_id'),100),
            'retailer':clean(r.get('retailer'),90),'city':clean(r.get('city'),100),
            'state':clean(r.get('state'),30),'product':clean(r.get('product_name'),220),
            'game':clean(r.get('game'),90),'reported_at':t.isoformat(),
            'source_url':clean(r.get('source_url'),500),
            'store_match_verified':r.get('store_match_verified') is True,
            'stock_verified':r.get('current_stock_verified') is True,
            'time_precision':clean(r.get('time_precision'),80)
        }
    # Join additional records by exact store ID, never by city alone.
    for r in exact_events:
        if not isinstance(r, dict): continue
        sid = clean(r.get('store_id'),100)
        if sid not in by_id: continue
        report_id = clean(r.get('event_id'),100)
        if report_id in reports: continue
        t = stamp(r.get('observed_at'))
        if not t or t > NOW+timedelta(hours=1) or NOW-t > timedelta(days=60): continue
        reports[report_id] = {
            'id':report_id,'store_id':sid,'retailer':clean(r.get('retailer'),90),
            'city':clean(r.get('city'),100),'state':clean(r.get('state'),30),
            'product':clean(r.get('product_name'),220),'game':clean(r.get('game'),90),
            'reported_at':t.isoformat(),'source_url':clean(r.get('source_url'),500),
            'store_match_verified':r.get('store_match_verified') is True,
            'stock_verified':False,'time_precision':clean(r.get('time_precision'),80)
        }

    by_city = defaultdict(list)
    verified_by_store = defaultdict(list)
    for report in reports.values():
        by_city[(key(report['retailer']),key(report['city']),key(report['state']))].append(report)
        if report['store_id'] in by_id and report['store_match_verified']:
            verified_by_store[report['store_id']].append(report)

    for s in by_id.values():
        sid = s['store_id']
        if sid in research:
            s['research_watch'] = True
            s['research_basis'] = clean(research[sid].get('basis'),250)
            s['research_source'] = clean(research[sid].get('source_url'),500)
        city_events = sorted(by_city.get((key(s['chain']),key(s['city']),key(s['state'])),[]),
                             key=lambda x:x['reported_at'],reverse=True)
        s['city_area_reports'] = [{k:r[k] for k in ('id','product','game','reported_at','source_url','time_precision')}
                                  for r in city_events[:3]]
        provisional = [r for r in city_events if r['store_id']==sid and not r['store_match_verified']]
        s['provisional_reports'] = [{k:r[k] for k in ('id','product','game','reported_at','source_url','time_precision')}
                                    for r in provisional[:3]]
        good = verified_by_store.get(sid,[])
        dates = sorted({r['reported_at'][:10] for r in good})
        s['verified_store_sightings'] = len(dates)
        if city_events: s['last_reported_at'] = city_events[0]['reported_at']
        if len(dates) >= 5 and (datetime.fromisoformat(dates[-1])-datetime.fromisoformat(dates[0])).days >= 21:
            weekday_counts = Counter(datetime.fromisoformat(d).strftime('%A') for d in dates)
            day, number = weekday_counts.most_common(1)[0]
            if number >= 3:
                s['watch_weekday'] = day
                s['confidence'] = 'Limited store history'
                s['outlook'] = 'Historical weekday pattern — not a delivery prediction'
        if s['outlook'] == 'No store-specific evidence':
            if provisional:
                s['outlook'] = 'Provisional community sighting — stock unknown'
            elif city_events:
                s['outlook'] = 'City-level community reports — not this store'
            elif s['research_watch']:
                s['outlook'] = 'Retailer research lead — no store-specific date'

    ordered = sorted(by_id.values(), key=lambda s:(s['state'],s['city'],s['chain'],s['store_name']))
    valid_releases = []
    for r in releases:
        if not isinstance(r,dict): continue
        ds = clean(r.get('date'),15)
        try: d = datetime.strptime(ds,'%Y-%m-%d').date()
        except ValueError: continue
        if d < NOW.date() or d > (NOW+timedelta(days=120)).date(): continue
        valid_releases.append({'name':clean(r.get('name'),220),'game':clean(r.get('game'),80),
                               'date':ds,'source_url':clean(r.get('source_url'),500),
                               'label':'Official release date — not a store stock confirmation'})
    valid_releases.sort(key=lambda x:x['date'])
    summary = {
        'version':'40.0','generated_at':NOW.isoformat(),
        'store_candidates':len(ordered),'public_unverified_sightings':len(reports),
        'stores_with_city_reports':sum(bool(s['city_area_reports']) for s in ordered),
        'stores_with_provisional_reports':sum(bool(s['provisional_reports']) for s in ordered),
        'stores_with_retailer_research_leads':sum(s['research_watch'] for s in ordered),
        'stores_with_historical_watch_weekday':sum(bool(s['watch_weekday']) for s in ordered),
        'verified_live_store_inventory':0,
        'meaning':'Research signals and sightings are not guaranteed current stock, truck deliveries, or forecasts.',
        'coverage_note':'Store candidates may not sell TCG products. Some community reports are city-level only.',
        'stores':ordered,'upcoming_official_releases':valid_releases[:16]
    }
    file = DATA/'store_outlook_40.json'
    encoded = json.dumps(summary,ensure_ascii=False,separators=(',',':'))+'\n'
    if not file.exists() or file.read_text(encoding='utf-8') != encoded:
        file.write_text(encoded, encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('stores','upcoming_official_releases')},indent=2))
if __name__ == '__main__': main()
