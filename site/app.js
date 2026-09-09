/* Montréal Cinéma — bilingual client, no build step. */

const DATA_URL = "./data/index.json";

/* --------------------------------------------------------------------- i18n */

const STR = {
  fr: {
    tagline: "Séances à Montréal",
    search: "Titre, réalisateur, acteur…",
    searchAria: "Rechercher un film",
    theme: "Thème clair / sombre",
    today: "Auj.", tomorrow: "Demain", all: "Tout",
    classics: "Classiques", restorations: "Restaurations", film35: "Pellicule 35 mm",
    indie: "Cinémas indépendants", vf: "Version française", vo: "Version anglaise", sub: "Sous-titré",
    allCinemas: "Tous les cinémas", allHoods: "Tous les quartiers", allGenres: "Tous les genres",
    cinema: "Cinéma", hood: "Quartier", genre: "Genre", sort: "Trier",
    sortRelevance: "Suggéré", sortSoonest: "Prochaine séance", sortRating: "Mieux noté",
    sortYear: "Plus récent", sortTitle: "Titre (A→Z)",
    reset: "Réinitialiser", filter: "Filtrer…",
    noneFound: "Aucun résultat",
    heroClassic: "Classique à l'affiche", heroNow: "À l'affiche",
    showtimes: "Voir les séances", trailer: "Bande-annonce",
    secTonight: "Ce soir", secTonightSub: "Séances qui n'ont pas encore commencé.",
    secFilm: "Sur pellicule", secFilmSub: "Projections 35 mm et 70 mm.",
    secClassics: "Classiques & reprises", secClassicsSub: "Restaurations, rétrospectives et grands films en salle.",
    secTop: "Les mieux notés sur Letterboxd",
    secOnce: "Séance unique", secOnceSub: "Une seule projection prévue.",
    secAll: "Tout à l'affiche",
    resultsFor: (q) => `Résultats pour « ${q} »`,
    screenings: "Séances",
    emptyTitle: "Aucune séance ne correspond", emptyBody: "Essayez une autre date ou retirez un filtre.",
    director: "Réalisation", cast: "Distribution", country: "Pays", genreL: "Genre", rated: "Classement",
    alsoAs: "Aussi à l'affiche sous",
    cinemaPage: "Fiche du cinéma",
    films: "films", showtimesN: "séances", cinemas: "cinémas", updated: "mis à jour le",
    sourcesDown: (n) => `${n} source${n > 1 ? "s" : ""} indisponible${n > 1 ? "s" : ""}`,
    dataNote: "Données agrégées depuis les sites des cinémas · notes : Letterboxd, IMDb",
    source: "Code source", made: "Fait pour soutenir les salles de Montréal 🎞️",
    unavailable: "Données indisponibles",
    unavailableBody: "Le fichier data/index.json n'a pas pu être chargé.",
    oneScreening: "Séance unique", classicTag: "Classique", restoTag: "Restauré",
    votes: "votes",
  },
  en: {
    tagline: "Showtimes in Montréal",
    search: "Title, director, actor…",
    searchAria: "Search for a film",
    theme: "Light / dark theme",
    today: "Today", tomorrow: "Tmrw", all: "All",
    classics: "Classics", restorations: "Restorations", film35: "35 mm film",
    indie: "Independent cinemas", vf: "French version", vo: "English version", sub: "Subtitled",
    allCinemas: "All cinemas", allHoods: "All neighbourhoods", allGenres: "All genres",
    cinema: "Cinema", hood: "Neighbourhood", genre: "Genre", sort: "Sort",
    sortRelevance: "Suggested", sortSoonest: "Next showing", sortRating: "Top rated",
    sortYear: "Newest", sortTitle: "Title (A→Z)",
    reset: "Reset", filter: "Filter…",
    noneFound: "No matches",
    heroClassic: "Classic on screen", heroNow: "Now showing",
    showtimes: "See showtimes", trailer: "Trailer",
    secTonight: "Tonight", secTonightSub: "Screenings that haven't started yet.",
    secFilm: "Shot on film", secFilmSub: "35 mm and 70 mm projections.",
    secClassics: "Classics & revivals", secClassicsSub: "Restorations, retrospectives and great films back on screen.",
    secTop: "Top rated on Letterboxd",
    secOnce: "One screening only", secOnceSub: "A single projection scheduled.",
    secAll: "Everything showing",
    resultsFor: (q) => `Results for “${q}”`,
    screenings: "Showtimes",
    emptyTitle: "Nothing matches", emptyBody: "Try another date or clear a filter.",
    director: "Director", cast: "Cast", country: "Country", genreL: "Genre", rated: "Rated",
    alsoAs: "Also listed as",
    cinemaPage: "Cinema page",
    films: "films", showtimesN: "showtimes", cinemas: "cinemas", updated: "updated",
    sourcesDown: (n) => `${n} source${n > 1 ? "s" : ""} unavailable`,
    dataNote: "Aggregated from the cinemas' own sites · ratings: Letterboxd, IMDb",
    source: "Source code", made: "Built to support Montréal's cinemas 🎞️",
    unavailable: "Data unavailable",
    unavailableBody: "data/index.json could not be loaded.",
    oneScreening: "One only", classicTag: "Classic", restoTag: "Restored",
    votes: "votes",
  },
};

