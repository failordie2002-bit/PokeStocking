(() => {
  const root = document.createElement('section'); root.id='ps46';
  root.style.cssText='max-width:1100px;margin:22px auto;padding:20px;border:1px solid #44546e;border-radius:16px;background:#152137;color:#fff';
  root.innerHTML='<h2 style="margin-top:0">Restock intelligence</h2><p>Public TCG restock reports and low-confidence rumors. <b>No verified shelf inventory.</b></p><div id="ps46filters" style="display:flex;flex-wrap:wrap;gap:8px"><select id="ps46game"><option value="">All TCGs</option></select><select id="ps46store"><option value="">All retailers</option></select><input id="ps46query" placeholder="Search city, product, store" aria-label="Search public reports" style="min-width:180px;flex:1"></div><h3>Rumor-based forecast</h3><div id="ps46forecast"></div><h3>Recent public mentions</h3><div id="ps46items">Loading source reports…</div><small id="ps46updated"></small>';
  document.body.appendChild(root);
  const get=id=>root.querySelector('#'+id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const css='padding:12px;margin:8px 0;border-radius:9px;border:1px solid #3d5270;background:#1c2b43';
  Promise.all(['data/rumor_signals_46.json','data/rumor_forecast_46.json'].map(url=>fetch(url+'?t='+Date.now()).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}))).then(([data,forecast])=>{
    const rows=Array.isArray(data.signals)?data.signals:[], leads=Array.isArray(forecast.leads)?forecast.leads:[];
    const games=new Set([...rows,...leads].map(x=>x.game).filter(Boolean));
    const stores=new Set([...rows,...leads].map(x=>x.retailer).filter(Boolean));
    for(const x of [...games].sort())get('ps46game').add(new Option(x,x));
    for(const x of [...stores].sort())get('ps46store').add(new Option(x,x));
    const draw=()=>{
      const g=get('ps46game').value, s=get('ps46store').value, q=get('ps46query').value.toLowerCase();
      const match=x=>(!g||x.game===g)&&(!s||x.retailer===s)&&(!q||[x.title,x.retailer,x.location,x.game,x.window].join(' ').toLowerCase().includes(q));
      const rs=rows.filter(match).slice(0,50), ls=leads.filter(match);
      get('ps46forecast').innerHTML=ls.map(x=>'<div style="'+css+'"><b>'+esc(x.retailer)+' · '+esc(x.location)+'</b><p>'+esc(x.game)+' — '+esc(x.window)+'</p><small>UNVERIFIED · '+esc(x.confidence)+' confidence · '+esc(x.reason)+'</small></div>').join('') || '<p>No matching rumor forecast.</p>';
      get('ps46items').innerHTML=rs.map(x=>{let link='';try{let u=new URL(x.url);if(u.protocol==='https:')link='<a href="'+esc(u.href)+'" target="_blank" rel="noopener noreferrer">Source</a>'}catch(e){}return '<article style="'+css+'"><b>'+esc(x.title)+'</b><p>'+esc(x.game)+' · '+esc(x.retailer)+' · '+esc(x.location)+'</p><small>UNVERIFIED public mention · '+esc(x.published_utc?.slice(0,10))+' · '+esc(x.source)+'</small> '+link+'</article>'}).join('') || '<p>No matching public reports. This does not imply out-of-stock.</p>';
    };
    ['ps46game','ps46store','ps46query'].forEach(id=>get(id).addEventListener('input',draw));
    get('ps46updated').textContent='Last checked: '+new Date(data.generated_utc).toLocaleString()+' · Partial public RSS coverage; not real-time store inventory.';
    draw();
  }).catch(e=>{get('ps46items').textContent='Research data not published yet ('+e.message+'). Existing PokéStock data is unaffected.';get('ps46forecast').textContent='Forecast unavailable.';});
})();
