
#!/usr/bin/env python3
"""PokéStock V7.2: conservative catalogue and independent-shop discovery.
Requires requests and beautifulsoup4 (existing GitHub workflow dependencies).
Optional configuration: data/shops.json and data/retailer_sources.json.
Never infers physical-store stock from online stock or search snippets.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

DB = Path('data/status.json')
SHOPS = Path('data/shops.json')
STORE_SOURCES = Path('data/retailer_sources.json')
VERSION = '7.2'
NOW = datetime.now(timezone.utc)
HEADERS = {'User-Agent': 'PokestockCatalogMonitor/7.2 (+public catalogues; no checkout automation)', 'Accept': 'text/html,application/json,application/xml;q=0.9,*/*;q=0.8'}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
ERRORS = []
HEALTH = {}
MAX_SHOPS = 12
MAX_ITEMS_PER_SHOP = 100
MAX_STORE_SOURCES = 20
TTL_SECONDS = 6 * 3600
POKEMON_PRESS = 'https://press.pokemon.com/en/Items/Schedule?period=All&types=3&sortAsc=False&sortBy=Date'
UNION = 'https://www.unionarena-tcg.com/na/products/'
SEALED = ('booster', 'elite trainer', 'collection', 'bundle', 'tin', 'blister', 'deck', 'display', 'battle academy', 'build & battle', 'premium', 'chest', 'battle stadium')
EXCLUDE = ('sleeves', 'binder', 'playmat', 'portfolio', 'deck box', 'plush', 'apparel', 'single card', 'individual card', 'graded', 'digital code')
BIG_RETAILERS = {'walmart.com':'Walmart','target.com':'Target','bestbuy.com':'Best Buy','gamestop.com':'GameStop','pokemoncenter.com':'Pokémon Center'}

def stamp(): return datetime.now(timezone.utc).isoformat()
def norm(s): return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', str(s or '').casefold().replace('é','e'))).strip()
def safe_url(s):
    try:
        u=urlparse(str(s)); return u.scheme=='https' and bool(u.hostname) and not u.username and not u.password
    except (TypeError,ValueError): return False

def host(url): return (urlparse(url).hostname or '').lower()
def same_host(a,b): return host(a)==host(b)
def get(url, json_mode=False):
    if not safe_url(url): raise ValueError('HTTPS URL required')
    r=SESSION.get(url,timeout=(7,17),allow_redirects=True)
    r.raise_for_status()
    if not same_host(url,r.url): raise ValueError('Cross-domain redirect rejected')
    if len(r.content)>5_000_000: raise ValueError('Response exceeds 5MB limit')
    return r.json() if json_mode else BeautifulSoup(r.text,'html.parser')

def walk(obj):
    if isinstance(obj,list):
        for x in obj: yield from walk(x)
    elif isinstance(obj,dict):
        yield obj
        for x in obj.values():
            if isinstance(x,(dict,list)): yield from walk(x)

def structured(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try: yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError): continue

def kind(obj,name):
    t=obj.get('@type',[]); t=[t] if isinstance(t,str) else t
    return any(str(v).split('/')[-1]==name for v in t)

def game(name):
    n=norm(name)
    if 'pokemon' in n: return 'Pokémon'
    if 'union arena' in n: return 'Union Arena'
    return ''

def sealed(name):
    n=norm(name)
    return bool(game(name)) and any(norm(x) in n for x in SEALED) and not any(norm(x) in n for x in EXCLUDE)

def image_of(value,base):
    if isinstance(value,list): value=next(iter(value),'')
    if isinstance(value,dict): value=value.get('url') or value.get('contentUrl','')
    if not isinstance(value,str): return ''
    url=urljoin(base,value)
    return url if safe_url(url) else ''

def record(name, fn):
    try:
        result=fn()
        HEALTH[name]={'status':'ok' if result else 'no_results','count':len(result),'checked_at':stamp()}
        return result
    except Exception as exc:
        msg=f'{type(exc).__name__}: {str(exc)[:220]}'
        ERRORS.append(f'{name}: {msg}')
        HEALTH[name]={'status':'error','error':msg,'checked_at':stamp()}
        return []

def load_json(path,default):
    if not path.exists(): return default
    return json.loads(path.read_text(encoding='utf-8'))

def official_pokemon():
    soup=get(POKEMON_PRESS); out={}
    for a in soup.select('a[href*="/products/"]'):
        title=a.get_text(' ',strip=True)
        if not re.search(r'Pok[eé]mon\s+TCG\s*:',title,re.I): continue
        url=urljoin(POKEMON_PRESS,a['href'])
        if not safe_url(url): continue
        parent=a
        date=''
        for _ in range(5):
            parent=parent.parent if parent.parent else parent
            match=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',parent.get_text(' ',strip=True),re.I)
            if match:
                try: date=datetime.strptime(match.group().replace(',',''),'%B %d %Y').date().isoformat()
                except ValueError: pass
                break
        out[url]={'name':title,'game':'Pokémon','type':'Set Release','date':date,'url':url}
    if not out: raise ValueError('Official schedule returned no parsable releases')
    return list(out.values())

def official_union():
    soup=get(UNION); out={}
    for a in soup.select('a[href]'):
        href=a.get('href','')
        if '/products/boosters/' not in href and '/products/decks/' not in href: continue
        url=urljoin(UNION,href)
        if not safe_url(url): continue
        title=a.get_text(' ',strip=True)
        if not title: continue
        title=re.sub(r'^(BOOSTERS|PRECONSTRUCTED DECKS)\s+','',title,flags=re.I)
        item={'name':title,'game':'Union Arena','type':'Starter Deck' if '/decks/' in href else 'Booster Pack','url':url,'source':'Union Arena official catalogue','stock_status':'Not checked','image':'','release_date':''}
        parent=a
        for _ in range(4):
            parent=parent.parent if parent.parent else parent
            for im in parent.select('img[src],img[data-src]'):
                candidate=image_of(im.get('src') or im.get('data-src'),UNION)
                if '/images/products/' in candidate: item['image']=candidate; break
            if item['image']: break
        out[url]=item
    if not out: raise ValueError('Official Union Arena catalogue returned no parsable products')
    return list(out.values())

def catalog_key(p):
    return (norm(p.get('game')),str(p.get('url','')).rstrip('/'))

def merge(old,new):
    result={}; added=0
    for p in old:
        if isinstance(p,dict) and p.get('url'): result[catalog_key(p)]=dict(p)
    for p in new:
        key=catalog_key(p)
        if not key[1]: continue
        if key not in result:
            result[key]=dict(p); result[key]['first_seen']=stamp(); added+=1
        else:
            for k,v in p.items():
                if v and k not in ('stock_status','first_seen'): result[key][k]=v
        result[key]['last_seen']=stamp()
    return list(result.values()),added

def shops_config():
    shops=load_json(SHOPS,[])
    if not isinstance(shops,list): raise ValueError('data/shops.json must contain a JSON array')
    cleaned=[]; seen=set()
    for shop in shops:
        if not isinstance(shop,dict): continue
        url=str(shop.get('url','')).rstrip('/')
        if not safe_url(url) or url in seen: continue
        seen.add(url)
        cleaned.append({'name':str(shop.get('name') or host(url)),'url':url,'city':str(shop.get('city','')),'state':str(shop.get('state','')),'id':str(shop.get('id') or hashlib.sha256(url.encode()).hexdigest()[:12])})
    return cleaned

def parse_shopify(shop):
    url=shop['url']+'/products.json?limit=250'
    payload=get(url,json_mode=True)
    products=payload.get('products') if isinstance(payload,dict) else None
    if not isinstance(products,list): raise ValueError('Shopify product endpoint missing products array')
    found=[]
    for p in products[:MAX_ITEMS_PER_SHOP]:
        title=str(p.get('title',''))
        if not sealed(title): continue
        handle=p.get('handle')
        if not handle: continue
        link=shop['url']+'/products/'+str(handle)
        if not safe_url(link): continue
        variants=p.get('variants') or []
        # Shopify available may represent ONLINE inventory, never physical location.
        availability=[v.get('available') for v in variants if isinstance(v,dict)]
        online='In stock' if any(v is True for v in availability) else 'Out of stock' if availability and all(v is False for v in availability) else 'Unknown'
        imgs=p.get('images') or []
        img=image_of(imgs[0].get('src'),shop['url']) if imgs and isinstance(imgs[0],dict) else ''
        found.append({'name':title,'game':game(title),'type':'Sealed TCG product','url':link,'image':img,'source':'Independent shop Shopify catalogue','retailer':shop['name'],'online_stock_status':online,'stock_status':'Not checked','shop_id':shop['id']})
    return found

def parse_woocommerce(shop):
    # Public WordPress Store API, if enabled by shop.
    url=shop['url']+'/wp-json/wc/store/v1/products?per_page=100'
    payload=get(url,json_mode=True)
    if not isinstance(payload,list): raise ValueError('WooCommerce public Store API unavailable')
    found=[]
    for p in payload[:MAX_ITEMS_PER_SHOP]:
        title=BeautifulSoup(str(p.get('name','')),'html.parser').get_text(' ',strip=True)
        if not sealed(title): continue
        link=p.get('permalink','')
        if not safe_url(link) or host(link)!=host(shop['url']): continue
        imgs=p.get('images') or []
        img=image_of(imgs[0].get('src'),shop['url']) if imgs and isinstance(imgs[0],dict) else ''
        availability=p.get('is_in_stock')
        online='In stock' if availability is True else 'Out of stock' if availability is False else 'Unknown'
        found.append({'name':title,'game':game(title),'type':'Sealed TCG product','url':link,'image':img,'source':'Independent shop WooCommerce Store API','retailer':shop['name'],'online_stock_status':online,'stock_status':'Not checked','shop_id':shop['id']})
    return found

def parse_structured_shop(shop):
    # Product JSON-LD from homepage only; not an exhaustive catalogue.
    soup=get(shop['url']); found=[]
    for p in structured(soup):
        if not kind(p,'Product'): continue
        title=str(p.get('name',''))
        if not sealed(title): continue
        link=p.get('url') or shop['url']
        if not safe_url(link) or host(link)!=host(shop['url']): continue
        found.append({'name':title,'game':game(title),'type':'Sealed TCG product','url':link,'image':image_of(p.get('image'),shop['url']),'source':'Independent shop structured product metadata','retailer':shop['name'],'online_stock_status':'Unknown','stock_status':'Not checked','shop_id':shop['id']})
    return found

def scan_shop(shop):
    errors=[]
    for label,fn in [('shopify',parse_shopify),('woocommerce',parse_woocommerce),('jsonld',parse_structured_shop)]:
        try:
            items=fn(shop)
            if items: return {'shop':shop,'products':items,'adapter':label,'status':'ok','errors':errors}
            errors.append(label+': no matching sealed products')
        except Exception as exc: errors.append(label+': '+type(exc).__name__+': '+str(exc)[:130])
    return {'shop':shop,'products':[],'adapter':None,'status':'no_results_or_blocked','errors':errors}

def verify_store(source):
    """Only explicitly configured, machine-readable, physical-store evidence qualifies."""
    result={'status':'Unknown','checked_at':stamp(),'source_url':source.get('source_url','')}
    required=('store_id','store_name','lat','lon','game','product_name','source_url','evidence_url')
    missing=[x for x in required if source.get(x) in ('',None)]
    if missing: return dict(result,reason='Missing '+','.join(missing))
    try:
        lat=float(source['lat']); lon=float(source['lon'])
        if abs(lat)>90 or abs(lon)>180: raise ValueError('Invalid coordinates')
        if not safe_url(source['source_url']) or not safe_url(source['evidence_url']): raise ValueError('Invalid HTTPS evidence URL')
        data=get(source['evidence_url'],json_mode=True)
        if not isinstance(data,dict): raise ValueError('Evidence must be a JSON object')
        if str(data.get('store_id',''))!=str(source['store_id']): raise ValueError('Store ID mismatch')
        if norm(data.get('product_name'))!=norm(source['product_name']): raise ValueError('Product mismatch')
        if data.get('inventory_scope')!='physical_store': raise ValueError('No explicit physical-store scope')
        status=str(data.get('availability','')).split('/')[-1]
        if status not in ('InStock','OutOfStock','PreOrder','BackOrder'): raise ValueError('Unrecognized availability')
        result['status']={'InStock':'In stock','OutOfStock':'Out of stock','PreOrder':'Preorder','BackOrder':'Backorder'}[status]
        if status=='InStock':
            result.update({'store_id':str(source['store_id']),'store_name':str(source['store_name']),'product_name':str(source['product_name']),'game':str(source['game']),'lat':lat,'lon':lon,'verified_at':stamp(),'source_url':source['source_url'],'evidence_url':source['evidence_url']})
    except Exception as exc: result.update({'reason':type(exc).__name__+': '+str(exc)[:200],'check_failed':True})
    return result

def recent(record):
    if not isinstance(record,dict) or record.get('status')!='In stock': return False
    try:
        dt=datetime.fromisoformat(record['verified_at'].replace('Z','+00:00'))
        return dt.tzinfo is not None and 0<=(NOW-dt).total_seconds()<=TTL_SECONDS
    except (KeyError,TypeError,ValueError): return False

def main():
    db=load_json(DB,{'products':[],'releases':[]})
    if not isinstance(db,dict) or not isinstance(db.get('products'),list) or not isinstance(db.get('releases'),list):
        raise ValueError('Existing database invalid; refusing to overwrite')
    original_products=db['products']; original_releases=db['releases']
    releases=record('Pokemon Press',official_pokemon)
    union=record('Union Arena',official_union)
    db['releases'],_=merge(original_releases,releases)
    products,added=merge(original_products,union)
    try:
        shops=shops_config()
        HEALTH['Independent shop configuration']={'status':'ok' if shops else 'not_configured','shops':len(shops),'checked_at':stamp()}
    except Exception as exc:
        shops=[]; ERRORS.append('Independent shop configuration: '+str(exc))
        HEALTH['Independent shop configuration']={'status':'error','error':str(exc),'checked_at':stamp()}
    cursor=int(db.get('v72_shop_cursor',0) or 0)
    selected=[shops[(cursor+i)%len(shops)] for i in range(min(MAX_SHOPS,len(shops)))] if shops else []
    db['v72_shop_cursor']=(cursor+len(selected))%len(shops) if shops else 0
    checks=[]; discovered=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(scan_shop,selected):
            checks.append({'shop':result['shop']['name'],'url':result['shop']['url'],'status':result['status'],'adapter':result['adapter'],'products_found':len(result['products']),'errors':result['errors'],'checked_at':stamp()})
            discovered.extend(result['products'])
    products,shop_added=merge(products,discovered)
    HEALTH['Independent shop catalogues']={'status':'ok' if discovered else 'no_results' if shops else 'not_configured','shops_checked':len(selected),'products_found':len(discovered),'shops_with_products':sum(x['products_found']>0 for x in checks),'checked_at':stamp()}
    for p in products: p['stock_status']='Not checked'
    try:
        sources=load_json(STORE_SOURCES,[])
        if not isinstance(sources,list): raise ValueError('Store sources must be a JSON array')
        HEALTH['Physical store evidence']={'status':'configured' if sources else 'not_configured','sources':len(sources),'checked_at':stamp()}
    except Exception as exc:
        sources=[]; ERRORS.append('Physical store evidence: '+str(exc))
        HEALTH['Physical store evidence']={'status':'error','error':str(exc),'checked_at':stamp()}
    scursor=int(db.get('v72_store_cursor',0) or 0)
    chosen=[sources[(scursor+i)%len(sources)] for i in range(min(MAX_STORE_SOURCES,len(sources)))] if sources else []
    db['v72_store_cursor']=(scursor+len(chosen))%len(sources) if sources else 0
    with ThreadPoolExecutor(max_workers=3) as pool: store_checks=list(pool.map(verify_store,chosen))
    inventory={}
    for item in db.get('store_inventory',[]):
        if recent(item): inventory[(str(item.get('store_id')),norm(item.get('product_name')))]=item
    # A failed check must not refresh or extend an older positive result.
    for item in store_checks:
        if 'store_id' not in item: continue
        key=(str(item['store_id']),norm(item['product_name']))
        if recent(item): inventory[key]=item
        else: inventory.pop(key,None)
    db.update({'products':products,'store_inventory':list(inventory.values()),'monitor_version':VERSION,'last_updated':stamp(),'catalogue_source_status':HEALTH,'monitor_errors':ERRORS,'v72_shop_checks':checks,'v72_store_checks':store_checks,'retailer_stock_checks':'configured' if sources else 'not_connected'})
    db['discovery_summary']={'new_products_this_run':added+shop_added,'total_products':len(products),'pokemon_products':sum(p.get('game')=='Pokémon' for p in products),'union_arena_products':sum(p.get('game')=='Union Arena' for p in products),'products_with_images':sum(bool(p.get('image')) for p in products),'independent_shops_configured':len(shops),'independent_shops_checked':len(selected),'independent_shop_products_discovered_this_run':len(discovered),'physical_store_sources_configured':len(sources),'store_checks_this_run':len(store_checks),'verified_in_stock_locations':len(inventory),'source_errors':len(ERRORS),'updated_at':stamp()}
    DB.parent.mkdir(parents=True,exist_ok=True)
    tmp=DB.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(DB)
    print(json.dumps(db['discovery_summary'],indent=2))
    for check in checks:
        if check['status']!='ok': print('Shop not verified:',check['shop'],check['errors'][:2])
    for err in ERRORS: print('SOURCE ERROR:',err)

if __name__=='__main__': main()
