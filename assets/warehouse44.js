(()=>{
'use strict';

const root=document.getElementById('ps2root');
if(!root||document.getElementById('ps44Radar'))return;

const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({
  '&':'&amp;','<':'&lt;','>':'&gt;',
  '"':'&quot;',"'":'&#39;'
}[c]));

const url=x=>{
  try{
    const u=new URL(x);
    return u.protocol==='https:'?u.href:'';
  }catch{return '';}
};

const age=x=>{
  const n=Date.parse(x);
  return Number.isFinite(n)?
    (Date.now()-n)/3600000:Infinity;
};

const moment=x=>{
  const d=new Date(x);
  return Number.isFinite(+d)?
    d.toLocaleString(undefined,{
      month:'short',day:'numeric',
      hour:'numeric',minute:'2-digit'
    }):'Unspecified';
};

const kmiles=(a,b,c,d)=>{
  const r=Math.PI/180;
  const h=Math.sin((c-a)*r/2)**2+
    Math.cos(a*r)*Math.cos(c*r)*
    Math.sin((d-b)*r/2)**2;
  return 3958.8*2*Math.asin(
    Math.min(1,Math.sqrt(h))
  );
};

const get=async(path,def)=>{
  try{
    const r=await fetch(
      path+'?q='+Date.now(),
      {cache:'no-store'}
    );
    return r.ok?await r.json():def;
  }catch{return def;}
};

let data={
  products:[],allocations:[],summary:{}
};
let shops=[];

const panel=document.createElement('section');
panel.id='ps44Radar';
panel.className='ps44';

panel.innerHTML=`
  <div class="ps44-head">
    <h2>🏬 Costco & Sam’s Club</h2>
    <span class="ps44-pill">Warehouse club radar</span>
  </div>
  <p class="ps44-sub">
    Public TCG listings, recorded shipping signals,
    and nearby club locations. Not shelf inventory.
  </p>
  <div class="ps44-grid" id="ps44Cards">
    <p>Checking warehouse product sources…</p>
  </div>
  <details class="ps44-extra">
    <summary>Nearby clubs and source details</summary>
    <div id="ps44Local">
      Set GPS or ZIP in Near Me to personalize clubs.
    </div>
    <p>
      Sam’s pickup requires selecting your club on
      its website; Costco warehouse stock may only
      appear for eligible items and selected
      locations. Unverified allocations are
      historical research, not live stock.
    </p>
  </details>`;

const discover=document.getElementById('ps2-discover');
const games=document.getElementById('ps2Games');

if(!discover)return;

if(games)games.after(panel);
else discover.prepend(panel);

const local=document.createElement('div');
local.id='ps44Near';
local.className='ps44';
local.innerHTML=`
  <div class="ps44-head">
    <h2>Warehouse clubs near you</h2>
    <span class="ps44-pill">Costco / Sam’s Club</span>
  </div>
  <p class="ps44-sub">
    Club locations only. Shipping signals are nationwide;
    pickup and shelf status are not verified here.
  </p>
  <div id="ps44NearList">
    Set GPS or ZIP above to find nearby clubs.
  </div>`;

const status=document.getElementById('ps2LocateStatus');
if(status)status.after(local);

function locationValue(){
  try{
    const x=JSON.parse(
      localStorage.getItem('ps2location')||'null'
    );
    return x&&Number.isFinite(+x.lat)&&
      Number.isFinite(+x.lon)&&
      Math.abs(+x.lat)<=90&&Math.abs(+x.lon)<=180?
      x:null;
  }catch{return null;}
}

function club(s){
  const n=String(s.name||'').trim().toLowerCase();
  return n==='costco'||
    n==='costco wholesale'||
    n==="sam's club"||
    n==='sams club';
}

function nearList(){
  const p=locationValue();
  const radius=Number(
    localStorage.getItem('ps2radius')
  )||50;

  if(!p)return null;

  return shops
    .filter(s=>
      club(s)&&s.lat!=null&&s.lon!=null&&
      Number.isFinite(+s.lat)&&
      Number.isFinite(+s.lon)
    )
    .map(s=>({
      ...s,
      miles:kmiles(
        +p.lat,+p.lon,+s.lat,+s.lon
      )
    }))
    .filter(s=>s.miles<=radius)
    .sort((a,b)=>a.miles-b.miles)
    .slice(0,8);
}

function localLine(s){
  const key=String(s.address||'')
    .toLowerCase().replace(/[^a-z0-9]/g,'');

  const reports=(data.allocations||[]).filter(a=>{
    const ad=String(a.address||'')
      .toLowerCase().replace(/[^a-z0-9]/g,'');
    return (s.name||'').toLowerCase()
      .includes('costco')&&
      key.length>=7&&ad.includes(key);
  });

  const report=reports[0];
  const date=report?.reported_as_of;
  const days=date?
    age(date+'T23:59:00Z')/24:Infinity;

  const allocation=report&&days>=0&&days<=7?`
    <p>
      Third-party allocation, as of ${esc(date)}:
      reported on hand ${report.reported_on_hand},
      on order ${report.reported_on_order},
      in transit ${report.reported_in_transit}.
      <b>Not verified shelf stock.</b>
    </p>`:'';

  return `
    <div class="ps44-localrow">
      <div>
        <strong>
          ${esc(s.name)} · ${s.miles.toFixed(1)} mi
        </strong>
        <span>
          ${esc([
            s.address,s.city,s.state
          ].filter(Boolean).join(', '))}
        </span>
        ${allocation}
      </div>
      <button type="button"
        data-ps44-route="${esc(s.id)}">
        Route
      </button>
    </div>`;
}

function renderNearby(){
  const items=nearList();
  let message=(
    'Choose GPS or ZIP in Near Me to '+
    'show club locations near you.'
  );

  if(items){
    message=items.length?
      items.map(localLine).join(''):
      'No listed Costco or Sam’s Club inside the selected radius.';
  }

  const a=document.getElementById('ps44Local');
  const b=document.getElementById('ps44NearList');
  if(a)a.innerHTML=message;
  if(b)b.innerHTML=message;
}

function product(x){
  const good=(
    x.shipping_status==='shipping_available_observed'
  );
  const bad=(
    x.shipping_status==='shipping_unavailable_observed'
  );
  const status=good?
    'Shipping observed available':
    bad?'Shipping observed unavailable':
    'Availability unverified';

  const dated=x.checked_at&&age(x.checked_at)<48?
    moment(x.checked_at):'Previous check';

  const price=x.price&&x.currency==='USD'?
    ' · observed $'+esc(x.price):'';

  return `
    <div class="ps44-product">
      <strong>
        ${esc(x.title||'Previously indexed TCG product')}
      </strong>
      <br>
      <span class="ps44-pill ${good?'good':bad?'warn':''}">
        ${status}
      </span>
      <small>
        ${esc(x.evidence||'Source evidence unavailable')}
        · ${esc(dated)}${price}
      </small>
      <details>
        <summary>Official product source</summary>
        ${url(x.url)?`
          <a href="${esc(url(x.url))}"
             target="_blank" rel="noopener noreferrer">
            View at ${esc(x.retailer)}
          </a>`:''}
      </details>
    </div>`;
}

function draw(){
  const brands=["Sam's Club",'Costco'];
  const items=brands.map(brand=>{
    const records=(data.products||[])
      .filter(x=>x.retailer===brand)
      .sort((a,b)=>
        Number(
          b.shipping_status==='shipping_available_observed'
        )-
        Number(
          a.shipping_status==='shipping_available_observed'
        )
      );

    const accessible=records.filter(x=>
      x.shipping_status!=='access_unavailable'
    );
    const available=records.filter(x=>
      x.shipping_status==='shipping_available_observed'
    );

    return `
      <article class="ps44-card">
        <h3>${esc(brand)}</h3>
        <span class="ps44-pill ${available.length?'good':''}">
          ${available.length?
            available.length+' reported shipping available':
            accessible.length?
            accessible.length+' product pages examined':
            'No accessible product evidence'}
        </span>
        <p>
          ${brand==='Costco'?
            'Warehouse availability depends on the selected location.':
            'Pickup and delivery require a selected club.'}
        </p>
        <div class="ps44-products">
          ${records.slice(0,3).map(product).join('')||
            '<p>No accessible TCG listings currently confirmed.</p>'}
        </div>
      </article>`;
  });

  document.getElementById('ps44Cards').innerHTML=
    items.join('');
  renderNearby();
}

async function init(){
  const [w,stores]=await Promise.all([
    get('data/warehouse_watch_44.json',{}),
    get('data/stores.json',[])
  ]);

  if(w&&Array.isArray(w.products))data=w;
  shops=Array.isArray(stores)?stores:[];
  draw();
}

root.addEventListener('click',e=>{
  const b=e.target.closest('[data-ps44-route]');
  if(b){
    if(typeof window.ps44RouteTo==='function'){
      window.ps44RouteTo(b.dataset.ps44Route);
    }else{
      document.querySelector(
        '[data-ps2-tab="near"]'
      )?.click();
    }
  }
});

document.addEventListener('click',e=>{
  if(e.target.closest(
    '#ps2GPS,#ps2ZipGo,#ps2Radius,'+
    '[data-ps2-tab],#ps2Place'
  )){
    requestAnimationFrame(renderNearby);
  }
});

window.addEventListener('storage',renderNearby);
init();
})();
