import { createPlayer, readingDuration } from "./player-core.js";
import { renderScene, fitHeroes } from "./scenes.js";
import { esc, periodLabel } from "./format.js";

const $ = (sel, root = document) => root.querySelector(sel);

const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
const state = {
  doc: null,
  chapter: null,
  current: null,       // rendered scene { el, onProgress, cleanup }
  renderedIndex: -1,
  renderedChapter: null,
  // ?motion=reduced forces the reduced-motion presentation (for testing and capture).
  reduced: reducedQuery.matches || new URLSearchParams(location.search).get("motion") === "reduced",
  chartCache: new Map(),
};

const player = createPlayer({
  durationOf: (s) => readingDuration(s),
  waitsForInput: (s) => s.type === "quiz",
  clock: { now: () => performance.now(), setTimeout: (f, ms) => window.setTimeout(f, ms), clearTimeout: (h) => window.clearTimeout(h) },
  onChange: (s) => onPlayerChange(s),
});

function loadChart(slug) {
  if (!state.chartCache.has(slug)) {
    state.chartCache.set(slug, fetch(`data/charts/${encodeURIComponent(slug)}.svg`).then((r) => {
      if (!r.ok) throw new Error(`chart ${slug}: ${r.status}`);
      return r.text();
    }).catch((e) => { state.chartCache.delete(slug); throw e; }));
  }
  return state.chartCache.get(slug);
}

// ---------------------------------------------------------------- rendering

function buildSegments() {
  const bar = $("#progress");
  bar.innerHTML = state.chapter.scenes.map((s, i) =>
    `<li><button type="button" class="seg" data-i="${i}" aria-label="Go to scene ${i + 1}: ${esc(s.kicker)}"><span class="fill"></span></button></li>`).join("");
  for (const b of bar.querySelectorAll(".seg")) {
    b.addEventListener("click", () => player.goTo(Number(b.dataset.i)));
  }
}

function showScene(s) {
  const stage = $("#stage");
  if (state.current) state.current.cleanup();
  const scene = s.scene;
  const ctx = {
    index: s.index,
    count: s.count,
    partial: state.chapter.partial,
    chapterLabel: state.chapter.id === "all" ? "Five years" : "Year in review",
    chapterId: state.chapter.id,
    chapters: state.doc.chapters,
    reduced: state.reduced,
    player,
    loadChart,
    replay: () => player.replay(),
    openChapter: (id) => openChapter(id, 0),
    openChart,
  };
  const r = renderScene(scene, ctx);
  stage.replaceChildren(r.el);
  fitHeroes(r.el);
  state.current = r;
  state.renderedIndex = s.index;
  state.renderedChapter = state.chapter.id;
  $("#live").textContent = `Scene ${s.index + 1} of ${s.count}. ${scene.headline}`;
  document.documentElement.dataset.palette = r.el.className.match(/palette-(\d)/)[1];
  history.replaceState(null, "", `#/${state.chapter.id}/${s.index}`);
}

function onPlayerChange(s) {
  if (!state.chapter) return;
  if (s.index !== state.renderedIndex || state.renderedChapter !== state.chapter.id) showScene(s);
  const segs = document.querySelectorAll("#progress .seg");
  segs.forEach((b, i) => {
    b.classList.toggle("done", i < s.index);
    b.classList.toggle("current", i === s.index);
    if (i === s.index) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
  });
  const pauseBtn = $("#btn-pause");
  const mode = s.ended ? "replay" : s.wantsPlay ? "pause" : "play";
  const label = { replay: "Replay chapter", pause: "Pause story", play: "Resume story" }[mode];
  pauseBtn.dataset.mode = mode;
  pauseBtn.setAttribute("aria-label", label);
  pauseBtn.querySelector(".lbl").textContent = label;
  pauseBtn.setAttribute("aria-pressed", String(!s.wantsPlay && !s.ended));
  $("#btn-prev").disabled = s.index === 0;
  $("#btn-next").disabled = s.ended;
  $("#status").textContent = statusText(s);
  document.documentElement.dataset.blocked = s.blockers.join(" ");
}

