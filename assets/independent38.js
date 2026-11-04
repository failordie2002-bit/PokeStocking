(()=>{
'use strict';
if(document.getElementById('ps38')) return;
const online=document.getElementById('online');
if(!online) return;
const STORE='pokestock38_prefs_v1', SEEN='pokestock38_seen_v1';
const escapeHTML=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=x=>{const d=new Date(x);return Number.isNaN(+d)?'Unknown':d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});};
const safeURL=x=>{try{let u=new URL(x);return u.protocol==='https:'?u.href:'';}catch{return '';}};
const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
const write=(key,val)=>{try{localStorage.setItem(key,JSON.stringify(val));}catch{}};
const el=id=>document.getElementById(id);
let prefs=read(STORE,{keyword:'',retailer:'',notify:false}), seen=new Set(read(SEEN,[]));
let alerts=[],report={},loaded=false,everLoaded=false;
const host=document.createElement('section');host.id='ps38';host.className='ps38';
host.innerHTML=`<div class="section-label">First-party PokéStock monitoring</div>
<h2>Independent Online Restock Alerts</h2>
<p class="muted">Stock transitions observed by PokéStock's own retailer checks. A timestamp is the <strong>last observation</strong>, not a guarantee that the product is still available. Local shelf inventory is not inferred.</p>
<div class="ps38-form"><label>Watch product or set <input id="ps38keyword" type="search" placeholder="All products (or type Pokémon, Union Arena…)" aria-label="Watch product keyword"></label>
<label>Retailer <select id="ps38retailer" aria-label="Watch retailer"><option value="">All retailers</option></select></label>
<button id="ps38notify" class="primary" type="button">Enable alerts while site is open</button></div>
<p class="muted" id="ps38privacy">Watch preferences stay in this browser, not on a third-party service. Notifications work only while this page is open.</p>
<p id="ps38status" class="muted" role="status">Loading independent reports…</p>
<div id="ps38cards" class="grid"></div>`;
online.insertBefore(host,online.firstChild);
el('ps38keyword').value=prefs.keyword||'';
function match(x){const q=(prefs.keyword||'').trim().toLowerCase();return (!q||[x.product_name,x.game,x.retailer,x.variant].join(' ').toLowerCase().includes(q))&&(!prefs.retailer||x.retailer===prefs.retailer);}
function render(){
  const filtered=alerts.filter(match);
  el('ps38notify').textContent=prefs.notify?'Alerts on while page is open':'Enable alerts while site is open';
  el('ps38status').textContent=`${filtered.length} matching independently observed online restocks · ${report.fresh_explicit_variant_listings||0} fresh merchant variants in the most recent evaluated feed · Last merchant check: ${date(report.last_processed_offer_check)}. No shelf stock is implied.`;
  el('ps38cards').innerHTML=filtered.slice(0,100).map(x=>{
    const u=safeURL(x.retailer_url),price=x.price_reported;
    return `<article class="tile ps38-card"><span class="pill unknown">Observed available · verify again before buying</span>
      <h3>${escapeHTML(x.product_name)}</h3>
      <p><strong>${escapeHTML(x.retailer)}</strong> · ${escapeHTML(x.game||'TCG')}</p>
      ${x.variant?`<p>Variant: ${escapeHTML(x.variant)}</p>`:''}
      ${price?`<p>Listing price: ${escapeHTML(price)} ${escapeHTML(x.currency==='Unverified'?'(currency unverified)':(x.currency||''))}</p>`:''}
      <p>Observed at: <strong>${escapeHTML(date(x.checked_at))}</strong></p>
      <p class="muted">Evidence: public merchant product variant · online availability only</p>
      ${u?`<details><summary>Optional retailer product page</summary><a href="${escapeHTML(u)}" target="_blank" rel="noopener noreferrer">Open source product page</a></details>`:''}</article>`;
   }).join('')||'<div class="empty">No independently observed restock transitions for these filters yet. This does not mean products are sold out.</div>';
}
async function notifyNative(x){
 const title='PokéStock reported online restock';
 const options={body:`${x.product_name} · ${x.retailer}. Check observed time and availability.`,tag:'ps38-'+x.id};
 try{
   if('serviceWorker' in navigator){const registration=await navigator.serviceWorker.register('ps38-sw.js');await registration.showNotification(title,options);return;}
   new Notification(title,options);
 }catch{try{new Notification(title,options);}catch{}}
}
async function check(){
 try{
  const q='?v='+Date.now();
  const [a,r]=await Promise.all([fetch('data/first_party_restocks_38.json'+q,{cache:'no-store'}),fetch('data/first_party_report_38.json'+q,{cache:'no-store'})]);
  if(!a.ok||!r.ok) throw new Error('feed not published');
  const data=await a.json();const rep=await r.json();
  if(!Array.isArray(data)||!rep||typeof rep!=='object') throw Error('invalid feed');
  alerts=data;report=rep;loaded=true;
  const names=[...new Set(data.map(x=>x.retailer).filter(Boolean))].sort();
  el('ps38retailer').replaceChildren(new Option('All retailers',''),...names.map(n=>new Option(n,n)));
  if(prefs.retailer&&!names.includes(prefs.retailer)) el('ps38retailer').add(new Option(prefs.retailer,prefs.retailer));
  el('ps38retailer').value=prefs.retailer||'';
  if(!everLoaded){for(const x of alerts)seen.add(x.id);everLoaded=true;}
  else if(prefs.notify){const fresh=alerts.filter(x=>!seen.has(x.id)&&match(x));
    for(const x of fresh.slice(0,3)){
      if(typeof Notification!=='undefined'&&Notification.permission==='granted'&&document.visibilityState==='visible'){
        notifyNative(x);
      }
    }
  }
  for(const x of alerts)seen.add(x.id);
  seen=new Set([...seen].slice(-1000));write(SEEN,[...seen]);render();
 }catch(err){el('ps38status').textContent=loaded?'Unable to refresh independent alerts; showing previously loaded results.':'Independent alert feed not published yet. Run Script 38 once to initialize it.';}
}
el('ps38keyword').addEventListener('input',e=>{prefs.keyword=e.target.value;write(STORE,prefs);render();});
el('ps38retailer').addEventListener('change',e=>{prefs.retailer=e.target.value;write(STORE,prefs);render();});
el('ps38notify').addEventListener('click',async()=>{
 if(prefs.notify){prefs.notify=false;write(STORE,prefs);render();return;}
 if(typeof Notification==='undefined'){
   el('ps38privacy').textContent='This browser does not support page-level notifications. Restock alerts remain visible inside PokéStock.';return;
 }
 let granted=Notification.permission==='granted';
 if(!granted&&Notification.permission==='default'){
   try{granted=(await Notification.requestPermission())==='granted';}catch{}
 }
 if(!granted){el('ps38privacy').textContent='Notifications are unavailable or blocked. Alerts still appear in PokéStock without an external app.';return;}
 prefs.notify=true;write(STORE,prefs);render();
 el('ps38privacy').textContent='Notifications enabled for new matching reports while this page remains open. Closed-page push requires a separate first-party push backend.';
});
check();setInterval(check,60000);
})();
