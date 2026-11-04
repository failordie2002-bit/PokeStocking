(()=>{
 'use strict';
 const online=document.getElementById('online');
 const shipment=document.getElementById('shipments');
 if(!online || !shipment || document.getElementById('ps37'))return;
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const safe=u=>{try{const a=new URL(u);return a.protocol==='https:'?a.href:'';}catch{return '';}};
 const date=t=>{const d=new Date(t);return isNaN(d.getTime())?'Unknown':d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});};
 const e=(id)=>document.getElementById(id);
 const radar=document.createElement('div');radar.id='ps37';radar.className='ps37-wrap';
 radar.innerHTML=`<div class="section-label">PokéStock unified intelligence</div>
  <h2>Live-ready Restock Radar</h2>
  <p class="muted">Information is displayed here. Reports from other services are <strong>historical restock alerts, not verified current stock</strong>. No major-retailer shelf counts are inferred.</p>
  <div class="ps37-metrics" id="ps37stats"></div>
  <div class="controls"><input id="ps37search" placeholder="Find Pokémon, Union Arena, products or sets" aria-label="Search restock alerts">
   <select id="ps37retailer"><option value="">All retailers</option></select>
   <select id="ps37source"><option value="">All report sources</option><option value="user_forwarded_notification">Forwarded app alerts</option><option value="external_delayed_alert">Public delayed history</option></select>
   <select id="ps37age"><option value="2">48 hours</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select>
  </div><p id="ps37notice" class="muted">Loading alerts…</p><div id="ps37grid" class="grid"></div>`;
 const old=document.getElementById('ps36');
 if(old){old.style.display='none';old.setAttribute('aria-hidden','true');}
 online.insertBefore(radar,online.firstChild);
 const forecast=document.createElement('section');forecast.id='ps37forecast';forecast.className='ps37-wrap';
 forecast.innerHTML=`<div class="section-label">Online inventory intelligence</div>
  <h2>Online Restock Forecaster</h2>
  <p class="muted">Analyzes dated <strong>online restock alerts</strong> by retailer. It does not predict physical card-shelf restocks, confirm shipments, or guarantee future availability. Weekday statistics require repeated observations across several weeks.</p>
  <div class="controls"><select id="ps37forecastRetailer"><option value="">All retailers</option></select></div>
  <p id="ps37forecastNote" class="muted">Loading forecast evidence…</p><div id="ps37forecastCards" class="grid"></div>`;
 shipment.insertBefore(forecast,shipment.firstChild);
 let rows=[], report={}, patterns=[];
 const get=async(path,fallback)=>{try{const r=await fetch(path+'?v='+Date.now(),{cache:'no-store'});return r.ok?await r.json():fallback;}catch{return fallback;}};
 const counters=()=>{
  const day=Date.now()-86400000;
  const active=rows.filter(x=>Date.parse(x.reported_at)>=day).length;
  const recentBest=rows.filter(x=>x.retailer==='Best Buy'&&Date.parse(x.reported_at)>=day).length;
  e('ps37stats').innerHTML=[['Alerts in 24h',active],['Best Buy in 24h',recentBest],['All historical alerts',rows.length],['Verified shelf counts',0]].map(([a,b])=>`<div><strong>${b}</strong><span>${esc(a)}</span></div>`).join('');
 };
 function renderAlerts(){
  const query=e('ps37search').value.trim().toLowerCase(),retailer=e('ps37retailer').value;
  const source=e('ps37source').value;
  const cutoff=Date.now()-Number(e('ps37age').value)*86400000;
  const filtered=rows.filter(x=>Date.parse(x.reported_at)>=cutoff &&
   (!retailer||x.retailer===retailer)&&(!source||x.source_kind===source)&&
   (!query||[x.product_name,x.game,x.retailer].join(' ').toLowerCase().includes(query)));
  e('ps37notice').textContent=`${filtered.length} matching reported restocks · Last data refresh: ${date(report.updated_at)}. Alerts are leads, not proof that products remain orderable or are on shelves.`;
  e('ps37grid').innerHTML=filtered.slice(0,200).map(x=>{
   const retailer=safe(x.retailer_url), origin=safe(x.source_url);
   const details=[`<p><strong>Evidence:</strong> ${esc(x.source)}</p>`,
    `<p>Checked stock now: <strong>Not independently verified</strong></p>`,
    x.source_kind==='external_delayed_alert'?'<p>Public source may delay publishing by 30+ minutes.</p>':'<p>Authorized phone-forwarded notification; source content not independently rechecked.</p>',
    retailer?`<a href="${esc(retailer)}" target="_blank" rel="noopener noreferrer">Retailer product / purchase page</a>`:'',
    origin?`<p><a href="${esc(origin)}" target="_blank" rel="noopener noreferrer">Original alert source</a></p>`:''].join('');
   return `<article class="tile ps37-card"><span class="pill unknown">Reported restock · stock unknown now</span>
    <h3>${esc(x.product_name)}</h3><p><strong>${esc(x.retailer)}</strong> · ${esc(x.game||'TCG')}</p>
    ${x.price_reported?`<p>Reported price: <strong>$${esc(x.price_reported)}</strong></p>`:'<p class="muted">Price not reported</p>'}
    <p>Alert received/reported: <strong>${esc(date(x.reported_at))}</strong></p>
    <p class="muted">Online signal · No store-level shelf evidence</p>
    <details class="ps37-details"><summary>Evidence and optional purchase link</summary>${details}</details></article>`;
  }).join('')||'<div class="empty">No matching alerts. This does not mean these retailers are sold out.</div>';
 }
 function renderForecast(){
  const chosen=e('ps37forecastRetailer').value;
  const filtered=patterns.filter(x=>!chosen||chosen===x.retailer);
  e('ps37forecastNote').textContent=`${filtered.length} retailer signal summaries. Historical weekdays are NOT a probability that a restock will occur. In-store shipment evidence is kept separate.`;
  e('ps37forecastCards').innerHTML=filtered.map(p=>{
    const strong=p.forecast_status==='historical_watch_window';
    const days=(p.weekday_counts||[]).filter(x=>x.count>0).map(x=>`${x.day.slice(0,3)}: ${x.count}`).join(' · ')||'No dated observations';
    const times=strong?(p.watch_windows||[]).map(w=>`<div class="ps37-watch">${esc(w.weekday)} · ${esc(w.historical_dates)} past dates · next occurrence ${esc(w.next_matching_date)}</div>`).join(''):'<p class="muted">Insufficient repeated dates for a watch window.</p>';
    return `<article class="tile ps37-card"><h3>${esc(p.retailer)}</h3><p><strong>${p.signal_count}</strong> reports on <strong>${p.distinct_observation_dates}</strong> distinct dates</p>
    <p><span class="pill unknown">${esc(p.confidence)}</span></p><p class="muted">Historical weekdays: ${esc(days)}</p>${times}
    <p class="muted">Online alerts only; not a delivery forecast or present stock confirmation.</p></article>`;
  }).join('')||'<div class="empty">No retailer forecast observations yet.</div>';
 }
 async function load(){
  const [a,b,c]=await Promise.all([get('data/alert_events_37.json',[]),get('data/alert_bridge_report_37.json',{}),get('data/online_forecaster_37.json',{})]);
  rows=Array.isArray(a)?a:[];report=b&&typeof b==='object'?b:{};patterns=Array.isArray(c?.retailer_patterns)?c.retailer_patterns:[];
  const names=[...new Set(rows.map(x=>x.retailer).filter(Boolean))].sort();
  for(const id of ['ps37retailer','ps37forecastRetailer']){
   const select=e(id),v=select.value;
   select.innerHTML='<option value="">All retailers</option>';
   for(const name of names){const op=document.createElement('option');op.value=name;op.textContent=name;select.append(op);}
   select.value=v;
  }
  counters();renderAlerts();renderForecast();
 }
 ['ps37search','ps37retailer','ps37source','ps37age'].forEach(id=>e(id).addEventListener('input',renderAlerts));
 e('ps37forecastRetailer').addEventListener('input',renderForecast);
 load();
})();
