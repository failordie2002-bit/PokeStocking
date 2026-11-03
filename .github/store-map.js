
/* PokéStock V7 — Verified Store Stock Map
   Free Leaflet + OpenStreetMap map.
   Only displays recent, explicitly verified
   store-level in-stock records.
*/

(() => {
  const MAX_AGE_HOURS = 6;
  const DATA_URL = "data/status.json";
  const LEAFLET_CSS =
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
  const LEAFLET_JS =
    "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";

  let map;
  let layer;
  let userLocation = null;
  let records = [];

  function escapeHTML(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[c]
    );
  }

  function addStyle() {
    const css = document.createElement("style");
    css.textContent = `
      .stock-map-panel {
        background:#191e2a;
        border:1px solid #30394c;
        border-radius:18px;
        padding:18px;
        margin:20px 0;
        color:#f5f4ef;
      }
      .stock-map-panel h2 {
        margin:0 0 8px;
        font-size:22px;
      }
      .stock-map-panel p {
        color:#a0a9ba;
        font-size:13px;
      }
      .stock-map-controls {
        display:flex;
        flex-wrap:wrap;
        gap:9px;
        margin:15px 0;
      }
      .stock-map-controls button,
      .stock-map-controls select {
        background:#252d3e;
        border:1px solid #414c61;
        border-radius:9px;
        padding:10px;
        color:#fff;
        font-size:13px;
      }
      .stock-map-controls button {
        background:#d6a83e;
        color:#17130a;
        font-weight:700;
      }
      #pokestock-map {
        height:390px;
        width:100%;
        border-radius:12px;
        background:#252d3e;
        z-index:0;
      }
      #stock-map-status {
        padding:12px 0;
        font-size:13px;
        color:#a0a9ba;
      }
      .stock-map-results {
        display:grid;
        gap:10px;
      }
      .stock-map-result {
        border:1px solid #30394c;
        border-radius:10px;
        padding:12px;
      }
      .stock-map-result strong {
        color:#f0cc76;
      }
      .stock-map-result small {
        display:block;
        margin:6px 0;
        color:#a0a9ba;
      }
      .stock-map-result a {
        color:#f0cc76;
      }
      @media(max-width:600px) {
        #pokestock-map {height:320px}
        .stock-map-panel {padding:12px}
      }
    `;
    document.head.appendChild(css);
  }

  function buildPanel() {
    const dashboard = document.getElementById(
      "dashboard"
    );

    if (!dashboard) return false;

    const panel = document.createElement("section");
    panel.className = "stock-map-panel";

    panel.innerHTML = `
      <h2>Nearby TCG Stock Map</h2>
      <p>
        Find recently verified Pokémon and
        Union Arena products near you.
        Location access is optional.
      </p>

      <div class="stock-map-controls">
        <button id="stock-locate">
          Use my location
        </button>

        <select id="stock-game">
          <option value="all">All games</option>
          <option value="pokemon">Pokémon</option>
          <option value="union arena">
            Union Arena
          </option>
        </select>

        <select id="stock-radius">
          <option value="10">10 miles</option>
          <option value="25">25 miles</option>
          <option value="50" selected>
            50 miles
          </option>
          <option value="100">100 miles</option>
          <option value="250">250 miles</option>
        </select>

        <button id="stock-refresh">
          Refresh
        </button>
      </div>

      <div id="pokestock-map"></div>

      <div id="stock-map-status">
        Loading verified stock data...
      </div>

      <div
        id="stock-map-results"
        class="stock-map-results"
      ></div>
    `;

    const hero = dashboard.querySelector(".hero");

    if (hero) {
      hero.insertAdjacentElement("afterend", panel);
    } else {
      dashboard.prepend(panel);
    }

    return true;
  }

  function loadLeaflet() {
    return new Promise((resolve, reject) => {
      if (window.L) {
        resolve();
        return;
      }

      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = LEAFLET_CSS;
      document.head.appendChild(link);

      const script = document.createElement("script");
      script.src = LEAFLET_JS;
      script.onload = resolve;
      script.onerror = () => reject(
        new Error("Map library unavailable")
      );
      document.head.appendChild(script);
    });
  }

  function distanceMiles(a, b) {
    const radians = d => d * Math.PI / 180;
    const R = 3958.8;

    const latDiff = radians(b.lat - a.lat);
    const lonDiff = radians(b.lon - a.lon);

    const x =
      Math.sin(latDiff / 2) ** 2 +
      Math.cos(radians(a.lat)) *
      Math.cos(radians(b.lat)) *
      Math.sin(lonDiff / 2) ** 2;

    return 2 * R * Math.asin(
      Math.min(1, Math.sqrt(x))
    );
  }

  function validRecord(r) {
    if (!r || typeof r !== "object") return false;

    if (r.status !== "In stock") return false;
    if (!r.store_name || !r.product_name) return false;
    if (!r.game || !r.source_url) return false;
    if (!r.verified_at) return false;

    const lat = Number(r.lat);
    const lon = Number(r.lon);

    if (!Number.isFinite(lat) ||
        !Number.isFinite(lon) ||
        lat < -90 || lat > 90 ||
        lon < -180 || lon > 180) {
      return false;
    }

    let source;
    try {
      source = new URL(r.source_url);
    } catch {
      return false;
    }

    if (source.protocol !== "https:") return false;

    const verified = Date.parse(r.verified_at);

    if (!Number.isFinite(verified)) return false;

    const age = Date.now() - verified;

    return age >= 0 &&
      age <= MAX_AGE_HOURS * 3600000;
  }

  function setStatus(message) {
    document.getElementById(
      "stock-map-status"
    ).textContent = message;
  }

  function directionsURL(r) {
    return (
      "https://www.google.com/maps/dir/?api=1" +
      "&destination=" +
      encodeURIComponent(r.lat + "," + r.lon)
    );
  }

  function render() {
    if (!map || !layer) return;

    layer.clearLayers();

    const game = document.getElementById(
      "stock-game"
    ).value;

    const radius = Number(
      document.getElementById("stock-radius").value
    );

    let visible = records.filter(r => {
      if (game !== "all" &&
          String(r.game).toLowerCase() !== game) {
        return false;
      }

      if (userLocation) {
        return distanceMiles(userLocation, {
          lat: Number(r.lat),
          lon: Number(r.lon)
        }) <= radius;
      }

      return true;
    });

    visible.sort((a, b) => {
      if (!userLocation) return 0;

      return distanceMiles(userLocation, a) -
        distanceMiles(userLocation, b);
    });

    const results = document.getElementById(
      "stock-map-results"
    );

    results.replaceChildren();

    const bounds = [];

    visible.forEach(r => {
      const lat = Number(r.lat);
      const lon = Number(r.lon);

      const marker = L.marker([lat, lon])
        .addTo(layer);

      const popup = document.createElement("div");

      const heading = document.createElement("strong");
      heading.textContent = r.store_name;

      const details = document.createElement("p");
      details.textContent =
        r.product_name + " — In stock";

      const checked = document.createElement("small");
      checked.textContent =
        "Verified: " +
        new Date(r.verified_at).toLocaleString();

      const source = document.createElement("a");
      source.href = r.source_url;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      source.textContent = "View stock source";

      popup.append(
        heading,
        document.createElement("br"),
        details,
        checked,
        document.createElement("br"),
        source
      );

      marker.bindPopup(popup);
      bounds.push([lat, lon]);

      const card = document.createElement("div");
      card.className = "stock-map-result";

      const title = document.createElement("strong");
      title.textContent = r.store_name;

      const description = document.createElement("div");
      description.textContent =
        r.product_name + " — In stock";

      const meta = document.createElement("small");
      const distance = userLocation
        ? distanceMiles(userLocation, {lat, lon})
            .toFixed(1) + " miles · "
        : "";

      meta.textContent =
        distance +
        "Verified " +
        new Date(r.verified_at).toLocaleString();

      const link = document.createElement("a");
      link.href = directionsURL(r);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Get directions";

      card.append(title, description, meta, link);
      results.appendChild(card);
    });

    if (userLocation) {
      L.circleMarker(
        [userLocation.lat, userLocation.lon],
        {
          radius:7,
          color:"#82b8ff",
          fillColor:"#82b8ff",
          fillOpacity:1
        }
      ).addTo(layer).bindPopup("Your location");

      map.setView(
        [userLocation.lat, userLocation.lon],
        11
      );
    } else if (bounds.length) {
      map.fitBounds(bounds, {
        padding:[30,30],
        maxZoom:12
      });
    }

    if (!visible.length) {
      setStatus(
        "No recently verified in-stock stores " +
        "match these filters. This does not mean " +
        "nearby stores are sold out."
      );
    } else {
      setStatus(
        visible.length +
        " recent verified stock report(s) found."
      );
    }
  }

  async function refresh() {
    setStatus("Checking published stock reports...");

    try {
      const response = await fetch(
        DATA_URL + "?t=" + Date.now(),
        {cache:"no-store"}
      );

      if (!response.ok) {
        throw new Error(
          "Inventory feed returned HTTP " +
          response.status
        );
      }

      const data = await response.json();

      const supplied = Array.isArray(
        data.store_inventory
      ) ? data.store_inventory : [];

      records = supplied.filter(validRecord);

      render();
    } catch (error) {
      records = [];
      render();
      setStatus(
        "Inventory feed unavailable: " +
        error.message
      );
    }
  }

  function locate() {
    if (!navigator.geolocation) {
      setStatus(
        "Geolocation is not supported."
      );
      return;
    }

    setStatus("Requesting location permission...");

    navigator.geolocation.getCurrentPosition(
      position => {
        userLocation = {
          lat:position.coords.latitude,
          lon:position.coords.longitude
        };

        render();
      },
      () => {
        setStatus(
          "Location unavailable or permission denied. " +
          "You can still view verified stock reports."
        );
      },
      {
        enableHighAccuracy:false,
        timeout:12000,
        maximumAge:300000
      }
    );
  }

  async function init() {
    addStyle();

    if (!buildPanel()) return;

    try {
      await loadLeaflet();

      map = L.map("pokestock-map").setView(
        [39.5, -98.35],
        4
      );

      L.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          attribution:
            "&copy; OpenStreetMap contributors",
          maxZoom:19
        }
      ).addTo(map);

      layer = L.layerGroup().addTo(map);

      document.getElementById(
        "stock-locate"
      ).addEventListener("click", locate);

      document.getElementById(
        "stock-refresh"
      ).addEventListener("click", refresh);

      document.getElementById(
        "stock-game"
      ).addEventListener("change", render);

      document.getElementById(
        "stock-radius"
      ).addEventListener("change", render);

      await refresh();

      // Keep the published reports fresh.
      setInterval(refresh, 60000);

      // Fix map dimensions after navigation.
      document.querySelectorAll(
        ".nav-btn"
      ).forEach(button => {
        button.addEventListener(
          "click",
          () => setTimeout(
            () => map.invalidateSize(),
            100
          )
        );
      });

    } catch (error) {
      setStatus(
        "Unable to initialize map: " +
        error.message
      );
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      init
    );
  } else {
    init();
  }
})();
