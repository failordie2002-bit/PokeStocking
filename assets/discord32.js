(() => {
  "use strict";

  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(
    /[&<>"']/g,
    c=>({
      "&":"&amp;","<":"&lt;",
      ">":"&gt;",'"':"&quot;","'":"&#39;"
    }[c])
  );

  let directory=[];

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

  function start() {
    const host=$("releases");
    if (!host||$("ps32")) return;

    const panel=document.createElement("div");
    panel.id="ps32";
    panel.innerHTML=`
      <h2>Discover TCG Discord Communities</h2>
      <p class="ps32-note">
        All communities are included.
        Location-specific groups appear first
        when geographic evidence exists.
      </p>
      <div class="ps32-controls">
        <input id="ps32Search"
          placeholder="Search communities">
        <select id="ps32Game">
          <option value="">All games</option>
        </select>
        <select id="ps32Type">
          <option value="">All community types</option>
          <option>Restock Alerts</option>
          <option>Buying and Trading</option>
          <option>Playing and Tournaments</option>
          <option>Collector Community</option>
        </select>
        <select id="ps32Location">
          <option value="all">All locations</option>
          <option value="local">My state first</option>
          <option value="only">My state only</option>
        </select>
      </div>
      <p id="ps32Count" class="ps32-note"></p>
      <div id="ps32Results"></div>
      <p class="ps32-note">
        These are public community listings,
        not live Discord message feeds.
        Stock and shipment claims are not verified.
      </p>
    `;

    host.insertBefore(
      panel,host.firstChild
    );

    [
      "ps32Search","ps32Game",
      "ps32Type","ps32Location"
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
    const q=$("ps32Search").value
      .trim().toLowerCase();
    const game=$("ps32Game").value;
    const type=$("ps32Type").value;
    const mode=$("ps32Location").value;
    const state=String(
      location().state||""
    ).toUpperCase();

    let rows=directory.filter(d=>{
      const text=[
        d.name,
        d.category,
        ...(d.games||[])
      ].join(" ").toLowerCase();

      if(q&&!text.includes(q))
        return false;

      if(game&&!(
        d.games||[]
      ).includes(game))
        return false;

      if(type&&d.category!==type)
        return false;

      if(mode==="only") {
        return !!state&&(
          d.states||[]
        ).includes(state);
      }

      return true;
    });

    if(mode!=="all"&&state) {
      rows.sort((a,b)=>{
        const av=(
          a.states||[]
        ).includes(state)?1:0;
        const bv=(
          b.states||[]
        ).includes(state)?1:0;
        return bv-av||
          a.name.localeCompare(b.name);
      });
    }

    $("ps32Count").textContent=
      rows.length+
      " matching community listings";

    const output=$("ps32Results");
    output.replaceChildren();

    if(!rows.length) {
      output.textContent=
        "No matching communities found.";
      return;
    }

    rows.slice(0,250).forEach(d=>{
      let url;
      try {
        url=new URL(d.url);
        if(url.protocol!=="https:")
          return;
      } catch {
        return;
      }

      const card=document.createElement(
        "article"
      );
      card.className="ps32-card";

      const local=!!state&&(
        d.states||[]
      ).includes(state);

      const title=document.createElement(
        "strong"
      );
      title.textContent=d.name;
      card.appendChild(title);

      const detail=document.createElement(
        "p"
      );
      detail.className="ps32-note";
      detail.textContent=[
        d.category||
          "Collector Community",
        (d.games||[]).join(", "),
        local?"Matches your state":
          (d.states||[]).length?
          "Regional listing":
          "Location unspecified"
      ].filter(Boolean).join(" · ");
      card.appendChild(detail);

      const link=document.createElement("a");
      link.href=url.href;
      link.target="_blank";
      link.rel="noopener noreferrer";
      link.textContent=
        "Open public community listing";
      card.appendChild(link);

      const note=document.createElement("p");
      note.className="ps32-note";
      note.textContent=
        "Public listing · Invite and " +
        "message access not verified";
      card.appendChild(note);

      output.appendChild(card);
    });
  }

  async function load() {
    try {
      const response=await fetch(
        "data/discord_directory_29.json?v="+
        Date.now(),
        {cache:"no-store"}
      );

      if(!response.ok)
        throw Error("HTTP "+response.status);

      const data=await response.json();

      directory=Array.isArray(data)?
        data.filter(d=>
          d&&typeof d.name==="string"&&
          typeof d.url==="string"
        ):[];

      const games=[
        ...new Set(
          directory.flatMap(
            d=>d.games||[]
          )
        )
      ].sort();

      games.forEach(g=>{
        const option=document.createElement(
          "option"
        );
        option.value=g;
        option.textContent=g;
        $("ps32Game").appendChild(option);
      });

      render();
    } catch(e) {
      $("ps32Count").textContent=
        "Directory could not be loaded: "+
        e.message;
    }
  }

  if(document.readyState==="loading") {
    document.addEventListener(
      "DOMContentLoaded",start,
      {once:true}
    );
  } else {
    start();
  }
})();
