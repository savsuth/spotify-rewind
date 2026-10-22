import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createPlayer, readingDuration, rankingMonthAt, rankingProgressFor, rankingStepMs,
} from "../../web/js/player-core.js";

// Deterministic fake clock with a timer queue.
function fakeClock() {
  let t = 0;
  let id = 0;
  const timers = new Map();
  return {
    now: () => t,
    setTimeout(fn, ms) { id += 1; timers.set(id, { at: t + ms, fn }); return id; },
    clearTimeout(h) { timers.delete(h); },
    pending: () => timers.size,
    advance(ms) {
      const end = t + ms;
      for (;;) {
        let next = null;
        for (const [h, v] of timers) if (v.at <= end && (!next || v.at < next[1].at)) next = [h, v];
        if (!next) break;
        timers.delete(next[0]);
        t = next[1].at;
        next[1].fn();
      }
      t = end;
    },
  };
}

const scenes = [
  { id: "a", type: "opening" }, { id: "b", type: "quiz" }, { id: "c", type: "top" }, { id: "d", type: "summary" },
];

function make(extra = {}) {
  const clock = fakeClock();
  const changes = [];
  const p = createPlayer({
    durationOf: () => 1000,
    waitsForInput: (s) => s.type === "quiz",
    clock,
    onChange: (s) => changes.push(s),
    ...extra,
  });
  return { p, clock, changes };
}

test("autoplay advances after the scene duration", () => {
  const { p, clock } = make();
  p.load(scenes);
  assert.equal(p.state().index, 0);
  clock.advance(999);
  assert.equal(p.state().index, 0);
  clock.advance(1);
  assert.equal(p.state().index, 1);
});

test("quiz scene waits for an answer, then runs its own duration", () => {
  const { p, clock } = make();
  p.load(scenes, 1);
  assert.deepEqual(p.state().blockers, ["quiz"]);
  clock.advance(10_000);
  assert.equal(p.state().index, 1, "does not advance while unanswered");
  assert.equal(clock.pending(), 0, "no timer while blocked");
  p.resolveQuiz();
  clock.advance(1000);
  assert.equal(p.state().index, 2);
});

test("skip on a quiz (next) moves on, and returning shows it resolved only if answered", () => {
  const { p } = make();
  p.load(scenes, 1);
  p.next();
  assert.equal(p.state().index, 2);
  p.goTo(1);
  assert.deepEqual(p.state().blockers, ["quiz"], "skipped quiz still waits");
  p.resolveQuiz();
  p.goTo(2);
  p.goTo(1);
  assert.deepEqual(p.state().blockers, [], "answered quiz does not block again");
});

test("pause and resume preserve progress", () => {
  const { p, clock } = make();
  p.load(scenes);
  clock.advance(400);
  p.pause();
  assert.equal(clock.pending(), 0);
  clock.advance(5000);
  assert.equal(p.state().index, 0);
  assert.ok(Math.abs(p.progress() - 0.4) < 1e-9);
  p.resume();
  clock.advance(599);
  assert.equal(p.state().index, 0);
  clock.advance(1);
  assert.equal(p.state().index, 1);
});

test("hidden tab and method panel block progress independently", () => {
  const { p, clock } = make();
  p.load(scenes);
  clock.advance(300);
  p.block("hidden");
  p.block("method");
  clock.advance(5000);
  p.unblock("hidden");
  clock.advance(5000);
  assert.equal(p.state().index, 0, "still blocked by method panel");
  assert.ok(Math.abs(p.progress() - 0.3) < 1e-9);
  p.unblock("method");
  clock.advance(700);
  assert.equal(p.state().index, 1);
});

test("unblocking does not resume a user pause", () => {
  const { p, clock } = make();
  p.load(scenes);
  p.pause();
  p.block("method");
  p.unblock("method");
  clock.advance(5000);
  assert.equal(p.state().index, 0);
  assert.equal(p.state().wantsPlay, false);
});

test("rapid navigation never leaves more than one pending timer", () => {
  const { p, clock } = make();
  p.load(scenes);
  for (let i = 0; i < 50; i += 1) {
    p.next(); p.prev(); p.goTo(i % 4); p.pause(); p.resume(); p.block("hidden"); p.unblock("hidden");
    assert.ok(clock.pending() <= 1, `pending ${clock.pending()}`);
  }
});

test("a timer from a previous chapter cannot fire into the new one", () => {
  const clock = fakeClock();
  let fired = 0;
  const p = createPlayer({ durationOf: () => 1000, clock, onChange: () => { fired += 1; } });
  p.load(scenes);
  clock.advance(900);
  p.load([{ id: "x", type: "opening" }, { id: "y", type: "opening" }]);
  clock.advance(500);
  assert.equal(p.state().index, 0, "old 100 ms remainder did not advance the new chapter");
  assert.equal(clock.pending(), 1);
});

