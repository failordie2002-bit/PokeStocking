(()=>{
'use strict';
if(document.getElementById('ps2root'))return;
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe=u=>{try{const x=new URL(String(u));return x.protocol==='https:'?x.href:'';}catch{return '';}};
const when=x=>{const t=new Date(x);return Number.isFinite(+t)?t.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Time unknown';};
const day=x=>{const t=new Date(x);return Number.isFinite(+t)?t.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Date not available';};
const age=x=>(Date.now()-Date.parse(x))/3600000;
const get=async(path,fallback)=>{try{const r=await fetch(path+'?v='+Date.now(),{cache:'no-store'});return r.ok?await r.json():fallback;}catch{return fallback;}};
const distance=(a,b,c,d)=>{const k=Math.PI/180,h=Math.sin((c-a)*k/2)**2+Math.cos(a*k)*Math.cos(c*k)*Math.sin((d-b)*k/2)**2;return 3958.8*2*Math.asin(Math.min(1,Math.sqrt(h)));};
const coords=o=>o&&o.lat!=null&&(o.lon!=null||o.long!=null)&&Number.isFinite(Number(o.lat))&&Number.isFinite(Number(o.lon??o.long))&&Math.abs(Number(o.lat))<=90&&Math.abs(Number(o.lon??o.long))<=180;
let location=null;try{const x=JSON.parse(localStorage.getItem('ps2location'));if(coords(x)&&typeof x.label==='string')location=x;}catch{}
let radius=Number(localStorage.getItem('ps2radius'))||50;if(![10,25,50,100,250].includes(radius))radius=50;
let stores=[],offers=[],social=[],sightings=[],outlook=new Map(),releases=[],news=[],map=null,pins=null,routeLayer=null,gpsLayer=null,selected=null,selectedForecast=null,navWatch=null,findGame='',postFilter='local',postsLimit=18;
let forecast43Records=[];
const root=document.createElement('div');root.id='ps2root';root.innerHTML=`
<header class="ps2top"><div class="ps2brand">✦ Poké<em>Stock</em></div><button id="ps2Place" class="ps2place" type="button">⌾ Set your location</button></header>
<nav class="ps2tabs" aria-label="Main navigation"><button class="ps2tab active" data-ps2-tab="discover">⌂ Discover</button><button class="ps2tab" data-ps2-tab="near">◎ Near Me</button><button class="ps2tab" data-ps2-tab="social">▣ Social</button><button class="ps2tab" data-ps2-tab="forecast">▥ Forecast</button></nav>
<div class="ps2wrap">
<section id="ps2-discover" class="ps2view active">
 <div class="ps2hero"><div class="ps2eyebrow">Your collector radar</div><h1>Never miss<br><em>the next drop.</em></h1><p>Find sealed TCG products, local activity, official releases and community posts. One simple home.</p>
 <div class="ps2searchbar"><input id="ps2Search" type="search" placeholder="Search Pokémon, Union Arena, booster boxes…" aria-label="Search products"><button class="ps2cta" id="ps2Find" type="button">Find stock</button></div></div>
 <div id="ps2Games" class="ps2chips"><button class="ps2chip sel" data-game="">All TCGs</button><button class="ps2chip" data-game="Pokemon">Pokémon</button><button class="ps2chip" data-game="Union Arena">Union Arena</button><button class="ps2chip" data-game="One Piece">One Piece</button><button class="ps2chip" data-game="Gundam">Gundam</button></div>
 <div class="ps2section"><h2>⚡ Online stock</h2><span class="ps2hint" id="ps2OnlineHint">Checking merchant observations…</span></div>
 <div id="ps2Products" class="ps2grid"></div><div class="ps2section"><h2>📍 Around you</h2><button class="ps2secondary" type="button" data-go="near">Explore nearby</button></div><div id="ps2Local" class="ps2grid"></div>
 <div class="ps2section"><h2>✦ Major releases</h2><button class="ps2secondary" type="button" data-go="social" data-news="1">All announcements</button></div><div id="ps2HomeReleases" class="ps2grid"></div>
</section>
<section id="ps2-near" class="ps2view"><div class="ps2eyebrow">GPS-enabled store discovery</div><h1>Find cards <em>near you.</em></h1><p>Browse stores inside your radius, see what evidence exists, then plan a driving route without installing an app.</p>
 <div class="ps2controls"><button class="ps2cta" id="ps2GPS" type="button">⌾ Use my GPS</button><input id="ps2Zip" type="text" inputmode="numeric" maxlength="5" placeholder="Enter US ZIP code" aria-label="ZIP code"><button class="ps2secondary" id="ps2ZipGo" type="button">Set ZIP</button><select id="ps2Radius" aria-label="Search radius"><option value="10">10 miles</option><option value="25">25 miles</option><option value="50">50 miles</option><option value="100">100 miles</option><option value="250">250 miles</option></select></div>
 <p class="ps2note" id="ps2LocateStatus">Location optional. Choose GPS or ZIP to personalize the map, store list, social reports and forecast.</p><div class="ps2map" id="ps2Map" role="region" aria-label="Nearby store map"></div>
 <div id="ps2Route" class="ps2route" hidden><div class="ps2section" style="margin:0"><h2 id="ps2RouteTitle">Driving route</h2><button class="ps2secondary" id="ps2CloseRoute" type="button">Close</button></div><p id="ps2RouteInfo">Calculating…</p><ol class="ps2steps" id="ps2Steps"></ol><div class="ps2routeactions"><button class="ps2secondary" id="ps2ReRoute" type="button">Recalculate from GPS</button><button class="ps2secondary" id="ps2LiveGPS" type="button">Follow my GPS position</button></div><p style="font-size:11px">Routing by OSRM/OpenStreetMap (ODbL). Routing demo availability is not guaranteed. Follow posted road signs and traffic laws.</p></div>
 <div class="ps2section"><h2>Nearby stores</h2><span class="ps2hint" id="ps2StoreCount">Set location to see stores</span></div><div id="ps2StoreCards" class="ps2stores"></div>
</section>
<section id="ps2-social" class="ps2view"><div class="ps2eyebrow">Media + collector updates</div><h1>The collector <em>feed.</em></h1><p>Local community activity, public social posts and major release announcements. Media plays here when the original platform permits embedding.</p>
 <div class="ps2chips" id="ps2SocialFilters"><button class="ps2chip sel" data-filter="local">📍 Local posts</button><button class="ps2chip" data-filter="national">🌎 Nationwide</button><button class="ps2chip" data-filter="releases">📣 Announcements</button></div><p class="ps2note" id="ps2SocialNote">Loading posts…</p><div id="ps2Feed" class="ps2social"></div><button class="ps2secondary" type="button" id="ps2MorePosts" hidden style="margin:20px auto;display:block">Show more posts</button>
</section>
<section id="ps2-forecast" class="ps2view"><div class="ps2eyebrow">Evidence-based local intelligence</div><h1>Restock <em>outlook.</em></h1><p>Professional store-specific charts, observed local activity, and confidence. A reported sighting is never treated as a confirmed shipment.</p>
 <div class="ps2controls"><select id="ps2ForecastStore" aria-label="Choose nearby store"><option value="">Choose a nearby store</option></select><button class="ps2secondary" id="ps2ForecastLocation" type="button">⌾ Change location</button></div><div id="ps2ForecastBody"><div class="ps2empty">Set your location in Near Me, then choose a store to inspect its evidence.</div></div>
</section></div>
<footer class="ps2footer"><span>PokéStock 2.0 · Independent collector intelligence · Sources and observation times shown</span><button id="ps2Advanced" type="button">Advanced & legacy tools</button></footer>`;
const back=document.createElement('button');back.id='ps2return';back.hidden=true;back.textContent='← Back to PokéStock 2.0';back.type='button';
document.body.append(root,back);document.body.classList.add('ps2-ready');
function setPlace(){ $('ps2Place').textContent=location?'⌾ '+location.label+' · '+radius+' mi':'⌾ Set your location';$('ps2Radius').value=String(radius);}
function view(name){
 root.querySelectorAll('.ps2view').forEach(x=>x.classList.toggle('active',x.id==='ps2-'+name));
 root.querySelectorAll('[data-ps2-tab]').forEach(x=>x.classList.toggle('active',x.dataset.ps2Tab===name));
 if(name==='near'){renderNear();setTimeout(()=>{if(map)map.invalidateSize();},200);}
 if(name==='social')renderSocial();if(name==='forecast')renderForecast();window.scrollTo({top:0,behavior:'smooth'});
}
root.querySelectorAll('[data-ps2-tab]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.ps2Tab)));
root.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>{if(b.dataset.news){postFilter='releases';setPostFilter();}view(b.dataset.go);}));
$('ps2Place').onclick=()=>view('near');$('ps2ForecastLocation').onclick=()=>view('near');
$('ps2Advanced').onclick=()=>{document.body.classList.remove('ps2-ready');root.hidden=true;back.hidden=false;window.scrollTo(0,0);};
back.onclick=()=>{root.hidden=false;document.body.classList.add('ps2-ready');back.hidden=true;window.scrollTo(0,0);};
setPlace();
function locate(point,label){location={lat:point.lat,lon:point.lon,label};try{localStorage.setItem('ps2location',JSON.stringify(location));}catch{}setPlace();renderNear();renderSocial();renderForecast();renderHome();}
function gps(){return new Promise((resolve,reject)=>{if(!navigator.geolocation)return reject(Error('Geolocation unsupported by browser'));navigator.geolocation.getCurrentPosition(x=>resolve({lat:x.coords.latitude,lon:x.coords.longitude}),reject,{enableHighAccuracy:true,timeout:18000,maximumAge:0});});}
$('ps2GPS').onclick=async()=>{ $('ps2LocateStatus').textContent='Requesting GPS permission…';try{const p=await gps();locate(p,'Your GPS location');$('ps2LocateStatus').textContent='GPS enabled. Showing candidates near your position; locations are not proof of stock.';}catch(e){$('ps2LocateStatus').textContent='GPS unavailable or denied. Enter a ZIP instead.';}};
$('ps2ZipGo').onclick=async()=>{const zip=$('ps2Zip').value.trim();if(!/^\d{5}$/.test(zip)){$('ps2LocateStatus').textContent='Enter a valid five-digit US ZIP.';return;}try{const r=await fetch('https://api.zippopotam.us/us/'+zip);if(!r.ok)throw Error();const j=await r.json();const p=j.places?.[0];if(!p)throw Error();locate({lat:Number(p.latitude),lon:Number(p.longitude)},zip+' · '+p['place name']);$('ps2LocateStatus').textContent='Location set to ZIP center (approximate), not your exact address.';}catch{$('ps2LocateStatus').textContent='ZIP lookup failed. You can try GPS or another ZIP.';}};
$('ps2Radius').onchange=e=>{radius=Number(e.target.value);try{localStorage.setItem('ps2radius',String(radius));}catch{}setPlace();renderNear();renderSocial();renderForecast();renderHome();};
function nearby(){if(!location)return[];return stores.filter(s=>coords(s)).map(s=>({...s,_miles:distance(location.lat,location.lon,Number(s.lat),Number(s.lon))})).filter(s=>s._miles<=radius).sort((a,b)=>a._miles-b._miles);}
function labelStore(s){return String(s.name||s.store_name||'Store candidate');}
function chain(s){return String(s.retailer_chain||s.chain||s.name||'Independent store');}
function storeEvidence(s){return outlook.get(String(s.id))||{};}
function ensureMap(){if(map||typeof L==='undefined')return;if(!$('ps2Map'))return;map=L.map('ps2Map',{zoomControl:true}).setView([39,-98],4);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);pins=L.layerGroup().addTo(map);}
function renderNear(){
 ensureMap();const list=nearby();$('ps2StoreCount').textContent=location?list.length+' mapped store candidates within '+radius+' miles':'Set GPS or ZIP for local results';
 if(map&&pins){pins.clearLayers();if(gpsLayer){map.removeLayer(gpsLayer);gpsLayer=null;}if(location){map.setView([location.lat,location.lon],radius<=25?10:radius<=50?9:radius<=100?8:7);gpsLayer=L.circleMarker([location.lat,location.lon],{radius:8,color:'#fff',weight:2,fillColor:'#b8a4ff',fillOpacity:1}).addTo(map).bindPopup('Your selected location');for(const s of list.slice(0,150)){const marker=L.marker([s.lat,s.lon]).addTo(pins);const pop=document.createElement('div');const title=document.createElement('strong');title.textContent=labelStore(s);pop.append(title);const info=document.createElement('p');info.textContent='Stock unknown · '+s._miles.toFixed(1)+' mi';pop.append(info);const btn=document.createElement('button');btn.textContent='Navigate here';btn.type='button';btn.style.cssText='padding:7px 10px;border:0;border-radius:7px;background:#b7a0ff;color:#201331;font-weight:bold';btn.onclick=()=>routeTo(s);pop.append(btn);marker.bindPopup(pop);marker.on('click',()=>{selected=s;});}}}
 $('ps2StoreCards').innerHTML=!location?'<div class="ps2empty">Choose GPS or a ZIP above to display nearby stores. Nothing outside your radius is substituted.</div>':list.length?list.slice(0,60).map(s=>{
 const e=storeEvidence(s),info=e.provisional_reports?.length?'Unverified branch sighting':e.city_area_reports?.length?'City-level sightings':e.research_watch?'General retailer research':'No current store evidence';
 return `<article class="ps2card"><div class="ps2storehead"><h3>${esc(labelStore(s))}</h3><span class="ps2badge ${info.includes('No current')?'warn':'purple'}">${esc(s._miles.toFixed(1))} mi</span></div><p>${esc([s.address,s.city,s.state].filter(Boolean).join(', '))}</p><p>${esc(info)} · <b>Stock unknown</b></p><div class="ps2storeactions"><button type="button" class="ps2secondary" data-store-forecast="${esc(s.id)}">Forecast</button><button type="button" class="ps2cta" data-store-route="${esc(s.id)}">⌁ Navigate</button></div></article>`;
 }).join(''):'<div class="ps2empty">No mapped candidates found within this radius. This does not mean there are no TCG retailers nearby.</div>';
}
function findStore(id){return stores.find(s=>String(s.id)===String(id));}
window.ps44RouteTo=(id)=>{const s=findStore(id);if(s)routeTo(s);};
$('ps2StoreCards').addEventListener('click',e=>{const fb=e.target.closest('[data-store-forecast]'), rb=e.target.closest('[data-store-route]');if(fb){selectedForecast=findStore(fb.dataset.storeForecast);view('forecast');}if(rb){selected=findStore(rb.dataset.storeRoute);routeTo(selected);}});
let routeBusy=false;async function routeTo(store){
 if(routeBusy||!store||!coords(store))return;routeBusy=true;selected=store;view('near');$('ps2Route').hidden=false;$('ps2RouteTitle').textContent='Route to '+labelStore(store);$('ps2RouteInfo').textContent='Getting GPS and road directions…';$('ps2Steps').replaceChildren();
 try{const here=await gps();if(!location)locate(here,'Your GPS location');if(!map)throw Error('Map unavailable');
 const endpoint='https://router.project-osrm.org/route/v1/driving/'+here.lon+','+here.lat+';'+Number(store.lon)+','+Number(store.lat)+'?overview=full&geometries=geojson&steps=true';
 const abort=new AbortController();const stop=setTimeout(()=>abort.abort(),15000);let response;try{response=await fetch(endpoint,{signal:abort.signal});}finally{clearTimeout(stop);}if(!response.ok)throw Error('Route service unavailable');const j=await response.json();const route=j.routes?.[0];if(!route?.geometry?.coordinates?.length)throw Error('No drivable route found');
 if(routeLayer){map.removeLayer(routeLayer);routeLayer=null;}routeLayer=L.geoJSON(route.geometry,{style:{color:'#80f0df',weight:6,opacity:.9}}).addTo(map);map.fitBounds(routeLayer.getBounds(),{padding:[36,36]});
 const mins=Math.round(route.duration/60),miles=(route.distance/1609.344).toFixed(1);$('ps2RouteInfo').textContent=`${miles} road miles · about ${mins} min at routing estimate · OSRM/OpenStreetMap`;const steps=[];
 for(const leg of route.legs||[])for(const s of leg.steps||[]){const maneuver=s.maneuver||{};const direction=(maneuver.modifier||'').replaceAll('_',' ');const name=s.name?' onto '+s.name:'';const phrase=maneuver.type==='arrive'?'Arrive at destination':maneuver.type==='depart'?'Depart'+name:(maneuver.type||'Continue')+' '+direction+name;steps.push(phrase.trim()+' · '+(s.distance/1609.344).toFixed(1)+' mi');}
 $('ps2Steps').innerHTML=steps.slice(0,100).map(x=>'<li>'+esc(x)+'</li>').join('')||'<li>Route calculated; no detailed maneuvers supplied.</li>';
 }catch(e){$('ps2RouteInfo').textContent='Road routing unavailable. Check GPS permission and your connection, then recalculate. No estimated travel time will be guessed.';}finally{routeBusy=false;}
}
$('ps2CloseRoute').onclick=()=>{if(routeLayer&&map){map.removeLayer(routeLayer);routeLayer=null;}$('ps2Route').hidden=true;if(navWatch!==null){navigator.geolocation.clearWatch(navWatch);navWatch=null;}};
$('ps2ReRoute').onclick=()=>routeTo(selected);
$('ps2LiveGPS').onclick=()=>{if(!navigator.geolocation){$('ps2RouteInfo').textContent='Live GPS unavailable in this browser';return;}if(navWatch!==null){navigator.geolocation.clearWatch(navWatch);navWatch=null;$('ps2LiveGPS').textContent='Follow my GPS position';return;}
 navWatch=navigator.geolocation.watchPosition(p=>{const pos=[p.coords.latitude,p.coords.longitude];if(!map)return;if(gpsLayer)map.removeLayer(gpsLayer);gpsLayer=L.circleMarker(pos,{radius:9,color:'#fff',weight:2,fillColor:'#bca6ff',fillOpacity:1}).addTo(map);},()=>{$('ps2RouteInfo').textContent+=' · GPS position update failed';},{enableHighAccuracy:true,maximumAge:5000,timeout:12000});$('ps2LiveGPS').textContent='Stop GPS tracking';};
function localSightings(){if(!location)return[];const centers=new Map();for(const s of stores){if(coords(s)&&s.city&&s.state){const k=(s.city+'|'+s.state).toLowerCase();if(!centers.has(k))centers.set(k,{lat:+s.lat,lon:+s.lon});}}return sightings.filter(s=>{const x=centers.get((String(s.city||'')+'|'+String(s.state||'')).toLowerCase());return x&&distance(location.lat,location.lon,x.lat,x.lon)<=radius;}).sort((a,b)=>String(b.reported_at_approx||'').localeCompare(String(a.reported_at_approx||'')));}
const gameOK=o=>!findGame||[o.game,o.product_name].join(' ').toLowerCase().replaceAll('é','e').includes(findGame.toLowerCase());
function productCard(o){const src=safe(o.image_candidate),url=safe(o.product_url),stamp=age(o.checked_at),fresh=Number.isFinite(stamp)&&stamp>=0&&stamp<=8,available=o.availability==='In stock',currency=o.currency==='USD'?'$':o.currency&&o.currency!=='Unverified'?o.currency+' ':'';return `<article class="ps2card"><span class="ps2badge ${fresh&&available?'':'warn'}">${esc(available?(fresh?'Available at last check':'Previously observed available'):o.availability||'Unknown')}</span><div class="ps2product" style="margin-top:12px">${src?`<img loading="lazy" src="${esc(src)}" alt="${esc(o.product_name||'TCG product')}" onerror="this.remove()">`:''}<div><h3>${esc(o.product_name)}</h3><p>${esc(o.retailer)} · ${esc(o.game||'TCG')}</p>${o.price?`<div class="ps2price">${esc(currency+o.price)}${!currency?' (currency unverified)':''}</div>`:''}</div></div><p>Checked ${esc(when(o.checked_at))} · Online listing only</p><details><summary>Evidence and optional purchase link</summary><p>Availability can change; checkout and shelf inventory not confirmed.</p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Retailer listing</a>`:''}</details></article>`;}
function releaseCard(r){const u=safe(r.source_url||r.url);return `<article class="ps2card"><span class="ps2badge">${esc(r.official?'Official date':'News / unverified')}</span><h3>${esc(r.name||r.title)}</h3><p>${esc(r.game||'TCG')} · ${esc(r.date?day(r.date):r.published_at?day(r.published_at):'Date unknown')}</p><p>No store stock is implied.</p>${u?`<details><summary>Original announcement</summary><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">View source</a></details>`:''}</article>`;}
function renderHome(){const q=$('ps2Search').value.trim().toLowerCase();const filtered=offers.filter(o=>o.inventory_scope==='online'&&o.availability==='In stock'&&gameOK(o)&&(!q||[o.product_name,o.retailer,o.game,o.variant].join(' ').toLowerCase().includes(q)));filtered.sort((a,b)=>{const af=age(a.checked_at)<=8?1:0,bf=age(b.checked_at)<=8?1:0;return bf-af||Date.parse(b.checked_at)-Date.parse(a.checked_at);});$('ps2OnlineHint').textContent=filtered.length+' last-observed available listings · only checks within 8 hours labeled recent';$('ps2Products').innerHTML=filtered.slice(0,q?24:8).map(productCard).join('')||'<div class="ps2empty">No available merchant listings match this search. This is not proof of a retailer sellout.</div>';
 const local=localSightings();$('ps2Local').innerHTML=!location?'<div class="ps2empty">Set GPS or ZIP to see reports near you. We will not substitute another city.</div>':local.length?local.slice(0,4).map(s=>`<article class="ps2card"><span class="ps2badge warn">Unverified community sighting</span><h3>${esc(s.product_name||'Trading cards')}</h3><p>${esc(s.retailer)} · ${esc(s.city)}, ${esc(s.state)} · ${esc(when(s.reported_at_approx))}</p><p>City-level report, not verified shelf stock.</p></article>`).join(''):'<div class="ps2empty">No nearby community reports currently in the connected feed. Local store monitoring remains available in Near Me.</div>';
 $('ps2HomeReleases').innerHTML=releases.slice(0,4).map(releaseCard).join('')||'<div class="ps2empty">Official release calendar not available yet.</div>';}
$('ps2Search').addEventListener('input',renderHome);$('ps2Find').onclick=renderHome;$('ps2Search').addEventListener('keydown',e=>{if(e.key==='Enter')renderHome();});$('ps2Games').addEventListener('click',e=>{const b=e.target.closest('[data-game]');if(!b)return;findGame=b.dataset.game;$('ps2Games').querySelectorAll('[data-game]').forEach(x=>x.classList.toggle('sel',x===b));renderHome();});
function mediaURL(post){const u=safe(post.original_post_url||post.url);if(!u)return null;try{const x=new URL(u),host=x.hostname.replace(/^www\./,'');let m;if(host==='youtube.com'||host==='m.youtube.com'){m=x.searchParams.get('v')||x.pathname.match(/^\/shorts\/([a-zA-Z0-9_-]{11})/)?.[1];if(m&&/^[a-zA-Z0-9_-]{11}$/.test(m))return {src:'https://www.youtube-nocookie.com/embed/'+m,type:'YouTube'};}
 if(host==='youtu.be'){m=x.pathname.match(/^\/([a-zA-Z0-9_-]{11})/)?.[1];if(m)return {src:'https://www.youtube-nocookie.com/embed/'+m,type:'YouTube'};}
 if(host==='tiktok.com'||host==='m.tiktok.com'){m=x.pathname.match(/\/video\/(\d{12,22})/);if(m)return {src:'https://www.tiktok.com/embed/v2/'+m[1],type:'TikTok'};}
 if(host==='instagram.com'){m=x.pathname.match(/^\/(p|reel)\/([\w-]+)/);if(m)return {src:'https://www.instagram.com/'+m[1]+'/'+m[2]+'/embed',type:'Instagram'};}
 if(host==='facebook.com'||host==='m.facebook.com'){if(/\/(posts|videos|reel)\//.test(x.pathname))return{src:'https://www.facebook.com/plugins/post.php?href='+encodeURIComponent(u)+'&show_text=true&width=500',type:'Facebook'};}
 if(host==='reddit.com'&&/^\/r\/[^/]+\/comments\//.test(x.pathname))return {src:'https://www.redditmedia.com'+x.pathname+'?embed=true&showmedia=true',type:'Reddit'};
 }catch{}return null;}
function socialCard(p){const url=safe(p.original_post_url||p.url),media=mediaURL(p);const loc=p.location?.city?`${p.location.city}, ${p.location.state||''}`:'Location not verified';const desc=String(p.description||'').slice(0,350);return `<article class="ps2post"><div class="ps2postbody"><span class="ps2badge purple">${esc(p.platform||'Public source')}</span><h3>${esc(p.title||'TCG collector post')}</h3><p>${esc(loc)} · ${esc(when(p.published_at))}</p></div>${media?`<div class="ps2embedbox"><button type="button" data-embed="${esc(media.src)}">▶ Play ${esc(media.type)} here</button><span class="ps2poster">Original public media · platform controls apply</span></div>`:''}<div class="ps2postbody"><p>${esc(desc)}${String(p.description||'').length>350?'…':''}</p><p>Public post, not independently verified inventory.</p>${url?`<details><summary>Source and attribution</summary><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Original post</a></details>`:''}</div></article>`;}
function setPostFilter(){$('ps2SocialFilters').querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('sel',x.dataset.filter===postFilter));}
$('ps2SocialFilters').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;postFilter=b.dataset.filter;postsLimit=18;setPostFilter();renderSocial();});
function renderSocial(){let list=[];const loc=location;if(postFilter==='releases'){$('ps2SocialNote').textContent='Official releases and separately labeled news leads; nationwide announcements are relevant to all users.';$('ps2Feed').innerHTML=releases.map(releaseCard).join('')+news.slice(0,30).map(releaseCard).join('')||'<div class="ps2empty">No announcements currently available.</div>';$('ps2MorePosts').hidden=true;return;}
 if(postFilter==='local'){if(!loc){$('ps2SocialNote').textContent='Set your location to display relevant local public posts.';$('ps2Feed').innerHTML='<div class="ps2empty">Local posts only: set your GPS or ZIP in Near Me to continue. National content is under the Nationwide filter.</div>';$('ps2MorePosts').hidden=true;return;}
 list=social.filter(x=>coords(x.location)&&distance(loc.lat,loc.lon,+x.location.lat,+(x.location.lon??x.location.long))<=radius);$('ps2SocialNote').textContent=list.length+' source-located posts within ~'+radius+' miles. Reported locations are often approximate city centers, not exact store locations.';}else{list=social;$('ps2SocialNote').textContent=list.length+' national and regional public collector posts. Stock claims are not verified.';}
 list.sort((a,b)=>Date.parse(b.published_at||0)-Date.parse(a.published_at||0));$('ps2Feed').innerHTML=list.slice(0,postsLimit).map(socialCard).join('')||'<div class="ps2empty">No posts with supported local location evidence inside your radius. Try a wider radius or Nationwide. We will not label unrelated posts as local.</div>';$('ps2MorePosts').hidden=list.length<=postsLimit;
}
$('ps2MorePosts').onclick=()=>{postsLimit+=18;renderSocial();};
$('ps2Feed').addEventListener('click',e=>{const b=e.target.closest('[data-embed]');if(!b)return;const src=safe(b.dataset.embed);if(!src)return;const box=b.closest('.ps2embedbox');if(!box)return;const iframe=document.createElement('iframe');iframe.src=src;iframe.title='Original social media embed';iframe.loading='lazy';iframe.referrerPolicy='strict-origin-when-cross-origin';iframe.allow='autoplay; encrypted-media; picture-in-picture; fullscreen';iframe.setAttribute('allowfullscreen','');box.replaceChildren(iframe);});
function matchingArea(store){const c=chain(store).toLowerCase();const city=String(store.city||'').toLowerCase(),state=String(store.state||'').toLowerCase();if(!city||!state)return[];const simple=x=>String(x||'').toLowerCase().replace(/[^a-z0-9]/g,'');return sightings.filter(x=>simple(x.city)===simple(city)&&simple(x.state)===simple(state)&&simple(x.retailer)===simple(c));}
/* Script 43: honest, location-aware forecast. */
/* Script 43: honest, location-aware forecast. */
/* Script 43: honest, location-aware forecast. */
/* Script 43: honest, location-aware forecast. */
/* Script 43: honest, location-aware forecast. */
function renderForecast(){
 const select=$('ps2ForecastStore');
 const candidates=nearby().filter(s=>String(s.city||s.address||'').trim());
 const used=new Set();
 const list=candidates.filter(s=>{
   const k=[
     String(s.name||'').toLowerCase(),
     String(s.address||'').toLowerCase(),
     Number(s.lat).toFixed(4),
     Number(s.lon??s.long).toFixed(4)
   ].join('|');
   if(used.has(k))return false;
   used.add(k);
   return true;
 });

 const prev=selectedForecast?.id||select.value;
 const shown=list.slice(0,250);

 if(prev&&!shown.some(s=>String(s.id)===String(prev))){
   const x=list.find(s=>String(s.id)===String(prev));
   if(x)shown.unshift(x);
 }

 select.replaceChildren(
   new Option('Select a nearby branch',''),
   ...shown.map(s=>new Option(
     [
       labelStore(s),
       s.address||s.city||'Nearby location',
       s._miles.toFixed(1)+' mi'
     ].filter(Boolean).join(' · '),
     String(s.id)
   ))
 );

 const wanted=shown.find(
   s=>String(s.id)===String(prev)
 )||shown[0];

 if(wanted)select.value=String(wanted.id);
 selectedForecast=wanted||null;

 const output=$('ps2ForecastBody');

 if(!wanted){
   output.innerHTML='<div class="ps2empty">Use GPS or enter a ZIP in Near Me to see identifiable stores and their local evidence. No nationwide store is substituted.</div>';
   return;
 }

 const store=wanted;
 const evidence=storeEvidence(store);
 const id=String(store.id);
 const normal=s=>String(s||'').toLowerCase().replace(/[^a-z0-9]/g,'');
 const retailer=normal(chain(store));
 const cutoff=Date.now()-45*86400000;

 const geo=forecast43Records.filter(x=>
   Number.isFinite(+x.lat)&&
   Number.isFinite(+x.lon)&&
   Number.isFinite(Date.parse(x.reported_at))&&
   Date.parse(x.reported_at)>=cutoff&&
   distance(
     location.lat,location.lon,
     +x.lat,+x.lon
   )<=radius
 ).sort(
   (a,b)=>Date.parse(b.reported_at)-Date.parse(a.reported_at)
 );

 const exact=[],city=[],area=[],posts=[];

 for(const x of geo){
   if(x.kind==='social_research_lead'){
     posts.push(x);
     continue;
   }
   if(String(x.store_id)===id&&x.store_match_verified===true){
     exact.push(x);
     continue;
   }
   if(
     retailer===normal(x.retailer)&&
     normal(store.city)&&
     normal(store.city)===normal(x.city)&&
     normal(store.state)===normal(x.state)
   ){
     city.push(x);
     continue;
   }
   area.push(x);
 }

 const bins=Array.from(
   {length:7},
   (_,i)=>({
     day:['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i],
     exact:0,city:0,area:0,social:0
   })
 );

 for(const [bucket,records] of [
   ['exact',exact],
   ['city',city],
   ['area',area],
   ['social',posts]
 ]){
   for(const event of records){
     const d=new Date(event.reported_at);
     const index=(d.getDay()+6)%7;
     bins[index][bucket]++;
   }
 }

 const peak=Math.max(
   5,
   ...bins.map(x=>x.exact+x.city+x.area+x.social)
 );

 const any=geo.length>0;

 const chart=any?`
   <div class="ps43chart">
     <div class="ps43chartgrid">
       ${bins.map(x=>{
         const num=x.exact+x.city+x.area+x.social;
         return `
         <div class="ps43day">
           <span class="ps43num">${num||'·'}</span>
           <div class="ps43track" title="${esc(x.day)}: ${num} public research signals">
             <div class="ps43fill social" style="height:${Math.round(x.social/peak*132)}px"></div>
             <div class="ps43fill area" style="height:${Math.round(x.area/peak*132)}px"></div>
             <div class="ps43fill city" style="height:${Math.round(x.city/peak*132)}px"></div>
             <div class="ps43fill exact" style="height:${Math.round(x.exact/peak*132)}px"></div>
           </div>
           <span>${x.day}</span>
         </div>`;
       }).join('')}
     </div>
     <p class="ps43small">Counts of collected public reports by weekday, not delivery probabilities. Location and time are approximate for many sources.</p>
   </div>`:
   '<div class="ps43none"><strong>No nearby dated reports in the connected feeds.</strong><p>We cannot infer a restock day from missing observations. Try a larger radius or another branch; future source reports will appear when collected.</p></div>';

 const link=x=>{
   const u=safe(x.source_url);
   return u?`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">View original evidence</a>`:'';
 };

 const recent=geo.slice(0,12).map(x=>`
   <article class="ps43event">
     <div>
       <b>${esc(x.title||'Public collector report')}</b>
       <p>
         ${esc(x.city||'Area')}
         ${x.state?', '+esc(x.state):''}
         · ${esc(when(x.reported_at))}
         · ${esc(
           x.kind==='social_research_lead'?
           'Geotagged social lead':
           exact.includes(x)?
           'Branch-matched report':
           city.includes(x)?
           'Retailer/city report':
           'Nearby community sighting'
         )}
       </p>
     </div>
     <div>${link(x)}</div>
   </article>
 `).join('');

 const research=evidence.research_watch?`
   <div class="ps43research">
     <strong>Retailer-wide research exists</strong>
     <p>${esc(evidence.research_basis||'General vendor or retailer guidance')}</p>
     <p>It does not establish a shipment date for this particular branch.</p>
     ${evidence.research_source&&safe(evidence.research_source)?
       `<a href="${esc(safe(evidence.research_source))}" target="_blank" rel="noopener noreferrer">Research source</a>`:''}
   </div>`:'';

 const upcoming=releases.filter(r=>{
   const time=Date.parse(r.date);
   return Number.isFinite(time)&&
     time>=Date.now()-86400000&&
     time<=Date.now()+30*86400000;
 }).slice(0,4);

 const releaseItems=upcoming.map(r=>`
   <div class="ps43event">
     <div>
       <b>${esc(r.name||'TCG release')}</b>
       <p>Official release ${esc(day(r.date))}; not branch inventory</p>
     </div>
     ${safe(r.source_url)?
       `<a href="${esc(safe(r.source_url))}" target="_blank" rel="noopener noreferrer">Official source</a>`:''}
   </div>
 `).join('');

 output.innerHTML=`
   <div class="ps2card ps43branch">
     <span class="ps2badge purple">${esc(chain(store))}</span>
     <h2>${esc(labelStore(store))}</h2>
     <p>${esc([store.address,store.city,store.state].filter(Boolean).join(', '))} · ${store._miles.toFixed(1)} miles from your selected location</p>
     <p><strong>In-store stock: Unknown.</strong> We have no verified live shelf quantities here.</p>
   </div>

   <div class="ps43stats">
     <div class="ps43stat">
       <strong>${exact.length}</strong>
       <span>Verified branch-matched reports</span>
     </div>
     <div class="ps43stat">
       <strong>${city.length}</strong>
       <span>Same retailer &amp; city reports</span>
     </div>
     <div class="ps43stat">
       <strong>${area.length+posts.length}</strong>
       <span>Other nearby research signals</span>
     </div>
   </div>

   <div class="ps2card ps43panel">
     <div class="ps43heading">
       <h2>Nearby activity by weekday</h2>
       <span class="ps2badge ${any?'warn':'purple'}">
         ${any?geo.length+' reports · 45 days':'Not enough local evidence'}
       </span>
     </div>
     <p>Only sources inside your ${radius}-mile radius. Same-city and nearby activity are not proof for ${esc(labelStore(store))}.</p>
     ${chart}
     <div class="ps43legend">
       <span><i class="exact"></i>Verified branch match</span>
       <span><i class="city"></i>Same retailer/city</span>
       <span><i class="area"></i>Other local sightings</span>
       <span><i class="social"></i>Social research</span>
     </div>
   </div>

   <div class="ps43research">
     <strong>${evidence.watch_weekday?
       'Limited historical weekday pattern: '+esc(evidence.watch_weekday):
       'Store-level forecast: insufficient history'}</strong>
     <p>${evidence.watch_weekday?
       'Repeated exact-store reports support a limited watch pattern, not guaranteed delivery.':
       'No defensible next delivery date exists for this branch. A retailer-wide schedule or another store’s report cannot be treated as confirmation.'}</p>
     <p>Verified historical report dates in store database: ${Number(evidence.verified_store_sightings)||0}. Current inventory: unknown.</p>
   </div>

   ${research}

   <div class="ps2card ps43panel">
     <h2>Evidence timeline</h2>
     <p>Latest available local source reports. Each is labeled as unverified research unless independently confirmed.</p>
     ${recent||'<div class="ps43none">No geographically supported public reports within this radius yet.</div>'}
   </div>

   ${releaseItems?`
     <div class="ps2card ps43panel">
       <h2>Upcoming official releases</h2>
       <p>National launch information for planning, not proof of local shipments.</p>
       ${releaseItems}
     </div>`:''}
 `;
}
$('ps2ForecastStore').onchange=e=>{selectedForecast=findStore(e.target.value);renderForecast();};
(async()=>{
 try{const [a,b,c,d,f,g,h]=await Promise.all([
 get('data/stores.json',[]),get('data/unified_online_39.json',[]),get('data/social_media_feed.json',{}),get('data/v34_public_sightings.json',[]),get('data/store_outlook_40.json',{}),get('data/v30_release_watch.json',[]),get('data/upcoming_drops_28.json',{})]);
 stores=Array.isArray(a)?a.filter(coords):[];offers=Array.isArray(b)?b:[];social=Array.isArray(c.posts)?c.posts:[];sightings=Array.isArray(d)?d:[];outlook=new Map(Array.isArray(f.stores)?f.stores.map(x=>[String(x.store_id),x]):[]);
 releases=(Array.isArray(g)?g:[]).filter(x=>x.status==='Official release date'&&/^\d{4}-\d{2}-\d{2}$/.test(x.date||'')).map(x=>({...x,official:true})).filter(x=>new Date(x.date+'T23:59:59Z').getTime()>=Date.now()-86400000).sort((a,b)=>a.date.localeCompare(b.date));
 news=(Array.isArray(h.announcements)?h.announcements:[]).filter(x=>x.source_type==='news_index').map(x=>({...x,name:x.title,official:false,date:x.release_date||null,source_url:x.url})).slice(0,25);
 renderHome();renderNear();renderSocial();renderForecast();get('data/forecast_activity_43.json',{}).then(v=>{forecast43Records=Array.isArray(v.events)?v.events:[];renderForecast();});get('data/forecast_activity_43.json',{}).then(v=>{forecast43Records=Array.isArray(v.events)?v.events:[];renderForecast();});get('data/forecast_activity_43.json',{}).then(v=>{forecast43Records=Array.isArray(v.events)?v.events:[];renderForecast();});get('data/forecast_activity_43.json',{}).then(v=>{forecast43Records=Array.isArray(v.events)?v.events:[];renderForecast();});get('data/forecast_activity_43.json',{}).then(v=>{forecast43Records=Array.isArray(v.events)?v.events:[];renderForecast();});
 }catch(e){console.error('Pokestock 2.0 load:',e);$('ps2Products').innerHTML='<div class="ps2empty">Inventory currently unavailable. Existing tools are still available under Advanced & legacy tools.</div>';}
})();
})();
