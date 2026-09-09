"""
Exp-04: When Cache Optimizations Make the Processor Slower.

Core simulator primitives, shared by every experiment in run_experiments.py:

  1. `Cache`            -- a generic N-way set-associative LRU cache that also
                            carries a per-line metadata slot (source: demand
                            or prefetch; used: bool; arrival_clock: int).
                            A fully-associative structure (the victim cache)
                            is just a `Cache` with `num_sets == 1`.
  2. `HierarchySim`      -- L1 -> (optional victim cache) -> L2 -> LLC -> DRAM,
                            strict inclusion-order lookup, cumulative
                            ("blocking") latency accounting, WITH a
                            prefetch-issue hook and enough per-line
                            provenance bookkeeping to compute prefetch
                            accuracy / coverage / timeliness / traffic and
                            useful-data-eviction (pollution) statistics.
  3. Three prefetcher classes: `NextLinePrefetcher`, `StridePrefetcher`,
                            `StreamPrefetcher`.

Modeling choices (stated explicitly, see report Section 2):
  - Latency accounting is a simple cumulative/serial model: a demand access
    that misses in L1 and hits in L2 costs L1_LAT + L2_LAT, etc. This is the
    same simplification used in the Exp-03 simulator. It is adequate for
    every experiment EXCEPT the blocking-vs-non-blocking / MSHR study, which
    is specifically ABOUT overlapping outstanding misses and therefore needs
    its own timing model (see mlp_model.py) -- a single cumulative-latency
    number cannot represent memory-level parallelism by construction.
  - Prefetched lines are inserted into the cache functionally at ISSUE time
    (so they correctly participate in LRU/eviction/pollution bookkeeping the
    moment they are fetched -- an early, unwanted prefetch pollutes the
    cache immediately, exactly as in a real design), but each prefetched
    line also carries a predicted `arrival_clock`. A later demand access to
    that line, if it occurs before `arrival_clock`, still has to wait out
    the remaining latency (a "late" prefetch: useful, but not timely). This
    gives a genuine timeliness signal without a full event-driven simulator.
  - Prefetches are issued for the L1 (aggressive: prefetch requests walk the
    full hierarchy and fill all the way up to L1), which is precisely what
    lets us observe L1 pollution/displacement effects, not just miss-count
    changes at L2/LLC.
"""

from __future__ import annotations

from collections import defaultdict

LINE_SIZE = 64
OFFSET_BITS = LINE_SIZE.bit_length() - 1  # 6


# =============================================================================
# 1. Generic N-way set-associative LRU cache with per-line metadata
# =============================================================================

