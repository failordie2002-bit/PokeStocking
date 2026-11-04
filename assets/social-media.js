(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  if(!$('social'))return;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=v=>String(v??'').trim().toLowerCase();
  const safe=v=>{try{const u=new URL(v);return u.protocol==='https:'?u.href:''}catch{return ''}};
  let posts=[],origin=null,visible=24;
  const miles=(a,b)=>{const r=Math.PI/180,lat=(b[0]-a[0])*r,lon=(b[1]-a[1])*r,h=Math.sin(lat/2)**2+Math.cos(a[0]*r)*Math.cos(b[0]*r)*Math.sin(lon/2)**2;return 7917.6*Math.asin(Math.min(1,Math.sqrt(h)))};
  const when=v=>{if(!v)return 'Date unknown';const d=new Date(v);return Number.isNaN(d.getTime())?'Date unknown':d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})};
  function embed(p){
    const url=safe(p.url);if(!url)return '';
    try{const u=new URL(url);if((u.hostname==='reddit.com'||u.hostname.endsWith('.reddit.com'))&&u.pathname.includes('/comments/')){
      const src='https://www.redditmedia.com'+u.pathname.replace(/\/$/,'')+'?ref_source=embed&ref=share';
      return `<details><summary>View embedded Reddit post</summary><iframe class="sm-embed" loading="lazy" title="Reddit post" sandbox="allow-scripts allow-same-origin allow-popups" src="${esc(src)}"></iframe></details>`;
    }}catch{}
    return '';
  }
  function card(p,d){
    const loc=p.location,place=loc?`${loc.city}, ${loc.state}`:'Location not established',url=safe(p.url),desc=String(p.description||'').slice(0,480),kind=p.report_type==='retail_sighting_lead'?'Possible retail sighting':'General discussion / promotion';
    return `<article class="sm-card"><span class="sm-tag">${esc(p.platform||'Public web')}</span><span class="sm-tag">${esc(p.game||'TCG')}</span><span class="sm-tag">${esc(kind)}</span><h3>${esc(p.title)}</h3><p>${esc(when(p.published_at))} · ${esc(place)}</p>${d!==null?`<p>Approx. ${d.toFixed(1)} miles (city-center distance)</p>`:''}${desc?`<p>${esc(desc)}</p>`:''}<p><strong>Unverified public lead — not confirmed store stock.</strong></p>${url?`<a class="action" href="${esc(url)}" target="_blank" rel="noopener noreferrer">View original post</a>`:''}${embed(p)}</article>`;
  }
  function render(){
    const radius=+$('smRadius').value,retailer=norm($('smRetailer').value),game=norm($('smGame').value),sort=$('smSort').value;
    const local=[],other=[];
    for(const p of posts){
      if(retailer&&!(p.retailer_mentions||[]).some(x=>norm(x)===retailer))continue;
      if(game&&norm(p.game)!==game)continue;
      const l=p.location,coords=l&&Number.isFinite(+l.lat)&&Number.isFinite(+l.lon)?[+l.lat,+l.lon]:null,d=coords&&origin?miles(origin,coords):null;
      if(p.report_type==='retail_sighting_lead'&&coords&&(radius===0||(origin&&d<=radius)))local.push({p,d});
      else if(!coords||p.report_type!=='retail_sighting_lead')other.push({p,d:null});
    }
    const recent=(a,b)=>String(b.p.published_at||b.p.first_seen_at||'').localeCompare(String(a.p.published_at||a.p.first_seen_at||''));
    local.sort((a,b)=>sort==='nearest'&&origin?(a.d??Infinity)-(b.d??Infinity):recent(a,b));other.sort(recent);
    $('smLocal').innerHTML=local.slice(0,visible).map(x=>card(x.p,x.d)).join('')||'<p class="muted">No geographically matched retail restock leads found for this radius.</p>';
    $('smOther').innerHTML=other.slice(0,visible).map(x=>card(x.p,null)).join('')||'<p class="muted">No other public posts match these filters.</p>';
    $('smMore').hidden=local.length<=visible&&other.length<=visible;
    $('smStatus').textContent=`${local.length} local retail leads; ${other.length} other public posts. `+(radius&&!origin?'Use GPS or ZIP to filter nearby reports.':'All reports are unverified.');
  }
  $('smGPS').onclick=()=>{if(!navigator.geolocation){$('smStatus').textContent='GPS unavailable; use ZIP.';return}navigator.geolocation.getCurrentPosition(p=>{origin=[p.coords.latitude,p.coords.longitude];visible=24;render()},e=>{$('smStatus').textContent='GPS unavailable: '+e.message},{timeout:15000})};
  $('smZIPGo').onclick=async()=>{const z=$('smZIP').value.trim();if(!/^\d{5}$/.test(z)){$('smStatus').textContent='Enter a five-digit ZIP.';return}try{const r=await fetch('https://api.zippopotam.us/us/'+z);if(!r.ok)throw Error('ZIP not found');const p=(await r.json()).places[0];origin=[+p.latitude,+p.longitude];visible=24;render()}catch(e){$('smStatus').textContent=e.message}};
  $('smZIP').onkeydown=e=>{if(e.key==='Enter')$('smZIPGo').click()};
  ['smRadius','smRetailer','smGame','smSort'].forEach(id=>$(id).onchange=()=>{visible=24;render()});
  $('smMore').onclick=()=>{visible+=24;render()};
  fetch('data/social_media_feed.json?t='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Feed unavailable');return r.json()}).then(d=>{posts=Array.isArray(d.posts)?d.posts:[];render()}).catch(e=>{$('smStatus').textContent='Could not load social posts: '+e.message});
})();
