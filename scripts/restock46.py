from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo
import hashlib, html, json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET

BASE=Path('data'); BASE.mkdir(exist_ok=True)
NOW=datetime.now(timezone.utc)
GAMES={
'Pokémon':r'pok[eé]mon|pokemon', 'Union Arena':r'union arena',
'One Piece':r'one piece', 'Magic: The Gathering':r'magic[: ]+the gathering|\bmtg\b',
'Disney Lorcana':r'lorcana', 'Yu-Gi-Oh!':r'yu[- ]?gi[- ]?oh',
'Gundam':r'gundam', 'Digimon':r'digimon', 'Dragon Ball Super':r'dragon ball',
'Riftbound':r'riftbound', 'Weiß Schwarz':r'wei(?:ss|ß) schwarz',
'Flesh and Blood':r'flesh and blood', 'Star Wars Unlimited':r'star wars unlimited',
'Final Fantasy TCG':r'final fantasy', 'Cardfight!! Vanguard':r'cardfight|vanguard',
'Grand Archive':r'grand archive', 'Altered':r'altered tcg',
'Shadowverse Evolve':r'shadowverse evolve', 'Battle Spirits Saga':r'battle spirits',
'Naruto':r'naruto',
}
STORES={
'Walmart':r'\bwalmart\b','Target':r'\btarget\b','Best Buy':r'\bbest buy\b',
'GameStop':r'\bgame\s*stop\b','Costco':r'\bcostco\b',
"Sam's Club":r"\bsam['’]?s club\b", "Lowe's":r"\blowe['’]?s\b",
'Barnes & Noble':r'\bbarnes (?:&|and) noble\b', 'Five Below':r'\bfive below\b',
'Walgreens':r'\bwalgreens\b','CVS':r'\bcvs\b','Amazon':r'\bamazon\b',
'Pokémon Center':r'pok[eé]mon center','Dollar General':r'dollar general',
'Kroger':r'\bkroger\b','Meijer':r'\bmeijer\b',
}
SEARCHES=[
'Pokemon TCG Walmart restock Virginia', 'Sam\'s Club Pokemon cards shipment',
'Costco Pokemon TCG sealed cards restock','Lowes Pokemon cards restock',
'Best Buy trading cards back in stock', 'Target One Piece TCG booster restock',
'GameStop trading cards release stock', 'Union Arena sealed booster restock',
'Lorcana trading card restock retail','Magic the Gathering booster store restock',
'Yu Gi Oh booster restock retail','Gundam trading card game booster restock',
'Digimon TCG boosters restock','Riftbound TCG restock stores',
'Flesh and Blood booster restock','Weiss Schwarz trading cards booster restock',
'Star Wars Unlimited booster restock','Dragon Ball Super TCG restock',
'Final Fantasy TCG booster restock','Cardfight Vanguard booster restock',
'new trading card games sealed products restock',
'Pokemon cards Staunton Waynesboro Harrisonburg Charlottesville restock',
'new TCG product release retailer allocations',
'Pokemon cards Walmart Thursday stocking rumors'
]
SEALED=re.compile(r'booster|trading cards?|\btcg\b|collection box|elite trainer|\betb\b|\btins?\b|blister|sealed|starter deck|box set|bundle|card game',re.I)
NEWS=re.compile(r'restock|stock|shipment|allocated|allocation|release|available|arrived|spotted|drop',re.I)
BAD=re.compile(r'\b(?:graded|single card|singles|psa\s*\d|playmat|binder|sleeve)\b',re.I)
strip_tags=lambda s:re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',html.unescape(s or ''))).strip()

def timeparse(s):
    if not s:return None
    try:d=parsedate_to_datetime(s)
    except (ValueError,TypeError):
        try:d=datetime.fromisoformat(s.replace('Z','+00:00'))
        except (ValueError,TypeError):return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

def read_old():
    try:
        old=json.loads((BASE/'rumor_signals_46.json').read_text())
        return {x['id']:x for x in old.get('signals',[]) if timeparse(x.get('published_utc'))
            and NOW-timedelta(days=45)<=timeparse(x['published_utc'])<=NOW}
    except (OSError,ValueError,KeyError,TypeError):return {}

