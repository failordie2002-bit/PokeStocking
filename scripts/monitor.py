
#!/usr/bin/env python3
"""PokéStock V8.0. Evidence-first nationwide catalogue and store pipeline."""
import json, re, hashlib, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
NOW=datetime.now(timezone.utc)
STAMP=NOW.isoformat()
UA={'User-Agent':'PokeStock/8.0 (public product catalogue monitor)'}
GAMES=['Pokémon','Union Arena','Gundam','One Piece']
SOURCES={
 'Pokémon':'https://press.pokemon.com/en/Items/Schedule?period=All&types=3&sortAsc=False&sortBy=Date',
 'Union Arena':'https://www.unionarena-tcg.com/na/products/',
 'Gundam':'https://www.gundam-gcg.com/en/products/',
 'One Piece':'https://en.onepiece-cardgame.com/products/'
}
errors=[]; health={}
def load(name,default):
 p=DATA/name
 if not p.exists(): return default
 return json.loads(p.read_text(encoding='utf-8'))
def save(name,obj):
 p=DATA/name;p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def https(u):
 try:
  p=urlparse(str(u));return p.scheme=='https' and bool(p.hostname) and not p.username and not p.password
 except ValueError:return False
def fetch(url):
 if not https(url):raise ValueError('HTTPS required')
 r=requests.get(url,headers=UA,timeout=18,allow_redirects=True)
 r.raise_for_status()
 if not https(r.url) or len(r.content)>4_000_000:raise ValueError('Invalid response')
 return r
def norm(x):return re.sub(r'[^a-z0-9]+',' ',str(x or '').lower().replace('é','e')).strip()
def key(p):return (norm(p.get('game')),p.get('url') or p.get('sku') or norm(p.get('name')))
def merge(existing,new):
 out={key(x):dict(x) for x in existing if isinstance(x,dict)}
 for p in new:
  k=key(p)
  if k in out:
   for field,val in p.items():
    if val not in ('',None,[]):out[k][field]=val
  else:out[k]=dict(p,first_seen=STAMP)
 return list(out.values())
def status(name,fn):
 try:
  result=fn();health[name]={'status':'ok' if result else 'no_results','count':len(result),'checked_at':STAMP};return result
 except Exception as e:
  msg=f'{type(e).__name__}: {str(e)[:180]}'
  errors.append(name+': '+msg);health[name]={'status':'error','error':msg,'checked_at':STAMP};return []
def official(game,url):
 soup=BeautifulSoup(fetch(url).text,'html.parser');results=[];seen=set()
 for a in soup.select('a[href]'):
  link=urljoin(url,a['href']);name=a.get_text(' ',strip=True)
  if not https(link) or urlparse(link).hostname!=urlparse(url).hostname or link in seen:continue
  path=urlparse(link).path.lower()
  if game=='Pokémon':
   if '/products/' not in path or not re.search(r'pok[eé]mon\s+tcg\s*:',name,re.I):continue
  elif game=='Union Arena':
   if not ('/products/boosters/' in path or '/products/decks/' in path):continue
  else:
   if '/products/' not in path or len(name)<8 or len(name)>140:continue
   if not any(w in norm(name) for w in ('booster','starter','deck','pack','set','collection')):continue
  seen.add(link)
  img=a.find('img')
  image=urljoin(url,img.get('src','')) if img else ''
  results.append({'name':name,'game':game,'type':'Official catalogue listing','url':link,'image':image if https(image) else '', 'stock_status':'Not checked','source':'Official catalogue'})
 if not results:raise ValueError('No product links parsed; source structure may have changed')
 return results[:300]
def shops():
 data=load('shops.json',[])
 if not isinstance(data,list):raise ValueError('shops.json must be a list')
 out=[];seen=set()
 for s in data:
  if not isinstance(s,dict) or not https(s.get('url')):continue
  u=s['url'].rstrip('/');sid=str(s.get('id') or hashlib.sha256(u.encode()).hexdigest()[:16])
  if sid in seen:continue
  seen.add(sid)
  out.append({'id':sid,'name':s.get('name') or urlparse(u).hostname,'url':u,'city':s.get('city',''),'state':s.get('state',''),'lat':s.get('lat'),'lon':s.get('lon'),'country':s.get('country','US')})
 return out
