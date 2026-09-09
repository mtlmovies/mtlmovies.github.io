/* Montréal Cinéma — client. Vanilla JS, no build step. */

const DATA_URL = "./data/index.json";

const state = {
  data: null,
  venues: new Map(),
  date: null,          // "YYYY-MM-DD" | "all"
  venue: "",
  neighbourhood: "",
  language: "",
  genre: "",
  tag: "",
  sort: "relevance",
  q: "",
  independentOnly: false,
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ------------------------------------------------------------------ utils */

const FR_DOW = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];
const FR_DOW_LONG = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const FR_MON = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"];

function parseDate(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function todayStr() {
  const n = new Date();
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
}
function dayLabel(s) {
  const d = parseDate(s);
  const t = todayStr();
  if (s === t) return "Aujourd'hui";
  const tm = new Date(parseDate(t).getTime() + 864e5);
  if (s === `${tm.getFullYear()}-${String(tm.getMonth() + 1).padStart(2, "0")}-${String(tm.getDate()).padStart(2, "0")}`)
    return "Demain";
  return `${FR_DOW_LONG[d.getDay()]} ${d.getDate()} ${FR_MON[d.getMonth()]}`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function runtimeStr(m) {
  if (!m) return "";
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} h ${String(r).padStart(2, "0")}` : `${r} min`;
}
function nowHHMM() {
  const n = new Date();
  return `${String(n.getHours()).padStart(2, "0")}:${String(n.getMinutes()).padStart(2, "0")}`;
}

/* --------------------------------------------------------------- filtering */

function showtimeMatches(st) {
  if (state.date && state.date !== "all" && st.date !== state.date) return false;
  if (state.venue && st.venue !== state.venue) return false;
  if (state.neighbourhood) {
    const v = state.venues.get(st.venue);
    if (!v || v.neighbourhood !== state.neighbourhood) return false;
  }
  if (state.independentOnly) {
    const v = state.venues.get(st.venue);
    if (!v || v.chain !== "independent") return false;
  }
  if (state.language) {
    if (state.language === "vo-st") {
      if (!st.subtitles) return false;
    } else if (st.language !== state.language) return false;
  }
  if (state.tag === "celluloid" || state.tag === "premium-format") {
    if (!(st.tags || []).includes(state.tag)) return false;
  }
  return true;
}

function movieMatches(m, shows) {
  if (!shows.length) return false;
  if (state.genre && !(m.genres || []).includes(state.genre)) return false;
  if (state.tag && state.tag !== "celluloid" && state.tag !== "premium-format") {
    if (!(m.tags || []).includes(state.tag)) return false;
  }
  if (state.q) {
    const q = state.q.toLowerCase();
    const hay = [m.title, m.original_title, m.director, m.cast, (m.genres || []).join(" "), m.country]
      .filter(Boolean).join(" ").toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

/** Returns [{movie, shows}] passing all filters. */
function visibleMovies() {
  const out = [];
  for (const m of state.data.movies) {
    const shows = m.showtimes.filter(showtimeMatches);
    if (movieMatches(m, shows)) out.push({ m, shows });
  }
  return sortMovies(out);
}

function sortMovies(list) {
  const s = state.sort;
  const lb = (x) => x.m.letterboxd_rating ?? -1;
  if (s === "rating") list.sort((a, b) => lb(b) - lb(a) || a.m.title.localeCompare(b.m.title, "fr"));
  else if (s === "title") list.sort((a, b) => a.m.title.localeCompare(b.m.title, "fr"));
  else if (s === "year") list.sort((a, b) => (b.m.year ?? 0) - (a.m.year ?? 0));
  else if (s === "soonest")
    list.sort((a, b) => (a.shows[0]?.start || "9").localeCompare(b.shows[0]?.start || "9"));
  else {
    // Relevance: independents & repertory first, then rating, then count.
    const score = (x) => {
      let n = 0;
      if ((x.m.tags || []).includes("classic")) n += 3;
      if ((x.m.tags || []).includes("restoration")) n += 2;
      if ((x.m.tags || []).includes("celluloid")) n += 3;
      if (x.m.letterboxd_rating) n += x.m.letterboxd_rating;
      const indie = x.shows.some((st) => state.venues.get(st.venue)?.chain === "independent");
      if (indie) n += 2;
      return n;
    };
    list.sort((a, b) => score(b) - score(a) || b.shows.length - a.shows.length);
  }
  return list;
}

/* ------------------------------------------------------------------ render */

function posterHTML(m) {
  if (m.poster) {
    return `<img loading="lazy" src="${esc(m.poster)}" alt="" onerror="this.remove()">
            <div class="poster-fallback" style="z-index:-1">${esc(m.title)}</div>`;
  }
  return `<div class="poster-fallback">${esc(m.title)}</div>`;
}

function badgesHTML(m, shows) {
  const b = [];
  const tags = new Set(m.tags || []);
  for (const st of shows) (st.tags || []).forEach((t) => tags.add(t));
  if (tags.has("celluloid")) b.push(`<span class="badge celluloid">35mm</span>`);
  if (tags.has("classic")) b.push(`<span class="badge classic">Classique</span>`);
  else if (tags.has("restoration")) b.push(`<span class="badge restoration">Restauré</span>`);
  if (shows.length === 1) b.push(`<span class="badge last">Séance unique</span>`);
  return b.length ? `<div class="badges">${b.join("")}</div>` : "";
}

function ratingPill(m) {
  if (!m.letterboxd_rating) return "";
  return `<span class="rating-pill"><span class="dot"></span>${m.letterboxd_rating.toFixed(1)}</span>`;
}

function cardHTML({ m, shows }, opts = {}) {
  const meta = [];
  if (m.year) meta.push(esc(m.year));
  if (m.runtime) meta.push(runtimeStr(m.runtime));
  const venueNames = [...new Set(shows.map((s) => state.venues.get(s.venue)?.short_name).filter(Boolean))];
  if (venueNames.length === 1) meta.push(esc(venueNames[0]));
  else if (venueNames.length > 1) meta.push(`${venueNames.length} cinémas`);

  let times = "";
  if (opts.showTimes) {
    const sorted = [...shows].sort((a, b) => a.start.localeCompare(b.start));
    const slice = sorted.slice(0, 4);
    times = `<div class="card-times">${slice
      .map((s) => `<span class="time-tag">${s.time}</span>`).join("")}${
      sorted.length > 4 ? `<span class="time-tag more">+${sorted.length - 4}</span>` : ""
    }</div>`;
  }

  return `<button class="card" data-id="${esc(m.id)}">
    <div class="poster">${posterHTML(m)}${badgesHTML(m, shows)}${ratingPill(m)}</div>
    <div class="card-title">${esc(m.title)}</div>
    <div class="card-meta">${meta.map((x, i) => (i ? `<span class="sep">·</span> ${x}` : x)).join(" ")}</div>
    ${times}
  </button>`;
}

function rowHTML(title, items, opts = {}) {
  if (!items.length) return "";
  const id = "row-" + Math.random().toString(36).slice(2, 8);
  return `<section class="section">
    <div class="section-head"><h2>${esc(title)}</h2><span class="count">${items.length}</span></div>
    ${opts.sub ? `<p class="section-sub">${esc(opts.sub)}</p>` : ""}
    <div class="row-wrap">
      <button class="row-nav" data-dir="prev" data-row="${id}" aria-label="Précédent"><span>${ICON.chevL}</span></button>
      <div class="row" id="${id}">${items.map((x) => cardHTML(x, opts)).join("")}</div>
      <button class="row-nav" data-dir="next" data-row="${id}" aria-label="Suivant"><span>${ICON.chevR}</span></button>
    </div>
  </section>`;
}

const ICON = {
  chevL: `<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3.5 5.5 8l4.5 4.5"/></svg>`,
  chevR: `<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>`,
  ticket: `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M2 5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1.2a1.8 1.8 0 0 0 0 3.6V11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9.8a1.8 1.8 0 0 0 0-3.6z"/></svg>`,
  play: `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M5 3.5v9l7-4.5z"/></svg>`,
  ext: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5H3.5v9h9v-3M9.5 3.5h3v3M12.5 3.5 7 9"/></svg>`,
};

/** The main content area. */
function render() {
  const list = visibleMovies();
  const root = $("#content");

  const filtering = state.q || state.venue || state.genre || state.tag ||
    state.language || state.neighbourhood || state.independentOnly ||
    state.sort !== "relevance";

  if (!list.length) {
    root.innerHTML = `<div class="empty">
      <h3>Aucune séance ne correspond</h3>
      <p>Essayez une autre date ou retirez un filtre.</p>
    </div>`;
    renderHero(null);
    return;
  }

  // Hero: the most interesting film on the selected day.
  renderHero(list[0]);

  if (filtering) {
    root.innerHTML = `<section class="section">
      <div class="section-head"><h2>${state.q ? `Résultats pour « ${esc(state.q)} »` : "Séances"}</h2>
      <span class="count">${list.length} film${list.length > 1 ? "s" : ""}</span></div>
      <div class="grid">${list.map((x) => cardHTML(x, { showTimes: true })).join("")}</div>
    </section>`;
    return;
  }

  // Curated rows.
  const has = (x, t) => (x.m.tags || []).includes(t) ||
    x.shows.some((s) => (s.tags || []).includes(t));
  const now = nowHHMM();
  const isToday = state.date === todayStr();

  const rest = new Set(list.map((x) => x.m.id));
  const used = new Set();
  const take = (pred, n = 24) => {
    const out = [];
    for (const x of list) {
      if (used.has(x.m.id)) continue;
      if (pred(x)) { out.push(x); used.add(x.m.id); }
      if (out.length >= n) break;
    }
    return out;
  };

  const parts = [];

  if (isToday) {
    const later = list
      .map((x) => ({ ...x, shows: x.shows.filter((s) => s.time >= now) }))
      .filter((x) => x.shows.length);
    if (later.length) {
      parts.push(rowHTML("Ce soir, il reste des places", later.slice(0, 24),
        { showTimes: true, sub: "Séances qui n'ont pas encore commencé." }));
      later.slice(0, 24).forEach((x) => used.add(x.m.id));
    }
  }

  parts.push(rowHTML("Sur pellicule", take((x) => has(x, "celluloid")),
    { showTimes: true, sub: "Projections 35 mm et 70 mm — à ne pas manquer." }));
  parts.push(rowHTML("Classiques & reprises", take((x) => has(x, "classic") || has(x, "restoration")),
    { showTimes: true, sub: "Restaurations, rétrospectives et grands films en salle." }));
  parts.push(rowHTML("Les mieux notés sur Letterboxd",
    take((x) => (x.m.letterboxd_rating ?? 0) >= 3.9, 24), { showTimes: true }));
  parts.push(rowHTML("Séance unique", take((x) => x.shows.length === 1),
    { showTimes: true, sub: "Une seule projection prévue." }));

  // A row per independent venue.
  for (const v of state.data.venues) {
    if (v.chain !== "independent") continue;
    const items = take((x) => x.shows.some((s) => s.venue === v.id), 24);
    if (items.length) parts.push(rowHTML(v.name, items, { showTimes: true, sub: v.address }));
  }

  const leftovers = list.filter((x) => !used.has(x.m.id));
  if (leftovers.length) {
    parts.push(`<section class="section">
      <div class="section-head"><h2>Tout à l'affiche</h2><span class="count">${leftovers.length}</span></div>
      <div class="grid">${leftovers.map((x) => cardHTML(x, { showTimes: true })).join("")}</div>
    </section>`);
  }

  root.innerHTML = parts.filter(Boolean).join("");
}

function renderHero(entry) {
  const hero = $("#hero");
  if (!entry) { hero.hidden = true; return; }
  const { m, shows } = entry;
  hero.hidden = false;
  const bg = m.backdrop || m.poster || "";
  const meta = [];
  if (m.year) meta.push(esc(m.year));
  if (m.director) meta.push(esc(m.director));
  if (m.runtime) meta.push(runtimeStr(m.runtime));
  if (m.country) meta.push(esc(m.country));
  const venues = [...new Set(shows.map((s) => state.venues.get(s.venue)?.short_name).filter(Boolean))];

  hero.innerHTML = `
    <div class="hero-bg" style="background-image:url('${esc(bg)}')"></div>
    <div class="hero-inner">
      <div class="hero-eyebrow">${(m.tags || []).includes("classic") ? "Classique à l'affiche" : "À voir"}</div>
      <h1>${esc(m.title)}</h1>
      <div class="hero-meta">
        ${meta.map((x) => `<span>${x}</span>`).join(`<span class="sep">·</span>`)}
        ${m.letterboxd_rating ? `<span class="pill accent">★ ${m.letterboxd_rating.toFixed(2)} Letterboxd</span>` : ""}
      </div>
      ${m.synopsis ? `<p>${esc(m.synopsis)}</p>` : ""}
      <div class="hero-actions">
        <button class="btn btn-primary" data-id="${esc(m.id)}">${ICON.ticket} Voir les séances</button>
        ${venues.length ? `<span class="btn btn-ghost" style="pointer-events:none">${esc(venues.slice(0, 3).join(" · "))}</span>` : ""}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ modal */

function openMovie(id) {
  const m = state.data.movies.find((x) => x.id === id);
  if (!m) return;
  const shows = m.showtimes.filter((st) => {
    if (state.venue && st.venue !== state.venue) return false;
    return true;
  });

  const byVenue = new Map();
  for (const st of shows) {
    if (!byVenue.has(st.venue)) byVenue.set(st.venue, []);
    byVenue.get(st.venue).push(st);
  }

  const ratings = [];
  if (m.letterboxd_rating)
    ratings.push(`<a class="rating-card lb" href="${esc(m.letterboxd_url || "#")}" target="_blank" rel="noopener">
      <div><div class="val">${m.letterboxd_rating.toFixed(2)}</div><div class="lbl">Letterboxd</div></div>
      ${m.letterboxd_votes ? `<span class="votes">${(m.letterboxd_votes / 1000).toFixed(0)}k</span>` : ""}</a>`);
  if (m.rt_rating != null)
    ratings.push(`<div class="rating-card rt"><div><div class="val">${m.rt_rating}%</div><div class="lbl">Rotten Tomatoes</div></div></div>`);
  if (m.imdb_rating)
    ratings.push(`<a class="rating-card imdb" href="${esc(m.imdb_url || "#")}" target="_blank" rel="noopener">
      <div><div class="val">${m.imdb_rating.toFixed(1)}</div><div class="lbl">IMDb</div></div></a>`);
  if (m.metacritic != null)
    ratings.push(`<div class="rating-card"><div><div class="val">${m.metacritic}</div><div class="lbl">Metacritic</div></div></div>`);

  const credits = [];
  if (m.director) credits.push(["Réalisation", m.director]);
  if (m.cast) credits.push(["Distribution", m.cast]);
  if (m.country) credits.push(["Pays", m.country]);
  if (m.genres?.length) credits.push(["Genre", m.genres.join(", ")]);
  if (m.rating) credits.push(["Classement", m.rating]);

  const today = todayStr(), now = nowHHMM();
  const venueBlocks = [...byVenue.entries()].map(([vid, sts]) => {
    const v = state.venues.get(vid) || { name: vid, address: "" };
    const byDay = new Map();
    for (const st of sts.sort((a, b) => a.start.localeCompare(b.start))) {
      if (!byDay.has(st.date)) byDay.set(st.date, []);
      byDay.get(st.date).push(st);
    }
    const days = [...byDay.entries()].map(([d, list]) => `
      <div class="day-line">
        <div class="day-label">${esc(dayLabel(d))}</div>
        <div class="slot-list">${list.map((st) => {
          const past = d < today || (d === today && st.time < now);
          const href = st.ticket_url || st.url;
          const label = [st.version_label, st.format && st.format !== "2D" ? st.format : ""]
            .filter(Boolean).join(" · ");
          const tag = href ? "a" : "span";
          return `<${tag} class="slot${past ? " past" : ""}"${href ? ` href="${esc(href)}" target="_blank" rel="noopener"` : ""}>
            ${st.time}${label ? `<small>${esc(label)}</small>` : ""}
          </${tag}>`;
        }).join("")}</div>
      </div>`).join("");
    return `<div class="venue-block">
      <div class="venue-head">
        <div>
          <div class="venue-name">${esc(v.name)}</div>
          <div class="venue-where">${esc([v.address, v.city].filter(Boolean).join(", "))}</div>
        </div>
      </div>${days}
    </div>`;
  }).join("");

  const heroImg = m.backdrop || m.poster;
  const links = [];
  if (m.trailer) links.push(`<a class="btn btn-secondary" href="${esc(m.trailer)}" target="_blank" rel="noopener">${ICON.play} Bande-annonce</a>`);
  if (m.letterboxd_url) links.push(`<a class="btn btn-secondary" href="${esc(m.letterboxd_url)}" target="_blank" rel="noopener">${ICON.ext} Letterboxd</a>`);
  if (m.imdb_url) links.push(`<a class="btn btn-secondary" href="${esc(m.imdb_url)}" target="_blank" rel="noopener">${ICON.ext} IMDb</a>`);
  const firstSrc = shows.find((s) => s.url)?.url;
  if (firstSrc) links.push(`<a class="btn btn-secondary" href="${esc(firstSrc)}" target="_blank" rel="noopener">${ICON.ext} Fiche du cinéma</a>`);

  $("#modal-content").innerHTML = `
    <button class="modal-close" aria-label="Fermer">✕</button>
    ${heroImg ? `<div class="modal-hero${m.backdrop ? "" : " is-poster"}"><img src="${esc(heroImg)}" alt=""></div>` : ""}
    <div class="modal-body">
      <h2 class="modal-title">${esc(m.title)}</h2>
      ${m.original_title && m.original_title.toLowerCase() !== m.title.toLowerCase()
        ? `<div class="modal-orig">${esc(m.original_title)}</div>` : ""}
      <div class="modal-meta">
        ${m.year ? `<span class="pill">${esc(m.year)}</span>` : ""}
        ${m.runtime ? `<span class="pill">${runtimeStr(m.runtime)}</span>` : ""}
        ${(m.genres || []).slice(0, 3).map((g) => `<span class="pill">${esc(g)}</span>`).join("")}
        ${(m.tags || []).includes("celluloid") ? `<span class="pill accent">Pellicule</span>` : ""}
        ${(m.tags || []).includes("restoration") ? `<span class="pill accent">Restauration</span>` : ""}
      </div>
      ${ratings.length ? `<div class="ratings">${ratings.join("")}</div>` : ""}
      ${m.synopsis ? `<div class="modal-synopsis">${esc(m.synopsis)}</div>` : ""}
      ${credits.length ? `<dl class="modal-credits">${credits
        .map(([k, v]) => `<div class="credit"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      ${links.length ? `<div class="modal-actions">${links.join("")}</div>` : ""}
      <div class="showtimes">
        <h3>Séances · ${shows.length}</h3>
        ${venueBlocks}
      </div>
    </div>`;

  const modal = $("#modal");
  modal.hidden = false;
  document.body.classList.add("is-locked");
  history.replaceState(null, "", `#film=${encodeURIComponent(m.id)}`);
  $(".modal-close", modal)?.focus();
}

function closeModal() {
  $("#modal").hidden = true;
  document.body.classList.remove("is-locked");
  if (location.hash.startsWith("#film=")) history.replaceState(null, "", location.pathname);
}

/* ----------------------------------------------------------------- chrome */

function buildDayStrip() {
  const dates = [...new Set(state.data.movies.flatMap((m) => m.showtimes.map((s) => s.date)))]
    .filter((d) => d >= todayStr()).sort();
  const strip = $("#daystrip");
  const shown = dates.slice(0, 21);
  strip.innerHTML = shown.map((d) => {
    const dt = parseDate(d);
    return `<button class="day" data-date="${d}" aria-pressed="${d === state.date}">
      <span class="dow">${d === todayStr() ? "Auj." : FR_DOW[dt.getDay()]}</span>
      <span class="dnum">${dt.getDate()}</span>
    </button>`;
  }).join("") +
    `<button class="day" data-date="all" aria-pressed="${state.date === "all"}" style="min-width:74px">
      <span class="dow">Tout</span><span class="dnum">∞</span></button>`;
}

function buildFilters() {
  const venues = state.data.venues;
  const genres = [...new Set(state.data.movies.flatMap((m) => m.genres || []))].sort((a, b) => a.localeCompare(b, "fr"));
  const hoods = [...new Set(venues.map((v) => v.neighbourhood).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"));

  $("#f-venue").innerHTML = `<option value="">Tous les cinémas</option>` +
    venues.map((v) => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join("");
  $("#f-hood").innerHTML = `<option value="">Tous les quartiers</option>` +
    hoods.map((h) => `<option value="${esc(h)}">${esc(h)}</option>`).join("");
  $("#f-genre").innerHTML = `<option value="">Tous les genres</option>` +
    genres.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
}

function syncChips() {
  $$("#chips [data-tag]").forEach((b) =>
    b.setAttribute("aria-pressed", String(state.tag === b.dataset.tag)));
  $$("#chips [data-lang]").forEach((b) =>
    b.setAttribute("aria-pressed", String(state.language === b.dataset.lang)));
  $("#f-indie")?.setAttribute("aria-pressed", String(state.independentOnly));
  for (const [id, val] of [["f-venue", state.venue], ["f-hood", state.neighbourhood],
                           ["f-genre", state.genre], ["f-sort", state.sort]]) {
    const el = $("#" + id);
    if (!el) continue;
    el.value = val;
    el.classList.toggle("is-set", !!val && !(id === "f-sort" && val === "relevance"));
  }
  $$("#daystrip .day").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.date === state.date)));
}

function wire() {
  document.addEventListener("click", (e) => {
    const card = e.target.closest("[data-id]");
    if (card) { openMovie(card.dataset.id); return; }

    const day = e.target.closest("#daystrip .day");
    if (day) { state.date = day.dataset.date; syncChips(); render(); return; }

    const tag = e.target.closest("#chips [data-tag]");
    if (tag) { state.tag = state.tag === tag.dataset.tag ? "" : tag.dataset.tag; syncChips(); render(); return; }

    const lang = e.target.closest("#chips [data-lang]");
    if (lang) { state.language = state.language === lang.dataset.lang ? "" : lang.dataset.lang; syncChips(); render(); return; }

    if (e.target.closest("#f-indie")) {
      state.independentOnly = !state.independentOnly; syncChips(); render(); return;
    }
    if (e.target.closest("#f-reset")) {
      Object.assign(state, { venue: "", neighbourhood: "", genre: "", tag: "", language: "",
        q: "", sort: "relevance", independentOnly: false, date: todayStr() });
      $("#q").value = ""; $(".search").classList.remove("has-value");
      buildDayStrip(); syncChips(); render(); return;
    }

    const nav = e.target.closest(".row-nav");
    if (nav) {
      const row = document.getElementById(nav.dataset.row);
      if (row) row.scrollBy({ left: (nav.dataset.dir === "next" ? 1 : -1) * row.clientWidth * 0.85, behavior: "smooth" });
      return;
    }

    if (e.target.closest(".modal-close") || e.target.classList.contains("modal-scrim")) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modal").hidden) closeModal();
    if (e.key === "/" && document.activeElement !== $("#q")) { e.preventDefault(); $("#q").focus(); }
  });

  let t;
  $("#q").addEventListener("input", (e) => {
    state.q = e.target.value.trim();
    $(".search").classList.toggle("has-value", !!state.q);
    clearTimeout(t); t = setTimeout(render, 140);
  });
  $(".search-clear").addEventListener("click", () => {
    state.q = ""; $("#q").value = ""; $(".search").classList.remove("has-value"); render();
  });

  for (const [id, key] of [["f-venue", "venue"], ["f-hood", "neighbourhood"],
                           ["f-genre", "genre"], ["f-sort", "sort"]]) {
    $("#" + id).addEventListener("change", (e) => { state[key] = e.target.value; syncChips(); render(); });
  }

  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "light" ? "dark" : cur === "dark" ? "" : "light";
    if (next) document.documentElement.setAttribute("data-theme", next);
    else document.documentElement.removeAttribute("data-theme");
    try { localStorage.setItem("mtlcine-theme", next); } catch {}
  });
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  try { const t = localStorage.getItem("mtlcine-theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch {}

  let data;
  try {
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch (e) {
    $("#content").innerHTML = `<div class="empty"><h3>Données indisponibles</h3>
      <p>Le fichier <code>data/index.json</code> n'a pas pu être chargé.<br>
      Lancez le rafraîchissement (GitHub Action) pour le générer.</p></div>`;
    return;
  }

  state.data = data;
  state.venues = new Map(data.venues.map((v) => [v.id, v]));
  const dates = [...new Set(data.movies.flatMap((m) => m.showtimes.map((s) => s.date)))].sort();
  state.date = dates.includes(todayStr()) ? todayStr() : (dates.find((d) => d >= todayStr()) || dates[0] || "all");

  buildDayStrip();
  buildFilters();
  syncChips();
  wire();
  render();

  const gen = new Date(data.generated_at);
  $("#meta").innerHTML =
    `${data.counts.movies} films · ${data.counts.showtimes} séances · ${data.counts.venues} cinémas` +
    ` · mis à jour le ${gen.toLocaleDateString("fr-CA", { day: "numeric", month: "long" })}`;

  const failed = (data.sources || []).filter((s) => !s.ok);
  if (failed.length) {
    $("#meta").innerHTML += ` · <span title="${esc(failed.map((f) => f.source + ": " + (f.error || "")).join(" | "))}">${failed.length} source(s) indisponible(s)</span>`;
  }

  const m = location.hash.match(/^#film=(.+)$/);
  if (m) openMovie(decodeURIComponent(m[1]));
}

boot();