let LANG = "fr";
const t = (k, ...a) => {
  const v = STR[LANG][k];
  return typeof v === "function" ? v(...a) : v ?? k;
};
const locale = () => (LANG === "fr" ? "fr-CA" : "en-CA");

/* -------------------------------------------------------------------- state */

const state = {
  data: null, venues: new Map(),
  date: null, venue: "", hood: "", genre: "", tag: "", language: "",
  sort: "relevance", q: "", indie: false,
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* -------------------------------------------------------------------- dates */

const parseDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayStr = () => iso(new Date());
const nowHHMM = () => { const n = new Date(); return `${String(n.getHours()).padStart(2, "0")}:${String(n.getMinutes()).padStart(2, "0")}`; };

function dayLong(s) {
  const today = todayStr();
  if (s === today) return LANG === "fr" ? "Aujourd'hui" : "Today";
  const tm = new Date(parseDate(today).getTime() + 864e5);
  if (s === iso(tm)) return LANG === "fr" ? "Demain" : "Tomorrow";
  return parseDate(s).toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "short" });
}
const runtimeStr = (m) => {
  if (!m) return "";
  const h = Math.floor(m / 60), r = m % 60;
  if (LANG === "fr") return h ? `${h} h ${String(r).padStart(2, "0")}` : `${r} min`;
  return h ? `${h}h ${r}m` : `${r}m`;
};

/* ----------------------------------------------------------------- filtering */

function showMatches(st) {
  if (state.date && state.date !== "all" && st.date !== state.date) return false;
  if (state.venue && st.venue !== state.venue) return false;
  if (state.hood) { const v = state.venues.get(st.venue); if (!v || v.neighbourhood !== state.hood) return false; }
  if (state.indie) { const v = state.venues.get(st.venue); if (!v || v.chain !== "independent") return false; }
  if (state.language) {
    if (state.language === "sub") { if (!st.subtitles) return false; }
    else if (st.language !== state.language) return false;
  }
  if (state.tag === "celluloid" && !(st.tags || []).includes("celluloid")) return false;
  return true;
}

