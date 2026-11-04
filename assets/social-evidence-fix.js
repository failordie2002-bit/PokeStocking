(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&":"&amp;",
      "<":"&lt;",
      ">":"&gt;",
      '"':"&quot;",
      "'":"&#39;"
    }[c])
  );

  const valid = value => {
    try {
      const u = new URL(value);
      return u.protocol === "https:" ? u : null;
    } catch {
      return null;
    }
  };

  // Only exact original post permalinks
  // qualify for native embeds.
  function embed(post) {
    const u = valid(
      post.original_post_url || post.url
    );
    if (!u) return "";

    const host = u.hostname.toLowerCase();
    const path = u.pathname;

    if (
      (
        host === "www.facebook.com" ||
        host === "facebook.com" ||
        host === "m.facebook.com"
      ) &&
      (
        path.includes("/posts/") ||
        path.includes("/permalink/") ||
        path.includes("/videos/") ||
        path.startsWith("/reel/")
      )
    ) {
      const src = path.includes("/videos/")
        ? "https://www.facebook.com/plugins/video.php?href="
        : "https://www.facebook.com/plugins/post.php?href=";

      return `
        <iframe
          title="Original public Facebook post"
          loading="lazy"
          style="width:100%;height:480px;border:0"
          src="${esc(
            src + encodeURIComponent(u.href) +
            "&show_text=true&width=500"
          )}">
        </iframe>`;
    }

    if (
      (
        host === "instagram.com" ||
        host === "www.instagram.com"
      ) &&
      /^\/(p|reel|tv)\/[^/]+/.test(path)
    ) {
      const parts = path.split("/").filter(Boolean);
      const src =
        "https://www.instagram.com/" +
        parts[0] + "/" + parts[1] + "/embed/";

      return `
        <iframe
          title="Original public Instagram post"
          loading="lazy"
          style="width:100%;height:540px;border:0"
          src="${esc(src)}">
        </iframe>`;
    }

    if (
      (
        host === "reddit.com" ||
        host.endsWith(".reddit.com")
      ) &&
      path.includes("/comments/")
    ) {
      const src =
        "https://www.redditmedia.com" +
        path.replace(/\/$/, "") +
        "?ref_source=embed&ref=share";

      return `
        <iframe
          title="Original Reddit post"
          loading="lazy"
          style="width:100%;height:460px;border:0"
          src="${esc(src)}">
        </iframe>`;
    }

    return "";
  }

  let feed = [];
  let observing = false;

  function installEmbeds() {
    const social = $("social");
    if (!social || !feed.length) return;

    const cards = social.querySelectorAll(
      "#smLocal .sm-card, #smOther .sm-card"
    );

    for (const card of cards) {
      if (card.querySelector(".ps-real-media")) {
        continue;
      }

      const link = card.querySelector(
        'a[href^="https://"]'
      );
      if (!link) continue;

      const post = feed.find(p =>
        p.url === link.href ||
        p.original_post_url === link.href
      );

      if (!post) continue;

      const markup = embed(post);
      const holder = document.createElement("div");
      holder.className = "ps-real-media";

      if (markup) {
        holder.innerHTML = markup;
        holder.style.marginTop = "12px";
        card.appendChild(holder);
      } else {
        // Indexed posts without a real permalink
        // cannot safely be embedded.
        holder.innerHTML =
          '<p style="font-size:12px;opacity:.75">' +
          'Original media unavailable from this ' +
          'indexed source. Open the source link ' +
          'to view the post.</p>';
        card.appendChild(holder);
      }
    }
  }

  async function loadFeed() {
    try {
      const r = await fetch(
        "data/social_media_feed.json?t=" +
        Date.now(),
        {cache:"no-store"}
      );
      if (!r.ok) throw Error("Feed unavailable");
      const data = await r.json();
      feed = Array.isArray(data.posts)
        ? data.posts : [];

      installEmbeds();

      if (!observing && $("social")) {
        observing = true;

        const observer = new MutationObserver(() => {
          // Avoid an observer loop: only schedule
          // work after a new batch of cards.
          if (observer.pending) return;
          observer.pending = true;
          requestAnimationFrame(() => {
            observer.pending = false;
            installEmbeds();
          });
        });

        for (const id of ["smLocal", "smOther"]) {
          if ($(id)) {
            observer.observe($(id), {
              childList:true
            });
          }
        }
      }
    } catch (e) {
      console.warn("Social media:", e.message);
    }
  }

  // Replace the broken, disconnected
  // window.psSocialMediaPosts dependency.
  if ($("social")) loadFeed();

  // Upgrade the existing shipment chart to use
  // the new evidence-weighted percentages.
  async function loadChart() {
    const chart = $("psWeekdayForecast");
    if (!chart) return;

    try {
      const r = await fetch(
        "data/social_shipment_predictions.json?t=" +
        Date.now(),
        {cache:"no-store"}
      );

      if (!r.ok) return;
      const data = await r.json();
      const predictions = data.predictions || [];

      const retailer = $("psChartRetailer");
      const game = $("psChartGame");
      const city = $("psChartCity");
      const bars = $("psChartBars");
      const status = $("psChartStatus");

      if (
        !retailer || !game || !city ||
        !bars || !status
      ) return;

      function redraw() {
        const matches = predictions.filter(p =>
          (!retailer.value ||
            p.retailer === retailer.value) &&
          (!game.value ||
            p.game === game.value) &&
          (!city.value ||
            p.city === city.value)
        );

        const counts = Array(7).fill(0);
        let verified = 0;
        let community = 0;
        let samples = 0;

        for (const p of matches) {
          verified += p.verified_count || 0;
          community += p.community_count || 0;
          samples += p.sample_size || 0;

          for (let i = 0; i < 7; i++) {
            counts[i] += Number(
              (p.counts || [])[i] || 0
            );
          }
        }

        const effective = counts.reduce(
          (a,b) => a+b, 0
        );

        status.textContent =
          `${verified} verified observations, ` +
          `${community} unverified community reports.`;

        if (
          samples < 5 ||
          verified < 2 ||
          effective < 3
        ) {
          bars.innerHTML =
            '<p style="grid-column:1/-1">' +
            'Not enough evidence for reliable ' +
            'weekday percentages yet.</p>';
          return;
        }

        const percentages = counts.map(
          n => 100 * (n+1)/(effective+7)
        );
        const max = Math.max(...percentages);

        const names = [
          "Mon","Tue","Wed","Thu",
          "Fri","Sat","Sun"
        ];

        bars.innerHTML = names.map((day,i) => `
          <div class="ps-col">
            <span class="ps-pct">
              ${percentages[i].toFixed(1)}%
            </span>
            <div class="ps-bar-track">
              <div class="ps-bar"
                style="height:${
                  145*percentages[i]/max
                }px">
              </div>
            </div>
            <span class="ps-day">${esc(day)}</span>
          </div>
        `).join("");
      }

      // Replace old chart handlers so this
      // version remains authoritative.
      retailer.onchange = redraw;
      game.onchange = redraw;
      city.onchange = redraw;
      redraw();

    } catch (e) {
      console.warn("Shipment chart:", e.message);
    }
  }

  // Chart is installed by a different deferred
  // script; both scripts run after HTML parsing.
  loadChart();
})();
