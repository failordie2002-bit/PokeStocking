#!/usr/bin/env python3
"""PokéStock 47: broader public-source coverage, not live inventory."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections import Counter
from zoneinfo import ZoneInfo
import hashlib, html, json, os, re, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

DATA=Path('data'); DATA.mkdir(exist_ok=True)
NOW=datetime.now(timezone.utc)
CUTOFF=NOW-timedelta(days=45)

GAMES={
 'Pokémon':r'pok[eé]mon|pokemon|prismatic evolutions|delta reign',
 'Union Arena':r'union arena',
 'One Piece':r'one piece(?: tcg| card| booster)?|\bop-\d{2}\b',
 'Magic: The Gathering':r'magic[: ]+the gathering|\bmtg\b',
 'Disney Lorcana':r'lorcana',
 'Yu-Gi-Oh!':r'yu[- ]?gi[- ]?oh',
 'Gundam':r'gundam (?:tcg|card)',
 'Digimon':r'digimon (?:tcg|card|booster)',
 'Dragon Ball Super':r'dragon ball (?:super|tcg|card)',
 'Riftbound':r'riftbound',
 'Weiß Schwarz':r'wei(?:ss|ß) schwarz',
 'Flesh and Blood':r'flesh and blood',
 'Star Wars Unlimited':r'star wars unlimited',
 'Final Fantasy TCG':r'final fantasy (?:tcg|card|booster)',
 'Cardfight!! Vanguard':r'cardfight|vanguard (?:tcg|card|booster)',
 'Grand Archive':r'grand archive',
 'Altered':r'altered (?:tcg|card game)',
 'Shadowverse Evolve':r'shadowverse evolve',
 'Battle Spirits Saga':r'battle spirits saga',
 'Naruto':r'naruto (?:tcg|booster|card game)',
}
RETAILERS={
 'Walmart':r'\bwalmart\b','Target':r'\btarget\b','Best Buy':r'\bbest buy\b',
 'GameStop':r'\bgame\s*stop\b','Costco':r'\bcostco\b',
 "Sam's Club":r"\bsam['’]?s club\b", "Lowe's":r"\blowe['’]?s\b",
 'Barnes & Noble':r'\bbarnes (?:&|and) noble\b','Five Below':r'\bfive below\b',
 'Walgreens':r'\bwalgreens\b','CVS':r'\bcvs\b','Amazon':r'\bamazon\b',
 'Pokémon Center':r'pok[eé]mon center', 'Dollar General':r'dollar general',
 'Meijer':r'\bmeijer\b','Kroger':r'\bkroger\b',
}
CITIES=[('Staunton, VA',r'\bstaunton\b'),('Waynesboro, VA',r'\bwaynesboro\b'),
 ('Harrisonburg, VA',r'\bharrisonburg\b'),('Charlottesville, VA',r'\bcharlottesville\b'),
 ('Richmond, VA',r'\brichmond\b.*\b(?:va|virginia)\b'),
 ('Northern Virginia',r'\bnorthern virginia\b|\bnova\b')]

LOCAL_QUERIES=[
 'Pokemon cards restock Staunton VA','Pokemon cards restock Waynesboro VA',
 'TCG booster restock Harrisonburg Virginia','Pokemon TCG restock Charlottesville Virginia',
 'Walmart Pokemon cards Thursday Staunton restock',
 'Target Pokémon sealed cards Harrisonburg Virginia restock',
 'Union Arena trading cards Charlottesville Virginia',
 'trading card restock Richmond Virginia stores',
 'TCG stocking days Northern Virginia retailers',
 'Pokemon cards Shenandoah Valley store shipment',
 "Sam's Club trading cards Virginia restock",
 'Costco trading cards Virginia restock',
]
STORE_QUERIES=[
 'Walmart trading card booster restock','Target TCG restock new drop',
 'Best Buy trading cards available restock','GameStop trading cards booster restock',
 'Costco Pokemon trading cards allocations','Sams Club Pokemon trading card restock',
 'Lowes Pokemon cards display stocked','Barnes and Noble trading cards restock',
 'Five Below TCG booster cards restock','Walgreens trading card restock',
 'CVS Pokemon packs restock','small independent TCG stores sealed booster restock',
]
GAME_QUERIES=[
 'Pokemon TCG booster restock release','Union Arena booster box restock',
 'One Piece TCG restock booster','Magic the Gathering sealed booster restock',
 'Lorcana booster restock stores','Yu Gi Oh trading card booster restock',
 'Gundam card game booster restock','Digimon TCG sealed booster restock',
 'Dragon Ball Super card game booster restock','Riftbound TCG booster restock',
 'Weiss Schwarz sealed box restock','Flesh and Blood booster restock',
 'Star Wars Unlimited TCG booster restock', 'Final Fantasy TCG booster restock',
 'Cardfight Vanguard booster restock','Grand Archive TCG new stock',
 'Altered trading card booster restock', 'Shadowverse Evolve TCG restock',
 'Battle Spirits Saga booster restock','Naruto trading card game booster restock',
 'new trading card game booster retail availability',
 'TCG specialty shop restock announcements',
 f'trading card games new release {NOW:%B %Y}',
 f'sealed TCG booster store allocation {NOW:%B %Y}',
]
STOCK_WORDS=re.compile(r'restock|stock(?:ed|ing)?\b|back in stock|shipment|allocation|release|drop(?:ped)?\b|arriv(?:ed|ing|al)|found at|spotted|available',re.I)
SEALED_WORDS=re.compile(r'booster|trading cards?|\btcg\b|card game|elite trainer|\betb\b|sealed|bundle|collection box|premium collection|display box|starter deck|tin(?:s)?\b|blister',re.I)
BAD_WORDS=re.compile(r'\bgraded\b|\bpsa\s*\d|\bsingles?\b|\bplaymat\b|\bbinder\b|\bsleeves?\b|\bproxy\b|\bdigital code\b',re.I)
TAG=re.compile(r'<[^>]+>')

def clean(s):return re.sub(r'\s+',' ',TAG.sub(' ',html.unescape(s or ''))).strip()
def dt(s):
 if not s:return None
 try:d=parsedate_to_datetime(s)
 except (ValueError,TypeError):
  try:d=datetime.fromisoformat(s.replace('Z','+00:00'))
  except (ValueError,TypeError):return None
 if not d.tzinfo:d=d.replace(tzinfo=timezone.utc)
 return d.astimezone(timezone.utc)

def articles(root):
 atom='{http://www.w3.org/2005/Atom}'
 for item in (root.findall('.//item')+root.findall(atom+'entry'))[:80]:
  title=clean(item.findtext('title') or item.findtext(atom+'title'))
  summary=clean(item.findtext('description') or item.findtext(atom+'summary') or item.findtext(atom+'content'))
  link=item.findtext('link') or ''
  if not link:
   for node in item.findall(atom+'link'):
    if node.get('rel','alternate')=='alternate' and node.get('href','').startswith('https://'):
     link=node.get('href','');break
  pub=item.findtext('pubDate') or item.findtext(atom+'published') or item.findtext(atom+'updated')
  yield title,summary,link,pub

def classify(title,summary,link,published,source):
 title=title[:280];summary=summary[:700];body=title+' '+summary
 timestamp=dt(published)
 if not timestamp or not CUTOFF<=timestamp<=NOW+timedelta(hours=2):return None
 if not link.startswith('https://'):return None
 if not STOCK_WORDS.search(body) or not SEALED_WORDS.search(body) or BAD_WORDS.search(title):return None
 game=next((name for name,exp in GAMES.items() if re.search(exp,body,re.I)),None)
 if not game and not re.search(r'trading cards?|\btcg\b|card game',body,re.I):return None
 retailer=next((name for name,exp in RETAILERS.items() if re.search(exp,body,re.I)),'Unspecified')
 locality=next((name for name,exp in CITIES if re.search(exp,body,re.I)),None)
 if not locality:locality='Virginia (unspecified)' if re.search(r'\bvirginia\b',body,re.I) else 'Location unspecified'
 # URL is a source link, not a product's order link or proof of shelf stock.
 key=hashlib.sha256((link.split('?')[0]+'|'+title.lower()).encode()).hexdigest()[:20]
 category=('LOCAL PUBLIC MENTION' if locality not in ('Location unspecified','Virginia (unspecified)')
     else 'PUBLIC MENTION')
 return {'id':key,'title':title,'summary':summary[:250],'game':game or 'Other / emerging TCG',
  'retailer':retailer,'location':locality,'published_utc':timestamp.isoformat(),
  'source':source,'url':link,'status':'UNVERIFIED '+category,
  'source_scope':'public RSS, no inventory access','confidence':'LOW',
  'note':'Publication time is not a restock timestamp.'}

def read_old(path):
 try:
  obj=json.loads(path.read_text(encoding='utf-8'))
  return [x for x in obj.get('signals',[]) if isinstance(x,dict) and dt(x.get('published_utc'))
   and CUTOFF<=dt(x['published_utc'])<=NOW+timedelta(hours=2)]
 except (OSError,TypeError,ValueError,KeyError):return []

def save(path,obj):
 path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

# Eight rotating targeted news queries per run, including two local.
slot=(NOW.hour//4)%6
queries=[LOCAL_QUERIES[slot*2+i] for i in range(2)]
queries += [STORE_QUERIES[slot*2+i] for i in range(2)]
queries += [GAME_QUERIES[slot*4+i] for i in range(4)]
feeds=[]
for q in queries:
 url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q+' when:30d','hl':'en-US','gl':'US','ceid':'US:en'})
 feeds.append(('Google News: '+q,url))
feeds.append(('Reddit PKMNTCGDeals','https://www.reddit.com/r/PKMNTCGDeals/new/.rss'))
# Public Reddit searches can be rate limited or disabled; log failure honestly.
reddit_q='pokemon restock virginia' if slot%2==0 else 'tcg booster restock'
feeds.append(('Reddit public search','https://www.reddit.com/search.rss?'+urllib.parse.urlencode({'q':reddit_q,'sort':'new','t':'month'})))

records={x['id']:x for x in read_old(DATA/'public_signal_archive_47.json') if x.get('id')}
errors=[];completed=0;seen=0
for source,url in feeds:
 if os.environ.get('PS47_OFFLINE')=='1':break
 try:
  req=urllib.request.Request(url,headers={
   'User-Agent':'PokeStock-Public-RSS/47 (no login; no CAPTCHA bypass)',
   'Accept':'application/rss+xml,application/atom+xml,application/xml;q=0.9'})
  with urllib.request.urlopen(req,timeout=7) as response:
   root=ET.fromstring(response.read(900_000))
  completed+=1
  for row in articles(root):
   record=classify(*row,source)
   if record:
    seen+=1;records[record['id']]=record
 except Exception as exc:
  errors.append({'source':source,'error':type(exc).__name__})

output=sorted(records.values(),key=lambda x:x['published_utc'],reverse=True)[:350]
save(DATA/'public_signal_archive_47.json',{'generated_utc':NOW.isoformat(),
 'coverage':'Sampled public RSS feeds, not full internet or real-time inventory',
 'availability':'NOT VERIFIED','signals':output})
save(DATA/'rumor_report_47.json',{'generated_utc':NOW.isoformat(),
 'feeds_attempted':0 if os.environ.get('PS47_OFFLINE')=='1' else len(feeds),
 'feeds_succeeded':completed,'feed_errors':errors,
 'mentions_this_run':seen,'unique_mentions_retained':len(output),
 'games_observed':dict(Counter(x['game'] for x in output)),
 'retailers_observed':dict(Counter(x['retailer'] for x in output)),
 'local_explicit_mentions':sum(x['location'] not in ('Location unspecified','Virginia (unspecified)') for x in output),
 'status':'Research complete; public mentions only'})
assert all(x['status'].startswith('UNVERIFIED') for x in output)
print('SCRIPT 47 GREEN:',completed,'feeds;',len(output),'unverified public mentions')