test("last scene ends at full progress without wrapping; replay restarts", () => {
  const { p, clock } = make();
  p.load(scenes, 3);
  clock.advance(1000);
  assert.equal(p.state().index, 3);
  assert.equal(p.state().ended, true);
  assert.equal(p.progress(), 1);
  assert.equal(clock.pending(), 0);
  p.next();
  assert.equal(p.state().index, 3);
  p.replay();
  assert.equal(p.state().index, 0);
  assert.equal(p.state().ended, false);
  assert.equal(p.state().wantsPlay, true);
});

test("replay clears quiz answers", () => {
  const { p } = make();
  p.load(scenes, 1);
  p.resolveQuiz();
  p.replay();
  p.goTo(1);
  assert.deepEqual(p.state().blockers, ["quiz"]);
});

test("prev restarts the scene after 1.5 s, otherwise goes back", () => {
  const clock = fakeClock();
  const p = createPlayer({ durationOf: () => 5000, clock });
  p.load(scenes, 2);
  clock.advance(2000);
  p.prev();
  assert.equal(p.state().index, 2);
  assert.equal(p.elapsedMs(), 0);
  p.prev();
  assert.equal(p.state().index, 1);
});

test("slower pace keeps the visible fraction and stretches the rest", () => {
  const { p, clock } = make();
  p.load(scenes);
  clock.advance(500);
  p.setSpeed(2);
  assert.ok(Math.abs(p.progress() - 0.5) < 1e-9);
  clock.advance(999);
  assert.equal(p.state().index, 0);
  clock.advance(1);
  assert.equal(p.state().index, 1);
});

test("seek moves within a scene and keeps playing", () => {
  const { p, clock } = make();
  p.load(scenes);
  p.seek(0.9);
  clock.advance(100);
  assert.equal(p.state().index, 1);
});

test("reading durations are at least 7 s and ranking scales with months", () => {
  assert.ok(readingDuration({ type: "opening", headline: "x" }) >= 7000);
  const long = readingDuration({ type: "transition", headline: "a ".repeat(80), body: "b ".repeat(80), chart: "c" });
  assert.equal(long, 16000);
  const ranking = readingDuration({ type: "ranking", data: { months: new Array(65).fill(0) } });
  assert.equal(ranking, 65 * 450 + 4000);
});

test("rankingMonthAt covers every month and holds on the last", () => {
  for (const n of [7, 12, 65]) {
    assert.equal(rankingMonthAt(0, n), 0);
    assert.equal(rankingMonthAt(1, n), n - 1);
    const seen = new Set();
    for (let k = 0; k <= 1000; k += 1) seen.add(rankingMonthAt(k / 1000, n));
    assert.equal(seen.size, n);
    for (let i = 0; i < n; i += 1) assert.equal(rankingMonthAt(rankingProgressFor(i, n), n), i);
  }
  assert.equal(rankingStepMs(12), 900);
});

test("a stale callback cannot discard the current chapter's timer handle", () => {
  const callbacks = [];
  const pending = new Set();
  const clock = {
    now: () => 0,
    setTimeout(fn) { callbacks.push(fn); pending.add(callbacks.length); return callbacks.length; },
    clearTimeout(id) { pending.delete(id); },
  };
  const p = createPlayer({ durationOf: () => 1000, clock });
  p.load(scenes);
  const stale = callbacks[0];
  p.load(scenes);
  stale();
  assert.equal(p.state().index, 0);
  assert.equal(p.hasPendingTimer(), true, "the replacement timer must still be tracked");
  p.pause();
  assert.equal(pending.size, 0, "pausing must clear the replacement timer");
});

test("scrub pauses the ranking and release resumes from the selected month", () => {
  const clock = fakeClock();
  const p = createPlayer({ durationOf: readingDuration, clock });
  p.load([{ type: "ranking", data: { months: new Array(12).fill(0) } }]);
  clock.advance(1000);
  p.block("scrub");
  p.seek(rankingProgressFor(5, 12));
  const fraction = p.progress();
  clock.advance(5000);
  assert.equal(p.progress(), fraction);
  assert.equal(rankingMonthAt(p.progress(), 12), 5);
  assert.equal(clock.pending(), 0);
  p.unblock("scrub");
  clock.advance(900);
  assert.equal(rankingMonthAt(p.progress(), 12), 6);
  assert.equal(clock.pending(), 1);
});
