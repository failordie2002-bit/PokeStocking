(() => {
  "use strict";

  const $=id=>document.getElementById(id);

  let communities=[];
  let reports=[];

  function location() {
    try {
      return JSON.parse(
        localStorage.getItem(
          "ps29Location"
        )||"{}"
      );
    } catch {
      return {};
    }
  }

  function el(tag,text,parent) {
    const node=document.createElement(tag);
    if(text!==undefined) {
      node.textContent=text;
    }
    if(parent) parent.appendChild(node);
    return node;
  }

  async function json(path,fallback) {
    try {
      const response=await fetch(
        path+"?v="+Date.now(),
        {cache:"no-store"}
      );
      if(!response.ok)
        return fallback;
      return await response.json();
    } catch {
      return fallback;
    }
  }

  function validLink(value) {
    try {
      const url=new URL(value);
      return url.protocol==="https:"?
        url.href:null;
    } catch {
      return null;
    }
  }

  function init() {
    const host=$("releases");
    if(!host||$("ps33")) return;

    // Replace the previous directory
    // interface without deleting its
    // underlying source files.
    const old=$("ps32");
    if(old) old.style.display="none";

    const panel=el("div",undefined,host);
    panel.id="ps33";
    panel.className="ps33-panel";

    panel.innerHTML=`
      <h2>TCG Discord Community Finder</h2>
      <p class="ps33-note">
        Discover collecting, restock,
        trading and tournament communities.
        Your location determines priority,
        not which communities are allowed.
      </p>
      <div class="ps33-filters">
        <input id="ps33Search"
          placeholder="Search communities">
        <select id="ps33Game">
          <option value="">All TCGs</option>
        </select>
        <select id="ps33Quality">
          <option value="">All quality levels</option>
          <option value="Strong TCG candidate">
            Strong TCG candidates
          </option>
          <option value="Possible TCG community">
            Possible TCG communities
          </option>
          <option value="Needs review">
            Needs review
          </option>
        </select>
        <select id="ps33Geo">
          <option value="priority">
            My location first
          </option>
          <option value="all">
            All locations
          </option>
          <option value="only">
            My state only
          </option>
        </select>
      </div>
      <p id="ps33Summary"
        class="ps33-note"></p>
      <div id="ps33Results"></div>
    `;

    host.insertBefore(
      panel,host.firstChild
    );

    [
      "ps33Search","ps33Game",
      "ps33Quality","ps33Geo"
    ].forEach(id=>{
      $(id).addEventListener(
        "input",render
      );
      $(id).addEventListener(
        "change",render
      );
    });

    load();
  }

  function render() {
    const q=$("ps33Search").value
      .trim().toLowerCase();
    const game=$("ps33Game").value;
    const quality=$("ps33Quality").value;
    const geo=$("ps33Geo").value;
    const state=String(
      location().state||""
    ).toUpperCase();

    let rows=communities.filter(x=>{
      const text=[
        x.name,
        x.category,
        ...(x.games||[])
      ].join(" ").toLowerCase();

      if(q&&!text.includes(q))
        return false;

      if(game&&!(
        x.games||[]
      ).includes(game))
        return false;

      if(quality&&
        x.quality_label!==quality)
        return false;

      if(geo==="only"&&
        (!state||!(
          x.states||[]
        ).includes(state)))
        return false;

      return true;
    });

    rows.sort((a,b)=>{
      if(geo==="priority"&&state) {
        const am=(
          a.states||[]
        ).includes(state)?1:0;
        const bm=(
          b.states||[]
        ).includes(state)?1:0;
        if(am!==bm)
          return bm-am;
      }
      return (
        (b.quality_score||0)-
        (a.quality_score||0)
      )||a.name.localeCompare(b.name);
    });

    $("ps33Summary").textContent=
      rows.length+" communities · "+
      "Automated classification, not "+
      "verified membership or live stock";

    const output=$("ps33Results");
    output.replaceChildren();

    if(!rows.length) {
      el(
        "p",
        "No matching communities.",
        output
      );
      return;
    }

    rows.slice(0,250).forEach(x=>{
      const link=validLink(x.url);
      if(!link) return;

      const card=el(
        "article",undefined,output
      );
      card.className="ps33-card";

      el(
        "strong",x.name,card
      );

      el(
        "p",
        [
          x.category||
            "Collector Community",
          (x.games||[]).join(", "),
          x.quality_label||
            "Needs review"
        ].filter(Boolean).join(" · "),
        card
      ).className="ps33-note";

      const local=state&&(
        x.states||[]
      ).includes(state);

      el(
        "p",
        local?
          "Matches your state":
          (x.states||[]).length?
          "Regional community candidate":
          "Location not specified",
        card
      ).className="ps33-note";

      const a=el(
        "a","View community listing",card
      );
      a.href=link;
      a.target="_blank";
      a.rel="noopener noreferrer";
    });
  }

  function renderEvidence() {
    const targets=[
      ["stores","physical_store"],
      ["online","online"],
      ["shipments","shipment"]
    ];

    targets.forEach(([tab,scope])=>{
      const host=$(tab);
      if(!host) return;

      let panel=$("ps33-"+scope);

      if(!panel) {
        panel=el(
          "div",undefined,host
        );
        panel.id="ps33-"+scope;
        panel.className="ps33-panel";
        host.appendChild(panel);
      }

      panel.replaceChildren();

      const title={
        physical_store:
          "Authorized Discord Store Reports",
        online:
          "Authorized Discord Online Reports",
        shipment:
          "Authorized Discord Shipment Reports"
      }[scope];

      el("h3",title,panel);

      const state=String(
        location().state||""
      ).toUpperCase();

      const matches=reports.filter(r=>{
        if(r.inventory_scope!==scope)
          return false;

        if(scope==="online")
          return true;

        if(!state)
          return false;

        return String(
          r.state||""
        ).toUpperCase()===state;
      });

      if(!matches.length) {
        el(
          "p",
          "No authorized Discord reports "+
          "available for this section. "+
          "No stock or shipment status "+
          "has been inferred.",
          panel
        ).className="ps33-note";
        return;
      }

      matches.slice(0,30).forEach(r=>{
        const card=el(
          "article",undefined,panel
        );
        card.className="ps33-card";

        el(
          "strong",
          r.product_name||
            "Community report",
          card
        );

        el(
          "p",
          [
            r.retailer,
            r.city,
            r.state,
            r.reported_at
          ].filter(Boolean).join(" · "),
          card
        );

        el(
          "p",
          "Authorized community report. "+
          "Current stock not verified.",
          card
        ).className="ps33-note";

        const url=validLink(
          r.source_url
        );

        if(url) {
          const a=el(
            "a","View source",card
          );
          a.href=url;
          a.target="_blank";
          a.rel="noopener noreferrer";
        }
      });
    });
  }

  async function load() {
    const [directory,evidence]=
      await Promise.all([
        json(
          "data/discord_quality_33.json",
          []
        ),
        json(
          "data/discord_accepted_reports_33.json",
          []
        )
      ]);

    communities=Array.isArray(directory)?
      directory:[];
    reports=Array.isArray(evidence)?
      evidence:[];

    const games=[
      ...new Set(
        communities.flatMap(
          x=>x.games||[]
        )
      )
    ].sort();

    games.forEach(g=>{
      const option=el(
        "option",g,$("ps33Game")
      );
      option.value=g;
    });

    render();
    renderEvidence();

    window.addEventListener(
      "storage",()=>{
        render();
        renderEvidence();
      }
    );

    const apply=$("ps29Apply");
    if(apply) {
      apply.addEventListener(
        "click",()=>{
          setTimeout(()=>{
            render();
            renderEvidence();
          },100);
        }
      );
    }
  }

  if(document.readyState==="loading") {
    document.addEventListener(
      "DOMContentLoaded",init,
      {once:true}
    );
  } else {
    init();
  }
})();
