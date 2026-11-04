#!/usr/bin/env python3
"""PokéStock 38: independently observed restock transitions from first-party merchant feeds.

No user app, token, external notification provider, or competitor alert is required.
Only public Shopify variant availability evidence, as observed by the existing
PokéStock online-inventory scanner, is eligible for a restock transition.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DATA=Path('data')
DATA.mkdir(exist_ok=True)
OFFERS=DATA/'online_offers.json'
STATE=DATA/'merchant_watch_state_38.json'
EVENTS=DATA/'first_party_restocks_38.json'
REPORT=DATA/'first_party_report_38.json'
NOW=datetime.now(timezone.utc)
MAX_AGE=timedelta(hours=4)
KEEP=timedelta(days=28)
GOOD={'shopify_public_variant'}


def load(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def iso_dt(raw):
    try:
        d=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError,ValueError,OverflowError): return None


def canon_url(raw):
    try:
        z=urlsplit(str(raw))
        if z.scheme!='https' or not z.hostname: return ''
        return urlunsplit(('https',z.netloc.lower(),z.path.rstrip('/'),'', ''))
    except (ValueError,TypeError): return ''


def status(raw):
    v=str(raw or '').strip().lower()
    if v in ('in stock','available','in_stock'): return True
    if v in ('out of stock','sold out','unavailable','out_of_stock'): return False
    return None


def clean(v,maxlen=280): return ' '.join(str(v or '').split())[:maxlen]


def save(path,obj):
    value=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
    if path.exists() and path.read_text(encoding='utf-8')==value: return False
    path.write_text(value,encoding='utf-8')
    return True


def main():
    raw=load(OFFERS,[])
    if not isinstance(raw,list): raise SystemExit('Invalid offers feed: expected list')
    prev=load(STATE,{})
    if not isinstance(prev,dict): prev={}
    initialized=STATE.exists()
    records=dict(prev)
    events=load(EVENTS,[])
    if not isinstance(events,list): events=[]
    known={x.get('id') for x in events if isinstance(x,dict)}
    examined=valid=up=down=0
    eligible={}
    for row in raw:
        examined+=1
        if not isinstance(row,dict) or row.get('evidence_type') not in GOOD: continue
        d=iso_dt(row.get('checked_at'))
        if d is None or d > NOW+timedelta(minutes=10) or NOW-d > MAX_AGE: continue
        st=status(row.get('availability'))
        if st is None: continue
        url=canon_url(row.get('product_url'))
        if not url: continue
        retailer=clean(row.get('retailer'),100)
        product=clean(row.get('product_name'),300)
        if not (retailer and product): continue
        variant=clean(row.get('variant'),100)
        sku=clean(row.get('sku'),100)
        key=hashlib.sha256(('\x1f'.join([retailer,url,sku,variant])).encode()).hexdigest()[:28]
        item={'key':key,'retailer':retailer,'product_name':product,'game':clean(row.get('game'),100),
              'product_url':url,'sku':sku,'variant':variant,
              'available':st,'checked_at':d.isoformat(),'price':clean(row.get('price'),40),
              'currency':clean(row.get('currency'),20),'evidence_type':'shopify_public_variant'}
        if key not in eligible or iso_dt(eligible[key]['checked_at']) < d:
            eligible[key]=item
    valid=len(eligible)
    for key,item in eligible.items():
        old=records.get(key)
        oldtime=iso_dt(old.get('checked_at')) if isinstance(old,dict) else None
        dt=iso_dt(item['checked_at'])
        if oldtime and dt<=oldtime: continue
        if old and isinstance(old,dict) and old.get('available') is False and item['available'] is True:
            up+=1
            event_id=hashlib.sha256((key+'|'+item['checked_at']).encode()).hexdigest()[:26]
            if 'merchant-'+event_id not in known:
                events.append({'id':'merchant-'+event_id,'source_kind':'first_party_storefront',
                   'event_type':'out_to_in_stock','inventory_scope':'online',
                   'stock_verified_now':False,'physical_store_verified':False,
                   'availability':'Storefront showed available at observation time',
                   'product_name':item['product_name'],'game':item['game'],
                   'retailer':item['retailer'],'price_reported':item['price'],
                   'currency':item['currency'],'variant':item['variant'],
                   'checked_at':item['checked_at'],'reported_at':item['checked_at'],
                   'retailer_url':item['product_url'],'source_url':item['product_url'],
                   'evidence_type':item['evidence_type'],
                   'evidence_quality':'direct_public_storefront_at_observation_time'})
                known.add('merchant-'+event_id)
        if old and isinstance(old,dict) and old.get('available') is True and item['available'] is False:
            down+=1
        records[key]={'available':item['available'],'checked_at':item['checked_at']}
    # A product omitted from a partial scan is NOT out of stock.
    recent=[]
    for e in events:
        if not isinstance(e,dict): continue
        t=iso_dt(e.get('checked_at'))
        if t and NOW-t<=KEEP and t<=NOW+timedelta(minutes=10): recent.append(e)
    recent.sort(key=lambda e:e['checked_at'],reverse=True)
    recent=recent[:300]
    stale=NOW-timedelta(days=120)
    records={k:v for k,v in records.items() if isinstance(v,dict) and (iso_dt(v.get('checked_at')) or stale-timedelta(days=1))>=stale}
    report={'version':'38.0','source':'PokéStock independently checked merchant listings',
       'seeded_initial_snapshot':not initialized,'source_offer_rows':examined,
       'fresh_explicit_variant_listings':valid,'tracked_variants':len(records),
       'new_restock_transitions':up,'new_stockout_transitions':down,
       'recent_restock_events':len(recent),
       'last_processed_offer_check':max((x['checked_at'] for x in eligible.values()),default=None),
       'not_supported':'Retailer shelf availability, online checkout success, push while site closed',
       'meaning':'Observations as of a recorded scan, not a promise of current stock'}
    changed_state=save(STATE,records)
    changed_events=save(EVENTS,recent)
    if changed_state or changed_events or not REPORT.exists(): save(REPORT,report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
