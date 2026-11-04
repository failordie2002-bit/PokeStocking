(()=>{
'use strict';

const root=document.getElementById('ps2root');
if(!root||document.getElementById('ps45RumorPanel'))return;

const safe=u=>{
  try{
    const x=new URL(u);
    return x.protocol==='https:'?x.href:'';
  }catch{return '';}
};

const esc=x=>String(x??'').replace(
  /[&<>"']/g,
  c=>({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    '"':'&quot;',
    "'":'&#39;'
  }[c])
);

const norm=x=>String(x||'')
  .toLowerCase()
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g,'')
  .replace(/[^a-z0-9]/g,'');

const load=async(p,def)=>{
  try{
    const r=await fetch(
      p+'?v='+Date.now(),
      {cache:'no-store'}
    );
    return r.ok?await r.json():def;
  }catch{return def;}
};

let rumors=[];
let allocations=[];
let listings=[];
let stores=[];
let games=[];

const choices=document.getElementById('ps2Games');

const panel=document.createElement('section');
panel.id='ps45RumorPanel';
panel.className='ps45panel';

const controls=document.querySelector(
  '#ps2-forecast .ps2controls'
);
if(controls)controls.after(panel);

const membership=document.createElement('section');
membership.className='ps45panel';
membership.id='ps45ClubReports';

const radar=document.getElementById('ps44Radar');

if(radar)radar.after(membership);
else if(choices)choices.after(membership);

const selection=document.getElementById(
  'ps2ForecastStore'
);

const aliases={'Pokémon':'Pokemon'};

function setGameFilters(){
  if(!choices||!games.length)return;

  const show=[
    'Pokémon','Union Arena','One Piece'
  ].filter(g=>games.includes(g));

  const other=games.filter(g=>!show.includes(g));

  choices.replaceChildren();

  const make=(label,val)=>{
    const b=document.createElement('button');
    b.type='button';
    b.className='ps2chip'+(!val?' sel':'');
    b.textContent=label;
    b.dataset.game=val;
    choices.append(b);
    return b;
  };

  make('All TCGs','');

  show.forEach(
    g=>make(g,aliases[g]||g)
  );

  const select=document.createElement('select');
  select.id='ps45Games';

  select.setAttribute(
    'aria-label',
    'Choose any trading card game'
  );

  select.innerHTML=
    '<option value="">More TCGs…</option>'+
    other.map(g=>`
      <option value="${esc(aliases[g]||g)}">
        ${esc(g)}
      </option>
    `).join('');

  select.addEventListener('change',()=>{
    let b=choices.querySelector(
      '[data-ps45-temp]'
    );

    if(b)b.remove();

    b=make(
      select.options[
        select.selectedIndex
      ].text,
      select.value
    );

    b.dataset.ps45Temp='1';
    b.click();
  });

  choices.append(select);

  choices.addEventListener('click',e=>{
    const b=e.target.closest('[data-game]');
    if(
      b&&b.dataset.ps45Temp!=='1'
    )select.value='';
  });
}

function renderRumors(){
  if(!panel||!selection)return;

  const store=stores.find(
    x=>String(x.id)===String(selection.value)
  );

  if(!store){
    panel.innerHTML=`
      <h3>Collector watch windows</h3>
      <p>
        Choose a nearby store to see dated,
        unverified restock rumors separately
        from actual observations.
      </p>`;
    return;
  }

  const chain=norm(store.name||'');
  const loc=norm(store.city||'');
  const state=norm(store.state||'');

  const same=rumors.filter(r=>
    r.scope==='city_retailer'&&
    norm(r.city)===loc&&
    norm(r.state)===state&&
    chain.includes(norm(r.retailer))
  );

  const broad=rumors.filter(r=>
    r.scope==='general_retailer'&&
    chain.includes(norm(r.retailer))
  ).slice(0,3);

  const line=r=>`
    <article class="ps45rumor">
      <strong>
        ${esc(r.game)} ·
        ${esc(r.weekday)}
        ${r.period&&r.period!=='unspecified'?
          ' '+esc(r.period):''}
      </strong>

      <span class="ps45level">
        Rumor · low confidence
      </span>

      <p>
        ${esc(
          r.note||r.title||'Unverified collector claim'
        )}
      </p>

      <small>
        First reported
        ${esc(String(r.reported_at||'').slice(0,10))}
        ·
        ${esc(
          r.scope==='city_retailer'?
          'City-specific hearsay':
          'General retailer claim; not branch evidence'
        )}
      </small>

      ${safe(r.source_url)?`
        <a href="${esc(safe(r.source_url))}"
           target="_blank"
           rel="noopener noreferrer">
          Source
        </a>`:''}
    </article>`;

  const selected=same.slice(0,4);

  const DAYS=[
    'Mon','Tue','Wed','Thu','Fri','Sat','Sun'
  ];

  const strip=selected.length?
    '<div class="ps45strip">'+
    DAYS.map(d=>{
      const n=selected.filter(
        r=>r.weekday.slice(0,3)
          .toLowerCase()===d.toLowerCase()
      ).length;

      return `
        <div class="${n?'watch':''}">
          <b>${d}</b>
          <span>
            ${n?n+' rumor':'—'}
          </span>
        </div>`;
    }).join('')+
    '</div>':'';

  const summary=selected.length?
    `<p class="ps45warning">
      ${selected.length} hearsay record(s)
      tied to ${esc(store.city)}.
      These are <b>not observed restocks</b>
      and do not indicate today's stock.
    </p>`:
    `<p>
      No city-specific restock rumor
      recorded for this branch.
    </p>`;

  panel.innerHTML=
    '<h3>Community restock watch</h3>'+
    summary+
    strip+
    selected.map(line).join('')+
    (broad.length?`
      <details>
        <summary>
          General retailer chatter
          (not local confirmation)
        </summary>
        ${broad.map(line).join('')}
      </details>`:'')+
    `<p class="ps45disclaimer">
      No predicted deliveries, live shelf
      quantities, or certainty percentages
      are claimed from rumors.
    </p>`;
}

function renderClubReports(){
  if(!membership)return;

  let loc=null;

  try{
    loc=JSON.parse(
      localStorage.getItem('ps2location')||'null'
    );
  }catch{}

  if(!loc||!stores.length){
    membership.innerHTML=`
      <h3>Sam’s Club historical allocations</h3>
      <p>
        Set GPS or ZIP in Near Me to identify
        nearby clubs. Reports are historical
        and unverified.
      </p>`;
    return;
  }

  const dist=(a,b,c,d)=>{
    const rad=Math.PI/180;
    const h=
      Math.sin((c-a)*rad/2)**2+
      Math.cos(a*rad)*Math.cos(c*rad)*
      Math.sin((d-b)*rad/2)**2;

    return 3958.8*2*Math.asin(
      Math.min(1,Math.sqrt(h))
    );
  };

  const radius=+(
    localStorage.getItem('ps2radius')||50
  );

  const near=stores.filter(s=>
    /^(sam's club|sams club)$/i.test(s.name||'')&&
    s.city&&s.lat!=null&&s.lon!=null
  ).map(s=>({
    ...s,
    miles:dist(
      +loc.lat,+loc.lon,+s.lat,+s.lon
    )
  })).filter(s=>
    s.miles<=radius
  ).sort((a,b)=>
    a.miles-b.miles
  ).slice(0,5);

  const rows=[];

  for(const s of near){
    const rs=allocations.filter(a=>
      norm(a.state)===norm(s.state)&&
      norm(a.city).startsWith(norm(s.city))
    );

    if(!rs.length)continue;

    const history=rs.sort(
      (a,b)=>String(b.report_date)
        .localeCompare(String(a.report_date))
    ).slice(0,3);

    rows.push(`
      <div class="ps45rumor">
        <strong>
          ${esc(s.name)} ·
          ${esc(s.city)} ·
          ${s.miles.toFixed(1)} mi
        </strong>

        ${history.map(a=>`
          <p>
            ${esc(a.product)}
            · <b>${esc(a.report_date)}</b>:
            ${a.reported_on_hand}
            historically reported on hand
            ${a.reported_on_order!=null?
              ', '+a.reported_on_order+
              ' on order':''}.
            <b>Not current inventory.</b>

            ${safe(a.source_url)?`
              <a href="${esc(safe(a.source_url))}"
                 target="_blank"
                 rel="noopener noreferrer">
                Source
              </a>`:''}
          </p>
        `).join('')}
      </div>`);
  }

  membership.innerHTML=`
    <h3>
      Sam’s Club historical allocation reports
    </h3>

    <p>
      Published club counts, not live shelf
      inventory. Different report dates are
      separate snapshots; quantities are never
      added together.
    </p>
    ${rows.join('')||`
      <p>
        No matching historical allocations
        found for clubs inside your radius.
      </p>`}`;
}

function extraOfficial(){
  if(!membership||!listings.length)return;

  const details=document.createElement('details');
  details.className='ps45extras';

  details.innerHTML=`
    <summary>
      Additional TCG listings at
      Costco, Sam’s &amp; Lowe’s
      (${listings.length})
    </summary>

    <p>
      Official product links only.
      No shipping or pickup is implied.
    </p>

    ${listings.slice(0,18).map(x=>`
      <div class="ps45link">
        <b>${esc(x.game)}</b>
        · ${esc(x.retailer)}
        · ${esc(x.title)}
        ${safe(x.url)?`
          <a href="${esc(safe(x.url))}"
             target="_blank"
             rel="noopener noreferrer">
            Source
          </a>`:''}
      </div>
    `).join('')}`;

  membership.append(details);
}

Promise.all([
  load('data/universal45.json',{}),
  load('data/rumor45.json',{}),
  load('data/sams_allocations_45.json',{}),
  load('data/stores.json',[])
]).then(([u,r,a,s])=>{
  games=Array.isArray(u.games)?u.games:[];
  listings=Array.isArray(
    u.retailer_listing_leads
  )?u.retailer_listing_leads:[];

  rumors=Array.isArray(
    r.reports
  )?r.reports:[];

  allocations=Array.isArray(
    a.records
  )?a.records:[];

  stores=Array.isArray(s)?s:[];

  setGameFilters();
  renderRumors();
  renderClubReports();
  extraOfficial();
});

selection?.addEventListener(
  'change',
  ()=>setTimeout(renderRumors,0)
);

if(selection){
  new MutationObserver(
    ()=>renderRumors()
  ).observe(
    selection,{childList:true}
  );
}

document.addEventListener('click',e=>{
  if(e.target.closest(
    '#ps2GPS,#ps2ZipGo,#ps2Place,'+
    '[data-ps2-tab],#ps2Radius'
  )){
    setTimeout(()=>{
      renderClubReports();
      renderRumors();
      extraOfficial();
    },300);
  }
});
})();
