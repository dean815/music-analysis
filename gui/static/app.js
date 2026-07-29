/* Lead sheet client.
 *
 * Deliberately thin. The server decides section order, which bars belong to
 * which section, and where repeat signs go, so everything here is either
 * reading a control or appending an element. The one piece of real logic is the
 * in-flight guard in refresh(): a slider drag fires far faster than a round
 * trip, and without it responses can land out of order and paint a stale chart
 * over a fresh one.
 */

const $ = (sel) => document.querySelector(sel);

const state = {
  track: null,
  overrides: {
    bpm: null,
    title: "",
    artist: "",
    intro_end: null,
    outro_start: null,
    loop_len: null,
    simplify: true,
    bars_per_line: 4,
  },
  sheet: null,
  pending: false,
  queued: false,
};

// ── Network ──────────────────────────────────────────────────────────────────

async function loadTracks() {
  const res = await fetch("/api/tracks");
  const data = await res.json();
  const picker = $("#track-picker");
  picker.replaceChildren();

  if (!data.tracks.length) {
    showError(
      `No analysed tracks in ${data.out_root}. Run: ${data.analyze_hint}`
    );
    return;
  }

  for (const track of data.tracks) {
    const opt = document.createElement("option");
    opt.value = track.name;
    opt.textContent = track.has_chart ? track.name : `${track.name} (no chord chart)`;
    picker.appendChild(opt);
  }

  const banner = $("#example-banner");
  banner.hidden = !data.is_example_fallback;
  if (data.is_example_fallback) {
    banner.textContent =
      "Showing the bundled example — nothing analysed in your out/ directory yet.";
  }

  state.track = data.tracks[0].name;
  picker.value = state.track;
  await refresh();
}

async function refresh() {
  if (!state.track) return;
  if (state.pending) {
    state.queued = true;
    return;
  }
  state.pending = true;
  try {
    const res = await fetch("/api/sheet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ out_dir: state.track, overrides: state.overrides }),
    });
    const data = await res.json();
    if (!res.ok) {
      // Keep the last good chart on screen. A 422 usually means one control is
      // wrong, and blanking the page would lose the context needed to fix it.
      showError(data.detail || `${res.status} ${res.statusText}`);
      return;
    }
    clearError();
    state.sheet = data;
    render(data);
  } catch (err) {
    showError(String(err));
  } finally {
    state.pending = false;
    if (state.queued) {
      state.queued = false;
      refresh();
    }
  }
}

// ── Rendering ────────────────────────────────────────────────────────────────

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderHeader(data) {
  const head = $("#sheet-header");
  head.replaceChildren();
  head.appendChild(el("h2", "sheet__title", data.title || "Untitled"));
  if (data.artist) head.appendChild(el("p", "sheet__artist", data.artist));

  const meta = el("p", "sheet__meta");
  meta.appendChild(el("span", "meta__item", `Key: ${data.key}`));
  meta.appendChild(el("span", "meta__item", `♩= ${Math.round(data.bpm)}`));
  meta.appendChild(el("span", "meta__item", "4/4"));
  meta.appendChild(el("span", "meta__item", `${data.total_bars} bars`));
  meta.appendChild(el("span", "meta__item", data.duration_timecode));
  head.appendChild(meta);
}

function barCell(cell) {
  const node = el("div", "bar");
  if (cell.display === "%") node.classList.add("bar--empty");
  node.appendChild(el("span", "bar__num", String(cell.number)));

  const chord = el("span", "bar__chord");
  cell.display.split(" / ").forEach((part, i) => {
    if (i > 0) chord.appendChild(el("span", "bar__slash", "/"));
    chord.appendChild(el("span", "chord", part));
  });
  node.appendChild(chord);
  return node;
}

function renderSection(section, barsPerLine) {
  const node = el("article", `section section--${section.kind}`);

  const head = el("div", "section__head");
  head.appendChild(el("h3", "section__label", section.label));
  if (section.detail) head.appendChild(el("span", "section__detail", section.detail));
  node.appendChild(head);

  const row = el("div", "bars-row");
  if (section.repeat) row.appendChild(el("span", "repeat repeat--open", "‖:"));

  const grid = el("div", "bars");
  grid.style.setProperty("--bars-per-line", barsPerLine);
  section.bars.forEach((cell) => grid.appendChild(barCell(cell)));
  row.appendChild(grid);

  if (section.repeat) row.appendChild(el("span", "repeat repeat--close", ":‖"));
  node.appendChild(row);

  if (section.note) node.appendChild(el("p", "section__note", `(${section.note})`));
  if (!section.bars.length) {
    node.appendChild(
      el("p", "section__note", "(no bars — check the intro and outro controls)")
    );
  }
  return node;
}

function renderDepartures(data) {
  const wrap = $("#departures");
  wrap.replaceChildren();
  if (!data.departures.length) return;

  wrap.appendChild(el("h3", "departures__label", "Harmonic departures"));
  wrap.appendChild(
    el("p", "departures__hint", "Bars whose root sits outside the loop's vocabulary.")
  );

  const list = el("ul", "departures__list");
  data.departures.forEach((d) => {
    const item = el("li", "departure");
    item.appendChild(el("span", "departure__bar", `bar ${d.bar}`));
    item.appendChild(el("span", "departure__time", d.timecode));
    item.appendChild(el("span", "departure__chord", d.chord));
    list.appendChild(item);
  });
  wrap.appendChild(list);
}

function render(data) {
  renderHeader(data);

  const body = $("#sheet-body");
  body.replaceChildren();
  data.sections.forEach((s) => body.appendChild(renderSection(s, data.bars_per_line)));

  renderDepartures(data);
  $("#cli-command").textContent = data.cli_command;
  $("#ascii-pane").textContent = data.ascii;
}

// ── Errors ───────────────────────────────────────────────────────────────────

function showError(message) {
  const banner = $("#error-banner");
  banner.textContent = message;
  banner.hidden = false;
}

function clearError() {
  $("#error-banner").hidden = true;
}

// ── Wiring ───────────────────────────────────────────────────────────────────

$("#track-picker").addEventListener("change", (e) => {
  state.track = e.target.value;
  refresh();
});

$("#copy-cli").addEventListener("click", async () => {
  const button = $("#copy-cli");
  await navigator.clipboard.writeText($("#cli-command").textContent);
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = "Copy"; }, 1200);
});

loadTracks();
