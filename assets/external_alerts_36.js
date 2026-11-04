(()=>{
  'use strict';
  const online=document.getElementById('online');
  if(!online || document.getElementById('ps36'))return;
  const root=document.createElement('section');
  root.id='ps36';root.className='panel';
  root.style.cssText='margin:8px 0 22px;padding:16px;border-color:#5479aa';
  root.innerHTML=`<div class="section-label">External restock intelligence</div>
    <h2>Major Retailer Alert Radar</h2>
    <p class="muted">Direct live alert sources plus publicly reported restocks. These are <b>leads, NOT verified current stock</b>; source website history can be delayed 30+ minutes. Not store-level shelf inventory.</p>
    <div id="ps36links" class="controls"></div>
    <div class="controls"><input id="ps36search" aria-label="Search reported products" placeholder="Search Pokémon sets, retailer, products"><select id="ps36retailer"><option value="">All retailers</option></select><select id="ps36age"><option value="2">Last 48 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">History: 90 days</option></select></div>
    <p id="ps36info" class="muted">Loading external alert sources…</p>
    <div id="ps36grid" class="grid"></div>`;
  online.insertBefore(root,online.firstChild);
  const $=id=>root.querySelector('#'+id);
  const esc=t=>String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const valid=u=>{try{let a=new URL(u);return a.protocol==='https:'?a.href:null;}catch{return null;}};
  let alerts=[];let report={};
  const fallbacks=[
    ['Live Pokémon alerts','https://live.pkmnalerts.com/'],
    ['Best Buy alert history','https://pokerestockapp.com/restocks/best-buy/'],
    ['All retailer history','https://pokerestockapp.com/restocks/'],
    ['Free Discord alerts','https://pikanotify.com/']
  ];
  async function get(p){try{let r=await fetch(p+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return await r.json();}catch(e){console.warn(p,e);return null;}}
  function render(){
    const q=$('ps36search').value.toLowerCase().trim();
    const retailer=$('ps36retailer').value;
    const days=Number($('ps36age').value);
    const limit=Date.now()-days*86400000;
    const rows=alerts.filter(x=>{
      const t=Date.parse(x.reported_at||'');
      return Number.isFinite(t)&&t>=limit&&t<=Date.now()+300000&&
        (!q||[x.product_name,x.retailer].join(' ').toLowerCase().includes(q))&&
        (!retailer||retailer===x.retailer)&&x.stock_verified_now===false;
    }).slice(0,100);
    const failed=(report.sources||[]).filter(x=>x.status!=='parsed').length;
    $('ps36info').textContent=rows.length+' matching historical reports (showing up to 100). '+
      'Last collected '+(report.updated_at?new Date(report.updated_at).toLocaleString():'unknown')+'. '+
      (failed?failed+' sources unavailable or empty. ':'')+'Open retailer to check current stock.';
    $('ps36grid').innerHTML=rows.map(x=>{
      const at=valid(x.retailer_url),source=valid(x.source_url);
      return `<article class="tile"><span class="pill unknown">Reported restock — not verified now</span>
        <h3>${esc(x.product_name)}</h3><p>${esc(x.retailer)}</p><p class="muted">Reported: ${esc(new Date(x.reported_at).toLocaleString())}</p>
        ${x.price_reported?`<p>Reported price: $${esc(x.price_reported)}</p>`:''}
        ${at?`<a class="action" target="_blank" rel="noopener noreferrer" href="${esc(at)}">Check retailer</a>`:''}
        ${source?`<a class="action" target="_blank" rel="noopener noreferrer" href="${esc(source)}">Original alert source</a>`:''}
      </article>`;
    }).join('')||'<div class="empty">No matching dated alerts. This does not mean retailers are sold out. Use the live source links above.</div>';
  }
  async function load(){
    const [a,r]=await Promise.all([get('data/external_alerts_36.json'),get('data/external_alert_report_36.json')]);
    alerts=Array.isArray(a)?a:[];report=r&&typeof r==='object'?r:{};
    const links=(report.live_external_links||[]).map(x=>[x.name,x.url]);
    $('ps36links').innerHTML=(links.length?links:fallbacks).map(x=>valid(x[1])?`<a class="action" target="_blank" rel="noopener noreferrer" href="${esc(x[1])}">${esc(x[0])}</a>`:'').join('');
    const sel=$('ps36retailer');
    for(const v of [...new Set(alerts.map(x=>x.retailer).filter(Boolean))].sort()){
      const o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);
    }
    render();
  }
  ['ps36search','ps36retailer','ps36age'].forEach(id=>$(id).addEventListener('input',render));
  load();
})();
