(() => {
  // Script 46 may be re-injected; keep only one visible panel.
  const style=document.createElement('style');
  style.textContent='#ps46{display:none!important}#ps48{max-width:1120px;margin:24px auto;padding:20px;color:#f5f8ff;background:#151d30;border:1px solid #384967;border-radius:18px;font-family:inherit}#ps48 *{box-sizing:border-box}#ps48 .filters{display:flex;gap:9px;flex-wrap:wrap;margin:14px 0}#ps48 select,#ps48 input{background:#222d46;color:#fff;border:1px solid #465977;border-radius:10px;padding:10px;flex:1;min-width:135px}#ps48 .item{border:1px solid #405270;background:#1d2940;border-radius:11px;padding:13px;margin:9px 0}#ps48 .muted{color:#b3c0d6;font-size:13px}#ps48 .tag{color:#ffd87d;font-size:12px;font-weight:800}#ps48 h2{margin:0;font-size:1.5rem}#ps48 h3{margin:18px 0 8px;font-size:1.08rem}#ps48 a{color:#9ad0ff}#ps48 .stat{display:inline-block;margin:4px 14px 6px 0}';
  document.head.appendChild(style);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const section=document.createElement('section'); section.id='ps48';
  section.innerHTML='<h2>Restock intelligence</h2><p class="muted">Recent public TCG reports, launches, and local rumors. None are confirmed shelf inventory.</p><div id="ps48stats"></div><div class="filters"><select id="ps48kind"><option value="">All report types</option><option value="Retailer stock mention">Retailer stock mentions</option><option value="Reported local sighting">Reported local sightings</option><option value="Release / shopping news">Releases & shopping news</option></select><select id="ps48game"><option value="">All TCGs</option></select><select id="ps48store"><option value="">All retailers</option></select><input id="ps48search" aria-label="Search restock intelligence" placeholder="Search city, product, or report"></div><h3>Low-confidence store forecasts</h3><div id="ps48tips"></div><h3>Public reports</h3><div id="ps48results">Loading reports…</div><p class="muted" id="ps48footer"></p>';
  document.body.appendChild(section);
  const $=id=>section.querySelector('#'+id);
  fetch('data/restock_intelligence_48.json?t='+Date.now()).then(r=>{if(!r.ok)throw Error('Research data not yet published');return r.json()}).then(data=>{
    const reports=Array.isArray(data.signals)?data.signals:[];
    const tips=Array.isArray(data.forecasts)?data.forecasts:[];
    const summary=data.summary||{};
    $('ps48stats').innerHTML='<span class="stat"><b>'+esc(summary.fresh_reports||0)+'</b> reports ≤7 days</span><span class="stat"><b>'+esc(summary.fresh_named_retailer||0)+'</b> recent retailer mentions</span><span class="stat"><b>'+esc(summary.local_explicit_reports||0)+'</b> locality-specific reports</span>';
    const games=[...new Set([...reports,...tips].map(x=>x.game).filter(Boolean))].sort();
    const stores=[...new Set([...reports,...tips].map(x=>x.retailer).filter(Boolean))].sort();
    for(const x of games)$('ps48game').add(new Option(x,x));
    for(const x of stores)$('ps48store').add(new Option(x,x));
    function draw(){
      const kind=$('ps48kind').value,game=$('ps48game').value,store=$('ps48store').value,q=$('ps48search').value.toLowerCase().trim();
      const match=x=>(!game||x.game===game)&&(!store||x.retailer===store)&&(!q||[x.title,x.game,x.retailer,x.location,x.window].join(' ').toLowerCase().includes(q));
      const rows=reports.filter(x=>(!kind||x.kind===kind)&&match(x)).slice(0,60);
      $('ps48results').innerHTML=rows.map(x=>{
        let link='';try{let u=new URL(x.url);if(u.protocol==='https:')link='<a href="'+esc(u.href)+'" rel="noopener noreferrer" target="_blank">Original source</a>'}catch(e){}
        return '<article class="item"><div class="tag">'+esc(x.kind)+' · UNVERIFIED'+(x.fresh?' · Recent':' · Historical')+'</div><b>'+esc(x.title)+'</b><div class="muted">'+esc(x.game)+' · '+esc(x.retailer)+' · '+esc(x.location)+' · '+esc((x.published_utc||'').slice(0,10))+'</div><p class="muted">Lead strength '+esc(x.lead_strength)+'/100 (prioritization only, NOT inventory probability)</p>'+link+'</article>';
      }).join('')||'<p class="muted">No matching public reports. That does not mean stores are out of stock.</p>';
      const matching=tips.filter(match);
      $('ps48tips').innerHTML=matching.map(x=>'<article class="item"><div class="tag">UNVERIFIED · LOW CONFIDENCE</div><b>'+esc(x.retailer)+' · '+esc(x.location)+'</b><div>'+esc(x.game)+' · '+esc(x.window)+'</div><p class="muted">'+esc(x.reason)+'</p></article>').join('')||'<p class="muted">No matching forecast.</p>';
    }
    ['ps48kind','ps48game','ps48store','ps48search'].forEach(id=>$(id).addEventListener('input',draw));
    $('ps48footer').textContent='Last reviewed: '+new Date(data.generated_utc).toLocaleString()+'. Public-source coverage is incomplete; forecasts and lead scores do not confirm inventory.';
    draw();
  }).catch(e=>{$('ps48results').textContent='Research results unavailable: '+e.message;$('ps48tips').textContent='Rumor forecasts currently unavailable.'});
})();
