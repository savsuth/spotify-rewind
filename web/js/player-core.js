// Story playback state machine. No DOM access: the clock and timer functions are
// injected, so tests can drive time deterministically.
//
// Invariants:
// - At most one pending timeout exists at any moment (sync() always clears first).
// - A timeout that fires after the scene or chapter changed is ignored (generation check).
// - Progress only advances while the user wants playback AND nothing blocks it.
//   Blockers: "hidden" (tab hidden), "method" (How calculated open), "picker"
//   (year picker open), "quiz" (quiz waiting for an answer), "scrub" (user scrubbing).

export function createPlayer({ durationOf, waitsForInput = () => false, clock, onChange = () => {} }) {
  const { now, setTimeout: setT, clearTimeout: clearT } = clock;
  let scenes = [];
  let index = 0;
  let wantsPlay = true;
  let ended = false;
  let elapsed = 0;          // ms of progress banked before the current run
  let runStart = null;      // clock time the current run started, or null when not running
  let timer = null;
  let generation = 0;
  let speed = 1;            // 1 = normal; > 1 = slower (durations multiplied)
  const blockers = new Set();
  const answered = new Set(); // scene indices whose quiz is resolved

  const duration = () => (scenes.length ? durationOf(scenes[index]) * speed : 0);
  const running = () => runStart !== null;
  const canRun = () => wantsPlay && !ended && blockers.size === 0 && scenes.length > 0;

  function bank() {
    if (running()) {
      elapsed += now() - runStart;
      runStart = null;
    }
  }

  function clearTimer() {
    if (timer !== null) {
      clearT(timer);
      timer = null;
    }
  }

  // Recompute the running state from the inputs. The only place a timer starts.
  function sync() {
    if (!canRun()) {
      bank();
      clearTimer();
      return;
    }
    if (!running()) runStart = now();
    clearTimer();
    const remaining = Math.max(0, duration() - elapsed - (now() - runStart));
    const gen = generation;
    timer = setT(() => {
      if (gen !== generation) return; // stale
      timer = null;
      advanceFromTimer();
    }, remaining);
  }

  function emit() {
    onChange(api.state());
  }

  function finish() {
    bank();
    elapsed = duration();
    ended = true;
    clearTimer();
    generation += 1;
    emit();
  }

  function enterScene(i) {
    generation += 1;
    clearTimer();
    runStart = null;
    elapsed = 0;
    index = Math.max(0, Math.min(scenes.length - 1, i));
    ended = false;
    blockers.delete("quiz");
    blockers.delete("scrub");
    if (waitsForInput(scenes[index]) && !answered.has(index)) blockers.add("quiz");
    sync();
    emit();
  }

  function advanceFromTimer() {
    // Last scene: stop at full progress and keep the final frame on screen.
    if (index >= scenes.length - 1) finish();
    else enterScene(index + 1);
  }

  const api = {
    load(newScenes, startIndex = 0) {
      scenes = newScenes.slice();
      answered.clear();
      wantsPlay = true;
      enterScene(startIndex);
    },
    next() {
      if (!scenes.length) return;
      if (index >= scenes.length - 1) finish();
      else enterScene(index + 1);
    },
    prev() {
      if (!scenes.length) return;
      // More than 1.5 s into a scene: restart it. Otherwise go back one scene.
      if (api.elapsedMs() > 1500 && !ended) enterScene(index);
      else enterScene(index - 1);
    },
    goTo(i) {
      if (scenes.length) enterScene(i);
    },
    replay() {
      answered.clear();
      wantsPlay = true;
      enterScene(0);
    },
    pause() {
      wantsPlay = false;
      sync();
      emit();
    },
    resume() {
      if (ended) return;
      wantsPlay = true;
      sync();
      emit();
    },
    toggle() {
      if (wantsPlay && !ended) api.pause();
      else api.resume();
    },
    block(reason) {
      if (blockers.has(reason)) return;
      blockers.add(reason);
      sync();
      emit();
    },
    unblock(reason) {
      if (!blockers.has(reason)) return;
      blockers.delete(reason);
      sync();
      emit();
    },
    resolveQuiz() {
      answered.add(index);
      api.unblock("quiz");
    },
    isQuizResolved(i = index) {
      return answered.has(i);
    },
    setSpeed(s) {
      // Keep the visible fraction of the scene when the pace changes.
      const frac = api.progress();
      bank();
      speed = s;
      elapsed = frac * duration();
      sync();
      emit();
    },
    elapsedMs() {
      return elapsed + (running() ? now() - runStart : 0);
    },
    progress() {
      if (ended) return 1;
      const d = duration();
      return d ? Math.min(1, api.elapsedMs() / d) : 0;
    },
    // Move within the current scene (used by the ranking scrubber). Frac in 0..1.
    seek(frac) {
      bank();
      elapsed = Math.max(0, Math.min(1, frac)) * duration();
      sync(); // restarts the run from the new point when playback is allowed
      emit();
    },
    hasPendingTimer() {
      return timer !== null;
    },
    state() {
      return {
        index,
        count: scenes.length,
        scene: scenes[index],
        playing: running(),
        wantsPlay,
        ended,
        speed,
        blockers: [...blockers].sort(),
      };
    },
  };
  return api;
}

export const RANKING_HOLD_MS = 4000;

export function rankingStepMs(months) {
  return months > 24 ? 450 : 900;
}

// Reading-time scene duration: never under 7 s, longer for text and charts.
export function readingDuration(scene, { perWordMs = 280, baseMs = 5000, minMs = 7000, maxMs = 16000 } = {}) {
  if (scene.type === "ranking") {
    const months = scene.data && scene.data.months ? scene.data.months.length : 0;
    return Math.max(minMs, months * rankingStepMs(months) + RANKING_HOLD_MS);
  }
  const words = `${scene.headline || ""} ${scene.body || ""}`.trim().split(/\s+/).filter(Boolean).length;
  let ms = baseMs + words * perWordMs;
  if (scene.chart) ms += 3000;
  if (scene.type === "top") ms += 4000;
  if (scene.type === "quiz") ms += 3000; // reading time for the reveal after an answer
  return Math.max(minMs, Math.min(maxMs, ms));
}

// Which month the ranking sprint shows at a given scene progress (0..1).
// Derived from progress, so pausing the story freezes the sprint with no extra timer.
export function rankingMonthAt(progress, months) {
  if (months <= 0) return 0;
  const step = rankingStepMs(months);
  const total = months * step + RANKING_HOLD_MS;
  const i = Math.floor((progress * total) / step);
  return Math.max(0, Math.min(months - 1, i));
}

// Inverse of rankingMonthAt: the progress fraction at which month i is first shown.
export function rankingProgressFor(i, months) {
  const step = rankingStepMs(months);
  const total = months * step + RANKING_HOLD_MS;
  return Math.min(1, (i * step + 1) / total);
}
