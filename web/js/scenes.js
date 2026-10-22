// Scene renderers. Each returns { el, onProgress(progress, elapsedMs), cleanup() }.
// All numbers come from stories.json; this file only formats and lays them out.
//
// Visual language (Wrapped 2025 "mixtape" direction): one oversized hero per
// scene set in a variable width font, a looping outlined type ribbon, tape
// labels, grain over two-tone gradients. Decorative layers are aria-hidden.

import { esc, int, one, pct, monthLabel } from "./format.js";
import { rankingMonthAt, rankingProgressFor } from "./player-core.js";

const PALETTE_BY_TYPE = {
  opening: 0, minutes: 4, quiz: 2, top: 1, ranking: 3, clock: 5, biggest_day: 6, session: 0,
  streak: 4, repeat: 2, transition: 3, eras: 6, sustained: 1, comeback: 2, stayed: 5,
  early_late: 1, arrival: 4, year_eras: 6, summary: 0,
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function ribbonWord(scene) {
  const d = scene.data || {};
  switch (scene.type) {
    case "opening": return "REWIND";
    case "minutes": return "MINUTES";
    case "quiz": return "TOP SONG";
    case "top": return d.artists ? d.artists[0].name : "TOP";
    case "ranking": return "NUMBER ONE";
    case "clock": return d.peak_hour_label || "CLOCK";
    case "biggest_day": return "BIGGEST DAY";
    case "session": return "ONE SESSION";
    case "streak": return d.streaks ? d.streaks[0].name : "STREAK";
    case "repeat": return d.track || "REPEAT";
    case "eras": case "year_eras": return "ERAS";
    case "summary": return "REWIND";
    default: return scene.kicker || "REWIND";
  }
}

function ribbon(word) {
  const unit = `${esc(word)} <i>&#9679;</i> `.repeat(6);
  return `<div class="ribbon"><div class="ribbon-track"><span>${unit}</span><span>${unit}</span></div></div>`;
}

function shell(scene, ctx, { hero = "", inner = "", visual = "" } = {}) {
  const el = document.createElement("section");
  const pal = PALETTE_BY_TYPE[scene.type] ?? 0;
  el.className = `scene scene--${scene.type} palette-${pal}`;
  el.setAttribute("aria-roledescription", "slide");
  el.setAttribute("aria-label", `Scene ${ctx.index + 1} of ${ctx.count}`);
  const chartBtn = scene.chart
    ? `<button type="button" class="pill chart-btn" data-chart="${esc(scene.chart)}">See the chart</button>` : "";
  el.innerHTML = `
    <div class="deco" aria-hidden="true"><div class="grain"></div>${ribbon(ribbonWord(scene))}</div>
    <div class="scene-inner">
      <p class="kicker"><span class="tape">${esc(scene.kicker)}</span>${ctx.partial ? ' <span class="badge">Partial year</span>' : ""}</p>
      ${hero ? `<div class="hero">${hero}</div>` : ""}
      ${inner}
      ${visual ? `<div class="visual">${visual}</div>` : ""}
      ${chartBtn}
    </div>`;
  const btn = el.querySelector(".chart-btn");
  if (btn) btn.addEventListener("click", () => ctx.openChart(scene));
  return el;
}

// Oversized text sized to fill the card width by character count (CSS reads --len).
function big(text, cls = "") {
  const s = String(text);
  return `<span class="big ${cls}" style="--len:${Math.max(3, s.length)}">${esc(s)}</span>`;
}

function headline(scene, cls = "") {
  return `<h1 class="headline ${cls}">${esc(scene.headline)}</h1>`;
}

function body(scene) {
  return scene.body ? `<p class="body">${esc(scene.body)}</p>` : "";
}

function durationShort(minutes) {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

// ---------------------------------------------------------------- types

function textScene(scene, ctx) {
  return { el: shell(scene, ctx, { inner: headline(scene, "solo") + body(scene) }) };
}

function opening(scene, ctx) {
  const a = scene.period.start.slice(0, 4);
  const b = scene.period.end.slice(0, 4);
  const years = a === b ? big(a, "years") : `${big(a, "years")}<span class="years-arrow" aria-hidden="true">to</span>${big(b, "years")}`;
  const hero = `<div class="cassette" aria-hidden="true"><span class="reel"></span><span class="label">${esc(ctx.chapterLabel)}</span><span class="reel"></span></div>
    <div class="years-stack">${years}</div>`;
  return { el: shell(scene, ctx, { hero, inner: headline(scene, "dates") + body(scene) }) };
}

function minutes(scene, ctx) {
  const target = scene.metrics.minutes;
  const hero = `<span class="big count" style="--len:${int(target).length}" data-count aria-label="${int(target)} minutes">${ctx.reduced ? int(target) : "0"}</span>
    <span class="unit">minutes</span>`;
  const el = shell(scene, ctx, { hero, inner: body(scene) });
  const out = el.querySelector("[data-count]");
  let last = -1;
  return {
    el,
    onProgress(_p, elapsed) {
      if (ctx.reduced) return;
      const k = Math.min(1, elapsed / 1800);
      const v = Math.round(target * (1 - Math.pow(1 - k, 3)));
      if (v !== last) { out.textContent = int(v); last = v; }
    },
  };
}

function quiz(scene, ctx) {
  const d = scene.data;
  const resolved = ctx.player.isQuizResolved();
  const opts = d.options.map((o, i) => `
    <li><button type="button" class="option" data-id="${esc(o.id)}">
      <span class="opt-key" aria-hidden="true">${"ABCD"[i]}</span>
      <span class="opt-text"><span class="opt-name">${esc(o.name)}</span><span class="opt-artist">${esc(o.artist)}</span></span>
    </button></li>`).join("");
  const a = d.answer_detail;
  const link = a.url ? `<a class="listen pill" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">Play it in Spotify</a>` : "";
  const inner = `${headline(scene, "quiz-q")}
    <ol class="options" aria-label="Answer options">${opts}</ol>
    <div class="quiz-actions"><button type="button" class="pill skip">Skip and reveal</button></div>
    <div class="reveal" hidden>
      <p class="verdict" role="status"></p>
      <p class="answer-name" style="--len:${Math.max(6, Math.min(a.name.length, 40))}">${esc(a.name)}</p>
      <p class="body">${esc(a.artist)}. ${one(a.minutes)} minutes across ${int(a.plays)} plays.</p>
      ${d.plays_note ? `<p class="note">${esc(d.plays_note)}</p>` : ""}
      ${link}
    </div>`;
  const el = shell(scene, ctx, { inner });
  const reveal = el.querySelector(".reveal");
  const verdict = el.querySelector(".verdict");
  const buttons = [...el.querySelectorAll(".option")];

  function show(choiceId) {
    for (const b of buttons) {
      b.disabled = true;
      if (b.dataset.id === d.answer) b.classList.add("correct");
      else if (b.dataset.id === choiceId) b.classList.add("wrong");
    }
    el.querySelector(".quiz-actions").hidden = true;
    verdict.textContent = choiceId == null ? "The answer" : choiceId === d.answer ? "Correct" : "Not quite. The answer";
    reveal.hidden = false;
    el.classList.add("answered");
    requestAnimationFrame(() => reveal.scrollIntoView({ block: "nearest", behavior: ctx.reduced ? "auto" : "smooth" }));
  }
  for (const b of buttons) {
    b.addEventListener("click", () => { show(b.dataset.id); ctx.player.resolveQuiz(); });
  }
  el.querySelector(".skip").addEventListener("click", () => { show(null); ctx.player.resolveQuiz(); });
  if (resolved) show(null);
  return { el };
}

function top(scene, ctx) {
  const d = scene.data;
  const lead = d.artists[0];
  const hero = `<span class="rank-tag">#1 artist</span>${big(lead.name, "name")}`;
  const rest = d.artists.slice(1).map((a, i) => `<li style="--i:${i}"><span class="rank">${i + 2}</span><span class="name">${esc(a.name)}</span><span class="val">${int(a.minutes)} min</span></li>`).join("");
  const tracks = d.tracks.map((t, i) => `<li style="--i:${i + 4}"><span class="rank">${i + 1}</span><span class="name song"><span class="clamp" title="${esc(t.name)}">${esc(t.name)}</span><small>${esc(t.artist)}</small></span><span class="val">${int(t.minutes)} min${t.url ? ` <a class="mini-link" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer" aria-label="Listen to ${esc(t.name)} in Spotify">Listen</a>` : ""}</span></li>`).join("");
  const visual = `<div class="lists">
      <div><h2 class="list-title">Artists 2 to 5</h2><ol class="ranked" start="2">${rest}</ol></div>
      <div><h2 class="list-title">Top songs</h2><ol class="ranked">${tracks}</ol></div>
    </div>`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene), visual }) };
}

