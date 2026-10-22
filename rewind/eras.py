"""Musical eras: PELT change-point detection on monthly artist-share vectors.

Representation: for every month, each artist's share of that month's recorded
music time, in one shared artist space (every artist that appears in the
export). Shares are square-rooted (Hellinger embedding), so the squared
Euclidean distance between two months is twice their squared Hellinger
distance and every artist's contribution to a boundary can be read off exactly.

Cost: squared error around the segment mean (L2). Penalty: a fixed amount per
segment, expressed as beta times a robust estimate of month-to-month noise.
Search: PELT (Killick et al. 2012) with min_size and jump=1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------- core search

class L2Cost:
    """Squared-error segment cost with O(d) evaluation via cumulative sums."""

    def __init__(self, X: np.ndarray):
        X = np.asarray(X, dtype=float)
        self.n = len(X)
        self.S1 = np.vstack([np.zeros(X.shape[1]), np.cumsum(X, axis=0)])
        self.S2 = np.concatenate([[0.0], np.cumsum(np.einsum("ij,ij->i", X, X))])

    def __call__(self, s: int, e: int) -> float:
        """Cost of rows s..e-1."""
        diff = self.S1[e] - self.S1[s]
        return float(self.S2[e] - self.S2[s] - diff @ diff / (e - s))


def pelt(X: np.ndarray, penalty: float, min_size: int = 3, jump: int = 1) -> list[int]:
    """Return segment end indices (exclusive), last one == len(X).

    Minimises sum(cost(segment)) + penalty * n_segments over segmentations whose
    segments all have at least min_size rows and whose boundaries fall on
    multiples of jump.
    """
    n = len(X)
    if n < 2 * min_size:
        return [n]
    cost = L2Cost(X)
    ends = [t for t in range(min_size, n) if t % jump == 0] + [n]
    F = {0: 0.0}
    last = {0: 0}
    candidates = [0]
    pruned_at: dict[int, int] = {}
    for t in ends:
        # A start s that lost at time u can only be discarded once the winner at
        # u can itself be extended, i.e. from u + min_size on.
        candidates = [s for s in candidates if not (s in pruned_at and t >= pruned_at[s] + min_size)]
        usable = [s for s in candidates if t - s >= min_size]
        values = [F[s] + cost(s, t) + penalty for s in usable]
        if not values:
            continue
        best = int(np.argmin(values))
        F[t] = values[best]
        last[t] = usable[best]
        for s, v in zip(usable, values):
            if v - penalty > F[t] and s not in pruned_at:
                pruned_at[s] = t
        candidates.append(t)
    if n not in F:
        return [n]
    out, t = [], n
    while t > 0:
        out.append(t)
        t = last[t]
    return sorted(out)


def optimal_partition(X: np.ndarray, penalty: float, min_size: int = 3) -> list[int]:
    """Exact O(n^2) dynamic programme with no pruning. Reference for tests."""
    n = len(X)
    if n < 2 * min_size:
        return [n]
    cost = L2Cost(X)
    F = np.full(n + 1, np.inf)
    F[0] = 0.0
    last = np.zeros(n + 1, dtype=int)
    for t in range(min_size, n + 1):
        for s in range(0, t - min_size + 1):
            if s != 0 and s < min_size:
                continue
            if not np.isfinite(F[s]):
                continue
            v = F[s] + cost(s, t) + penalty
            if v < F[t] - 1e-12:
                F[t], last[t] = v, s
    out, t = [], n
    while t > 0:
        out.append(t)
        t = int(last[t])
    return sorted(out)


def noise_scale(X: np.ndarray) -> float:
    """Robust per-month noise: median squared distance between adjacent months / 2."""
    if len(X) < 2:
        return 0.0
    d = np.sum(np.diff(X, axis=0) ** 2, axis=1)
    return float(np.median(d) / 2.0)


def adjacent_distance_baseline(X: np.ndarray, k: float = 3.0, min_gap: int = 3) -> list[int]:
    """Baseline: flag month t when ||x_t - x_{t-1}||^2 exceeds median + k*MAD.

    Peaks closer than min_gap months are suppressed (largest kept). Returns
    boundary indices (start of the new segment) in the same convention as the
    inner ends of pelt().
    """
    if len(X) < 3:
        return []
    d = np.sum(np.diff(X, axis=0) ** 2, axis=1)  # d[i] is between i and i+1
    med = np.median(d)
    mad = np.median(np.abs(d - med)) * 1.4826
    thr = med + k * mad
    flagged = [i + 1 for i in np.argsort(-d) if d[i] > thr]
    chosen: list[int] = []
    for b in flagged:
        if b < min_gap or len(X) - b < min_gap:
            continue
        if all(abs(b - c) >= min_gap for c in chosen):
            chosen.append(b)
    return sorted(chosen)


# ---------------------------------------------------------------- data shaping

@dataclass
class MonthlySpace:
    months: list[str]              # every calendar month in coverage
    artist_ids: list[str]
    artist_names: dict[str, str]
    minutes: np.ndarray            # months x artists, minutes
    total_minutes: np.ndarray      # per month
    coverage_ratio: np.ndarray     # per month
    valid: np.ndarray              # bool per month: used for segmentation
    exclusion_reason: list[str | None] = field(default_factory=list)

    @property
    def shares(self) -> np.ndarray:
        tot = self.minutes.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            s = np.where(tot > 0, self.minutes / np.where(tot > 0, tot, 1), 0.0)
        return s

    @property
    def embedded(self) -> np.ndarray:
        return np.sqrt(self.shares)


def build_space(music: pd.DataFrame, month_rows: list[dict],
                low_activity_minutes: float = config.LOW_ACTIVITY_MINUTES,
                exclude_partial: bool = False) -> MonthlySpace:
    months = [r["month"] for r in month_rows]
    names = music.groupby("artist_id")["artist"].first()
    artist_ids = sorted(names.index)
    col = {a: i for i, a in enumerate(artist_ids)}
    row = {m: i for i, m in enumerate(months)}
    mat = np.zeros((len(months), len(artist_ids)))
    agg = music.groupby(["month", "artist_id"])["ms_played"].sum()
    for (m, a), ms in agg.items():
        mat[row[m], col[a]] += ms / 60000.0
    total = mat.sum(axis=1)
    cov = np.array([r["coverage_ratio"] for r in month_rows])
    valid = np.ones(len(months), dtype=bool)
    reasons: list[str | None] = []
    for i, r in enumerate(month_rows):
        reason = None
        if total[i] == 0:
            reason = "no music listening"
        elif total[i] < low_activity_minutes:
            reason = f"low activity ({total[i]:.0f} < {low_activity_minutes:.0f} min)"
        elif exclude_partial and cov[i] < config.PARTIAL_MONTH_MIN_COVERAGE:
            reason = f"partial month ({cov[i]:.0%} of days covered)"
        valid[i] = reason is None
        reasons.append(reason)
    return MonthlySpace(months, artist_ids, names.to_dict(), mat, total, cov, valid, reasons)


# ---------------------------------------------------------------- detection

@dataclass
class EraResult:
    beta: float
    penalty: float
    noise: float
    min_size: int
    valid_months: list[str]
    boundaries: list[int]          # indices into valid_months where a new era starts
    segments: list[tuple[int, int]]  # [start, end) indices into valid_months


def detect(space: MonthlySpace, beta: float, min_size: int = config.ERA_MIN_SIZE,
           jump: int = config.ERA_JUMP) -> EraResult:
    X = space.embedded[space.valid]
    noise = noise_scale(X)
    penalty = beta * noise
    ends = pelt(X, penalty, min_size=min_size, jump=jump)
    starts = [0] + ends[:-1]
    valid_months = [m for m, v in zip(space.months, space.valid) if v]
    return EraResult(beta, penalty, noise, min_size, valid_months, ends[:-1],
                     list(zip(starts, ends)))


# ---------------------------------------------------------------- explanation

def pooled_shares(space: MonthlySpace, month_idx: list[int]) -> np.ndarray:
    tot = space.minutes[month_idx].sum()
    return space.minutes[month_idx].sum(axis=0) / tot if tot > 0 else np.zeros(space.minutes.shape[1])


def describe_segments(space: MonthlySpace, res: EraResult, top: int = 5) -> list[dict]:
    valid_idx = np.flatnonzero(space.valid)
    overall = pooled_shares(space, list(valid_idx))
    eras = []
    for k, (s, e) in enumerate(res.segments):
        idx = list(valid_idx[s:e])
        sh = pooled_shares(space, idx)
        order = np.lexsort((np.array(space.artist_ids), -sh))
        outside = [i for i in valid_idx if i not in idx]
        sh_out = pooled_shares(space, outside) if outside else np.zeros_like(sh)
        lift = sh - sh_out
        sig_order = [i for i in np.lexsort((np.array(space.artist_ids), -lift)) if sh[i] >= 0.03]
        first_m, last_m = space.months[idx[0]], space.months[idx[-1]]
        span = space.months[space.months.index(first_m): space.months.index(last_m) + 1]
        excluded_inside = [m for m in span if not space.valid[space.months.index(m)]]
        eras.append({
            "id": f"era-{k + 1}",
            "index": k + 1,
            "start_month": first_m,
            "end_month": last_m,
            "valid_months": len(idx),
            "excluded_months_inside": excluded_inside,
            "minutes": round(float(space.total_minutes[idx].sum()), 1),
            "top_artists": [
                {"id": space.artist_ids[i], "name": space.artist_names[space.artist_ids[i]],
                 "share": round(float(sh[i]), 4),
                 "minutes": round(float(space.minutes[idx, i].sum()), 1)}
                for i in order[:top]
            ],
            "signature_artist": (
                {"id": space.artist_ids[sig_order[0]], "name": space.artist_names[space.artist_ids[sig_order[0]]],
                 "share": round(float(sh[sig_order[0]]), 4),
                 "share_outside": round(float(sh_out[sig_order[0]]), 4)}
                if sig_order else None
            ),
        })
    return eras


def explain_boundary(space: MonthlySpace, res: EraResult, b: int, top: int = 4,
                     move: float = 0.02) -> dict:
    """Explain the boundary between segment b-1 and segment b by artist share changes."""
    valid_idx = np.flatnonzero(space.valid)
    (s0, e0), (s1, e1) = res.segments[b - 1], res.segments[b]
    before, after = list(valid_idx[s0:e0]), list(valid_idx[s1:e1])
    earlier = list(valid_idx[:s0])
    X = space.embedded
    mA, mB = X[before].mean(axis=0), X[after].mean(axis=0)
    contrib = (mB - mA) ** 2
    total = float(contrib.sum())
    shA, shB = pooled_shares(space, before), pooled_shares(space, after)
    shE = pooled_shares(space, earlier) if earlier else np.zeros_like(shA)
    ids = np.array(space.artist_ids)

    def item(i):
        return {"id": space.artist_ids[i], "name": space.artist_names[space.artist_ids[i]],
                "share_before": round(float(shA[i]), 4), "share_after": round(float(shB[i]), 4),
                "change": round(float(shB[i] - shA[i]), 4),
                "contribution": round(float(contrib[i] / total), 4) if total else 0.0}

    delta = shB - shA
    rose = [i for i in np.lexsort((ids, -delta)) if delta[i] >= move][:top]
    declined = [i for i in np.lexsort((ids, delta)) if -delta[i] >= move][:top]
    persisted = [i for i in np.lexsort((ids, -np.minimum(shA, shB)))
                 if shA[i] >= 0.03 and shB[i] >= 0.03][:top]
    returned = [i for i in np.lexsort((ids, -shB))
                if shB[i] >= move and shA[i] < 0.005 and shE[i] >= move][:top]
    top_contrib = np.lexsort((ids, -contrib))[:8]
    return {
        "boundary_month": space.months[after[0]],
        "previous_era_end": space.months[before[-1]],
        "distance": round(total, 4),
        "hellinger": round(math.sqrt(total / 2.0), 4),
        "top_contributors": [item(i) for i in top_contrib],
        "top8_contribution": round(float(contrib[top_contrib].sum() / total), 4) if total else 0.0,
        "rose": [item(i) for i in rose],
        "declined": [item(i) for i in declined],
        "persisted": [item(i) for i in persisted],
        "returned": [item(i) for i in returned],
    }


def keep_boundaries(res: EraResult, keep: list[int]) -> EraResult:
    """Drop boundaries not in keep (indices into valid_months), merging the eras around them."""
    kept = sorted(b for b in res.boundaries if b in keep)
    ends = kept + [len(res.valid_months)]
    starts = [0] + kept
    return EraResult(res.beta, res.penalty, res.noise, res.min_size, res.valid_months, kept,
                     list(zip(starts, ends)))
