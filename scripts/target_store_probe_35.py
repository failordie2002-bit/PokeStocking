import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

OUTPUT = Path('data/target_store_probe_35.json')
SHOTS = Path('target35_screenshots')
SHOTS.mkdir(exist_ok=True)
STORE = {'store_id':'2294','name':'Waynesboro',
         'address':'811 Town Center Dr', 'zip':'22980'}
PRODUCTS = [
    ('1013166578','Delta Reign Booster Bundle'),
    ('94884496','Phantasmal Flames Booster Bundle'),
    ('1011407490','30th Celebration Booster Bundle')
]
BLOCK = re.compile(
    r'captcha|access denied|attention required|verify you are human|'
    r'cloudflare|unusual traffic|automated requests', re.I)
ST_STATUS = re.compile(
    r'\b(in stock|out of stock|limited stock|available for pickup|'
    r'pickup available|unavailable for pickup|not available|sold out)\b', re.I)
PRODUCT_WORDS = re.compile(r'pok[eé]mon|trading card game', re.I)

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def save(data):
    OUTPUT.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

def target_match(text):
    text=' '.join(text.split())
    if len(text) > 380 or len(text) < 20:
        return None
    if not re.search(r'\bWaynesboro\b',text,re.I):
        return None
    if not (re.search(r'811\s+Town\s+Center',text,re.I)
            or re.search(r'\b2294\b',text)
            or re.search(r'\b22980\b',text)):
        return None
    label=ST_STATUS.search(text)
    return {'label':label.group(1),'excerpt':text[:380]} if label else None

async def store_cards(page):
    # Never treat generic page stock as store-specific stock.
    rows=await page.locator(
        'li, article, [role="row"], [role="option"], '
        '[data-test*="store"], [data-testid*="store"]'
    ).all()
    for node in rows[:140]:
        try:
            if not await node.is_visible(timeout=500):
                continue
            found=target_match(await node.inner_text(timeout=1200))
            if found:
                return found
        except Exception:
            continue
    return None

def network_evidence(tree):
    # Require exact store ID and explicit pickup status.
    stack=[tree]
    examined=0
    while stack and examined<25000:
        item=stack.pop()
        examined+=1
        if isinstance(item,list):
            stack.extend(item[:150])
            continue
        if not isinstance(item,dict):
            continue
        identifiers=[]
        for key in ('location_id','store_id','locationId','storeId'):
            if item.get(key) is not None:
                identifiers.append(str(item[key]))
        if '2294' in identifiers:
            pickup=item.get('order_pickup') or item.get('pickup')
            if isinstance(pickup,dict):
                raw=pickup.get('availability_status') or pickup.get('availability')
                status=str(raw or '').upper()
                if status in ('IN_STOCK','LIMITED_STOCK','OUT_OF_STOCK',
                              'NOT_AVAILABLE','UNAVAILABLE','NOT_SOLD_IN_STORE'):
                    return {'label':status,'excerpt':'Store 2294 pickup status '+status}
        stack.extend(x for x in item.values() if isinstance(x,(dict,list)))
    return None

