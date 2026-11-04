(() => {
  "use strict";

  const $ = id => document.getElementById(id);

  const esc = value => String(
    value ?? ""
  ).replace(
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
    "Mon", "Tue", "Wed", "Thu",
    "Fri", "Sat", "Sun"
  ];

  async function json(path) {
    const response = await fetch(
      path + "?v=" + Date.now(),
      {cache: "no-store"}
    );

    if (!response.ok) {
      throw Error("HTTP " + response.status);
    }

    return response.json();
  }

  function createChart() {
    const section = $("shipments");
    if (!section) return null;

    // The chart is part of the page
    // regardless of available data.
    let root = $("ps26");

    if (root) return root;

    root = document.createElement("div");
    root.id = "ps26";

    root.innerHTML = `
      <style>
        #ps26 {
          margin: 18px 0 26px;
          padding: 18px;
          border: 1px solid #435575;
          border-radius: 16px;
          background: #142039;
          color: #f2f6ff;
        }

        #ps26 h2 {
          margin: 0 0 8px;
        }

        #ps26 .ps26-muted {
          color: #b7c7e1;
          font-size: 13px;
          line-height: 1.5;
        }

        #ps26 .ps26-filters {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin: 16px 0;
        }

        #ps26 select {
          min-width: 120px;
          max-width: 100%;
          padding: 9px;
          border: 1px solid #526685;
          border-radius: 8px;
          background: #253451;
          color: #fff;
        }

        #ps26 .ps26-chart {
          display: grid;
          grid-template-columns:
            repeat(7, minmax(0, 1fr));
          gap: 6px;
          margin: 16px 0;
        }

        #ps26 .ps26-col {
          min-width: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 7px;
        }

        #ps26 .ps26-track {
          height: 155px;
          width: 100%;
          background: #263550;
          border-radius: 8px;
          display: flex;
          align-items: flex-end;
          overflow: hidden;
        }

        #ps26 .ps26-bar {
          width: 100%;
          background: linear-gradient(
            #57d5f1, #526ef0
          );
          border-radius: 7px 7px 0 0;
          min-height: 0;
        }

        #ps26 .ps26-value {
          font-size: 12px;
          font-weight: 700;
          white-space: nowrap;
        }

        #ps26 .ps26-day {
          font-size: 12px;
        }

        #ps26 .ps26-status {
          margin: 12px 0;
          padding: 10px;
          background: #22314b;
          border-radius: 8px;
          font-size: 13px;
        }

        #ps26 .ps26-link {
          display: inline-block;
          margin: 5px 6px 5px 0;
          padding: 8px 11px;
          border: 1px solid #506688;
          border-radius: 8px;
          color: #bde9ff;
          text-decoration: none;
        }

        #ps26 .ps26-retailers {
          margin-top: 22px;
          padding-top: 18px;
          border-top: 1px solid #405270;
        }

        #ps26 .ps26-retail-grid {
          display: grid;
          grid-template-columns:
            repeat(
              auto-fit,
              minmax(200px, 1fr)
            );
          gap: 10px;
          margin-top: 12px;
        }

        #ps26 .ps26-retail-card {
          padding: 12px;
          border: 1px solid #405270;
          border-radius: 10px;
          background: #1b2a43;
        }

        #ps26 .ps26-retail-card h3 {
          margin: 0 0 8px;
          font-size: 15px;
        }

        @media(max-width: 600px) {
          #ps26 {
            padding: 12px;
          }

          #ps26 .ps26-chart {
            gap: 3px;
          }

          #ps26 .ps26-value,
          #ps26 .ps26-day {
            font-size: 10px;
          }

          #ps26 select {
            min-width: 100px;
          }
        }
      </style>

      <h2>📊 Weekly Restock Likelihood</h2>

      <p class="ps26-muted">
        Monday–Sunday restock observations
        for your selected retailer, game,
        and location.
      </p>

      <div class="ps26-filters">
        <select id="ps26Retailer">
          <option value="">All retailers</option>
        </select>

        <select id="ps26Game">
          <option value="">All TCGs</option>
        </select>

        <select id="ps26City">
          <option value="">All locations</option>
        </select>

        <select id="ps26Type">
          <option value="restocks">
            Restock sightings
          </option>
          <option value="shipments">
            Confirmed shipments
          </option>
        </select>
      </div>

      <div id="ps26Status"
        class="ps26-status">
        Loading evidence...
      </div>

      <div id="ps26Chart"
        class="ps26-chart">
      </div>

      <p class="ps26-muted">
        Percentages represent the relative
        share of recorded observations by
        weekday. They are not guaranteed
        shipment arrival probabilities.
        Unverified reports have reduced weight.
      </p>

      <div class="ps26-retailers">
        <h2>🏪 Pharmacy & Dollar Store Stock</h2>

        <p class="ps26-muted">
          Search retailer listings for
          trading cards. Store-level stock
          is not confirmed unless independently
          verified.
        </p>

        <div class="ps26-filters">
          <select id="ps26RetailGame">
            <option value="">
              Choose a trading card game
            </option>
          </select>
        </div>

        <div id="ps26RetailGrid"
          class="ps26-retail-grid">
        </div>
      </div>
    `;

    // Keep the chart at the top of
    // Shipment Center.
    section.prepend(root);

    // Older chart remains installed but
    // is superseded by this one.
    const old = $("psWeekdayForecast");
    if (old) old.hidden = true;

    return root;
  }

  function options(select, values) {
    if (!select) return;

    const current = select.value;

    select.querySelectorAll(
      "option:not(:first-child)"
    ).forEach(x => x.remove());

    [...new Set(values)]
      .filter(Boolean)
      .sort((a,b) => a.localeCompare(b))
      .forEach(value => {
        const opt =
          document.createElement("option");
        opt.value = value;
        opt.textContent = value;
        select.appendChild(opt);
      });

    if ([...select.options].some(
      o => o.value === current
    )) {
      select.value = current;
    }
  }

  function renderEmpty() {
    const chart = $("ps26Chart");
    if (!chart) return;

    chart.innerHTML = days.map(day => `
      <div class="ps26-col">
        <span class="ps26-value">N/A</span>
        <div class="ps26-track">
          <div class="ps26-bar"
            style="height:0%">
          </div>
        </div>
        <span class="ps26-day">
          ${day}
        </span>
      </div>
    `).join("");
  }

  async function initChart() {
    if (!createChart()) return;

    renderEmpty();

    const status = $("ps26Status");

    try {
      const data = await json(
        "data/weekday_chart_26.json"
      );

      const events = Array.isArray(
        data.events
      ) ? data.events : [];

      options(
        $("ps26Retailer"),
        events.map(e => e.retailer)
      );

      options(
        $("ps26Game"),
        events.map(e => e.game)
      );

      options(
        $("ps26City"),
        events.map(e => e.city)
      );

      function draw() {
        const retailer =
          $("ps26Retailer").value;
        const game =
          $("ps26Game").value;
        const city =
          $("ps26City").value;
        const type =
          $("ps26Type").value;

        const filtered = events.filter(e =>
          (!retailer ||
            e.retailer === retailer) &&
          (!game ||
            e.game === game) &&
          (!city ||
            e.city === city) &&
          (
            type !== "shipments" ||
            e.shipment_confirmed === true
          )
        );

        const counts = Array(7).fill(0);

        let verified = 0;
        let effective = 0;

        for (const e of filtered) {
          const day = Number(e.weekday);
          if (
            !Number.isInteger(day) ||
            day < 0 || day > 6
          ) continue;

          const weight = type === "shipments"
            ? 1
            : Math.max(
                0,
                Number(e.weight) || 0
              );

          counts[day] += weight;
          effective += weight;

          if (e.verified) verified++;
        }

        const enough =
          filtered.length >= 5 &&
          verified >= 2 &&
          effective >= 3;

        if (!enough) {
          status.textContent =
            filtered.length +
            " dated observations; " +
            verified +
            " verified. Not enough evidence " +
            "for meaningful percentages.";

          renderEmpty();
          return;
        }

        const total = effective + 7;

        const percentages = counts.map(
          count =>
            100 * (count + 1) / total
        );

        const maximum =
          Math.max(...percentages);

        status.textContent =
          filtered.length +
          " observations, including " +
          verified +
          " verified reports. Historical " +
          "weekday distribution shown.";

        $("ps26Chart").innerHTML =
          days.map((day,i) => {
            const pct = percentages[i];
            const height =
              pct / maximum * 100;

            return `
              <div class="ps26-col">
                <span class="ps26-value">
                  ${pct.toFixed(1)}%
                </span>

                <div class="ps26-track">
                  <div class="ps26-bar"
                    style="height:${height}%">
                  </div>
                </div>

                <span class="ps26-day">
                  ${day}
                </span>
              </div>
            `;
          }).join("");
      }

      [
        "ps26Retailer",
        "ps26Game",
        "ps26City",
        "ps26Type"
      ].forEach(id => {
        $(id).addEventListener(
          "change", draw
        );
      });

      draw();

    } catch (error) {
      status.textContent =
        "Evidence unavailable: " +
        error.message;
      renderEmpty();
    }
  }

  async function initRetailers() {
    const target = $("ps26RetailGrid");
    if (!target) return;

    try {
      const data = await json(
        "data/retail_expansion_26.json"
      );

      const retailers =
        data.retailers || [];

      const games =
        data.games_monitored || [];

      options($("ps26RetailGame"), games);

      if (games.length) {
        $("ps26RetailGame").value =
          games.includes("Pokémon")
            ? "Pokémon"
            : games[0];
      }

      function draw() {
        const game =
          $("ps26RetailGame").value;

        target.innerHTML =
          retailers.map(retailer => {
            const item = (
              retailer.games || []
            ).find(x =>
              x.game === game
            );

            const url = item?.search_url ||
              retailer.website;

            let safeUrl = "";

            try {
              const parsed = new URL(url);
              if (
                parsed.protocol === "https:"
              ) {
                safeUrl = parsed.href;
              }
            } catch {}

            return `
              <div class="ps26-retail-card">
                <h3>
                  ${esc(retailer.name)}
                </h3>

                <p class="ps26-muted">
                  Local stock: Not verified
                </p>

                ${safeUrl ? `
                  <a class="ps26-link"
                    target="_blank"
                    rel="noopener noreferrer"
                    href="${esc(safeUrl)}">
                    Check listings
                  </a>
                ` : ""}
              </div>
            `;
          }).join("");
      }

      $("ps26RetailGame")
        .addEventListener("change", draw);

      draw();

    } catch (error) {
      target.textContent =
        "Retailer listings unavailable: " +
        error.message;
    }
  }

  // DOM is parsed before deferred scripts
  // execute, so the chart is installed
  // immediately when this file runs.
  createChart();
  initChart();
  initRetailers();
})();