def sealed(name):
 n=norm(name)
 return any(x in n for x in ('pokemon','union arena','gundam','one piece')) and any(x in n for x in ('booster','deck','bundle','tin','collection','display','trainer box','starter')) and not any(x in n for x in ('single card','sleeves','binder','playmat','graded'))
def shop_products(shop):
 base=shop['url'];found=[];attempts=[]
 for adapter,path in [('shopify','/products.json?limit=100'),('woocommerce','/wp-json/wc/store/v1/products?per_page=100')]:
  try:
   r=fetch(base+path)
   if urlparse(r.url).hostname!=urlparse(base).hostname:raise ValueError('Redirected off shop domain')
   payload=r.json();items=payload.get('products',[]) if adapter=='shopify' and isinstance(payload,dict) else payload if isinstance(payload,list) else []
   if not isinstance(items,list):raise ValueError('Invalid product list')
   for item in items[:100]:
    title=BeautifulSoup(str(item.get('title') or item.get('name') or ''),'html.parser').get_text(' ',strip=True)
    if not sealed(title):continue
    link=(base+'/products/'+str(item.get('handle',''))) if adapter=='shopify' else item.get('permalink','')
    if not https(link) or urlparse(link).hostname!=urlparse(base).hostname:continue
    n=norm(title)
    game=next((g for g in GAMES if norm(g) in n),'')
    if not game:continue
    variants=item.get('variants') or []
    available=any(v.get('available') is True for v in variants if isinstance(v,dict)) if adapter=='shopify' else item.get('is_in_stock') is True
    # Online availability is NOT store shelf availability.
    found.append({'name':title,'game':game,'type':'Sealed product','url':link,'retailer':shop['name'],'shop_id':shop['id'],'online_stock_status':'In stock' if available else 'Unknown','stock_status':'Not checked','source':adapter})
   attempts.append({'adapter':adapter,'status':'ok','items':len(items)})
   if found:break
  except Exception as e:attempts.append({'adapter':adapter,'status':'error','reason':str(e)[:120]})
 return found,attempts
def evidence_rows():
 sources=load('retailer_sources.json',[])
 if not isinstance(sources,list):raise ValueError('retailer_sources.json must be a list')
 rows=[];checks=[]
 for s in sources[:40]:
  try:
   required=('store_id','store_name','product_name','game','lat','lon','source_url','evidence_url')
   if not isinstance(s,dict) or any(s.get(x) in (None,'') for x in required):raise ValueError('Missing required source fields')
   if not https(s['source_url']) or not https(s['evidence_url']):raise ValueError('Invalid evidence URL')
   r=fetch(s['evidence_url'])
   if urlparse(r.url).hostname!=urlparse(s['evidence_url']).hostname:raise ValueError('Redirected evidence')
   d=r.json()
   if not isinstance(d,dict) or str(d.get('store_id'))!=str(s['store_id']) or norm(d.get('product_name'))!=norm(s['product_name']) or d.get('inventory_scope')!='physical_store':raise ValueError('Store-specific evidence mismatch')
   if d.get('availability')!='InStock':checks.append({'store_id':s['store_id'],'product_name':s['product_name'],'status':'not_in_stock','checked_at':STAMP});continue
   lat,lon=float(s['lat']),float(s['lon'])
   if not -90<=lat<=90 or not -180<=lon<=180:raise ValueError('Invalid coordinates')
   rows.append({'store_id':str(s['store_id']),'store_name':s['store_name'],'product_name':s['product_name'],'game':s['game'],'lat':lat,'lon':lon,'status':'In stock','verified_at':STAMP,'source_url':s['source_url'],'evidence_url':s['evidence_url']})
   checks.append({'store_id':s['store_id'],'status':'verified_in_stock','checked_at':STAMP})
  except Exception as e:checks.append({'store_id':s.get('store_id') if isinstance(s,dict) else '', 'status':'error','reason':str(e)[:150],'checked_at':STAMP})
 return rows,checks,len(sources)
