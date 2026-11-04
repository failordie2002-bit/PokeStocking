(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  if (!$("ps28")) return;

  let announcements = [];

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

  const safeURL = value => {
    try {
      const url = new URL(value);
      return url.protocol === "https:"
        ? url.href : "";
    } catch {
      return "";
    }
  };

  async function get(path) {
    const response = await fetch(
      path + "?v=" + Date.now(),
      {cache:"no-store"}
    );
    if (!response.ok) {
      throw Error("HTTP " + response.status);
    }
    return response.json();
  }

  function options(id, values) {
    const select = $(id);
    [...new Set(values)]
      .filter(Boolean)
      .sort((a,b) => a.localeCompare(b))
      .forEach(value => {
        const option =
          document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
  }

  function draw() {
    const game = $("ps28Game").value;
    const retailer = $("ps28Retailer").value;
    const type = $("ps28StatusFilter").value;
    const search = $("ps28Search")
      .value.toLowerCase().trim();

    const matching = announcements.filter(a =>
      (!game || a.game === game) &&
      (!retailer ||
        (a.retailers || []).includes(retailer)) &&
      (!search ||
        String(a.title).toLowerCase()
          .includes(search)) &&
      (
        !type ||
        (type === "dated" && a.release_date) ||
        (type === "undated" && !a.release_date)
      )
    );

    $("ps28Status").textContent =
      matching.length +
      " public announcement leads. " +
      "Dates and retailer availability " +
      "must be confirmed at the source.";

    $("ps28Cards").innerHTML =
      matching.slice(0,150).map(a => {
        const link = safeURL(a.url);
        const retailers = a.retailers || [];

        return `
          <article class="card">
            <span class="tag">
              ${escapeHTML(a.game)}
            </span>
            <h3>${escapeHTML(a.title)}</h3>
            <p class="muted">
              Date mentioned:
              <strong>
                ${escapeHTML(
                  a.release_date ||
                  "Not established"
                )}
              </strong>
            </p>
            <p class="muted">
              ${escapeHTML(a.status)}
            </p>
            <p class="muted">
              ${escapeHTML(
                retailers.length
                  ? "Retailers mentioned: " +
                    retailers.join(", ")
                  : "No retailer identified"
              )}
            </p>
            <p class="muted">
              Store-specific drop:
              Not verified
            </p>
            ${link ? `
              <a href="${escapeHTML(link)}"
                target="_blank"
                rel="noopener noreferrer">
                Review source
              </a>
            ` : ""}
          </article>
        `;
      }).join("") ||
      '<p class="muted">' +
      'No announcements match these filters.' +
      '</p>';
  }

  async function init() {
    try {
      const data = await get(
        "data/upcoming_drops_28.json"
      );

      announcements = Array.isArray(
        data.announcements
      ) ? data.announcements : [];

      options(
        "ps28Game",
        data.games || []
      );

      options(
        "ps28Retailer",
        data.retailers || []
      );

      [
        "ps28Game",
        "ps28Retailer",
        "ps28StatusFilter"
      ].forEach(id => {
        $(id).addEventListener(
          "change", draw
        );
      });

      $("ps28Search")
        .addEventListener("input", draw);

      draw();
    } catch (error) {
      $("ps28Status").textContent =
        "Release feed unavailable: " +
        error.message;
    }

    try {
      const data = await get(
        "data/discord_sources_28.json"
      );

      $("ps28Discord").innerHTML =
        (data.servers || []).map(s => {
          const url = safeURL(s.url);
          return `
            <article class="card">
              <h3>
                ${escapeHTML(s.name)}
              </h3>
              <p class="muted">
                ${escapeHTML(s.focus)}
              </p>
              <p class="muted">
                Automated feed:
                Not connected
              </p>
              ${url ? `
                <a href="${escapeHTML(url)}"
                  target="_blank"
                  rel="noopener noreferrer">
                  Open Discord community
                </a>
              ` : ""}
            </article>
          `;
        }).join("");
    } catch {
      $("ps28Discord").textContent =
        "Discord directory unavailable.";
    }
  }

  init();
})();