class Cache:
    __slots__ = (
        "name", "ways", "num_sets", "set_mask", "index_bits", "latency",
        "tags", "lru", "meta", "clock", "hits", "misses", "capacity_bytes",
    )

    def __init__(self, name: str, size_bytes: int, line_size: int, ways: int, latency: int):
        self.name = name
        self.ways = ways
        self.capacity_bytes = size_bytes
        num_lines = size_bytes // line_size
        self.num_sets = max(1, num_lines // ways)
        assert self.num_sets & (self.num_sets - 1) == 0, (
            f"{name}: num_sets={self.num_sets} must be a power of two "
            f"(size={size_bytes}, ways={ways}, line={line_size})"
        )
        self.set_mask = self.num_sets - 1
        self.index_bits = self.num_sets.bit_length() - 1
        self.latency = latency

        self.tags = [[-1] * ways for _ in range(self.num_sets)]
        self.lru = [[0] * ways for _ in range(self.num_sets)]
        self.meta = [[None] * ways for _ in range(self.num_sets)]
        self.clock = 0
        self.hits = 0
        self.misses = 0

    def index_tag(self, line_id: int):
        return line_id & self.set_mask, line_id >> self.index_bits

    def probe(self, line_id: int):
        idx, tag = self.index_tag(line_id)
        row = self.tags[idx]
        for w in range(self.ways):
            if row[w] == tag:
                return True, idx, w
        return False, idx, None

    def touch(self, idx: int, way: int) -> None:
        self.clock += 1
        self.lru[idx][way] = self.clock

    def invalidate(self, idx: int, way: int) -> None:
        self.tags[idx][way] = -1
        self.meta[idx][way] = None

    def install(self, idx: int, tag: int, meta):
        """Insert (idx, tag) with metadata `meta`. Returns the evicted
        (old_line_id, old_meta) if a resident line had to be replaced, else
        None if an empty way was used."""
        self.clock += 1
        row_tags = self.tags[idx]
        row_lru = self.lru[idx]
        row_meta = self.meta[idx]
        for w in range(self.ways):
            if row_tags[w] == -1:
                row_tags[w] = tag
                row_lru[w] = self.clock
                row_meta[w] = meta
                return None
        victim = 0
        min_stamp = row_lru[0]
        for w in range(1, self.ways):
            if row_lru[w] < min_stamp:
                min_stamp = row_lru[w]
                victim = w
        old_tag = row_tags[victim]
        old_meta = row_meta[victim]
        old_line_id = (old_tag << self.index_bits) | idx
        row_tags[victim] = tag
        row_lru[victim] = self.clock
        row_meta[victim] = meta
        return (old_line_id, old_meta)

    def put(self, line_id: int, meta):
        idx, tag = self.index_tag(line_id)
        return self.install(idx, tag, meta)

    def occupancy(self) -> int:
        return sum(1 for row in self.tags for t in row if t != -1)


# =============================================================================
# 2. Prefetchers
# =============================================================================

class NextLinePrefetcher:
    """Fixed, stateless: on every triggering (miss) reference to line L,
    prefetch L+1. Distance is not configurable by design (that is the whole
    point of contrasting it with stride/stream)."""
    name = "next_line"

    def observe(self, stream_id, line_id: int, was_hit: bool):
        return (line_id + 1,)


class StridePrefetcher:
    """Per-stream (per access-stream identity, standing in for a per-PC
    stride table in real hardware) two-delta stride detector. Once the last
    two deltas agree, issues ONE prefetch `distance` strides ahead."""
    name = "stride"

    def __init__(self, distance: int, confirm: int = 1):
        self.distance = distance
        self.confirm = confirm
        self.state: dict = {}

    def observe(self, stream_id, line_id: int, was_hit: bool):
        st = self.state.get(stream_id)
        if st is None:
            self.state[stream_id] = {"last": line_id, "stride": None, "conf": 0}
            return ()
        cands = ()
        if st["last"] is not None:
            delta = line_id - st["last"]
            if delta != 0 and delta == st["stride"]:
                st["conf"] += 1
            else:
                st["conf"] = 0
            st["stride"] = delta
            if st["conf"] >= self.confirm and st["stride"]:
                cands = (line_id + self.distance * st["stride"],)
        st["last"] = line_id
        return cands


class StreamPrefetcher:
    """Per-stream run-ahead engine. Requires TWO consecutive matching deltas
    to confirm a stream (more conservative than the stride detector), then
    maintains a run-ahead window of `distance` lines: fills the whole window
    on confirmation, and thereafter advances it by one stride per confirmed
    step, mimicking a hardware stream buffer's steady-state behaviour."""
    name = "stream"

    def __init__(self, distance: int, confirm: int = 2):
        self.distance = distance
        self.confirm = confirm
        self.state: dict = {}

    def observe(self, stream_id, line_id: int, was_hit: bool):
        st = self.state.get(stream_id)
        if st is None:
            self.state[stream_id] = {"last": line_id, "stride": None, "conf": 0, "frontier": None}
            return ()
        cands = []
        delta = line_id - st["last"]
        if delta != 0 and delta == st["stride"]:
            st["conf"] += 1
        else:
            st["conf"] = 0
            st["frontier"] = None
        st["stride"] = delta
        if st["conf"] >= self.confirm and st["stride"]:
            if st["frontier"] is None:
                for k in range(1, self.distance + 1):
                    cands.append(line_id + k * st["stride"])
                st["frontier"] = line_id + self.distance * st["stride"]
            else:
                target = line_id + self.distance * st["stride"]
                if target != st["frontier"]:
                    cands.append(target)
                    st["frontier"] = target
        st["last"] = line_id
        return cands


# =============================================================================
# 3. Cache hierarchy simulator
# =============================================================================

class HierarchySim:
    def __init__(self, l1_cfg, l2_cfg, llc_cfg, dram_latency: int,
                 victim_entries: int = 0, victim_latency: int = 3,
                 prefetcher=None):
        self.l1 = Cache("L1", *l1_cfg)
        self.l2 = Cache("L2", *l2_cfg)
        self.llc = Cache("LLC", *llc_cfg)
        self.vc = (Cache("VC", victim_entries * LINE_SIZE, LINE_SIZE, victim_entries, victim_latency)
                   if victim_entries > 0 else None)
        self.dram_latency = dram_latency
        self.prefetcher = prefetcher

        self.clock = 0
        self.total_accesses = 0
        self.dram_accesses = 0
        self.dram_prefetch_accesses = 0

        self.prefetch_issued = 0
        self.prefetch_redundant = 0
        self.prefetch_useful = 0
        self.prefetch_timely = 0
        self.prefetch_late = 0
        self.prefetch_wasted_evicted = 0
        self.useful_data_evictions = 0

        # L1 hit/miss broken out per logical access-stream ("agg_state",
        # "ingest_records", ...) -- lets us see e.g. the aggregation
        # state's own residency/hit-rate collapse under pressure, which
        # the aggregate L1 miss rate alone would hide.
        self.stream_stats = defaultdict(lambda: {"hits": 0, "misses": 0})

    # ---- eviction bookkeeping ------------------------------------------
    def _account_eviction(self, evicted) -> None:
        if evicted is None:
            return
        _old_line_id, old_meta = evicted
        if old_meta is None:
            return
        if old_meta["source"] == "demand" and old_meta.get("used"):
            self.useful_data_evictions += 1
        elif old_meta["source"] == "prefetch" and not old_meta.get("used"):
            self.prefetch_wasted_evicted += 1

    def _fill_l1_from(self, line_id: int, meta: dict) -> None:
        evicted = self.l1.put(line_id, dict(meta))
        self._account_eviction(evicted)
        if evicted is not None and self.vc is not None:
            old_line_id, old_meta = evicted
            if old_meta is not None:
                ev2 = self.vc.put(old_line_id, old_meta)
                self._account_eviction(ev2)

    def _fill_l2_l1_from(self, line_id: int, meta: dict) -> None:
        ev2 = self.l2.put(line_id, dict(meta))
        self._account_eviction(ev2)
        self._fill_l1_from(line_id, meta)

    def _fill_llc_l2_l1_from(self, line_id: int, meta: dict) -> None:
        evL = self.llc.put(line_id, dict(meta))
        self._account_eviction(evL)
        self._fill_l2_l1_from(line_id, meta)

    # ---- demand access ---------------------------------------------------
    def access(self, addr: int, stream_id="default") -> None:
        self.total_accesses += 1
        line_id = addr >> OFFSET_BITS
        now = self.clock

        hit1, idx1, way1 = self.l1.probe(line_id)
        ss = self.stream_stats[stream_id]
        ss["hits" if hit1 else "misses"] += 1
        if hit1:
            meta = self.l1.meta[idx1][way1]
            self.l1.touch(idx1, way1)
            self.l1.hits += 1
            cost = self.l1.latency
            if meta is not None:
                if meta["source"] == "prefetch" and not meta["used"]:
                    meta["used"] = True
                    self.prefetch_useful += 1
                    if now >= meta["arrival_clock"]:
                        self.prefetch_timely += 1
                    else:
                        self.prefetch_late += 1
                        cost += (meta["arrival_clock"] - now)
                else:
                    meta["used"] = True
            self.clock += cost
            was_hit = True
        else:
            self.l1.misses += 1
            was_hit = False
            served = False
            if self.vc is not None:
                hitv, idxv, wayv = self.vc.probe(line_id)
                if hitv:
                    self.vc.hits += 1
                    vmeta = self.vc.meta[idxv][wayv] or {"source": "demand", "used": True}
                    vmeta["used"] = True
                    self.vc.invalidate(idxv, wayv)
                    evicted = self.l1.put(line_id, vmeta)
                    self._account_eviction(evicted)
                    if evicted is not None:
                        old_line_id, old_meta = evicted
                        if old_meta is not None:
                            ev2 = self.vc.put(old_line_id, old_meta)
                            self._account_eviction(ev2)
                    self.clock += self.l1.latency + self.vc.latency
                    served = True
                else:
                    self.vc.misses += 1

            if not served:
                hit2, idx2, way2 = self.l2.probe(line_id)
                if hit2:
                    meta = self.l2.meta[idx2][way2] or {"source": "demand", "used": True}
                    meta["used"] = True
                    self.l2.touch(idx2, way2)
                    self.l2.hits += 1
                    self._fill_l1_from(line_id, meta)
                    self.clock += self.l1.latency + self.l2.latency
                else:
                    self.l2.misses += 1
                    hit3, idx3, way3 = self.llc.probe(line_id)
                    if hit3:
                        meta = self.llc.meta[idx3][way3] or {"source": "demand", "used": True}
                        meta["used"] = True
                        self.llc.touch(idx3, way3)
                        self.llc.hits += 1
                        self._fill_l2_l1_from(line_id, meta)
                        self.clock += self.l1.latency + self.l2.latency + self.llc.latency
                    else:
                        self.llc.misses += 1
                        self.dram_accesses += 1
                        self._fill_llc_l2_l1_from(line_id, {"source": "demand", "used": True})
                        self.clock += self.l1.latency + self.l2.latency + self.llc.latency + self.dram_latency

        if self.prefetcher is not None:
            for cand in self.prefetcher.observe(stream_id, line_id, was_hit):
                if cand >= 0:
                    self._issue_prefetch(cand)

    # ---- prefetch issue (async w.r.t. the demand clock, but walks the
    # same functional hierarchy so it generates real traffic/evictions) ---
    def _issue_prefetch(self, line_id: int) -> None:
        hit1, _, _ = self.l1.probe(line_id)
        if hit1:
            self.prefetch_redundant += 1
            return
        if self.vc is not None:
            hitv, _, _ = self.vc.probe(line_id)
            if hitv:
                self.prefetch_redundant += 1
                return

        self.prefetch_issued += 1
        now = self.clock
        hit2, _, _ = self.l2.probe(line_id)
        if hit2:
            lat = self.l1.latency + self.l2.latency
            meta = {"source": "prefetch", "used": False, "arrival_clock": now + lat}
            self._fill_l1_from(line_id, meta)
            return
        hit3, _, _ = self.llc.probe(line_id)
        if hit3:
            lat = self.l1.latency + self.l2.latency + self.llc.latency
            meta = {"source": "prefetch", "used": False, "arrival_clock": now + lat}
            self._fill_l2_l1_from(line_id, meta)
            return
        self.dram_prefetch_accesses += 1
        lat = self.l1.latency + self.l2.latency + self.llc.latency + self.dram_latency
        meta = {"source": "prefetch", "used": False, "arrival_clock": now + lat}
        self._fill_llc_l2_l1_from(line_id, meta)

    # ---- reporting ---------------------------------------------------
    def snapshot(self) -> dict:
        def rate(h, m):
            return 100.0 * m / (h + m) if (h + m) else 0.0
        return {
            "total_accesses": self.total_accesses,
            "clock": self.clock,
            "amat": self.clock / self.total_accesses if self.total_accesses else 0.0,
            "l1_hits": self.l1.hits, "l1_misses": self.l1.misses,
            "l1_miss_pct": rate(self.l1.hits, self.l1.misses),
            "vc_hits": self.vc.hits if self.vc else 0,
            "vc_misses": self.vc.misses if self.vc else 0,
            "l2_hits": self.l2.hits, "l2_misses": self.l2.misses,
            "l2_miss_pct": rate(self.l2.hits, self.l2.misses),
            "llc_hits": self.llc.hits, "llc_misses": self.llc.misses,
            "llc_miss_pct": rate(self.llc.hits, self.llc.misses),
            "dram_accesses": self.dram_accesses,
            "dram_prefetch_accesses": self.dram_prefetch_accesses,
            "prefetch_issued": self.prefetch_issued,
            "prefetch_redundant": self.prefetch_redundant,
            "prefetch_useful": self.prefetch_useful,
            "prefetch_timely": self.prefetch_timely,
            "prefetch_late": self.prefetch_late,
            "prefetch_wasted_evicted": self.prefetch_wasted_evicted,
            "prefetch_accuracy_pct": 100.0 * self.prefetch_useful / self.prefetch_issued if self.prefetch_issued else 0.0,
            "prefetch_timeliness_pct": 100.0 * self.prefetch_timely / self.prefetch_useful if self.prefetch_useful else 0.0,
            "useful_data_evictions": self.useful_data_evictions,
        }


# =============================================================================
# 4. Standard processor-model parameters (Sapphire Rapids, simplified --
#    see report Section 1 for the exact caveats on these numbers)
# =============================================================================

L1_SIZE = 48 * 1024        # 48 KB
L1_WAYS = 12
L1_LATENCY = 5

L2_SIZE = 2 * 1024 * 1024  # 2 MB
L2_WAYS = 16
L2_LATENCY = 16

LLC_SIZE = 15 * 1024 * 1024  # 15 MiB aggregate (8 x 1.875 MB)
LLC_WAYS = 15
LLC_LATENCY = 60

DRAM_LATENCY = 200

VC_LATENCY = 3


def baseline_kwargs(**overrides):
    cfg = dict(
        l1_cfg=(L1_SIZE, LINE_SIZE, L1_WAYS, L1_LATENCY),
        l2_cfg=(L2_SIZE, LINE_SIZE, L2_WAYS, L2_LATENCY),
        llc_cfg=(LLC_SIZE, LINE_SIZE, LLC_WAYS, LLC_LATENCY),
        dram_latency=DRAM_LATENCY,
        victim_entries=0,
        victim_latency=VC_LATENCY,
        prefetcher=None,
    )
    cfg.update(overrides)
    return cfg