function movieMatches(m, shows) {
  if (!shows.length) return false;
  if (state.genre && !(m.genres || []).includes(state.genre)) return false;
  if (state.tag && state.tag !== "celluloid" && !(m.tags || []).includes(state.tag)) return false;
  if (state.q) {
    const q = state.q.toLowerCase();
    const hay = [m.title, m.original_title, m.director, m.cast, (m.genres || []).join(" "), m.country,
                 (m.alt_titles || []).join(" ")].filter(Boolean).join(" ").toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function visible() {
  const out = [];
  for (const m of state.data.movies) {
    const shows = m.showtimes.filter(showMatches);
    if (movieMatches(m, shows)) out.push({ m, shows });
  }
  const lb = (x) => x.m.letterboxd_rating ?? -1;
  const s = state.sort;
  if (s === "rating") out.sort((a, b) => lb(b) - lb(a) || a.m.title.localeCompare(b.m.title, locale()));
  else if (s === "title") out.sort((a, b) => a.m.title.localeCompare(b.m.title, locale()));
  else if (s === "year") out.sort((a, b) => (b.m.year ?? 0) - (a.m.year ?? 0));
  else if (s === "soonest") out.sort((a, b) => (a.shows[0]?.start || "9").localeCompare(b.shows[0]?.start || "9"));
  else {
    const score = (x) => {
      let n = 0;
      const tg = new Set(x.m.tags || []);
      if (tg.has("classic")) n += 3;
      if (tg.has("restoration")) n += 2;
      if (tg.has("celluloid")) n += 3;
      if (x.m.letterboxd_rating) n += x.m.letterboxd_rating;
      if (x.shows.some((st) => state.venues.get(st.venue)?.chain === "independent")) n += 2;
      return n;
    };
    out.sort((a, b) => score(b) - score(a) || b.shows.length - a.shows.length);
  }
  return out;
}

/* ------------------------------------------------------------------- render */

const ICON = {
  chevL: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3.5 5.5 8l4.5 4.5"/></svg>`,
  chevR: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>`,
  ticket: `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M2 5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1.2a1.8 1.8 0 0 0 0 3.6V11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9.8a1.8 1.8 0 0 0 0-3.6z"/></svg>`,
  play: `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M5 3.2v9.6l7.5-4.8z"/></svg>`,
  ext: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5H3.5v9h9v-3M9.5 3.5h3v3M12.5 3.5 7 9"/></svg>`,
  star: `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 1.6l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.4 4.2 13.4l.7-4.3-3.1-3 4.3-.6z"/></svg>`,
};

function artHTML(m) {
  // Posters only. A 16:9 still centre-cropped into a 2:3 tile reads as a
  // screenshot, not artwork, so a titled placeholder is the better fallback.
  const ph = `<div class="ph">${esc(m.title)}</div>`;
  return m.poster ? `${ph}<img loading="lazy" src="${esc(m.poster)}" alt="" onerror="this.remove()">` : ph;
}

function tagsHTML(m, shows) {
  const tg = new Set(m.tags || []);
  for (const s of shows) (s.tags || []).forEach((x) => tg.add(x));
  const out = [];
  if (tg.has("celluloid")) out.push(`<span class="tag film">35mm</span>`);
  if (tg.has("classic")) out.push(`<span class="tag classic">${esc(t("classicTag"))}</span>`);
  else if (tg.has("restoration")) out.push(`<span class="tag resto">${esc(t("restoTag"))}</span>`);
  return out.length ? `<div class="tags">${out.join("")}</div>` : "";
}

function cardHTML({ m, shows }) {
  const sorted = [...shows].sort((a, b) => a.start.localeCompare(b.start));
  const times = sorted.slice(0, 4).map((s) => `<b>${s.time}</b>`).join("") +
    (sorted.length > 4 ? `<b class="more">+${sorted.length - 4}</b>` : "");
  const vs = [...new Set(shows.map((s) => state.venues.get(s.venue)?.short_name).filter(Boolean))];
  const vlabel = vs.length === 1 ? vs[0] : `${vs.length} ${t("cinemas")}`;
  const meta = [m.year, runtimeStr(m.runtime)].filter(Boolean).join(" · ");

  return `<button class="card" data-id="${esc(m.id)}">
    <div class="art">
      ${artHTML(m)}
      ${tagsHTML(m, shows)}
      ${m.letterboxd_rating ? `<span class="score">${m.letterboxd_rating.toFixed(1)}</span>` : ""}
      <div class="over">
        <div class="t">${esc(m.title)}</div>
        <div class="v">${esc(vlabel)}</div>
        <div class="times">${times}</div>
      </div>
    </div>
    <div class="cap">
      <div class="n">${esc(m.title)}</div>
      <div class="m">${esc(meta || vlabel)}</div>
    </div>
  </button>`;
}

function rowHTML(title, items, sub) {
  if (!items.length) return "";
  const id = "r" + Math.random().toString(36).slice(2, 8);
  const scrollable = items.length > 5;
  return `<section class="sec">
    <div class="sec-head">
      <h2>${esc(title)}<em>${items.length}</em></h2>
      ${sub ? `<p>${esc(sub)}</p>` : ""}
    </div>
    <div class="rowwrap">
      <button class="arrow prev ${scrollable ? "show" : ""}" data-row="${id}" data-dir="-1" aria-label="←"><i>${ICON.chevL}</i></button>
      <div class="row" id="${id}">${items.map(cardHTML).join("")}</div>
      <button class="arrow next ${scrollable ? "show" : ""}" data-row="${id}" data-dir="1" aria-label="→"><i>${ICON.chevR}</i></button>
    </div>
  </section>`;
}

function render() {
  const list = visible();
  const root = $("#content");

  const filtering = state.q || state.venue || state.genre || state.tag ||
    state.language || state.hood || state.indie || state.sort !== "relevance";

  if (!list.length) {
    $("#hero").hidden = true;
    root.innerHTML = `<div class="empty"><h3>${esc(t("emptyTitle"))}</h3><p>${esc(t("emptyBody"))}</p></div>`;
    return;
  }

  renderHero(list[0]);

  if (filtering) {
    root.innerHTML = `<section class="sec">
      <div class="sec-head"><h2>${esc(state.q ? t("resultsFor", state.q) : t("screenings"))}<em>${list.length}</em></h2></div>
      <div class="grid">${list.map(cardHTML).join("")}</div>
    </section>`;
    return;
  }

  // A film may appear in several themed rows — a Kurosawa classic belongs in
  // both "Tonight" and "Classics". Only the final catch-all row excludes what
  // has already been shown.
  const shown = new Set();
  const pick = (pred, n = 22) => {
    const out = [];
    for (const x of list) {
      if (!pred(x)) continue;
      out.push(x);
      if (out.length >= n) break;
    }
    out.forEach((x) => shown.add(x.m.id));
    return out;
  };
  const has = (x, tag) => (x.m.tags || []).includes(tag) || x.shows.some((s) => (s.tags || []).includes(tag));

  const parts = [];
  if (state.date === todayStr()) {
    const now = nowHHMM();
    const later = list.map((x) => ({ ...x, shows: x.shows.filter((s) => s.time >= now) }))
      .filter((x) => x.shows.length).slice(0, 22);
    if (later.length) {
      parts.push(rowHTML(t("secTonight"), later, t("secTonightSub")));
      later.forEach((x) => shown.add(x.m.id));
    }
  }
  parts.push(rowHTML(t("secFilm"), pick((x) => has(x, "celluloid")), t("secFilmSub")));
  parts.push(rowHTML(t("secClassics"), pick((x) => has(x, "classic") || has(x, "restoration")), t("secClassicsSub")));
  parts.push(rowHTML(t("secTop"), pick((x) => (x.m.letterboxd_rating ?? 0) >= 3.9)));
  parts.push(rowHTML(t("secOnce"), pick((x) => x.shows.length === 1), t("secOnceSub")));

  for (const v of state.data.venues) {
    if (v.chain !== "independent") continue;
    const items = pick((x) => x.shows.some((s) => s.venue === v.id));
    if (items.length) parts.push(rowHTML(v.name, items, v.address));
  }

  const rest = list.filter((x) => !shown.has(x.m.id));
  if (rest.length) {
    parts.push(`<section class="sec">
      <div class="sec-head"><h2>${esc(t("secAll"))}<em>${rest.length}</em></h2></div>
      <div class="grid">${rest.map(cardHTML).join("")}</div>
    </section>`);
  }
  root.innerHTML = parts.filter(Boolean).join("");
}

function renderHero(entry) {
  const hero = $("#hero");
  if (!entry) { hero.hidden = true; return; }
  const { m, shows } = entry;
  hero.hidden = false;
  const art = m.backdrop || m.poster || "";
  const meta = [m.year, m.director, runtimeStr(m.runtime), m.country].filter(Boolean);
  const vs = [...new Set(shows.map((s) => state.venues.get(s.venue)?.short_name).filter(Boolean))];

  hero.innerHTML = `
    <div class="hero-media">${art ? `<img src="${esc(art)}" alt="">` : ""}</div>
    <div class="hero-in">
      <div class="eyebrow">${esc((m.tags || []).includes("classic") ? t("heroClassic") : t("heroNow"))}</div>
      <h1>${esc(m.title)}</h1>
      <div class="hero-meta">
        ${meta.map((x) => `<span>${esc(x)}</span>`).join(`<span class="dot"></span>`)}
        ${m.letterboxd_rating ? `<span class="rate-chip">${ICON.star} ${m.letterboxd_rating.toFixed(2)}</span>` : ""}
        ${m.imdb_rating ? `<span class="rate-chip imdb">IMDb ${m.imdb_rating.toFixed(1)}</span>` : ""}
      </div>
      ${m.synopsis ? `<p>${esc(m.synopsis)}</p>` : ""}
      <div class="hero-act">
        <button class="btn btn-white" data-id="${esc(m.id)}">${ICON.ticket} ${esc(t("showtimes"))}</button>
        ${m.trailer ? `<a class="btn btn-glass" href="${esc(m.trailer)}" target="_blank" rel="noopener">${ICON.play} ${esc(t("trailer"))}</a>` : ""}
        ${vs.length ? `<span class="btn btn-glass btn-sm" style="pointer-events:none">${esc(vs.slice(0, 2).join(" · "))}</span>` : ""}
      </div>
    </div>`;
}

/* -------------------------------------------------------------------- modal */

function openMovie(id) {
  const m = state.data.movies.find((x) => x.id === id);
  if (!m) return;
  const shows = m.showtimes;

  const byVenue = new Map();
  for (const s of shows) { if (!byVenue.has(s.venue)) byVenue.set(s.venue, []); byVenue.get(s.venue).push(s); }

  const nf = new Intl.NumberFormat(locale());
  const scores = [];
  if (m.letterboxd_rating) scores.push(`<a class="sc lb" href="${esc(m.letterboxd_url || "#")}" target="_blank" rel="noopener">
    <div><div class="v">${m.letterboxd_rating.toFixed(2)}</div><div class="k">Letterboxd</div></div>
    ${m.letterboxd_votes ? `<span class="c">${nf.format(m.letterboxd_votes)}</span>` : ""}</a>`);
  if (m.imdb_rating) scores.push(`<a class="sc imdb" href="${esc(m.imdb_url || "#")}" target="_blank" rel="noopener">
    <div><div class="v">${m.imdb_rating.toFixed(1)}</div><div class="k">IMDb</div></div>
    ${m.imdb_votes ? `<span class="c">${nf.format(m.imdb_votes)}</span>` : ""}</a>`);
  if (m.rt_rating != null) scores.push(`<div class="sc rt"><div><div class="v">${m.rt_rating}%</div><div class="k">Rotten Tomatoes</div></div></div>`);
  if (m.metacritic != null) scores.push(`<div class="sc"><div><div class="v">${m.metacritic}</div><div class="k">Metacritic</div></div></div>`);

  const credits = [];
  if (m.director) credits.push([t("director"), m.director]);
  if (m.cast) credits.push([t("cast"), m.cast]);
  if (m.country) credits.push([t("country"), m.country]);
  if (m.genres?.length) credits.push([t("genreL"), m.genres.join(", ")]);
  if (m.rating) credits.push([t("rated"), m.rating]);

  const today = todayStr(), now = nowHHMM();
  const venues = [...byVenue.entries()].map(([vid, sts]) => {
    const v = state.venues.get(vid) || { name: vid, address: "" };
    const byDay = new Map();
    for (const s of sts.sort((a, b) => a.start.localeCompare(b.start))) {
      if (!byDay.has(s.date)) byDay.set(s.date, []);
      byDay.get(s.date).push(s);
    }
    const days = [...byDay.entries()].map(([d, l]) => `
      <div class="dayline"><div class="d">${esc(dayLong(d))}</div><div class="slots">${l.map((s) => {
        const past = d < today || (d === today && s.time < now);
        const href = s.ticket_url || s.url;
        const lbl = [s.version_label, s.format && s.format !== "2D" ? s.format : ""].filter(Boolean).join(" · ");
        const tag = href ? "a" : "span";
        return `<${tag} class="slot${past ? " past" : ""}"${href ? ` href="${esc(href)}" target="_blank" rel="noopener"` : ""}>${s.time}${lbl ? `<small>${esc(lbl)}</small>` : ""}</${tag}>`;
      }).join("")}</div></div>`).join("");
    return `<div class="venue">
      <div class="venue-n">${esc(v.name)}</div>
      <div class="venue-a">${esc([v.address, v.city].filter(Boolean).join(", "))}</div>
      ${days}</div>`;
  }).join("");

  const links = [];
  if (m.trailer) links.push(`<a class="btn btn-glass btn-sm" href="${esc(m.trailer)}" target="_blank" rel="noopener">${ICON.play} ${esc(t("trailer"))}</a>`);
  if (m.letterboxd_url) links.push(`<a class="btn btn-glass btn-sm" href="${esc(m.letterboxd_url)}" target="_blank" rel="noopener">${ICON.ext} Letterboxd</a>`);
  if (m.imdb_url) links.push(`<a class="btn btn-glass btn-sm" href="${esc(m.imdb_url)}" target="_blank" rel="noopener">${ICON.ext} IMDb</a>`);
  const src = shows.find((s) => s.url)?.url;
  if (src) links.push(`<a class="btn btn-glass btn-sm" href="${esc(src)}" target="_blank" rel="noopener">${ICON.ext} ${esc(t("cinemaPage"))}</a>`);

  const img = m.backdrop || m.poster;
  $("#panel").innerHTML = `
    <button class="x" aria-label="Close">✕</button>
    ${img ? `<div class="phero${m.backdrop ? "" : " contain"}"><img src="${esc(img)}" alt=""></div>` : ""}
    <div class="pbody">
      <h2>${esc(m.title)}</h2>
      ${m.original_title && m.original_title.toLowerCase() !== m.title.toLowerCase() ? `<div class="alt">${esc(m.original_title)}</div>` : ""}
      ${(m.alt_titles || []).length ? `<div class="alt">${esc(t("alsoAs"))} : ${esc(m.alt_titles.join(" · "))}</div>` : ""}
      <div class="facts">
        ${m.year ? `<span class="fact hi">${m.year}</span>` : ""}
        ${m.runtime ? `<span class="fact">${esc(runtimeStr(m.runtime))}</span>` : ""}
        ${(m.genres || []).slice(0, 3).map((g) => `<span class="fact">${esc(g)}</span>`).join("")}
        ${(m.tags || []).includes("celluloid") ? `<span class="fact hi">35 mm</span>` : ""}
        ${(m.tags || []).includes("restoration") ? `<span class="fact hi">${esc(t("restoTag"))}</span>` : ""}
      </div>
      ${scores.length ? `<div class="scores">${scores.join("")}</div>` : ""}
      ${m.synopsis ? `<div class="syn">${esc(m.synopsis)}</div>` : ""}
      ${credits.length ? `<dl class="credits">${credits.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      ${links.length ? `<div class="links">${links.join("")}</div>` : ""}
      <div class="shows"><h3>${esc(t("screenings"))} · ${shows.length}</h3>${venues}</div>
    </div>`;

  $("#modal").hidden = false;
  document.body.classList.add("locked");
  history.replaceState(null, "", `#film=${encodeURIComponent(m.id)}`);
  $("#panel .x")?.focus();
}

function closeModal() {
  $("#modal").hidden = true;
  document.body.classList.remove("locked");
  if (location.hash.startsWith("#film=")) history.replaceState(null, "", location.pathname);
}

/* ------------------------------------------------- searchable select (combobox) */

const SELECTS = {};

function makeSelect(host, { key, label, options }) {
  SELECTS[key] = { host, key, label, options, open: false, cursor: 0, query: "" };
  host.innerHTML = `
    <button class="sel-btn" type="button" aria-haspopup="listbox" aria-expanded="false"><span></span></button>
    <div class="sel-pop" hidden>
      <div class="f"><input type="text" placeholder="${esc(t("filter"))}" aria-label="${esc(label)}"></div>
      <div class="sel-list" role="listbox"></div>
    </div>`;
  host.querySelector(".sel-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleSelect(key); });
  const input = host.querySelector("input");
  input.addEventListener("input", () => { SELECTS[key].query = input.value; SELECTS[key].cursor = 0; paintSelect(key); });
  input.addEventListener("keydown", (e) => {
    const s = SELECTS[key];
    const opts = filteredOptions(key);
    if (e.key === "ArrowDown") { e.preventDefault(); s.cursor = Math.min(s.cursor + 1, opts.length - 1); paintSelect(key, true); }
    else if (e.key === "ArrowUp") { e.preventDefault(); s.cursor = Math.max(s.cursor - 1, 0); paintSelect(key, true); }
    else if (e.key === "Enter") { e.preventDefault(); const o = opts[s.cursor]; if (o) chooseSelect(key, o.value); }
    else if (e.key === "Escape") { e.preventDefault(); closeSelect(key); }
  });
  host.querySelector(".sel-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-value]");
    if (b) chooseSelect(key, b.dataset.value);
  });
  paintSelectButton(key);
}

const filteredOptions = (key) => {
  const s = SELECTS[key];
  const q = s.query.trim().toLowerCase();
  return q ? s.options.filter((o) => o.label.toLowerCase().includes(q)) : s.options;
};

function paintSelectButton(key) {
  const s = SELECTS[key];
  const cur = s.options.find((o) => o.value === state[key]);
  const isSet = !!state[key] && !(key === "sort" && state[key] === "relevance");
  s.host.classList.toggle("set", isSet);
  s.host.querySelector(".sel-btn span").textContent = cur && cur.value ? cur.label : s.label;
}

function paintSelect(key, keepFocus) {
  const s = SELECTS[key];
  const opts = filteredOptions(key);
  const list = s.host.querySelector(".sel-list");
  list.innerHTML = opts.length
    ? opts.map((o, i) => `<button class="sel-opt ${i === s.cursor ? "cur" : ""}" role="option"
        aria-selected="${state[key] === o.value}" data-value="${esc(o.value)}">
        <span>${esc(o.label)}</span>${o.count != null ? `<small>${o.count}</small>` : ""}</button>`).join("")
    : `<div class="sel-none">${esc(t("noneFound"))}</div>`;
  if (keepFocus) list.querySelector(".cur")?.scrollIntoView({ block: "nearest" });
  paintSelectButton(key);
}

function toggleSelect(key) { SELECTS[key].open ? closeSelect(key) : openSelect(key); }

function openSelect(key) {
  Object.keys(SELECTS).forEach((k) => k !== key && closeSelect(k));
  const s = SELECTS[key];
  s.open = true; s.query = ""; s.cursor = Math.max(0, s.options.findIndex((o) => o.value === state[key]));
  s.host.querySelector(".sel-pop").hidden = false;
  s.host.querySelector(".sel-btn").setAttribute("aria-expanded", "true");
  const input = s.host.querySelector("input");
  input.value = "";
  paintSelect(key, true);
  input.focus();
}

function closeSelect(key) {
  const s = SELECTS[key];
  if (!s || !s.open) return;
  s.open = false;
  s.host.querySelector(".sel-pop").hidden = true;
  s.host.querySelector(".sel-btn").setAttribute("aria-expanded", "false");
}

function chooseSelect(key, value) {
  state[key] = state[key] === value && value !== "relevance" ? "" : value;
  closeSelect(key);
  paintSelectButton(key);
  render();
}

/* --------------------------------------------------------------------- chrome */

function buildDays() {
  // Every date that actually has a screening — no arbitrary cap.
  const dates = [...new Set(state.data.movies.flatMap((m) => m.showtimes.map((s) => s.date)))]
    .filter((d) => d >= todayStr()).sort();
  $("#days").innerHTML = dates.map((d) => {
    const dt = parseDate(d);
    const dow = d === todayStr() ? t("today")
      : dt.toLocaleDateString(locale(), { weekday: "short" }).replace(".", "");
    return `<button class="day" data-date="${d}" aria-pressed="${d === state.date}">
      <i>${esc(dow)}</i><b>${dt.getDate()}</b></button>`;
  }).join("") +
    `<button class="day" data-date="all" aria-pressed="${state.date === "all"}" style="min-width:70px">
      <i>${esc(t("all"))}</i><b>∞</b></button>`;
}

function buildFilters() {
  const d = state.data;
  const countVenue = new Map(), countHood = new Map(), countGenre = new Map();
  for (const m of d.movies) {
    for (const s of m.showtimes) {
      countVenue.set(s.venue, (countVenue.get(s.venue) || 0) + 1);
      const v = state.venues.get(s.venue);
      if (v?.neighbourhood) countHood.set(v.neighbourhood, (countHood.get(v.neighbourhood) || 0) + 1);
    }
    for (const g of m.genres || []) countGenre.set(g, (countGenre.get(g) || 0) + 1);
  }

  makeSelect($("#f-venue"), {
    key: "venue", label: t("allCinemas"),
    options: [{ value: "", label: t("allCinemas") }].concat(
      d.venues.slice().sort((a, b) => a.name.localeCompare(b.name, locale()))
        .map((v) => ({ value: v.id, label: v.name, count: countVenue.get(v.id) || 0 }))),
  });
  makeSelect($("#f-hood"), {
    key: "hood", label: t("allHoods"),
    options: [{ value: "", label: t("allHoods") }].concat(
      [...countHood.entries()].sort((a, b) => a[0].localeCompare(b[0], locale()))
        .map(([h, c]) => ({ value: h, label: h, count: c }))),
  });
  makeSelect($("#f-genre"), {
    key: "genre", label: t("allGenres"),
    options: [{ value: "", label: t("allGenres") }].concat(
      [...countGenre.entries()].sort((a, b) => a[0].localeCompare(b[0], locale()))
        .map(([g, c]) => ({ value: g, label: g, count: c }))),
  });
  makeSelect($("#f-sort"), {
    key: "sort", label: t("sort"),
    options: [
      { value: "relevance", label: t("sortRelevance") },
      { value: "soonest", label: t("sortSoonest") },
      { value: "rating", label: t("sortRating") },
      { value: "year", label: t("sortYear") },
      { value: "title", label: t("sortTitle") },
    ],
  });
}

function paintStatic() {
  document.documentElement.lang = LANG === "fr" ? "fr-CA" : "en-CA";
  $("#brand-tag").textContent = t("tagline");
  const qi = $("#q");
  qi.placeholder = t("search"); qi.setAttribute("aria-label", t("searchAria"));
  $("#theme").title = t("theme");
  const chips = {
    "chip-classic": "classics", "chip-resto": "restorations", "chip-film": "film35",
    "chip-indie": "indie", "chip-vf": "vf", "chip-vo": "vo", "chip-sub": "sub",
  };
  for (const [id, k] of Object.entries(chips)) { const el = document.getElementById(id); if (el) el.textContent = t(k); }
  $("#f-reset").textContent = t("reset");
  $$(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  paintMeta();
}

function paintMeta() {
  const d = state.data;
  if (!d) return;
  const gen = new Date(d.generated_at);
  const parts = [
    `${d.counts.movies} ${t("films")}`,
    `${d.counts.showtimes} ${t("showtimesN")}`,
    `${d.counts.venues} ${t("cinemas")}`,
    `${t("updated")} ${gen.toLocaleDateString(locale(), { day: "numeric", month: "long" })}`,
  ];
  const failed = (d.sources || []).filter((s) => !s.ok);
  if (failed.length) parts.push(t("sourcesDown", failed.length));
  $("#meta").textContent = parts.join(" · ");
  $("#foot-note").textContent = t("dataNote");
  $("#foot-src").textContent = t("source");
  $("#foot-made").textContent = t("made");
}

function setLang(l) {
  if (l === LANG) return;
  LANG = l;
  try { localStorage.setItem("mtlcine-lang", l); } catch {}
  paintStatic();
  buildDays();
  buildFilters();
  render();
  if (!$("#modal").hidden) {
    const m = location.hash.match(/^#film=(.+)$/);
    if (m) openMovie(decodeURIComponent(m[1]));
  }
}

/* ---------------------------------------------------------------------- wire */

function wire() {
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".sel")) Object.keys(SELECTS).forEach(closeSelect);

    const lang = e.target.closest("[data-lang]");
    if (lang) { setLang(lang.dataset.lang); return; }

    const card = e.target.closest("[data-id]");
    if (card) { openMovie(card.dataset.id); return; }

    const day = e.target.closest("#days .day");
    if (day) {
      state.date = day.dataset.date;
      $$("#days .day").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.date === state.date)));
      render(); return;
    }

    const chip = e.target.closest("[data-tag],[data-langv],#chip-indie");
    if (chip) {
      if (chip.id === "chip-indie") state.indie = !state.indie;
      else if (chip.dataset.tag) state.tag = state.tag === chip.dataset.tag ? "" : chip.dataset.tag;
      else state.language = state.language === chip.dataset.langv ? "" : chip.dataset.langv;
      syncChips(); render(); return;
    }

    if (e.target.closest("#f-reset")) {
      Object.assign(state, { venue: "", hood: "", genre: "", tag: "", language: "", q: "",
        sort: "relevance", indie: false, date: todayStr() });
      $("#q").value = ""; $(".search").classList.remove("open");
      buildDays(); syncChips(); Object.keys(SELECTS).forEach(paintSelectButton); render(); return;
    }

    const arrow = e.target.closest(".arrow");
    if (arrow) {
      const row = document.getElementById(arrow.dataset.row);
      if (row) row.scrollBy({ left: Number(arrow.dataset.dir) * row.clientWidth * 0.82, behavior: "smooth" });
      return;
    }

    if (e.target.closest(".x") || e.target.classList.contains("scrim")) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (!$("#modal").hidden) closeModal(); else Object.keys(SELECTS).forEach(closeSelect); }
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") {
      e.preventDefault(); $(".search").classList.add("open"); $("#q").focus();
    }
  });

  let tm;
  $("#q").addEventListener("input", (e) => {
    state.q = e.target.value.trim();
    clearTimeout(tm); tm = setTimeout(render, 140);
  });
  $("#q").addEventListener("blur", () => { if (!state.q) $(".search").classList.remove("open"); });
  $("#search-btn").addEventListener("click", () => { $(".search").classList.add("open"); $("#q").focus(); });

  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "light" ? "" : "light";
    if (next) document.documentElement.setAttribute("data-theme", next);
    else document.documentElement.removeAttribute("data-theme");
    try { localStorage.setItem("mtlcine-theme", next); } catch {}
  });

  const nav = $(".nav");
  const onScroll = () => nav.classList.toggle("solid", window.scrollY > 40);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

