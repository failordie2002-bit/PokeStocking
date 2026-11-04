(()=>{
'use strict';
if(document.getElementById('ps40Home'))return;
const tabs=document.querySelector('main .tabs');
const header=document.querySelector('body>header');
if(!tabs||!header)return;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe=u=>{try{const v=new URL(u);return v.protocol==='https:'?v.href:'';}catch{return '';}};
const elem=id=>document.getElementById(id);
const date=s=>{let v=new Date(s);return Number.isNaN(+v)?'Unknown':v.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});};
const hours=s=>(Date.now()-Date.parse(s))/3600000;
const fetchJSON=async(path,otherwise)=>{try{let x=await fetch(path+'?t='+Date.now(),{cache:'no-store'});return x.ok?await x.json():otherwise;}catch{return otherwise;}};
const nav=document.createElement('div');nav.className='ps40-nav';nav.setAttribute('aria-label','Primary navigation');
nav.innerHTML=`<button data-ps40-go="ps40Home" aria-current="page">Discover</button><button data-ps40-go="online">Online Stock</button><button data-ps40-go="stores">Stores Near Me</button><button data-ps40-go="ps40Forecast">Restock Outlook</button><select id="ps40More" aria-label="More PokéStock features"><option value="">More ▾</option><option value="pickup">Store Pickup</option><option value="products">All Products</option><option value="releases">New Releases</option><option value="social">Community</option><option value="shipments">Legacy Shipments</option><option value="sources">Data Sources</option></select>`;
header.append(nav);
const home=document.createElement('section');home.className='panel active';home.id='ps40Home';
home.innerHTML=`<div class="ps40-hero"><div class="ps40-kicker">The collector's radar</div><h1 class="ps40-title">Find the cards.<br>Skip the guesswork.</h1><p class="ps40-lede">Track sealed TCG products, compare observed online listings, and explore local retailer signals—all from one place.</p><div class="ps40-searchbar"><input id="ps40Find" type="search" placeholder="Search sets, booster boxes, Pokémon, Union Arena…" aria-label="Search products"><button class="ps40-gold-btn" id="ps40SearchGo" type="button">Find products</button></div><div class="ps40-chips" id="ps40Chips"><button type="button" data-ps40-game="" aria-pressed="true">All TCGs</button><button type="button" data-ps40-game="Pokémon">Pokémon</button><button type="button" data-ps40-game="Union Arena">Union Arena</button><button type="button" data-ps40-game="One Piece">One Piece</button><button type="button" data-ps40-game="Gundam">Gundam</button></div></div><div class="ps40-metrics" id="ps40Metrics"><div class="ps40-metric">Loading merchant listings…</div></div><div class="ps40-split"><h2>Recently observed online</h2><span class="ps40-secondary" id="ps40Freshness">Checking last observations…</span></div><div id="ps40Offers" class="ps40-grid"></div><div class="ps40-split"><h2>Collector intelligence</h2></div><div class="ps40-callout" id="ps40Insight">Loading store and community evidence…</div><p class="ps40-foot">Listings and community reports show what sources said at recorded times. They do not guarantee checkout, store pickup, or shelf stock. Source details are available inside PokéStock.</p>`;
const forecast=document.createElement('section');forecast.className='panel';forecast.id='ps40Forecast';
forecast.innerHTML=`<div class="ps40-head"><div><div class="ps40-kicker">Location-based intelligence</div><h1 class="ps40-title">Restock Outlook</h1><p class="ps40-lede">Check individual stores, dated sightings, and research leads without confusing retailer-wide speculation with verified deliveries.</p></div></div><div id="ps40OutlookStatus" class="ps40-callout">Loading independently collected evidence…</div><div id="ps40EvidenceBars" class="ps40-bars"></div><div class="ps40-controls"><input id="ps40StoreQuery" type="search" placeholder="Search retailer, city, store or ZIP" aria-label="Search store outlook"><select id="ps40State" aria-label="State"><option value="">All states</option></select><select id="ps40Evidence" aria-label="Evidence level"><option value="">All evidence</option><option value="reports">Community sightings</option><option value="research">Retailer research leads</option><option value="history">Historical weekday patterns</option><option value="unknown">No evidence yet</option></select></div><p id="ps40OutlookCount" class="ps40-foot">Loading stores…</p><div id="ps40StoreGrid" class="ps40-grid"></div><button id="ps40MoreStores" class="ps40-more" type="button" hidden>Show more stores</button><div class="ps40-split"><h2>Upcoming official TCG releases</h2><span class="ps40-secondary">Release dates are not store stock confirmations</span></div><div id="ps40Releases" class="ps40-grid"></div>`;
tabs.prepend(forecast);tabs.prepend(home);
tabs.querySelectorAll(':scope>section').forEach(x=>x.classList.toggle('active',x===home));
let offers=[], outlook={stores:[],upcoming_official_releases:[]}, game='',viewCount=36;
const storeOldTab=id=>document.querySelector('body>header nav button[data-tab="'+id+'"]');
function go(id){
  if(!['ps40Home','ps40Forecast'].includes(id)){
    const original=storeOldTab(id);
    if(!original)return;
    original.click();
  }else{
    tabs.querySelectorAll(':scope>section').forEach(x=>x.classList.toggle('active',x.id===id));
  }
  nav.querySelectorAll('[data-ps40-go]').forEach(b=>{if(b.dataset.ps40Go===id)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(['ps40Home','ps40Forecast','online','stores'].includes(id))elem('ps40More').value='';
  window.scrollTo({top:0,behavior:'smooth'});
}
nav.querySelectorAll('[data-ps40-go]').forEach(b=>b.addEventListener('click',()=>go(b.dataset.ps40Go)));
elem('ps40More').addEventListener('change',e=>{if(e.target.value)go(e.target.value);});
const gameMatch=(o,g)=>!g||String(o.game||'').toLowerCase().includes(g.toLowerCase().replace('é','e'))||String(o.game||'').toLowerCase().includes(g.toLowerCase());
const available=o=>o.availability==='In stock'&&o.inventory_scope==='online';
const fresh=o=>Number.isFinite(hours(o.checked_at))&&hours(o.checked_at)>=0&&hours(o.checked_at)<=8;
const price=o=>{if(!o.price)return 'Price not reported';const currency=String(o.currency||'');return currency==='USD'?'$'+esc(o.price):currency&&currency!=='Unverified'?esc(o.price)+' '+esc(currency):esc(o.price)+' (currency unverified)';};
function renderHome(){
  const q=elem('ps40Find').value.trim().toLowerCase();
  const eligible=offers.filter(o=>available(o)&&fresh(o));
  const filtered=eligible.filter(o=>gameMatch(o,game)&&(!q||[o.product_name,o.retailer,o.game,o.variant].join(' ').toLowerCase().includes(q)));
  const retailers=new Set(eligible.map(o=>o.retailer));
  elem('ps40Metrics').innerHTML=`<div class="ps40-metric"><strong>${eligible.length.toLocaleString()}</strong><span>Recently observed available listings</span></div><div class="ps40-metric"><strong>${retailers.size}</strong><span>Retailers with recent listings</span></div><div class="ps40-metric"><strong>${Number(outlook.store_candidates||0).toLocaleString()}</strong><span>Mapped store candidates nationwide</span></div>`;
  elem('ps40Freshness').textContent=filtered.length+' matching listings · Observations within 8 hours';
  elem('ps40Offers').innerHTML=filtered.slice(0,12).map(o=>{const url=safe(o.product_url),evidence=safe(o.evidence_url);return `<article class="ps40-card"><span class="ps40-tag teal">Storefront observed available</span><h3>${esc(o.product_name)}</h3><p><b>${esc(o.retailer)}</b> · ${esc(o.game||'Trading cards')}</p><p class="ps40-price">${price(o)}</p><p>Last checked: ${esc(date(o.checked_at))}</p><details><summary>Evidence & optional purchase link</summary><p>${esc(o.evidence_type||'Retailer website observation')} · Online listing only</p>${url?`<p><a class="ps40-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Retailer product page</a></p>`:''}${evidence?`<p><a class="ps40-link" href="${esc(evidence)}" target="_blank" rel="noopener noreferrer">Original evidence</a></p>`:''}</details></article>`;}).join('')||'<div class="ps40-empty">No recently checked, available online listings match that search. This does not mean products are sold out. Try another game or the full Online Stock tab.</div>';
  elem('ps40Insight').innerHTML=`<strong>${Number(outlook.public_unverified_sightings||0)} public sighting reports</strong> have been collected for research. ${Number(outlook.stores_with_provisional_reports||0)} candidate stores have provisional branch-level matches. <strong>${Number(outlook.stores_with_historical_watch_weekday||0)} stores</strong> currently meet the minimum history requirement for a weekday watch pattern. Browse Restock Outlook to see what is known for each location.`;
}
function renderOutlook(){
  const all=Array.isArray(outlook.stores)?outlook.stores:[];
  const state=elem('ps40State').value;
  const filter=elem('ps40Evidence').value;
  const q=elem('ps40StoreQuery').value.trim().toLowerCase();
  const matched=all.filter(s=>(!state||s.state===state)&&(!q||[s.store_name,s.chain,s.city,s.state,s.zip].join(' ').toLowerCase().includes(q))&&(!filter||(filter==='reports'&&(s.city_area_reports||[]).length>0)||(filter==='research'&&s.research_watch)||(filter==='history'&&s.watch_weekday)||(filter==='unknown'&&!(s.city_area_reports||[]).length&&!s.research_watch&&!s.watch_weekday)));
  elem('ps40OutlookCount').textContent=`${matched.length.toLocaleString()} store candidates matching filters. Store listings do not themselves prove TCG availability.`;
  elem('ps40MoreStores').hidden=matched.length<=viewCount;
  elem('ps40StoreGrid').innerHTML=matched.slice(0,viewCount).map(s=>{
    const sight=(s.provisional_reports||[])[0];const area=(s.city_area_reports||[])[0];
    const source=safe(sight?.source_url||area?.source_url||s.research_source);
    return `<article class="ps40-card"><span class="ps40-tag ${s.watch_weekday?'teal':s.provisional_reports?.length?'amber':''}">${esc(s.watch_weekday?'Historical watch weekday':s.provisional_reports?.length?'Unverified branch match':area?'City-level reports':s.research_watch?'Research only':'Evidence pending')}</span><h3>${esc(s.store_name)}</h3><p>${esc([s.city,s.state].filter(Boolean).join(', '))} ${s.zip?'· '+esc(s.zip):''}</p><p><b>${esc(s.chain)}</b></p><p>${esc(s.outlook)}</p>${s.watch_weekday?`<p>Historical watch weekday: <b>${esc(s.watch_weekday)}</b> (not guaranteed)</p>`:''}${sight?`<p>Provisional report: ${esc(sight.product)} · ${esc(date(sight.reported_at))}</p>`:area?`<p>City report (not linked to this branch): ${esc(area.product)} · ${esc(date(area.reported_at))}</p>`:s.research_watch?'<p>Retailer-wide guidance exists, but no branch-specific delivery evidence.</p>':'<p>No dated store observations yet. Current stock: unknown.</p>'}<details><summary>Evidence quality and source</summary><p>Exact-store verified sighting days: ${Number(s.verified_store_sightings)||0}. Community reports may be approximate. A research lead never confirms a shipment.</p>${source?`<a class="ps40-link" href="${esc(source)}" target="_blank" rel="noopener noreferrer">Original supporting source</a>`:''}</details></article>`;
  }).join('')||'<div class="ps40-empty">No stores match these filters. Try another city, chain, or evidence level.</div>';
}
function renderEvidence(){
  const all=Array.isArray(outlook.stores)?outlook.stores:[];
  const metrics=[['Store candidates',all.length],['Stores with city reports',outlook.stores_with_city_reports||0],['Research watch leads',outlook.stores_with_retailer_research_leads||0]];
  elem('ps40EvidenceBars').innerHTML=metrics.map(([n,v])=>`<div class="ps40-bar"><b>${Number(v).toLocaleString()}</b><span>${esc(n)}</span><div class="ps40-track"><div class="ps40-fill" style="width:${all.length?Math.max(0,Math.min(100,100*Number(v)/all.length)):0}%"></div></div></div>`).join('');
  elem('ps40OutlookStatus').innerHTML=`<strong>What the evidence supports:</strong> ${Number(outlook.public_unverified_sightings||0)} recently collected community reports; ${Number(outlook.stores_with_provisional_reports||0)} store candidates with provisional report matches; ${Number(outlook.stores_with_historical_watch_weekday||0)} with enough repeated verified store history for a limited weekday watch. <b>No generic freight schedule is treated as an actual card shipment.</b> Last compiled: ${esc(date(outlook.generated_at))}.`;
  elem('ps40Releases').innerHTML=(outlook.upcoming_official_releases||[]).slice(0,8).map(x=>{const url=safe(x.source_url);return `<article class="ps40-card"><span class="ps40-tag teal">Official release · ${esc(x.date)}</span><h3>${esc(x.name)}</h3><p>${esc(x.game||'TCG')} · No local stock confirmation</p>${url?`<details><summary>Source</summary><a class="ps40-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Official announcement</a></details>`:''}</article>`;}).join('')||'<div class="ps40-empty">No upcoming official dates in the connected release feed.</div>';
  const states=[...new Set(all.map(x=>x.state).filter(Boolean))].sort();
  elem('ps40State').innerHTML='<option value="">All states</option>'+states.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
}
elem('ps40Find').addEventListener('input',renderHome);
elem('ps40SearchGo').addEventListener('click',()=>{const value=elem('ps40Find').value.trim();const search=elem('onlineSearch');if(search){search.value=value;search.dispatchEvent(new Event('input',{bubbles:true}));}go('online');});
elem('ps40Find').addEventListener('keydown',e=>{if(e.key==='Enter')elem('ps40SearchGo').click();});
elem('ps40Chips').querySelectorAll('[data-ps40-game]').forEach(b=>b.addEventListener('click',()=>{game=b.dataset.ps40Game;elem('ps40Chips').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderHome();}));
['ps40StoreQuery','ps40State','ps40Evidence'].forEach(id=>elem(id).addEventListener('input',()=>{viewCount=36;renderOutlook();}));
elem('ps40MoreStores').addEventListener('click',()=>{viewCount+=36;renderOutlook();});
(async()=>{
  const [a,b]=await Promise.all([fetchJSON('data/unified_online_39.json',null),fetchJSON('data/store_outlook_40.json',null)]);
  if(Array.isArray(a))offers=a;
  if(b&&Array.isArray(b.stores))outlook=b;
  renderEvidence();renderHome();renderOutlook();
})();
})();
