(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c])
  );

  const days = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday"
  ];

  const safe = value => {
    try {
      const u = new URL(value);
      return u.protocol === "https:" ? u : null;
    } catch {
      return null;
    }
  };

  function mediaHTML(post) {
    const u = safe(
      post.original_post_url || post.url
    );
    if (!u) return "";

    const host = u.hostname.toLowerCase();
    const path = u.pathname;

    // Facebook's official public-post iframe endpoint.
    if (
      host.endsWith("facebook.com") &&
      (
        path.includes("/posts/") ||
        path.includes("/permalink/") ||
        path.includes("/videos/") ||
        path.includes("/groups/")
      )
    ) {
      const src =
        "https://www.facebook.com/plugins/post.php?href=" +
        encodeURIComponent(u.href) +
        "&show_text=true&width=500";

      return `
        <iframe
          title="Public Facebook post"
          loading="lazy"
          referrerpolicy="strict-origin-when-cross-origin"
          style="width:100%;height:470px;border:0"
          src="${esc(src)}">
        </iframe>`;
    }

    // Instagram's public embed endpoint.
    if (
      host.endsWith("instagram.com") &&
      /^\/(p|reel|tv)\/[^/]+/.test(path)
    ) {
      const parts = path.split("/").filter(Boolean);
      const src =
        "https://www.instagram.com/" +
        parts[0] + "/" + parts[1] + "/embed/";

      return `
        <iframe
          title="Public Instagram post"
          loading="lazy"
          style="width:100%;height:530px;border:0"
          src="${esc(src)}">
        </iframe>`;
    }

    // Reddit public comment-post embeds.
    if (
      host.endsWith("reddit.com") &&
      path.includes("/comments/")
    ) {
      const src =
        "https://www.redditmedia.com" +
        path.replace(/\/$/, "") +
        "?ref_source=embed&ref=share";

      return `
        <iframe
          title="Reddit post"
          loading="lazy"
          style="width:100%;height:420px;border:0"
          src="${esc(src)}">
        </iframe>`;
    }

    return "";
  }

  // Augment the existing social cards with real embeds.
  // Do not substitute unrelated product photographs.
  function addMediaToSocial() {
    if (!$("smLocal") || !$("smOther")) return;

    const cards = [
      ...document.querySelectorAll(
        "#smLocal .sm-card, #smOther .sm-card"
      )
    ];

    const posts = window.psSocialMediaPosts || [];
    if (!Array.isArray(posts) || !posts.length) return;

    for (const card of cards) {
      if (card.querySelector(".ps-media-embed")) continue;

      const anchor = card.querySelector(
        'a[href^="https://"]'
      );
      if (!anchor) continue;

      const p = posts.find(x =>
        x.url === anchor.href ||
        x.original_post_url === anchor.href
      );
      if (!p) continue;

      const media = mediaHTML(p);
      if (!media) continue;

      const details = document.createElement("details");
      details.className = "ps-media-embed";
      details.innerHTML =
        "<summary>View original post and media</summary>" +
        media;
      card.appendChild(details);
    }
  }

  // Expose media helper for integration with the
  // existing social-media renderer.
  window.PokeStockMedia = {
    embed: mediaHTML,
    refresh: addMediaToSocial
  };

  const section = $("shipments");
  if (!section) return;

  const wrap = document.createElement("div");
  wrap.id = "psWeekdayForecast";

  wrap.innerHTML = `
    <style>
      #psWeekdayForecast {
        margin:22px 0;
        padding:18px;
        border:1px solid #435574;
        border-radius:18px;
        background:#152139;
        color:#eef3fc;
      }
      #psWeekdayForecast .ps-filters {
        display:flex;
        flex-wrap:wrap;
        gap:10px;
        margin:14px 0;
      }
      #psWeekdayForecast select {
        min-width:150px;
        max-width:100%;
        padding:10px;
        border-radius:9px;
        background:#202e49;
        color:white;
        border:1px solid #536581;
      }
      #psWeekdayForecast .ps-bars {
        display:grid;
        grid-template-columns:repeat(7,minmax(0,1fr));
        align-items:end;
        gap:8px;
        min-height:220px;
        margin-top:20px;
      }
      #psWeekdayForecast .ps-col {
        display:flex;
        flex-direction:column;
        justify-content:flex-end;
        align-items:center;
        gap:7px;
        text-align:center;
        min-width:0;
      }
      #psWeekdayForecast .ps-bar-track {
        width:100%;
        height:145px;
        display:flex;
        align-items:flex-end;
        background:#24334e;
        border-radius:8px;
        overflow:hidden;
      }
      #psWeekdayForecast .ps-bar {
        width:100%;
        background:linear-gradient(
          180deg,#53d5f5,#5379f3
        );
        border-radius:8px 8px 0 0;
      }
      #psWeekdayForecast .ps-day {
        font-size:11px;
      }
      #psWeekdayForecast .ps-pct {
        font-size:12px;
        font-weight:800;
      }
      #psWeekdayForecast .ps-note {
        color:#b9c8e0;
        font-size:12px;
        line-height:1.6;
      }
      @media(max-width:600px) {
        #psWeekdayForecast {
          padding:12px;
        }
        #psWeekdayForecast .ps-bars {
          gap:4px;
        }
        #psWeekdayForecast .ps-day {
          font-size:10px;
        }
        #psWeekdayForecast .ps-pct {
          font-size:10px;
        }
      }
    </style>

    <h2>📊 Weekly Restock Likelihood</h2>
    <p class="ps-note">
      Monday–Sunday historical restock patterns.
      These percentages describe observed restock
      weekdays, not confirmed delivery schedules.
    </p>

    <div class="ps-filters">
      <select id="psChartRetailer">
        <option value="">All retailers</option>
      </select>
      <select id="psChartGame">
        <option value="">All TCGs</option>
      </select>
      <select id="psChartCity">
        <option value="">All locations</option>
      </select>
    </div>

    <div id="psChartStatus" class="ps-note">
      Loading shipment intelligence...
    </div>

    <div id="psChartBars" class="ps-bars"></div>

    <p class="ps-note">
      Social posts can contribute potential restock
      evidence. Unverified posts and posts without
      an actual observation date do not influence
      percentages.
    </p>
  `;

  section.insertBefore(wrap, section.firstChild);

  let predictions = [];

  function options(id, values) {
    const sel = $(id);
    for (const value of [...new Set(values)]
      .filter(Boolean).sort()) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value;
      sel.appendChild(opt);
    }
  }

  function draw() {
    const retailer = $("psChartRetailer").value;
    const game = $("psChartGame").value;
    const city = $("psChartCity").value;

    const selected = predictions.filter(p =>
      (!retailer || p.retailer === retailer) &&
      (!game || p.game === game) &&
      (!city || p.city === city)
    );

    const counts = Array(7).fill(0);
    let sample = 0;

    for (const p of selected) {
      if (!Array.isArray(p.counts)) continue;
      for (let i = 0; i < 7; i++) {
        counts[i] += Number(p.counts[i] || 0);
      }
      sample += Number(p.sample_size || 0);
    }

    if (sample < 5) {
      $("psChartStatus").textContent =
        "Insufficient verified, precisely dated " +
        "observations (" + sample +
        "). No defensible weekday percentages yet.";
      $("psChartBars").innerHTML = "";
      return;
    }

    const total = sample + 7;
    const pct = counts.map(c =>
      100 * (c + 1) / total
    );

    const maximum = Math.max(...pct);

    $("psChartStatus").textContent =
      sample + " dated restock observations. " +
      "Percentages are smoothed historical frequencies.";

    $("psChartBars").innerHTML = days.map((day, i) => {
      const height = Math.max(
        4, pct[i] / maximum * 145
      );
      return `
        <div class="ps-col">
          <span class="ps-pct">
            ${pct[i].toFixed(1)}%
          </span>
          <div class="ps-bar-track">
            <div class="ps-bar"
              style="height:${height}px">
            </div>
          </div>
          <span class="ps-day">
            ${esc(day.slice(0,3))}
          </span>
        </div>`;
    }).join("");
  }

  fetch(
    "data/social_shipment_predictions.json?t=" +
    Date.now(),
    {cache:"no-store"}
  )
    .then(r => {
      if (!r.ok) throw Error("Data unavailable");
      return r.json();
    })
    .then(d => {
      predictions = Array.isArray(d.predictions)
        ? d.predictions : [];

      options(
        "psChartRetailer",
        predictions.map(x => x.retailer)
      );
      options(
        "psChartGame",
        predictions.map(x => x.game)
      );
      options(
        "psChartCity",
        predictions.map(x => x.city)
      );

      [
        "psChartRetailer",
        "psChartGame",
        "psChartCity"
      ].forEach(id => $(id).onchange = draw);

      draw();
    })
    .catch(e => {
      $("psChartStatus").textContent =
        "Unable to load predictions: " + e.message;
    });
})();