function ranking(scene, ctx) {
  const months = scene.data.months;
  const n = months.length;
  const visual = `<div class="sprint">
      <p class="sprint-month" aria-live="off"><span class="sprint-label"></span> <span class="sprint-tag"></span></p>
      <ol class="leaderboard" aria-label="Top 5 artists for the month shown"></ol>
      <label class="scrub"><span class="visually-hidden">Month</span>
        <input type="range" min="0" max="${n - 1}" step="1" value="0" aria-valuetext="${esc(months[0].label)}">
      </label>
      <p class="scrub-ends" aria-hidden="true"><span>${esc(months[0].label)}</span><span>${esc(months[n - 1].label)}</span></p>
    </div>`;
  const el = shell(scene, ctx, { inner: headline(scene) + body(scene), visual });
  const board = el.querySelector(".leaderboard");
  const label = el.querySelector(".sprint-label");
  const tag = el.querySelector(".sprint-tag");
  const range = el.querySelector("input[type=range]");
  const rows = new Map(); // artist id -> li, so identity survives reordering
  let shown = -1;

  function render(i) {
    if (i === shown) return;
    shown = i;
    const m = months[i];
    label.textContent = m.label;
    tag.textContent = m.partial && m.low_activity ? "Partial, low activity" : m.partial ? "Partial month" : m.low_activity ? "Low activity" : "";
    range.value = String(i);
    range.setAttribute("aria-valuetext", m.label);
    // Rows that drop out of the top 5 are removed; rows that stay keep their
    // element, so the transform transition moves the same artist to its new rank.
    const present = new Set(m.top.map((a) => a.id));
    for (const [id, li] of rows) {
      if (!present.has(id)) {
        li.remove();
        rows.delete(id);
      }
    }
    m.top.forEach((a, pos) => {
      let li = rows.get(a.id);
      if (!li) {
        li = document.createElement("li");
        li.className = "lb-row";
        li.dataset.id = a.id;
        li.innerHTML = `<span class="rank"></span><span class="name">${esc(a.name)}</span><span class="val"></span>`;
        li.style.setProperty("--pos", String(pos));
        board.appendChild(li);
        rows.set(a.id, li);
      }
      li.style.setProperty("--pos", String(pos));
      li.querySelector(".rank").textContent = String(pos + 1);
      li.querySelector(".val").textContent = `${int(a.minutes)} min · ${pct(a.share)}`;
      li.classList.toggle("lead", pos === 0);
    });
  }
  render(0);
  // Scrubbing pauses the sprint and moves the story playhead to that month.
  const start = () => ctx.player.block("scrub");
  const end = () => ctx.player.unblock("scrub");
  range.addEventListener("pointerdown", start);
  range.addEventListener("pointerup", end);
  range.addEventListener("blur", end);
  range.addEventListener("input", () => {
    const i = Number(range.value);
    ctx.player.seek(rankingProgressFor(i, n));
    render(i);
  });
  return { el, onProgress(p) { render(rankingMonthAt(p, n)); } };
}

