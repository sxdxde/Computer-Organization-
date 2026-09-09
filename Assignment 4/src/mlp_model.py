"""
Blocking vs. non-blocking cache / MSHR timing model, used ONLY for the
Result-Generation experiment (Section 7 of the report).

Why a separate model from `HierarchySim`'s own cumulative clock: that clock
is deliberately a *blocking*, single-outstanding-miss model (every access,
hit or miss, is fully serialized). Memory-level parallelism is precisely the
ability of MULTIPLE misses to be outstanding and completing concurrently,
which a single running cycle counter cannot represent. So this module takes
the hit/miss CLASSIFICATION (and the latency each access would cost in
isolation) from `HierarchySim`, and re-times the access sequence under an
explicit MSHR model:

  - `mshr_count` outstanding-miss slots, each tracked by its "free at" cycle.
  - A demand HIT never needs an MSHR; it is charged its L1 latency and the
    core's issue point advances by that amount (simple in-order issue).
  - A demand MISS needs a free MSHR slot. If one is free, the request starts
    immediately (possibly overlapping previously issued, still-outstanding
    misses); if all `mshr_count` slots are busy, issuing STALLS until one
    frees (the "no free MSHR -> stall" structural hazard).
  - `dependent=True` additionally forces the core to wait for the miss's
    OWN completion before issuing anything else (the next address is not
    known until this load returns) -- this is true regardless of
    `mshr_count`, which is exactly the point: extra MSHRs cannot help a
    request stream that has no independence to exploit.
  - `dependent=False` lets the core keep issuing subsequent (independent)
    misses into other free MSHR slots while earlier ones are still
    outstanding -- multiple misses overlap in time, hiding their latency
    behind one another (memory-level parallelism).

`mshr_count=1` with `dependent=False` degenerates to a fully blocking
cache: only one miss can ever be outstanding, so independent streams gain
nothing over the dependent case -- exactly the textbook definition of a
blocking cache.
"""

from __future__ import annotations

import heapq

from cache_core import HierarchySim


def classify_stream(addr_stream, hierarchy_kwargs):
    """Run the address stream through a baseline (no VC, no prefetch)
    HierarchySim purely to classify each access as a hit or a miss and to
    record the latency it would cost IN ISOLATION (i.e. the per-access
    delta of the hierarchy's own blocking clock) -- this delta already
    encodes which level served the request (L1/L2/LLC/DRAM) via the
    cumulative-latency convention used everywhere else in this project."""
    sim = HierarchySim(**hierarchy_kwargs)
    lats = []
    sids = []
    for addr, sid in addr_stream:
        before = sim.clock
        sim.access(addr, sid)
        lats.append(sim.clock - before)
        sids.append(sid)
    return lats, sids, sim.snapshot(), sim.l1.latency


def simulate_mshr(lats, stream_ids, mshr_count: int, l1_latency: int):
    """General timing model with two overlapping constraints:

      1. WITHIN one stream_id, accesses are dependent -- the next access on
         that stream cannot issue before the previous one on that SAME
         stream has completed (`stream_ready[sid]`).
      2. ACROSS all streams, at most `mshr_count` misses may be outstanding
         at once (the shared MSHR resource, `heap`); a miss that finds no
         free slot stalls until one frees.
      3. A single global issue port (>= 1 cycle between any two issues) is
         also modeled, but with realistic MSHR counts this is never the
         binding constraint here -- (1) and (2) are.

    Pass every access with the SAME stream_id to get the fully-serialized
    "dependent chain" behaviour (case 1 alone forces total serialization,
    irrespective of `mshr_count`). Pass K distinct stream_ids (round-robin
    interleaved) to get the "K independent streams" behaviour, where
    increasing `mshr_count` helps only up to about K before saturating,
    since at most K requests (one per stream) can ever be simultaneously
    ready to issue.
    """
    heap = [0] * max(1, mshr_count)
    heapq.heapify(heap)
    stream_ready: dict = {}
    global_issue = 0
    max_completion = 0
    n_misses = 0
    n_hits = 0
    miss_service_sum = 0

    for lat, sid in zip(lats, stream_ids):
        ready = stream_ready.get(sid, 0)
        if global_issue > ready:
            ready = global_issue
        is_miss = lat > l1_latency
        if not is_miss:
            n_hits += 1
            finish = ready + lat
            stream_ready[sid] = finish
            global_issue = ready + 1
            if finish > max_completion:
                max_completion = finish
            continue

        n_misses += 1
        miss_service_sum += lat
        earliest_free = heap[0]
        start = ready if ready > earliest_free else earliest_free
        completion = start + lat
        heapq.heapreplace(heap, completion)
        stream_ready[sid] = completion
        global_issue = start + 1
        if completion > max_completion:
            max_completion = completion

    total_cycles = max(global_issue, max_completion)
    avg_miss_service = miss_service_sum / n_misses if n_misses else 0.0
    return {
        "total_cycles": total_cycles,
        "n_accesses": len(lats),
        "n_hits": n_hits,
        "n_misses": n_misses,
        "avg_miss_service_cycles": avg_miss_service,
        "cycles_per_access": total_cycles / len(lats) if lats else 0.0,
    }
