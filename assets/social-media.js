(() => {
  "use strict";

  const $ = id =>
    document.getElementById(id);

  if (!$("social")) return;

  const esc = value =>
    String(value ?? "").replace(
      /[&<>"']/g,
      c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[c]
    );

  const norm = value =>
    String(value ?? "")
      .trim().toLowerCase();

  const safe = value => {
    try {
      const u = new URL(value);
      return u.protocol === "https:"
        ? u.href : "";
    } catch {
      return "";
    }
  };

  let posts = [];
  let origin = null;
  let visible = 24;

  const miles = (a, b) => {
    const rad = Math.PI / 180;
    const lat = (b[0] - a[0]) * rad;
    const lon = (b[1] - a[1]) * rad;
    const h =
      Math.sin(lat / 2) ** 2 +
      Math.cos(a[0] * rad) *
      Math.cos(b[0] * rad) *
      Math.sin(lon / 2) ** 2;

    return 7917.6 * Math.asin(
      Math.min(1, Math.sqrt(h))
    );
  };

  function time(value) {
    if (!value) return "Date unknown";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) {
      return "Date unknown";
    }
    return d.toLocaleDateString(
      "en-US",
      {
        month: "short",
        day: "numeric",
        year: "numeric"
      }
    );
  }

  function embed(post) {
    const url = safe(post.url);
    if (!url) return "";

    // Reddit's official public embed.
    // Other platforms can restrict embeds.
    try {
      const u = new URL(url);
      if (
        (u.hostname === "reddit.com" ||
         u.hostname.endsWith(".reddit.com")) &&
        u.pathname.includes("/comments/")
      ) {
        const src =
          "https://www.redditmedia.com" +
          u.pathname.replace(/\/$/, "") +
          "?ref_source=embed&ref=share";

        return `
          <details>
            <summary>View Reddit post</summary>
            <iframe class="sm-embed"
              loading="lazy"
              title="Reddit public post"
              sandbox="allow-scripts allow-same-origin allow-popups"
              src="${esc(src)}">
            </iframe>
          </details>`;
      }
    } catch {}

    return "";
  }

  function card(post, distance) {
    const url = safe(post.url);
    const loc = post.location;
    const place = loc
      ? `${loc.city}, ${loc.state}`
      : "Location not established";

    const platform =
      post.platform || "Public web";

    const desc =
      String(post.description || "")
        .slice(0, 450);

    return `
      <article class="sm-card">
        <div>
          <span class="sm-tag">
            ${esc(platform)}
          </span>
          <span class="sm-tag">
            ${esc(post.game || "TCG")}
          </span>
        </div>

        <h3>${esc(post.title)}</h3>

        <p>
          ${esc(time(post.published_at))}
          · ${esc(place)}
        </p>

        ${distance !== null ? `
          <p>
            Approximately
            ${distance.toFixed(1)} miles
            straight-line, using
            city-center coordinates
          </p>` : ""}

        ${desc ? `
          <p>${esc(desc)}</p>
        ` : ""}

        <p>
          <strong>
            Unverified public report.
            Not confirmed stock.
          </strong>
        </p>

        ${url ? `
          <a class="action"
            href="${esc(url)}"
            target="_blank"
            rel="noopener noreferrer">
            View original post
          </a>` : ""}

        ${embed(post)}
      </article>`;
  }

  function render() {
    const radius =
      Number($("smRadius").value);

    const retailer =
      norm($("smRetailer").value);

    const game =
      norm($("smGame").value);

    const sort =
      $("smSort").value;

    const local = [];
    const other = [];

    for (const post of posts) {
      if (
        retailer &&
        !(post.retailer_mentions || [])
          .some(x => norm(x) === retailer)
      ) continue;

      if (
        game &&
        norm(post.game) !== game
      ) continue;

      const loc = post.location;

      const p =
        loc &&
        Number.isFinite(+loc.lat) &&
        Number.isFinite(+loc.lon)
          ? [+loc.lat, +loc.lon]
          : null;

      const d =
        p && origin
          ? miles(origin, p)
          : null;

      if (
        p &&
        (radius === 0 ||
          (origin && d <= radius))
      ) {
        local.push({post, distance:d});
      } else if (!p) {
        other.push({
          post,
          distance:null
        });
      }
    }

    const recent = (a, b) =>
      String(
        b.post.published_at ||
        b.post.first_seen_at || ""
      ).localeCompare(
        String(
          a.post.published_at ||
          a.post.first_seen_at || ""
        )
      );

    local.sort((a,b) => {
      if (
        sort === "nearest" &&
        origin
      ) {
        return (
          (a.distance ?? Infinity) -
          (b.distance ?? Infinity)
        );
      }
      return recent(a,b);
    });

    other.sort(recent);

    $("smLocal").innerHTML =
      local.slice(0,visible)
        .map(x => card(
          x.post,x.distance
        )).join("") ||
      `<p class="muted">
        No location-matched reports
        found within this radius.
      </p>`;

    $("smOther").innerHTML =
      other.slice(0,visible)
        .map(x => card(
          x.post,null
        )).join("") ||
      `<p class="muted">
        No other reports match.
      </p>`;

    $("smMore").hidden =
      local.length <= visible &&
      other.length <= visible;

    $("smStatus").textContent =
      `${local.length} location-matched leads; ` +
      `${other.length} unlocated leads. ` +
      (radius && !origin
        ? "Use GPS or ZIP to activate local filtering."
        : "Reports are unverified.");
  }

  $("smGPS").onclick = () => {
    if (!navigator.geolocation) {
      $("smStatus").textContent =
        "GPS unavailable. Use ZIP.";
      return;
    }

    $("smStatus").textContent =
      "Requesting location...";

    navigator.geolocation
      .getCurrentPosition(
        p => {
          origin = [
            p.coords.latitude,
            p.coords.longitude
          ];
          visible = 24;
          render();
        },
        error => {
          $("smStatus").textContent =
            "GPS unavailable: " +
            error.message;
        },
        {
          enableHighAccuracy:false,
          timeout:15000
        }
      );
  };

  $("smZIPGo").onclick = async () => {
    const zip =
      $("smZIP").value.trim();

    if (!/^\d{5}$/.test(zip)) {
      $("smStatus").textContent =
        "Enter a valid ZIP code.";
      return;
    }

    try {
      $("smStatus").textContent =
        "Looking up ZIP...";

      const r = await fetch(
        "https://api.zippopotam.us/us/" +
        zip
      );

      if (!r.ok) {
        throw Error("ZIP not found");
      }

      const data = await r.json();
      const place = data.places?.[0];

      if (!place) {
        throw Error("ZIP not found");
      }

      origin = [
        Number(place.latitude),
        Number(place.longitude)
      ];

      if (!origin.every(Number.isFinite)) {
        throw Error(
          "Invalid ZIP coordinates"
        );
      }

      visible = 24;
      render();
    } catch (error) {
      $("smStatus").textContent =
        error.message;
    }
  };

  $("smZIP").onkeydown = event => {
    if (event.key === "Enter") {
      $("smZIPGo").click();
    }
  };

  [
    "smRadius",
    "smRetailer",
    "smGame",
    "smSort"
  ].forEach(id => {
    $(id).onchange = () => {
      visible = 24;
      render();
    };
  });

  $("smMore").onclick = () => {
    visible += 24;
    render();
  };

  fetch(
    "data/social_media_feed.json?t=" +
    Date.now(),
    {cache:"no-store"}
  )
    .then(r => {
      if (!r.ok) {
        throw Error(
          "Social feed unavailable"
        );
      }
      return r.json();
    })
    .then(data => {
      posts = Array.isArray(data.posts)
        ? data.posts : [];
      render();
    })
    .catch(error => {
      $("smStatus").textContent =
        "Could not load social reports: " +
        error.message;
    });
})();