function statusText(s) {
  if (s.ended) return "End of chapter";
  if (s.blockers.includes("quiz")) return "Waiting for your answer";
  if (!s.wantsPlay) return "Paused";
  if (s.blockers.includes("method") || s.blockers.includes("chart")) return "Paused while reading";
  return "";
}

function tick() {
  const s = player.state();
  if (state.chapter && s.count) {
    const p = player.progress();
    const seg = document.querySelector(`#progress .seg[data-i="${s.index}"] .fill`);
    if (seg) seg.style.transform = `scaleX(${p})`;
    document.querySelectorAll("#progress .seg").forEach((b, i) => {
      if (i !== s.index) b.querySelector(".fill").style.transform = `scaleX(${i < s.index ? 1 : 0})`;
    });
    if (state.current) state.current.onProgress(p, player.elapsedMs());
  }
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------- chapters

function openChapter(id, index = 0) {
  const ch = state.doc.chapters.find((c) => c.id === id) || state.doc.chapters[0];
  state.chapter = ch;
  state.renderedIndex = -1;
  $("#chapter-name").textContent = ch.id === "all" ? "All years" : `${ch.label}${ch.partial ? " (partial)" : ""}`;
  buildSegments();
  player.load(ch.scenes, Math.min(Math.max(0, index), ch.scenes.length - 1));
}

function parseHash() {
  const m = location.hash.match(/^#\/([\w-]+)\/(\d+)$/);
  return m ? { id: m[1], index: Number(m[2]) } : null;
}

// ---------------------------------------------------------------- dialogs

// Close a dialog and release its blocker at once. The dialog "close" event also
// unblocks, but Chromium can deliver it only on the next rendered frame.
const DIALOG_TRIGGERS = { method: "#btn-method", picker: "#btn-chapter", chart: "#stage .chart-btn" };

function closeDialog(id) {
  $(`#${id}`).close();
  player.unblock(id);
  const trigger = $(DIALOG_TRIGGERS[id]);
  if (trigger) trigger.focus(); // return focus to the control that opened it
}

async function fillChart(figure, slug) {
  figure.innerHTML = '<p class="chart-loading">Loading chart</p>';
  try {
    figure.innerHTML = await loadChart(slug);
  } catch {
    figure.innerHTML = '<p class="chart-loading">Chart unavailable. The numbers in the story are complete without it.</p>';
  }
}

// The validated diagram-design chart, behind the scene's "See the chart" button.
function openChart(scene) {
  if (!scene.chart) return;
  $("#chart-title").textContent = scene.headline;
  player.block("chart");
  $("#chart").showModal();
  fillChart($("#chart-figure"), scene.chart);
}

function openMethod() {
  const s = player.state().scene;
  const dlg = $("#method");
  $("#method-title").textContent = s.headline;
  $("#method-period").textContent = `${periodLabel(s.period)} · Story ID ${s.id}`;
  $("#method-text").textContent = s.method;
  const fig = $("#method-chart");
  fig.hidden = !s.chart;
  if (s.chart) fillChart(fig, s.chart); else fig.replaceChildren();
  $("#method-evidence").innerHTML = s.evidence.map((e) =>
    `<tr><th scope="row">${esc(e.label)}</th><td>${esc(e.value)}</td><td class="src">${esc(e.source)}</td></tr>`).join("");
  player.block("method");
  dlg.showModal();
}

function openPicker() {
  const dlg = $("#picker");
  $("#picker-list").innerHTML = state.doc.chapters.map((c) => `
    <li><button type="button" class="chip big" data-chapter="${esc(c.id)}"${c.id === state.chapter.id ? ' aria-current="true"' : ""}>
      <span>${esc(c.id === "all" ? "All years" : c.label)}</span>
      <small>${esc(c.partial ? c.partial_note : periodLabel(c.period))}</small>
    </button></li>`).join("");
  for (const b of dlg.querySelectorAll("[data-chapter]")) {
    b.addEventListener("click", () => {
      closeDialog("picker");
      openChapter(b.dataset.chapter, 0);
    });
  }
  player.block("picker");
  dlg.showModal();
}

// ---------------------------------------------------------------- input

function isInteractive(target) {
  return Boolean(target.closest("button, a, input, select, textarea, label, dialog, [role=dialog], .interactive, .leaderboard, .options"));
}

function bindInput() {
  $("#btn-prev").addEventListener("click", () => player.prev());
  $("#btn-next").addEventListener("click", () => player.next());
  $("#btn-pause").addEventListener("click", () => {
    if (player.state().ended) player.replay(); else player.toggle();
  });
  $("#btn-method").addEventListener("click", openMethod);
  $("#btn-chapter").addEventListener("click", openPicker);
  $("#btn-pace").addEventListener("click", () => {
    const slower = player.state().speed === 1;
    player.setSpeed(slower ? 1.5 : 1);
    $("#btn-pace").setAttribute("aria-pressed", String(slower));
  });
  for (const id of ["method", "picker", "chart"]) {
    $(`#${id}`).addEventListener("close", () => player.unblock(id));
    $(`#${id}`).addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      closeDialog(id);
    });
  }
  $("#method-close").addEventListener("click", () => closeDialog("method"));
  $("#picker-close").addEventListener("click", () => closeDialog("picker"));
  $("#chart-close").addEventListener("click", () => closeDialog("chart"));

  // Tap navigation on the stage background only; never on controls or content widgets.
  $("#stage").addEventListener("click", (ev) => {
    if (isInteractive(ev.target)) return;
    const rect = $("#stage").getBoundingClientRect();
    if (ev.clientX - rect.left < rect.width * 0.3) player.prev(); else player.next();
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (document.querySelector("dialog[open]")) return; // dialogs handle their own keys (Esc closes)
    const tag = ev.target.tagName;
    const onControl = ["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"].includes(tag);
    if (tag === "INPUT" && (ev.key === "ArrowLeft" || ev.key === "ArrowRight")) return; // let the scrubber work
    switch (ev.key) {
      case "ArrowRight": player.next(); ev.preventDefault(); break;
      case "ArrowLeft": player.prev(); ev.preventDefault(); break;
      case "Home": player.goTo(0); ev.preventDefault(); break;
      case "End": player.goTo(player.state().count - 1); ev.preventDefault(); break;
      case " ":
      case "k":
      case "K":
        if (onControl && ev.key === " ") return; // Space activates the focused control instead
        if (player.state().ended) player.replay(); else player.toggle();
        ev.preventDefault();
        break;
      case "r":
      case "R": player.replay(); ev.preventDefault(); break;
      case "i":
      case "I": openMethod(); ev.preventDefault(); break;
      default:
    }
  });

  // Deep links: a typed or pasted #/<chapter>/<scene> moves the story there.
  window.addEventListener("hashchange", () => {
    const h = parseHash();
    if (!h) return;
    const s = player.state();
    if (h.id !== state.chapter.id) openChapter(h.id, h.index);
    else if (h.index !== s.index) player.goTo(h.index);
  });

  // Hero sizes depend on the loaded font and the card size.
  document.fonts.ready.then(() => { if (state.current) fitHeroes(state.current.el); });
  window.addEventListener("resize", () => { if (state.current) fitHeroes(state.current.el); });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) player.block("hidden"); else player.unblock("hidden");
  });
  reducedQuery.addEventListener("change", (e) => {
    state.reduced = e.matches || new URLSearchParams(location.search).get("motion") === "reduced";
    document.documentElement.classList.toggle("reduced", state.reduced);
    showScene(player.state());
  });
}

async function main() {
  document.documentElement.classList.toggle("reduced", state.reduced);
  try {
    const r = await fetch("data/stories.json");
    if (!r.ok) throw new Error(String(r.status));
    state.doc = await r.json();
  } catch (e) {
    $("#stage").innerHTML = `<section class="scene palette-0"><div class="scene-inner">
      <h1 class="headline solo">Story data not found</h1>
      <p class="body">Run <code>python3 -m rewind.pipeline</code>, then serve the web folder over HTTP.</p></div></section>`;
    return;
  }
  bindInput();
  if (document.hidden) player.block("hidden");
  const h = parseHash();
  openChapter(h ? h.id : "all", h ? h.index : 0);
  requestAnimationFrame(tick);
}

main();
