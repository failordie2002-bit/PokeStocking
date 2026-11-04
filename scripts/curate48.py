#!/usr/bin/env python3
"""PokéStock 48: conservative quality gate for existing public reports.

No source is elevated to verified inventory by this classifier.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import json, re, hashlib

DATA = Path('data'); DATA.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)
GAME = {
 'Pokémon': r'pok[eé]mon|pokemon', 'Union Arena': r'union arena',
 'One Piece': r'one piece (?:tcg|card|booster)|\bop[- ]?\d{2}\b',
 'Magic: The Gathering': r'magic[: ]+the gathering|\bmtg\b',
 'Disney Lorcana': r'lorcana', 'Yu-Gi-Oh!': r'yu[- ]?gi[- ]?oh',
 'Gundam': r'gundam (?:tcg|card)', 'Digimon': r'digimon (?:tcg|card)',
 'Dragon Ball Super': r'dragon ball (?:super|tcg|card)', 'Riftbound': r'riftbound',
 'Weiß Schwarz': r'wei(?:ss|ß) schwarz', 'Flesh and Blood': r'flesh and blood',
 'Star Wars Unlimited': r'star wars unlimited', 'Final Fantasy TCG': r'final fantasy (?:tcg|card|booster)',
 'Cardfight!! Vanguard': r'cardfight|vanguard (?:tcg|card)',
 'Grand Archive': r'grand archive', 'Altered': r'altered (?:tcg|card game)',
 'Shadowverse Evolve': r'shadowverse evolve', 'Battle Spirits Saga': r'battle spirits saga',
 'Naruto': r'naruto (?:tcg|booster|card game)'
}
STORES = {
 'Walmart':r'\bwalmart\b','Target':r'\btarget\b','Best Buy':r'\bbest buy\b',
 'GameStop':r'\bgame\s*stop\b','Costco':r'\bcostco\b',
 "Sam's Club":r"\bsam['’]?s club\b", "Lowe's":r"\blowe['’]?s\b",
 'Barnes & Noble':r'\bbarnes (?:&|and) noble\b','Five Below':r'\bfive below\b',
 'Amazon':r'\bamazon\b','Pokémon Center':r'pok[eé]mon center',
 'Walgreens':r'\bwalgreens\b','CVS':r'\bcvs\b','Dollar General':r'\bdollar general\b',
 'Meijer':r'\bmeijer\b','Kroger':r'\bkroger\b',
}
CITIES = ['Staunton','Waynesboro','Harrisonburg','Charlottesville','Richmond','Roanoke',
          'Fredericksburg','Alexandria','Fairfax','Winchester','Lynchburg']
PRODUCT = re.compile(r'booster|elite trainer|\betb\b|tin\b|blister|bundle|starter deck|sealed|collection box|premium collection|display box',re.I)
STOCK = re.compile(r'restock(?:ed|ing)?|back in stock|stock alert|in stock|shipment|shelf|picked up|found (?:at|in)|spotted|drop(?:ped)?',re.I)
SIGHTING = re.compile(r'\bfound\b|spotted|picked up|on (?:the )?shelf|my (?:local )?store|in store',re.I)
RELEASE = re.compile(r'release|pre.?order|launch|calendar|where to buy|new products?|lineup|available now|debut',re.I)
IRRELEVANT = re.compile(r'skateboard|santa cruz|\besco\b|\blisa\b|sports and entertainment|\bgraded\b|\bsingle card\b|\bplaymat\b|\bbinder\b|\bsleeves?\b',re.I)

def read(path, key):
 try:
  o=json.loads(Path(path).read_text(encoding='utf-8'))
  return o.get(key,[]) if isinstance(o.get(key,[]),list) else []
 except (OSError, ValueError, TypeError): return []

def timestamp(value):
 try:
  d=datetime.fromisoformat(value.replace('Z','+00:00'))
  return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
 except (ValueError, TypeError, AttributeError):return None

def curate(original):
 if not isinstance(original,dict): return None
 title=str(original.get('title') or '').strip()[:300]
 details=str(original.get('summary') or '').strip()[:400]
 url=str(original.get('url') or '')
 when=timestamp(original.get('published_utc'))
 if not when or when < NOW-timedelta(days=45) or when>NOW+timedelta(hours=2): return None
 if urlsplit(url).scheme!='https' or not urlsplit(url).netloc: return None
 if IRRELEVANT.search(title):return None
 combined=title+' '+details
 game=next((g for g,p in GAME.items() if re.search(p,combined,re.I)),None)
 if not game:
  # Generic trading cards may describe non-TCG celebrity merchandise.
  if not (re.search(r'\bTCG\b|trading card game',combined,re.I) and PRODUCT.search(combined)):return None
  game='Other / emerging TCG'
 source=str(original.get('source') or '')
 retailer=next((s for s,p in STORES.items() if re.search(p,combined,re.I)),None)
 oldstore=str(original.get('retailer') or '')
 if not retailer and oldstore not in ('Unspecified','Unspecified retailer',''):
  retailer=oldstore
 city=next((c+', VA' for c in CITIES if re.search(r'\b'+c+r'\b',combined,re.I)),None)
 oldcity=str(original.get('location') or '')
 if not city and oldcity not in ('Location unspecified','Virginia (unspecified)',''):
  city=oldcity
 age_days=max(0,(NOW-when).total_seconds()/86400)
 fresh=age_days<=7
 has_stock=bool(STOCK.search(title))
 reddit=('reddit' in source.lower() or 'reddit.com' in urlsplit(url).netloc)
 local_claim=bool(city and retailer and reddit and SIGHTING.search(combined))
 if local_claim: kind='Reported local sighting'
 elif retailer and has_stock: kind='Retailer stock mention'
 elif RELEASE.search(title): kind='Release / shopping news'
 else: kind='General TCG mention'
 # This score prioritizes leads; it is NOT inventory probability.
 score=10 + (25 if retailer else 0)+(20 if has_stock else 0)+(18 if city else 0)
 score+=(15 if age_days<=3 else 9 if fresh else 0)
 score+= (12 if local_claim else 0)
 score+= (7 if PRODUCT.search(title) else 0)
 if age_days>14:score-=12
 if kind=='Release / shopping news':score=min(score,40)
 score=max(0,min(95,score))
 uid=str(original.get('id') or hashlib.sha256((url+title).encode()).hexdigest()[:20])
 return {'id':uid,'title':title,'summary':details[:250], 'game':game,
  'retailer':retailer or 'Unspecified','location':city or 'Location unspecified',
  'published_utc':when.isoformat(), 'source':source,'url':url,
  'status':'UNVERIFIED PUBLIC MENTION','kind':kind,'fresh':fresh,
  'lead_strength':score,'age_days':round(age_days,1),
  'evidence_note':'Public post/article; not independently verified inventory.'}

def main():
 raw=[]
 for path in ['data/rumor_signals_46.json','data/public_signal_archive_47.json']:
  raw.extend(read(path,'signals'))
 # Preserve recent observations if an upstream file disappears.
 raw.extend(read('data/restock_intelligence_48.json','signals'))
 ranked={}
 for item in raw:
  x=curate(item)
  if x and (x['id'] not in ranked or x['lead_strength']>ranked[x['id']]['lead_strength']):
   ranked[x['id']]=x
 reports=sorted(ranked.values(),key=lambda x:(x['fresh'],x['lead_strength'],x['published_utc']),reverse=True)[:250]
 tips=read('data/rumor_forecast_46.json','leads')
 tips=[{'retailer':str(x.get('retailer','')),'game':str(x.get('game','')),
        'location':str(x.get('location','')),'window':str(x.get('window','')),
        'reason':str(x.get('reason') or x.get('based_on') or ''),
        'confidence':'LOW','status':'UNVERIFIED RUMOR'}
       for x in tips if isinstance(x,dict)][:25]
 result={'generated_utc':NOW.isoformat(), 'disclaimer':'All source reports and forecasts are unverified. No shelf inventory is confirmed.',
   'signals':reports,'forecasts':tips,
   'summary':{'raw_candidates':len(raw),'kept':len(reports),'fresh_reports':sum(r['fresh'] for r in reports),
      'fresh_named_retailer':sum(r['fresh'] and r['retailer']!='Unspecified' for r in reports),
      'local_explicit_reports':sum(r['location']!='Location unspecified' for r in reports),
      'local_firsthand_claims':sum(r['kind']=='Reported local sighting' for r in reports)}}
 (DATA/'restock_intelligence_48.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
 assert all(r['status'].startswith('UNVERIFIED') for r in reports)
 print('SCRIPT 48 GREEN',json.dumps(result['summary']))

if __name__=='__main__':main()
