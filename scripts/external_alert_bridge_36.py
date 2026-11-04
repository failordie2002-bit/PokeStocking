"""Public alert-page bridge. Reports leads, NEVER confirms current stock."""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

DATA = Path('data')
NOW = datetime.now(timezone.utc)
UA = 'PokeStock/36 (collector site: github.com/failordie2002-bit/PokeStocking; public-page research)'
S = requests.Session()
S.headers.update({'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
EASTERN = ZoneInfo('America/New_York')
SOURCES = [
    ('PokeRestock — all retailers','https://pokerestockapp.com/restocks/'),
    ('PokeRestock — Best Buy','https://pokerestockapp.com/restocks/best-buy/'),
]
LIVE_LINKS = [
    {'name':'Live multi-retailer alerts', 'url':'https://live.pkmnalerts.com/',
     'note':'External live dashboard — check retailer details directly'},
    {'name':'Best Buy restock history', 'url':'https://pokerestockapp.com/restocks/best-buy/',
     'note':'Public historical alerts, delayed at least 30 minutes'},
    {'name':'Major-retailer alert feed', 'url':'https://pokerestockapp.com/restocks/',
     'note':'Public historical alerts, delayed at least 30 minutes'},
    {'name':'PikaNotify free alerts', 'url':'https://pikanotify.com/',
     'note':'Separate provider; Discord enrollment required for alerts'},
]
DATE = re.compile(r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2},\s+\d{1,2}:\d{2}\s*[AP]M\s*ET)\b',re.I)
VIEW = re.compile(r'View at\s+(.+?)(?:\s*\(opens|\s*$)',re.I)
ALLOWED = re.compile(r'booster|trainer box|\bETB\b|collection|tin\b|deck|trading card|\bTCG\b|\bpok[eé]mon\b|\bpokemon\b|\bpack\b',re.I)
BAD = re.compile(r'graded|single card|\bPSA\s*\d|playmat|sleeves|binder|figurine|plush',re.I)

def save(path,obj):
    target=DATA/path
    tmp=target.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    tmp.replace(target)

def clean(x):
    return ' '.join(str(x or '').split())

def https(url):
    try:
        u=urlparse(url)
        return url if u.scheme=='https' and u.hostname else None
    except ValueError:
        return None

def is_allowed(url):
    """Honor robots.txt. Treat a blocked/unreadable robots file conservatively."""
    root=f'{urlparse(url).scheme}://{urlparse(url).netloc}'
    try:
        r=S.get(root+'/robots.txt',timeout=(4,10))
        if r.status_code in (404,410):
            return True,'robots_not_present'
        if r.status_code!=200:
            return False,'robots_http_'+str(r.status_code)
        rp=RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(UA,url),'robots_checked'
    except requests.RequestException as e:
        return False,'robots_unavailable_'+type(e).__name__

def parse_date(text):
    m=DATE.search(text)
    if not m: return None
    try:
        value=re.sub(r'\s+',' ',m.group(1).strip())
        dt=datetime.strptime(value,'%b %d, %Y, %I:%M %p ET')
        return dt.replace(tzinfo=EASTERN).astimezone(timezone.utc)
    except ValueError:
        return None

def parse_items(html,source_url):
    """Only take dated alert rows with a specific retailer link."""
    soup=BeautifulSoup(html,'html.parser')
    rows=[]
    for li in soup.select('li'):
        full=clean(li.get_text(' ',strip=True))
        if len(full)>950 or not DATE.search(full):
            continue
        dt=parse_date(full)
        if not dt or dt>NOW+timedelta(minutes=5) or dt<NOW-timedelta(days=90):
            continue
        link=None
        for a in li.find_all('a',href=True):
            if re.search(r'\bView at\b',clean(a.get_text(' ',strip=True)),re.I):
                link=a
                break
        if link is None: continue
        retailer_label=clean(link.get_text(' ',strip=True))
        m=VIEW.search(retailer_label)
        if not m: continue
        retailer=clean(m.group(1))
        href=https(urljoin(source_url,link.get('href','')))
        if not href: continue
        raw_date=DATE.search(full)
        after=full[raw_date.end():]
        idx=after.lower().find('view at ')
        if idx==-1: continue
        before=after[:idx]
        name=clean(re.sub(r'\$\s*\d[\d,]*(?:\.\d{2})?\s*[·•]?',' ',before))
        name=re.sub(r'^\s*[·•\-:]+|\s*[·•\-:]+$','',name).strip()
        # Prefer a real product title in a heading if available.
        title_node=li.find(['h3','h4'])
        if title_node:
            title=clean(title_node.get_text(' ',strip=True))
            if 8<=len(title)<=230 and ALLOWED.search(title):name=title
        if len(name)<10 or len(name)>250 or not ALLOWED.search(name) or BAD.search(name):
            continue
        price_match=re.search(r'\$\s*([\d,]+\.\d{2})',before)
        item={'id':hashlib.sha256((retailer+'|'+name+'|'+dt.isoformat()).encode()).hexdigest()[:20],
              'product_name':name,'retailer':retailer,
              'reported_at':dt.isoformat(),'first_seen_at':NOW.isoformat(),
              'price_reported':price_match.group(1).replace(',','') if price_match else None,
              'retailer_url':href,'source_url':source_url,
              'evidence_level':'external_delayed_alert',
              'stock_verified_now':False,'physical_store_verified':False,
              'availability':'Reported restock — not current stock'}
        rows.append(item)
    return rows

def main():
    previous=Path('data/external_alerts_36.json')
    old=[]
    if previous.exists():
        try:
            old=json.loads(previous.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    latest={r['id']:r for r in old if isinstance(r,dict) and r.get('id')}
    status=[]
    for name,url in SOURCES:
        check={'name':name,'url':url,'status':'not_checked','rows':0}
        status.append(check)
        permitted,why=is_allowed(url)
        if not permitted:
            check['status']='skipped_'+why
            continue
        try:
            r=S.get(url,timeout=(5,14),allow_redirects=True)
            if r.status_code!=200:
                check['status']='http_'+str(r.status_code);continue
            if not r.url.startswith('https://pokerestockapp.com/restocks/'):
                check['status']='redirected_unexpectedly';continue
            if len(r.content)>4000000:
                check['status']='page_too_large';continue
            items=parse_items(r.text,url)
            check['rows']=len(items)
            check['status']='parsed' if items else 'no_dated_alert_rows_found'
            for item in items:
                if item['id'] in latest:
                    item['first_seen_at']=latest[item['id']].get('first_seen_at',item['first_seen_at'])
                latest[item['id']]=item
        except requests.RequestException as e:
            check['status']='request_error_'+type(e).__name__
        time.sleep(0.7)
    cutoff=NOW-timedelta(days=90)
    recent=[x for x in latest.values()
            if isinstance(x,dict) and x.get('reported_at')
            and datetime.fromisoformat(x['reported_at'])>=cutoff]
    recent.sort(key=lambda x:x['reported_at'],reverse=True)
    recent=recent[:350]
    save('external_alerts_36.json',recent)
    report={'version':'36.0','updated_at':NOW.isoformat(),
            'sources':status,'saved_historical_alerts':len(recent),
            'last_48h':sum(datetime.fromisoformat(x['reported_at'])>=NOW-timedelta(hours=48) for x in recent),
            'last_48h_best_buy':sum(x['retailer'].lower()=='best buy' and datetime.fromisoformat(x['reported_at'])>=NOW-timedelta(hours=48) for x in recent),
            'live_external_links':LIVE_LINKS,
            'important':'External delayed restock reports. No alert proves current inventory or local shelf stock.'}
    save('external_alert_report_36.json',report)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
