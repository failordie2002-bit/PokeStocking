(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const root = $("ps27");
  if (!root) return;

  const days = [
    "Mon","Tue","Wed","Thu",
    "Fri","Sat","Sun"
  ];

  let stores = [];
  let events = [];
  let retailers = [];
  const selected = new Set();

  const norm = value =>
    String(value ?? "").trim().toLowerCase();

  const escapeHTML = value =>
    String(value ?? "").replace(
      /[&<>"']/g,
      c => ({
        "&":"&amp;",
        "<":"&lt;",
        ">":"&gt;",
        '"':"&quot;",
        "'":"&#39;"
      }[c])
    );

  async function load(path) {
    const r = await fetch(
      path + "?t=" + Date.now(),
      {cache:"no-store"}
    );
    if (!r.ok) throw Error(path);
    return r.json();
  }

  function addOptions(id, values) {
    const el = $(id);
    const existing = el.value;

    el.querySelectorAll(
      "option:not(:first-child)"
    ).forEach(o => o.remove());

    [...new Set(values)]
      .filter(Boolean)
      .sort((a,b) => a.localeCompare(b))
      .forEach(value => {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = value;
        el.appendChild(o);
      });

    if ([...el.options].some(
      o => o.value === existing
    )) el.value = existing;
  }

  function storeId(store) {
    return String(store.source_id || "");
  }

  function storeLabel(store) {
    return [
      store.name || store.chain,
      store.address,
      store.city,
      store.state
    ].filter(Boolean).join(" · ");
  }

  function visibleStores() {
    const q = norm($("ps27Search").value);
    const state = $("ps27State").value;

    return stores.filter(store => {
      if (
        state &&
        store.state !== state
      ) return false;

      return !q ||
        norm(storeLabel(store)).includes(q);
    });
  }

  function renderStores() {
    const visible = visibleStores();
    const box = $("ps27Stores");

    box.replaceChildren();

    if (!visible.length) {
      box.textContent =
        "No stores match this search.";
    }

    // Render at most 200 visible checkboxes
    // to keep mobile scrolling responsive.
    for (const store of visible.slice(0,200)) {
      const id = storeId(store);
      if (!id) continue;

      const label =
        document.createElement("label");
      label.className = "ps27-store";

      const check =
        document.createElement("input");
      check.type = "checkbox";
      check.checked = selected.has(id);

      check.addEventListener(
        "change", () => {
          if (check.checked) selected.add(id);
          else selected.delete(id);
          renderChart();
        }
      );

      const span =
        document.createElement("span");
      span.textContent = storeLabel(store);

      label.append(check,span);
      box.appendChild(label);
    }

    if (visible.length > 200) {
      const note =
        document.createElement("p");
      note.className = "ps27-note";
      note.textContent =
        "Showing first 200 matches. " +
        "Narrow your search to find " +
        "more individual stores.";
      box.appendChild(note);
    }

    $("ps27Selected").textContent =
      selected.size
        ? selected.size + " stores selected"
        : "No individual filter: all stores included";
  }

  function renderEmpty() {
    $("ps27Bars").innerHTML = days.map(day => `
      <div class="ps27-column">
        <span class="ps27-value">N/A</span>
        <div class="ps27-track">
          <div class="ps27-fill"
            style="height:0%"></div>
        </div>
        <span class="ps27-day">${day}</span>
      </div>
    `).join("");
  }

  function renderChart() {
    const state = $("ps27State").value;
    const game = $("ps27Game").value;
    const type = $("ps27Type").value;

    const matching = events.filter(e => {
      if (game && e.game !== game) return false;

      if (
        type === "shipments" &&
        e.shipment_confirmed !== true
      ) return false;

      if (
        selected.size === 0 &&
        state
      ) {
        // Existing weekday events may not
        // include state; match via known
        // store city and retailer.
        const found = stores.some(s =>
          s.state === state &&
          norm(s.city) === norm(e.city) &&
          (
            norm(s.chain) === norm(e.retailer) ||
            norm(s.name) === norm(e.retailer)
          )
        );
        if (!found) return false;
      }

      if (selected.size > 0) {
        const found = stores.some(s =>
          selected.has(storeId(s)) &&
          norm(s.city) === norm(e.city) &&
          (
            norm(s.chain) === norm(e.retailer) ||
            norm(s.name) === norm(e.retailer)
          )
        );

        if (!found) return false;
      }

      return true;
    });

    const counts = Array(7).fill(0);
    let verified = 0;
    let effective = 0;

    for (const e of matching) {
      const day = Number(e.weekday);
      if (
        !Number.isInteger(day) ||
        day < 0 || day > 6
      ) continue;

      const weight =
        Math.max(0,Number(e.weight) || 0);

      counts[day] += weight;
      effective += weight;

      if (e.verified) verified++;
    }

    const sufficient =
      matching.length >= 5 &&
      verified >= 2 &&
      effective >= 3;

    if (!sufficient) {
      $("ps27Status").textContent =
        matching.length +
        " dated observations; " +
        verified +
        " verified. Insufficient evidence " +
        "for meaningful weekday percentages.";

      renderEmpty();
      return;
    }

    const total = effective + 7;
    const percentages = counts.map(
      count => 100*(count+1)/total
    );
    const max = Math.max(...percentages);

    $("ps27Status").textContent =
      matching.length +
      " dated observations; " +
      verified +
      " verified. Historical weekday " +
      "distribution shown.";

    $("ps27Bars").innerHTML =
      days.map((day,i) => `
        <div class="ps27-column">
          <span class="ps27-value">
            ${percentages[i].toFixed(1)}%
          </span>
          <div class="ps27-track">
            <div class="ps27-fill"
              style="height:${
                100*percentages[i]/max
              }%"></div>
          </div>
          <span class="ps27-day">
            ${day}
          </span>
        </div>
      `).join("");
  }

  function renderRetailers() {
    const box = $("ps27Retail");
    box.replaceChildren();

    for (const r of retailers) {
      const card =
        document.createElement("div");
      card.className = "ps27-retail";

      const heading =
        document.createElement("strong");
      heading.textContent = r.name;

      const p = document.createElement("p");
      p.className = "ps27-note";

      const branches = stores.filter(s =>
        norm(s.chain) === norm(r.name) ||
        norm(s.name) === norm(r.name) ||
        (
          r.name === "CVS Pharmacy" &&
          norm(s.chain) === "cvs"
        )
      ).length;

      p.textContent =
        branches + " candidate branches in " +
        "the store database. Local stock unknown.";

      const a = document.createElement("a");
      a.href = r.website;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "Open retailer";

      card.append(heading,p,a);
      box.appendChild(card);
    }
  }

  $("ps27Search").addEventListener(
    "input", renderStores
  );

  $("ps27State").addEventListener(
    "change", () => {
      renderStores();
      renderChart();
    }
  );

  $("ps27Game").addEventListener(
    "change", renderChart
  );

  $("ps27Type").addEventListener(
    "change", renderChart
  );

  $("ps27SelectVisible").onclick = () => {
    for (
      const store of visibleStores().slice(0,200)
    ) {
      const id = storeId(store);
      if (id) selected.add(id);
    }
    renderStores();
    renderChart();
  };

  $("ps27Clear").onclick = () => {
    selected.clear();
    renderStores();
    renderChart();
  };

  renderEmpty();

  Promise.allSettled([
    load("data/physical_inventory_sources.json"),
    load("data/weekday_chart_26.json"),
    load("data/retail_expansion_26.json")
  ]).then(results => {
    if (results[0].status === "fulfilled") {
      const value = results[0].value;
      stores = Array.isArray(value) ? value : [];
    }

    if (results[1].status === "fulfilled") {
      const value = results[1].value;
      events = Array.isArray(value.events)
        ? value.events : [];
    }

    if (results[2].status === "fulfilled") {
      const value = results[2].value;
      retailers = Array.isArray(value.retailers)
        ? value.retailers : [];
    }

    addOptions(
      "ps27State",
      stores.map(s => s.state)
    );

    addOptions(
      "ps27Game",
      [
        ...events.map(e => e.game),
        ...(
          results[2].status === "fulfilled"
            ? results[2].value.games_monitored || []
            : []
        )
      ]
    );

    renderStores();
    renderChart();
    renderRetailers();
  });
})();
