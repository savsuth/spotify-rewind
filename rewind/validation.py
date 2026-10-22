"""Validation for the era detector.

1. Synthetic histories with known boundaries (calibrates the penalty).
2. Parameter sensitivity on the real data.
3. Boundary stability under block resampling of listening days.
4. Comparison with an adjacent-month-distance baseline.
5. A month-order permutation null on the real data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, eras

BETA_GRID = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)
MIN_SIZE_GRID = (2, 3, 4, 6)
BASELINE_K_GRID = (1.0, 2.0, 3.0, 4.0, 6.0)
TOLERANCE = 1  # a detected boundary matches a true one within +/- 1 month


# ---------------------------------------------------------------- synthetic

def _regimes(rng: np.random.Generator, n_artists: int, n_regimes: int) -> np.ndarray:
    """Regime share vectors: a shared base of steady artists plus regime favourites."""
    base = rng.dirichlet(np.full(n_artists, 0.15))
    out = []
    for _ in range(n_regimes):
        fav = np.zeros(n_artists)
        picks = rng.choice(n_artists, size=6, replace=False)
        fav[picks] = rng.dirichlet(np.full(6, 1.0))
        out.append(0.55 * base + 0.45 * fav)
    return np.array(out)


def synth_history(rng: np.random.Generator, regime_of_month: np.ndarray, regimes: np.ndarray,
                  plays: np.ndarray, alpha: float) -> np.ndarray:
    """Monthly share vectors with month-level overdispersion and multinomial sampling."""
    rows = []
    for m, r in enumerate(regime_of_month):
        p = regimes[r] if np.ndim(r) == 0 else r
        pm = rng.dirichlet(alpha * p + 1e-6)
        counts = rng.multinomial(int(plays[m]), pm)
        rows.append(counts / max(counts.sum(), 1))
    return np.array(rows)


def scenarios(rng: np.random.Generator, n: int = 64) -> dict[str, dict]:
    """Scenario name -> regime index per month (or explicit mixtures) and true boundaries.

    Change points are placed at fixed fractions of the history length, so any export
    length works; for n = 64 they fall at the same months as the original design.
    """
    at = lambda f: int(round(f * n))
    out = {}
    out["null"] = {"regime": np.zeros(n, dtype=int), "truth": []}
    c = at(.47)
    out["one_change"] = {"regime": np.array([0] * c + [1] * (n - c)), "truth": [c]}
    cuts = [at(.22), at(.48), at(.73)]
    reg = np.zeros(n, dtype=int)
    for k, cut in enumerate(cuts):
        reg[cut:] = k + 1
    out["three_changes"] = {"regime": reg, "truth": cuts}
    a, b = at(.34), at(.66)
    out["return"] = {"regime": np.array([0] * a + [1] * (b - a) + [0] * (n - b)), "truth": [a, b]}
    s0 = at(.44)
    out["short_era"] = {"regime": np.array([0] * s0 + [1] * 4 + [0] * (n - s0 - 4)), "truth": [s0, s0 + 4]}
    return out


def drift_mixture(regimes: np.ndarray, n: int = 64, start: int | None = None, length: int | None = None) -> np.ndarray:
    start = int(round(.4 * n)) if start is None else start
    length = min(12, max(4, n // 5)) if length is None else length
    w = np.clip((np.arange(n) - start) / length, 0, 1)
    return np.outer(1 - w, regimes[0]) + np.outer(w, regimes[1])


def match(detected: list[int], truth: list[int], tol: int = TOLERANCE) -> tuple[int, int, int]:
    """Greedy one-to-one matching. Returns (true positives, false positives, false negatives)."""
    unused = list(truth)
    tp = 0
    for d in sorted(detected):
        hits = [t for t in unused if abs(t - d) <= tol]
        if hits:
            unused.remove(min(hits, key=lambda t: abs(t - d)))
            tp += 1
    return tp, len(detected) - tp, len(unused)


def calibrate_alpha(target_noise: float, plays: np.ndarray, seed: int) -> float:
    """Pick month-level overdispersion so synthetic noise matches the real noise scale."""
    rng = np.random.default_rng(seed)
    regimes = _regimes(rng, 400, 1)
    best, best_gap = None, np.inf
    for alpha in (25, 50, 75, 100, 150, 200, 300, 400, 600, 800):
        vals = []
        for _ in range(6):
            X = np.sqrt(synth_history(rng, np.zeros(len(plays), dtype=int), regimes, plays, alpha))
            vals.append(eras.noise_scale(X))
        gap = abs(np.median(vals) - target_noise)
        if gap < best_gap:
            best, best_gap = alpha, gap
    return float(best)


def run_synthetic(plays: np.ndarray, target_noise: float, reps: int = 30,
                  seed: int = config.RANDOM_SEED) -> dict:
    alpha = calibrate_alpha(target_noise, plays, seed)
    rng = np.random.default_rng(seed + 1)
    n = len(plays)
    names = list(scenarios(rng, n)) + ["drift"]
    tallies: dict = {}

    def tally(method: str, scen: str, det: list[int], truth: list[int], tol: int):
        tp, fp, fn = match(det, truth, tol)
        t = tallies.setdefault(method, {}).setdefault(scen, {"tp": 0, "fp": 0, "fn": 0, "runs": 0,
                                                              "runs_with_fp": 0, "n_detected": []})
        t["tp"] += tp
        t["fp"] += fp
        t["fn"] += fn
        t["runs"] += 1
        t["runs_with_fp"] += int(fp > 0)
        t["n_detected"].append(len(det))

    for rep in range(reps):
        regimes = _regimes(rng, 400, 4)
        scen = scenarios(rng, n)
        d_start, d_len = int(round(.4 * n)), min(12, max(4, n // 5))
        scen["drift"] = {"regime": drift_mixture(regimes, n, d_start, d_len), "truth": [d_start + d_len // 2]}
        for name in names:
            spec = scen[name]
            # Drift has no single true month; accept +/- 6 around its midpoint.
            tol = 6 if name == "drift" else TOLERANCE
            X = np.sqrt(synth_history(rng, spec["regime"], regimes, plays, alpha))
            noise = eras.noise_scale(X)
            for beta in BETA_GRID:
                for ms in MIN_SIZE_GRID:
                    det = eras.pelt(X, beta * noise, min_size=ms)[:-1]
                    tally(f"pelt b={beta} m={ms}", name, det, spec["truth"], tol)
            for k in BASELINE_K_GRID:
                det = eras.adjacent_distance_baseline(X, k=k, min_gap=3)
                tally(f"baseline k={k}", name, det, spec["truth"], tol)

    summary = {}
    for method, by_scen in tallies.items():
        rows = {}
        TP = FP = FN = 0
        for name, t in by_scen.items():
            prec = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else (1.0 if not t["fn"] else 0.0)
            rec = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 1.0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            rows[name] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
                          "false_positive_runs": round(t["runs_with_fp"] / t["runs"], 3),
                          "mean_detected": round(float(np.mean(t["n_detected"])), 2)}
            if name not in ("null",):
                TP += t["tp"]; FP += t["fp"]; FN += t["fn"]
        p = TP / (TP + FP) if TP + FP else 0.0
        r = TP / (TP + FN) if TP + FN else 0.0
        rows["pooled_changes"] = {"precision": round(p, 3), "recall": round(r, 3),
                                  "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}
        summary[method] = rows
    return {"alpha": alpha, "reps": reps, "months": n, "tolerance_months": TOLERANCE,
            "drift_tolerance_months": 6, "methods": summary}


def choose_beta(synthetic: dict, min_size: int = config.ERA_MIN_SIZE, max_null_fp: float = 0.1) -> dict:
    """Smallest-risk beta: best pooled F1 among betas whose null false-positive rate <= max_null_fp."""
    rows = []
    for beta in BETA_GRID:
        m = synthetic["methods"][f"pelt b={beta} m={min_size}"]
        rows.append((beta, m["null"]["false_positive_runs"], m["pooled_changes"]["f1"]))
    ok = [r for r in rows if r[1] <= max_null_fp]
    pool = ok if ok else rows
    best = max(pool, key=lambda r: (r[2], -r[0]))
    return {"beta": best[0], "null_false_positive_runs": best[1], "pooled_f1": best[2],
            "rule": f"highest pooled F1 among betas with null false-positive rate <= {max_null_fp}",
            "table": [{"beta": b, "null_fp_runs": f, "pooled_f1": s} for b, f, s in rows]}


def choose_baseline_k(synthetic: dict, max_null_fp: float = 0.1) -> float:
    rows = []
    for k in BASELINE_K_GRID:
        m = synthetic["methods"][f"baseline k={k}"]
        rows.append((k, m["null"]["false_positive_runs"], m["pooled_changes"]["f1"]))
    ok = [r for r in rows if r[1] <= max_null_fp] or rows
    return max(ok, key=lambda r: (r[2], -r[0]))[0]


# ---------------------------------------------------------------- real data

def sensitivity(music: pd.DataFrame, month_rows: list[dict]) -> list[dict]:
    """Boundaries under alternative settings and month-handling rules."""
    variants = []
    base_space = eras.build_space(music, month_rows)
    for beta in BETA_GRID:
        for ms in MIN_SIZE_GRID:
            r = eras.detect(base_space, beta, ms)
            variants.append({"variant": "default months", "beta": beta, "min_size": ms,
                             "boundaries": [r.valid_months[b] for b in r.boundaries]})
    alt = {
        "exclude partial months": eras.build_space(music, month_rows, exclude_partial=True),
        "low-activity floor 150 min": eras.build_space(music, month_rows, low_activity_minutes=150),
        "low-activity floor 600 min": eras.build_space(music, month_rows, low_activity_minutes=600),
    }
    for name, space in alt.items():
        for beta in BETA_GRID:
            r = eras.detect(space, beta, config.ERA_MIN_SIZE)
            variants.append({"variant": name, "beta": beta, "min_size": config.ERA_MIN_SIZE,
                             "boundaries": [r.valid_months[b] for b in r.boundaries]})
    return variants


def day_matrix(music: pd.DataFrame, space: eras.MonthlySpace) -> tuple[np.ndarray, np.ndarray, list[pd.Timestamp]]:
    """Days x artists minutes, and the month index of each day (all covered days, zeros kept)."""
    first, last = music["local_date"].min(), music["local_date"].max()
    days = list(pd.date_range(first, last, freq="D"))
    drow = {d: i for i, d in enumerate(days)}
    col = {a: i for i, a in enumerate(space.artist_ids)}
    mat = np.zeros((len(days), len(space.artist_ids)), dtype=np.float32)
    agg = music.groupby(["local_date", "artist_id"])["ms_played"].sum()
    for (d, a), ms in agg.items():
        mat[drow[d], col[a]] += ms / 60000.0
    mrow = {m: i for i, m in enumerate(space.months)}
    month_of_day = np.array([mrow[d.strftime("%Y-%m")] for d in days])
    return mat, month_of_day, days


def bootstrap(music: pd.DataFrame, space: eras.MonthlySpace, result: eras.EraResult,
              reps: int = 200, block_days: int = 7, seed: int = config.RANDOM_SEED) -> dict:
    """Moving-block resampling of listening days within each month; rerun the detector."""
    rng = np.random.default_rng(seed)
    mat, month_of_day, _ = day_matrix(music, space)
    n_months = len(space.months)
    day_idx_by_month = [np.flatnonzero(month_of_day == m) for m in range(n_months)]
    detected_months = [result.valid_months[b] for b in result.boundaries]
    hits = {m: 0 for m in detected_months}
    counts = []
    positions: dict[str, int] = {}
    valid_months = result.valid_months
    pos = {m: i for i, m in enumerate(valid_months)}
    for _ in range(reps):
        resampled = np.zeros_like(space.minutes)
        for m, idx in enumerate(day_idx_by_month):
            L = len(idx)
            if L == 0:
                continue
            b = min(block_days, L)
            n_blocks = int(np.ceil(L / b))
            starts = rng.integers(0, L - b + 1, size=n_blocks)
            chosen = np.concatenate([idx[s:s + b] for s in starts])[:L]
            resampled[m] = mat[chosen].sum(axis=0)
        boot_space = eras.MonthlySpace(space.months, space.artist_ids, space.artist_names, resampled,
                                       resampled.sum(axis=1), space.coverage_ratio, space.valid,
                                       space.exclusion_reason)
        r = eras.detect(boot_space, result.beta, result.min_size)
        found = [r.valid_months[b] for b in r.boundaries]
        counts.append(len(found))
        for f in found:
            positions[f] = positions.get(f, 0) + 1
        for m in detected_months:
            if any(abs(pos[f] - pos[m]) <= TOLERANCE for f in found):
                hits[m] += 1
    return {
        "reps": reps,
        "block_days": block_days,
        "tolerance_months": TOLERANCE,
        "boundary_stability": {m: round(h / reps, 3) for m, h in hits.items()},
        "boundary_count_distribution": {str(k): int(v) for k, v in
                                        zip(*np.unique(counts, return_counts=True))},
        "boundary_frequency_by_month": {m: round(c / reps, 3) for m, c in sorted(positions.items())},
    }


def permutation_null(space: eras.MonthlySpace, beta: float, min_size: int, reps: int = 200,
                     seed: int = config.RANDOM_SEED) -> dict:
    """Shuffle the order of valid months; temporal structure gone, so boundaries should vanish."""
    rng = np.random.default_rng(seed + 7)
    X = space.embedded[space.valid]
    counts = []
    for _ in range(reps):
        Xp = X[rng.permutation(len(X))]
        counts.append(len(eras.pelt(Xp, beta * eras.noise_scale(Xp), min_size=min_size)) - 1)
    counts = np.array(counts)
    return {"reps": reps, "runs_with_any_boundary": round(float(np.mean(counts > 0)), 3),
            "mean_boundaries": round(float(counts.mean()), 3)}