function clock(scene, ctx) {
  const d = scene.data;
  const parts = [["Evening", "5 PM to midnight", d.dayparts.evening], ["Afternoon", "noon to 5 PM", d.dayparts.afternoon],
    ["Morning", "5 AM to noon", d.dayparts.morning], ["Night", "midnight to 5 AM", d.dayparts.night]];
  const hero = `<span class="rank-tag">peak hour</span>${big(d.peak_hour_label, "clock")}`;
  const visual = `<ul class="stat-rows">${parts.map(([k, span, v], i) => `<li style="--i:${i}"><span class="stat-k">${k}<small>${span}</small></span><span class="stat-v">${pct(v)}</span></li>`).join("")}</ul>`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene), visual }) };
}

function biggestDay(scene, ctx) {
  const [y, m, dd] = scene.metrics.date.split("-").map(Number);
  const hero = `<span class="rank-tag">biggest day</span>${big(String(dd), "day")}<span class="unit day-unit">${MONTHS[m - 1]} ${y}</span>`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene) }) };
}

function session(scene, ctx) {
  const hero = `<span class="rank-tag">longest session</span>${big(durationShort(scene.metrics.minutes), "dur")}`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene) }) };
}

function streak(scene, ctx) {
  const s = scene.data.streaks[0];
  const hero = `${big(String(scene.metrics.days), "num")}<span class="unit">days in a row with</span>${big(s.name, "name")}`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene) }) };
}