function syncChips() {
  $$("[data-tag]").forEach((b) => b.setAttribute("aria-pressed", String(state.tag === b.dataset.tag)));
  $$("[data-langv]").forEach((b) => b.setAttribute("aria-pressed", String(state.language === b.dataset.langv)));
  $("#chip-indie").setAttribute("aria-pressed", String(state.indie));
}

/* ---------------------------------------------------------------------- boot */

async function boot() {
  try {
    const th = localStorage.getItem("mtlcine-theme");
    if (th) document.documentElement.setAttribute("data-theme", th);
    const lg = localStorage.getItem("mtlcine-lang");
    if (lg === "en" || lg === "fr") LANG = lg;
  } catch {}
  if (!localStorage.getItem?.("mtlcine-lang") && (navigator.language || "").toLowerCase().startsWith("en")) LANG = "en";

  let data;
  try {
    const r = await fetch(DATA_URL, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    data = await r.json();
  } catch {
    $("#content").innerHTML = `<div class="empty"><h3>${esc(t("unavailable"))}</h3><p>${esc(t("unavailableBody"))}</p></div>`;
    return;
  }

  state.data = data;
  state.venues = new Map(data.venues.map((v) => [v.id, v]));
  const dates = [...new Set(data.movies.flatMap((m) => m.showtimes.map((s) => s.date)))].sort();
  state.date = dates.includes(todayStr()) ? todayStr() : (dates.find((d) => d >= todayStr()) || dates[0] || "all");

  paintStatic();
  buildDays();
  buildFilters();
  syncChips();
  wire();
  render();

  const h = location.hash.match(/^#film=(.+)$/);
  if (h) openMovie(decodeURIComponent(h[1]));
}

boot();
