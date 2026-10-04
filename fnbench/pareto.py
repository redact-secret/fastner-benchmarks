"""Pareto-frontier selection. No scalarization, no weights (issue #2)."""


def dominates(a, b, dims):
    """a dominates b iff a is >= b on every dim and strictly better on at least one.

    `a`/`b` map dim id -> number. Both must be complete over `dims`; a missing value
    makes the pair incomparable rather than worse (unavailable is never zero).
    """
    better = False
    for d in dims:
        va, vb = a.get(d["id"]), b.get(d["id"])
        if va is None or vb is None:
            return False
        if d["direction"] == "max":
            va, vb = va, vb
        else:
            va, vb = -va, -vb
        if va < vb:
            return False
        if va > vb:
            better = True
    return better


def frontier(candidates, dims):
    """candidates: {name: {dim_id: value|None}}.

    Returns (frontier_names, dominated {name: [dominators]}, incomplete {name: [missing dims]}).
    Incomplete candidates are excluded from ranking and reported, never zero-filled.
    """
    incomplete, complete = {}, {}
    for name, vals in candidates.items():
        miss = [d["id"] for d in dims if vals.get(d["id"]) is None]
        if miss:
            incomplete[name] = miss
        else:
            complete[name] = vals
    dominated = {}
    for n, v in complete.items():
        doms = sorted(m for m, w in complete.items() if m != n and dominates(w, v, dims))
        if doms:
            dominated[n] = doms
    front = sorted(n for n in complete if n not in dominated)
    return front, dominated, incomplete