function repeat(scene, ctx) {
  const hero = `${big(`${scene.metrics.plays}x`, "num")}<span class="unit">plays in one week</span>${big(scene.data.track, "name")}`;
  return { el: shell(scene, ctx, { hero, inner: `<h1 class="visually-hidden">${esc(scene.headline)}</h1>` + body(scene) }) };
}

function eras(scene, ctx) {
  const list = scene.data.eras.map((e, i) => `<li style="--i:${i}"><span class="era-n">${String(e.index).padStart(2, "0")}</span><span class="era-name">${esc(e.label_artist)}</span><span class="era-span">${esc(monthLabel(e.start_month))} to ${esc(monthLabel(e.end_month))}</span></li>`).join("");
  return { el: shell(scene, ctx, { inner: headline(scene) + body(scene), visual: `<ol class="tracklist">${list}</ol>` }) };
}

function earlyLate(scene, ctx) {
  const e = scene.metrics.early;
  const l = scene.metrics.late;
  const stat = (label, a, b) => `<div class="vs"><span class="vs-label">${label}</span><span class="vs-a">${a}</span><span class="vs-b">${b}</span></div>`;
  const visual = `
    <div class="vs-head"><span></span><span>${esc(monthLabel(e.start_month))} to ${esc(monthLabel(e.end_month))}</span><span>${esc(monthLabel(l.start_month))} to ${esc(monthLabel(l.end_month))}</span></div>
    ${stat("Minutes a day", one(e.minutes_per_day), one(l.minutes_per_day))}
    ${stat("Days with a play", pct(e.active_day_rate), pct(l.active_day_rate))}
    ${stat("Artists played", int(e.distinct_artists), int(l.distinct_artists))}
    ${stat("Top 10 artists' share", pct(e.top10_share), pct(l.top10_share))}`;
  return { el: shell(scene, ctx, { inner: headline(scene, "long") + body(scene), visual }) };
}

function summary(scene, ctx) {
  const lines = scene.data.lines.map((l, i) => `<li style="--i:${i}"><span class="sum-label">${esc(l.label)}</span><span class="sum-val">${esc(l.value)}</span></li>`).join("");
  const years = ctx.chapters.map((c) => `<li><button type="button" class="pill chip" data-chapter="${esc(c.id)}"${c.id === ctx.chapterId ? ' aria-current="true"' : ""}>${esc(c.id === "all" ? "All years" : c.label)}${c.partial ? " (partial)" : ""}</button></li>`).join("");
  const inner = headline(scene) + `<div class="jcard"><p class="jcard-title" aria-hidden="true">${esc(ctx.chapterLabel)}</p><ul class="sum-lines">${lines}</ul></div>
    <div class="sum-actions"><button type="button" class="pill solid replay">Replay</button></div>
    <nav aria-label="Chapters"><ul class="chips">${years}</ul></nav>`;
  const el = shell(scene, ctx, { inner });
  el.querySelector(".replay").addEventListener("click", () => ctx.replay());
  for (const b of el.querySelectorAll("[data-chapter]")) b.addEventListener("click", () => ctx.openChapter(b.dataset.chapter));
  return { el };
}

const RENDERERS = {
  opening, minutes, quiz, top, ranking, clock, biggest_day: biggestDay, session, streak, repeat,
  eras, summary, early_late: earlyLate,
};

// Shrink oversized hero type that would overflow the card. CSS gives the starting
// size from character count; real glyph widths vary (M and W are twice as wide as I),
// so measure and scale down once. Never scales up.
export function fitHeroes(root) {
  for (const el of root.querySelectorAll(".big, .answer-name")) {
    el.style.fontSize = "";
    // Measure the resting shape: the entry animation starts with stretched letters.
    el.style.animation = "none";
    const avail = el.clientWidth;
    const need = Math.max(el.scrollWidth, ...[...el.getClientRects()].map((r) => r.width));
    if (avail > 0 && need > avail + 1) {
      const size = parseFloat(getComputedStyle(el).fontSize);
      el.style.fontSize = `${Math.floor(size * (avail / need) * 0.98)}px`;
    }
    el.style.animation = "";
  }
}

export function renderScene(scene, ctx) {
  const r = (RENDERERS[scene.type] || textScene)(scene, ctx);
  return { onProgress() {}, cleanup() {}, ...r };
}