def main():
 db=load('status.json',{'products':[],'releases':[]})
 if not isinstance(db,dict) or not isinstance(db.get('products'),list) or not isinstance(db.get('releases'),list):raise ValueError('Invalid existing status.json; refusing overwrite')
 old=len(db['products']);discovered=[]
 for g,url in SOURCES.items():discovered+=status('Official '+g,lambda g=g,url=url:official(g,url))
 # Keep all existing products/releases even if upstream sites fail.
 db['products']=merge(db['products'],discovered)
 try:directory=shops();health['Shop directory']={'status':'ok' if directory else 'not_configured','count':len(directory),'checked_at':STAMP}
 except Exception as e:directory=[];errors.append('Shop directory: '+str(e))
 cursor=int(db.get('v8_shop_cursor',0));chosen=[directory[(cursor+i)%len(directory)] for i in range(min(10,len(directory)))] if directory else []
 db['v8_shop_cursor']=(cursor+len(chosen))%len(directory) if directory else 0
 reports=[];offers=[]
 for s in chosen:
  products,attempts=shop_products(s);offers.extend(products)
  reports.append({'store_id':s['id'],'name':s['name'],'found':len(products),'adapters':attempts,'checked_at':STAMP})
 db['products']=merge(db['products'],offers)
 # Preserve independently curated store records, but never invent locations.
 previous=load('stores.json',[])
 if not isinstance(previous,list):previous=[]
 by_id={str(s['id']):s for s in previous if isinstance(s,dict) and s.get('id')}
 for s in directory:by_id[s['id']]={**by_id.get(s['id'],{}),**s}
 save('stores.json',list(by_id.values()))
 try:confirmed,checks,configured=evidence_rows()
 except Exception as e:confirmed=[];checks=[];configured=0;errors.append('Physical-store evidence: '+str(e))
 # Preserve only previously verified records younger than six hours.
 for item in db.get('store_inventory',[]):
  try:
   t=datetime.fromisoformat(item['verified_at'].replace('Z','+00:00'))
   if item.get('status')=='In stock' and timedelta(0)<=NOW-t<=timedelta(hours=6):
    if not any(str(x.get('store_id'))==str(item.get('store_id')) and norm(x.get('product_name'))==norm(item.get('product_name')) for x in confirmed):confirmed.append(item)
  except (KeyError,ValueError,TypeError):pass
 # Remove stale positives when an explicit negative observation is received.
 negative={(str(x.get('store_id')),norm(x.get('product_name'))) for x in checks if x.get('status')=='not_in_stock'}
 confirmed=[x for x in confirmed if (str(x.get('store_id')),norm(x.get('product_name'))) not in negative]
 # Shipment Catcher is schema-ready; no inferred delivery events.
 shipment=load('shipments.json',{'events':[],'forecasts':[]})
 if not isinstance(shipment,dict):shipment={'events':[],'forecasts':[]}
 shipment.setdefault('events',[]);shipment.setdefault('forecasts',[])
 save('shipments.json',shipment)
 db.update({'monitor_version':'8.0','last_updated':STAMP,'store_inventory':confirmed,'catalogue_source_status':health,'monitor_errors':errors,'v8_shop_checks':reports,'v8_store_checks':checks,'v8_store_count':len(by_id),'v8_shipment_schema':'data/shipments.json'})
 db['discovery_summary']={'previous_products':old,'total_products':len(db['products']),'stores':len(by_id),'shop_checks':len(reports),'store_sources':configured,'verified_in_stock_locations':len(confirmed),'source_errors':len(errors),'updated_at':STAMP}
 save('status.json',db)
 print(json.dumps(db['discovery_summary'],indent=2))
 for e in errors:print('SOURCE ERROR:',e)
if __name__=='__main__':main()