async def run_product(browser,tcin,name):
    row={'tcin':tcin,'product':name,'store':STORE,
         'status':'unknown','reason':'not_checked',
         'http_status':None,'proof':None,'steps':[],
         'network':[],'checked_at':timestamp()}
    page=await browser.new_page(locale='en-US',
                                timezone_id='America/New_York',
                                viewport={'width':1280,'height':900})
    response_tasks=[]
    evidence=[]

    async def watch(resp):
        try:
            u=urlparse(resp.url)
            if not (u.hostname or '').endswith('target.com'):
                return
            if len(row['network'])<25 and ('redsky' in u.hostname or 'fulfillment' in u.path):
                row['network'].append({'path':u.path[:130],'status':resp.status})
            if resp.status!=200 or 'json' not in resp.headers.get('content-type','').lower():
                return
            if tcin not in resp.url:
                return
            if not any(x in resp.url.lower() for x in ('fulfillment','availability')):
                return
            payload=await resp.json()
            proof=network_evidence(payload)
            if proof:
                proof['kind']='store_pickup_network'
                evidence.append(proof)
        except Exception:
            pass

    page.on('response',lambda r: response_tasks.append(asyncio.create_task(watch(r))))
    try:
        url='https://www.target.com/p/-/A-'+tcin
        resp=await page.goto(url,wait_until='domcontentloaded',timeout=35000)
        row['http_status']=resp.status if resp else None
        await page.wait_for_timeout(3500)
        await page.screenshot(path=str(SHOTS/(tcin+'_initial.png')),timeout=8000)
        title=await page.title()
        body=(await page.locator('body').inner_text(timeout=8000))[:1600]
        row['title']=title[:160]
        row['page_excerpt']=' '.join(body.split())[:420]
        if row['http_status'] in (401,403,429) or BLOCK.search(title) or BLOCK.search(body[:600]):
            row['status']='blocked'
            row['reason']='Target blocked or challenged browser access'
            return row
        if not PRODUCT_WORDS.search(title+' '+body):
            row['reason']='Expected Target Pokemon product page not found'
            return row
        local=await store_cards(page)
        if local:
            local['kind']='store_picker_ui'
            evidence.append(local)
        if not evidence:
            for label in ('Check other stores','Edit store','Change store','Select store','Find in store'):
                try:
                    control=page.get_by_role('button',name=re.compile(label,re.I)).first
                    if await control.is_visible(timeout=1000):
                        await control.click(timeout=4500)
                        row['steps'].append('Opened '+label)
                        await page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue
            if not evidence:
                inputs=page.locator('input[type="search"], input[placeholder*="zip" i], input[placeholder*="city" i], input[placeholder*="store" i]')
                for i in range(min(await inputs.count(),5)):
                    try:
                        inp=inputs.nth(i)
                        if await inp.is_visible(timeout=500):
                            await inp.fill('22980',timeout=4000)
                            await inp.press('Enter',timeout=4000)
                            row['steps'].append('Searched ZIP 22980')
                            await page.wait_for_timeout(2400)
                            break
                    except Exception:
                        continue
                local=await store_cards(page)
                if local:
                    local['kind']='store_picker_ui'
                    evidence.append(local)
        if response_tasks:
            await asyncio.gather(*response_tasks,return_exceptions=True)
        if evidence:
            row['status']='store_specific_observation'
            row['reason']='Exact store and explicit pickup status observed'
            row['proof']=evidence[0]
        else:
            row['reason']='No unambiguous Waynesboro store pickup status found'
        await page.screenshot(path=str(SHOTS/(tcin+'_final.png')),timeout=8000)
    except Exception as exc:
        row['status']='error'
        row['reason']=type(exc).__name__+': '+str(exc)[:250]
        try:
            await page.screenshot(path=str(SHOTS/(tcin+'_error.png')),timeout=6000)
        except Exception:
            pass
    finally:
        await page.close()
    return row

async def main():
    report={'version':'35.1','result':'NOT_PROVEN',
            'store':STORE,'checked_at':timestamp(),
            'products':[],'observations':[],
            'note':'Pickup availability is not physical shelf proof.'}
    save(report)
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True,args=['--no-sandbox'])
            try:
                for tcin,name in PRODUCTS:
                    row=await run_product(browser,tcin,name)
                    report['products'].append(row)
                    if row['status']=='store_specific_observation':
                        report['observations'].append(row)
                    save(report)
                    print(tcin,row['status'],row['reason'],flush=True)
                    if row['status']=='blocked':
                        break
            finally:
                await browser.close()
        if report['observations']:
            report['result']='PROVEN_STORE_PICKUP'
        else:
            report['reason']='No store-specific observation confirmed'
    except Exception as exc:
        report['reason']=type(exc).__name__+': '+str(exc)[:350]
    finally:
        report['finished_at']=timestamp()
        save(report)
    print('RESULT:',report['result'],flush=True)

if __name__=='__main__':
    asyncio.run(main())