records=read_old(); failures=[]; successes=0
slot=(NOW.hour//4)%6
queries=SEARCHES[slot*4:slot*4+4]
feeds=[]
for q in queries:
    args=urllib.parse.urlencode({'q':q+' when:30d','hl':'en-US','gl':'US','ceid':'US:en'})
    feeds.append(('Google News: '+q,'https://news.google.com/rss/search?'+args))
feeds.append(('Reddit PKMNTCGDeals','https://www.reddit.com/r/PKMNTCGDeals/new/.rss'))
for source,url in feeds:
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'PokeStock/46 (public RSS research)','Accept':'application/rss+xml, application/xml, text/xml'})
        with urllib.request.urlopen(req,timeout=7) as response:
            xml=ET.fromstring(response.read(700000))
        successes+=1
        candidates=xml.findall('.//item')+xml.findall('{http://www.w3.org/2005/Atom}entry')
        for e in candidates[:70]:
            name='{http://www.w3.org/2005/Atom}'
            title=strip_tags(e.findtext('title') or e.findtext(name+'title'))[:240]
            desc=strip_tags(e.findtext('description') or e.findtext(name+'summary'))[:400]
            pub=timeparse(e.findtext('pubDate') or e.findtext(name+'published') or e.findtext(name+'updated'))
            link=e.findtext('link') or ''
            if not link:
                node=e.find(name+'link'); link=node.get('href','') if node is not None else ''
            content=title+' '+desc
            if not(pub and NOW-timedelta(days=45)<=pub<=NOW+timedelta(hours=1)):continue
            if not link.startswith('https://') or not NEWS.search(content):continue
            if not SEALED.search(content) or BAD.search(title):continue
            game=next((k for k,v in GAMES.items() if re.search(v,content,re.I)),None)
            if not game and not re.search(r'trading card|\btcg\b|card game',content,re.I):continue
            store=next((k for k,v in STORES.items() if re.search(v,content,re.I)),'Unspecified')
            city=next((c for c in ('Staunton','Waynesboro','Harrisonburg','Charlottesville') if re.search(r'\b'+c+r'\b',content,re.I)),None)
            city=(city+', VA') if city else ('Virginia (unspecified)' if re.search(r'\bVirginia\b',content,re.I) else 'Location unspecified')
            id=hashlib.sha256((link.split('?')[0]+title.lower()).encode()).hexdigest()[:20]
            records[id]={'id':id,'title':title,'summary':desc[:250], 'game':game or 'Other TCG',
              'retailer':store,'location':city,'published_utc':pub.isoformat(),
              'source':source,'url':link,'status':'UNVERIFIED PUBLIC MENTION'}
    except Exception as e:
        failures.append({'feed':source,'type':type(e).__name__})

signals=sorted(records.values(),key=lambda x:x['published_utc'],reverse=True)[:350]
leads=[{'retailer':'Walmart','location':'Staunton, VA','game':'Pokémon',
        'window':'Thursday, early morning','confidence':'LOW',
        'status':'UNVERIFIED LOCAL RUMOR',
        'reason':'User-reported rumor, not a confirmed shelf restock.'}]
# A public post's publication date is NOT necessarily a real store restock date.
# Do not extrapolate a delivery calendar from generic articles or press releases.
for filename,obj in [
('rumor_signals_46.json',{'generated_utc':NOW.isoformat(),'availability':'NOT VERIFIED',
 'coverage':'Public RSS feed samples; not comprehensive','signals':signals}),
('rumor_forecast_46.json',{'generated_utc':NOW.isoformat(),
 'disclaimer':'All forecasts are low-confidence leads, not inventory reports.','leads':leads}),
('rumor_report_46.json',{'generated_utc':NOW.isoformat(),'feeds_attempted':len(feeds),
 'feeds_succeeded':successes,'feed_failures':failures,'public_mentions':len(signals),
 'status':'OK - feed coverage may be partial'})]:
    (BASE/filename).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert all('UNVERIFIED' in s['status'] for s in signals)
print('Script 46 collection completed: '+str(len(signals))+' public mentions; '+str(successes)+' feeds accessible')
