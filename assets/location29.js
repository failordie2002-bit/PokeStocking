(() => {
  "use strict";

  const NATIONAL = [
    {
      name:"Pokemon Restocks and Alerts",
      url:"https://discord.com/servers/pokemon-restocks-and-alerts-1369077918244012072",
      games:["Pokemon"],
      states:[],
      cities:[]
    },
    {
      name:"PokePings",
      url:"https://discord.com/servers/pokepings-restock-alerts-1423812860043333695",
      games:["Pokemon"],
      states:[],
      cities:[]
    },
    {
      name:"Restockd",
      url:"https://discord.com/servers/restockd-pokemon-restocks-1331120711405932626",
      games:["Pokemon"],
      states:[],
      cities:[]
    },
    {
      name:"TCG Notify",
      url:"https://discord.com/servers/tcg-notify-1410829344850444380",
      games:["Pokemon","One Piece","Riftbound"],
      states:[],
      cities:[]
    }
  ];

  const STATES = {
    AL:"Alabama",AK:"Alaska",AZ:"Arizona",
    AR:"Arkansas",CA:"California",CO:"Colorado",
    CT:"Connecticut",DE:"Delaware",FL:"Florida",
    GA:"Georgia",HI:"Hawaii",ID:"Idaho",
    IL:"Illinois",IN:"Indiana",IA:"Iowa",
    KS:"Kansas",KY:"Kentucky",LA:"Louisiana",
    ME:"Maine",MD:"Maryland",MA:"Massachusetts",
    MI:"Michigan",MN:"Minnesota",MS:"Mississippi",
    MO:"Missouri",MT:"Montana",NE:"Nebraska",
    NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",
    NM:"New Mexico",NY:"New York",NC:"North Carolina",
    ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",
    OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",
    SC:"South Carolina",SD:"South Dakota",
    TN:"Tennessee",TX:"Texas",UT:"Utah",
    VT:"Vermont",VA:"Virginia",WA:"Washington",
    WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",
    DC:"District of Columbia"
  };

  const $ = id => document.getElementById(id);

  const esc = v => String(v ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",
      '"':"&quot;","'":"&#39;"
    }[c])
  );

  const norm = v =>
    String(v ?? "").trim().toLowerCase();

  const safeURL = v => {
    try {
      const u = new URL(v);
      return u.protocol === "https:" ? u.href : "";
    } catch {
      return "";
    }
  };

  let location = {
    city:"",
    state:"",
    radius:50
  };

  let sightings = [];
  let directory = [];

  try {
    const saved = JSON.parse(
      localStorage.getItem("ps29Location") || "null"
    );
    if (saved && typeof saved === "object") {
      location = {
        city:String(saved.city || "").slice(0,100),
        state:String(saved.state || "").toUpperCase(),
        radius:Number(saved.radius) || 50
      };
    }
  } catch {}

  function persist() {
    try {
      localStorage.setItem(
        "ps29Location",
        JSON.stringify(location)
      );
    } catch {}
  }

  function stateCode(value) {
    const v = String(value || "").trim();
    const code = v.toUpperCase();
    if (STATES[code]) return code;
    return Object.keys(STATES).find(
      k => norm(STATES[k]) === norm(v)
    ) || "";
  }

  function make(tag, attrs = {}, parent) {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k,v]) => {
      if (k === "text") el.textContent = v;
      else el.setAttribute(k,v);
    });
    if (parent) parent.appendChild(el);
    return el;
  }

  function section(tab, title, id) {
    const host = document.getElementById(tab);
    if (!host) return;

    const box = make("div",{
      class:"ps29-panel",
      id
    });

    make("h3",{text:title},box);
    make("div",{
      class:"ps29-content",
      text:"Loading..."
    },box);

    host.insertBefore(box,host.firstChild);
  }

  function labelLocation() {
    return [
      location.city,
      STATES[location.state] || location.state
    ].filter(Boolean).join(", ") ||
      "No location selected";
  }

  function scoped(report) {
    if (!location.state) return false;

    if (
      stateCode(report.state) !== location.state
    ) return false;

    // Without coordinates, only exact city
    // matching is supported. Never pretend
    // the radius is a measured distance.
    if (location.city) {
      return norm(report.city) ===
        norm(location.city);
    }

    return true;
  }

  function recent(report) {
    const raw = report.reported_at_approx;
    const time = Date.parse(raw || "");
    if (!Number.isFinite(time)) return false;
    const age = Date.now() - time;
    return age >= 0 &&
      age <= 48 * 60 * 60 * 1000;
  }

  function communityCard(r) {
    const url = safeURL(r.source_url);
    const card = document.createElement("article");
    card.className = "ps29-card";

    card.innerHTML = `
      <strong>${esc(r.product_name || "TCG sighting")}</strong>
      <p>${esc(r.retailer || "Retailer unknown")}
        — ${esc(r.city || "")},
        ${esc(r.state || "")}</p>
      <p class="ps29-muted">
        Community reported · Not verified stock
      </p>
      <p class="ps29-muted">
        Reported:
        ${esc(r.reported_age_text ||
          r.reported_at_approx ||
          "Time unknown")}
      </p>
      ${url ? `
        <a href="${esc(url)}"
          target="_blank"
          rel="noopener noreferrer">
          View original source
        </a>
      ` : ""}
    `;
    return card;
  }

  function drawReports(id, kind) {
    const box = $(id);
    if (!box) return;
    const content = box.querySelector(
      ".ps29-content"
    );
    content.replaceChildren();

    if (!location.state) {
      content.textContent =
        "Select your location above to see " +
        "geographically relevant reports.";
      return;
    }

    const matches = sightings
      .filter(scoped)
      .filter(recent)
      .filter(r => {
        const scope = norm(r.inventory_scope);
        if (kind === "online") {
          return scope === "online";
        }
        return scope === "physical_store";
      })
      .slice(0,30);

    if (!matches.length) {
      content.textContent =
        "No recent matching community reports. " +
        "This does not mean stores are out of stock.";
      return;
    }

    make("p",{
      class:"ps29-muted",
      text:matches.length +
        " recent unverified reports. " +
        "Do not treat these as confirmed inventory."
    },content);

    matches.forEach(r =>
      content.appendChild(communityCard(r))
    );
  }

  function matchingServers() {
    if (!location.state) {
      return {
        local:[],
        national:directory.filter(
          d => !(d.states || []).length
        )
      };
    }

    const local = directory.filter(d => {
      const states = d.states || [];
      const cities = d.cities || [];

      if (!states.includes(location.state)) {
        return false;
      }

      if (!cities.length) return true;

      return !!location.city &&
        cities.some(c =>
          norm(c) === norm(location.city)
        );
    });

    const national = directory.filter(
      d => !(d.states || []).length
    );

    return {local,national};
  }

  function drawDiscord() {
    const box = $("ps29Discord");
    if (!box) return;

    const content = box.querySelector(
      ".ps29-content"
    );
    content.replaceChildren();

    const {local,national} = matchingServers();

    make("p",{
      class:"ps29-muted",
      text:"Location: " + labelLocation()
    },content);

    if (!local.length) {
      make("p",{
        class:"ps29-muted",
        text:"No verified regional Discord " +
          "directory entries are currently " +
          "available for this location. " +
          "Showing nationwide communities instead."
      },content);
    }

    const groups = [
      ["Regional communities",local],
      ["Nationwide communities",national]
    ];

    groups.forEach(([title,items]) => {
      if (!items.length) return;

      make("h4",{text:title},content);

      items.forEach(s => {
        const url = safeURL(s.url);
        if (!url) return;

        const card = make("div",{
          class:"ps29-card"
        },content);

        make("strong",{
          text:s.name
        },card);

        make("p",{
          class:"ps29-muted",
          text:(s.games || []).join(", ") ||
            "Trading card games"
        },card);

        const link = make("a",{
          href:url,
          target:"_blank",
          rel:"noopener noreferrer",
          text:"Open Discord server"
        },card);
      });
    });

    make("p",{
      class:"ps29-muted",
      text:"Directory links only. Pokestock " +
        "does not read Discord messages " +
        "without authorized integration."
    },content);
  }

  function drawShipment() {
    const box = $("ps29Shipment");
    if (!box) return;

    const content = box.querySelector(
      ".ps29-content"
    );
    content.replaceChildren();

    if (!location.state) {
      content.textContent =
        "Choose your location to inspect " +
        "recent local restock reports.";
      return;
    }

    const matches = sightings
      .filter(scoped)
      .filter(recent)
      .filter(r =>
        norm(r.inventory_scope) ===
        "physical_store"
      );

    make("p",{
      class:"ps29-muted",
      text:matches.length +
        " recent community shelf sightings " +
        "for " + labelLocation() + ". " +
        "These are not confirmed shipments " +
        "and are not added to the probability " +
        "chart without validated evidence."
    },content);

    matches.slice(0,20).forEach(r =>
      content.appendChild(communityCard(r))
    );
  }

  function drawAll() {
    drawReports("ps29Stores","store");
    drawReports("ps29Online","online");
    drawShipment();
    drawDiscord();

    const status = $("ps29LocationStatus");
    if (status) {
      status.textContent =
        "Active location: " + labelLocation();
    }
  }

  function applyLocation() {
    const city = $("ps29City").value.trim();
    const state = stateCode(
      $("ps29State").value
    );

    if (!state) {
      $("ps29LocationStatus").textContent =
        "Enter a valid US state abbreviation.";
      return;
    }

    location.city = city.slice(0,100);
    location.state = state;
    location.radius = Number(
      $("ps29Radius").value
    ) || 50;

    persist();
    drawAll();
  }

  async function detectLocation() {
    const status = $("ps29LocationStatus");

    if (!navigator.geolocation) {
      status.textContent =
        "Geolocation unavailable. Enter " +
        "your city and state manually.";
      return;
    }

    status.textContent =
      "Requesting location permission...";

    navigator.geolocation.getCurrentPosition(
      async position => {
        try {
          const lat =
            position.coords.latitude;
          const lon =
            position.coords.longitude;

          const url =
            "https://nominatim.openstreetmap.org/" +
            "reverse?format=json&zoom=10" +
            "&lat=" + encodeURIComponent(lat) +
            "&lon=" + encodeURIComponent(lon);

          const response = await fetch(url);
          if (!response.ok) {
            throw Error("Reverse lookup failed");
          }

          const result = await response.json();
          const a = result.address || {};

          const state = stateCode(
            a.state_code || a.state
          );

          if (!state) {
            throw Error("US state not resolved");
          }

          const city = (
            a.city || a.town ||
            a.village || a.municipality || ""
          );

          $("ps29City").value = city;
          $("ps29State").value = state;
          applyLocation();
        } catch {
          status.textContent =
            "Could not resolve your location. " +
            "Enter city and state manually.";
        }
      },
      () => {
        status.textContent =
          "Location permission unavailable. " +
          "Enter city and state manually.";
      },
      {
        enableHighAccuracy:false,
        timeout:12000,
        maximumAge:300000
      }
    );
  }

  function installControls() {
    const host = document.querySelector("main") ||
      document.body;

    const panel = document.createElement("div");
    panel.id = "ps29Location";
    panel.className = "ps29-panel";

    panel.innerHTML = `
      <h3>Location-Based Stock Intelligence</h3>
      <p class="ps29-muted">
        Your location controls local reports
        and Discord recommendations throughout
        Pokestock.
      </p>
      <div class="ps29-controls">
        <input id="ps29City"
          placeholder="City"
          aria-label="City">
        <input id="ps29State"
          placeholder="State (VA, CA, TX...)"
          aria-label="State">
        <select id="ps29Radius"
          aria-label="Preferred radius">
          <option value="25">25 miles</option>
          <option value="50">50 miles</option>
          <option value="100">100 miles</option>
          <option value="250">250 miles</option>
        </select>
        <button id="ps29Apply">
          Apply location
        </button>
        <button id="ps29Detect">
          Use my location
        </button>
      </div>
      <p id="ps29LocationStatus"
        class="ps29-muted"></p>
      <p class="ps29-muted">
        Current report matching uses exact
        city or state. Radius filtering will
        require verified coordinates.
      </p>
    `;

    host.insertBefore(panel,host.firstChild);

    $("ps29City").value = location.city;
    $("ps29State").value = location.state;
    $("ps29Radius").value =
      String(location.radius);

    $("ps29Apply").addEventListener(
      "click",applyLocation
    );
    $("ps29Detect").addEventListener(
      "click",detectLocation
    );
  }

  async function loadJSON(path, fallback) {
    try {
      const response = await fetch(
        path + "?v=" + Date.now(),
        {cache:"no-store"}
      );
      if (!response.ok) return fallback;
      return await response.json();
    } catch {
      return fallback;
    }
  }

  async function start() {
    if ($("ps29Location")) return;

    installControls();

    section(
      "stores",
      "Nearby Community Stock Sightings",
      "ps29Stores"
    );
    section(
      "online",
      "Community Online Restock Alerts",
      "ps29Online"
    );
    section(
      "shipments",
      "Local Restock Evidence",
      "ps29Shipment"
    );
    section(
      "releases",
      "Discord Servers for Your Location",
      "ps29Discord"
    );

    const [reports,servers] =
      await Promise.all([
        loadJSON(
          "data/v34_public_sightings.json",
          []
        ),
        loadJSON(
          "data/discord_directory_29.json",
          []
        )
      ]);

    sightings = Array.isArray(reports)
      ? reports : [];

    directory = Array.isArray(servers)
      ? servers : NATIONAL;

    drawAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",start,
      {once:true}
    );
  } else {
    start();
  }
})();
