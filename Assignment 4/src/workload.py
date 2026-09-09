"""
Exp-04 workload: a five-stage synthetic data-processing pipeline.

  1. Data Ingestion     -- sequential scan of a record array (much larger
                            than any private cache) interleaved with repeated
                            touches of a small, reused metadata/parameter
                            block.
  2. Feature Extraction -- per-record field extraction at a CONFIGURABLE
                            record-level stride (contiguous -> large),
                            forward or backward, touching a fixed number of
                            records regardless of stride so "useful work"
                            stays constant while only the ADDRESS PATTERN
                            changes.
  3. Feature Aggregation-- small, frequently-reused accumulator state,
                            updated every `agg_batch` input records (batch
                            size controls reuse distance / interleave
                            pressure).
  4. Lookup & Scoring   -- an index structure accessed with a configurable
                            mix of pseudo-random indices and a periodic,
                            partially-predictable regular component.
  5. Result Generation  -- two variants of equal "useful work":
                              (a) a dependent pointer-chase (each address
                                  depends on the previous "load"), and
                              (b) K independent streams, round-robin
                                  interleaved so consecutive accesses are
                                  mutually independent.

All generators yield `(address, stream_id)` pairs. `stream_id` stands in for
"the load instruction/PC that issued this access" -- the granularity real
stride/stream prefetchers key their per-stream state on. Every stage is a
plain Python generator (no data values are modeled, only the address
stream -- the same convention used in Assignment 1 / Assignment 3), except
the dependent-chain result-generation stream, whose *visitation order* is a
precomputed random cyclic permutation: this is the standard way pointer-
chasing benchmarks (e.g. lat_mem_rd) are modeled without simulating actual
memory contents, and it preserves the property that matters for this
assignment -- each hop is not predictable from the previous address, and by
construction the next request cannot be issued before the previous one
"returns".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# =============================================================================
# Layout helpers -- disjoint byte-address regions, one per array
# =============================================================================

@dataclass
class Layout:
    bases: dict = field(default_factory=dict)
    _cursor: int = 0

    def alloc(self, name: str, nbytes: int) -> int:
        base = self._cursor
        self.bases[name] = base
        self._cursor += nbytes
        return base

    def __getitem__(self, name):
        return self.bases[name]


# =============================================================================
# Stage 1: Data Ingestion
# =============================================================================

RECORD_BYTES = 128
FIELD_BYTES = 8
FIELDS_PER_RECORD = RECORD_BYTES // FIELD_BYTES  # 16
METADATA_BYTES = 4096  # small, reused every record


def stage_ingestion(layout: Layout, n_records: int, metadata_touches: int = 2):
    """Sequential record scan; the metadata/params block is re-touched
    `metadata_touches` times per record (stands in for configurable
    per-record computation intensity that repeatedly consults shared
    parameters)."""
    rec_base = layout["records"]
    meta_base = layout["metadata"]
    n_meta_lines = max(1, METADATA_BYTES // 64)
    for i in range(n_records):
        rb = rec_base + i * RECORD_BYTES
        for f in range(0, FIELDS_PER_RECORD, 8):  # touch every 8th field -> 2 lines/record
            yield rb + f * FIELD_BYTES, "ingest_records"
        for t in range(metadata_touches):
            yield meta_base + (t % n_meta_lines) * 64, "ingest_metadata"


# =============================================================================
# Stage 2: Feature Extraction
# =============================================================================

def stage_extraction(layout: Layout, n_records: int, extract_count: int,
                      stride_records: int, fields_per_record: int = 3,
                      forward: bool = True):
    """Touch `extract_count` records (regardless of stride, so useful work
    is constant), selecting record i_k = (k * stride_records) % n_records,
    k ascending (forward) or descending (backward). At each selected
    record, read `fields_per_record` fields."""
    rec_base = layout["records"]
    field_offsets = [f * (FIELD_BYTES * 3) for f in range(fields_per_record)]  # spread within record
    ks = range(extract_count) if forward else range(extract_count - 1, -1, -1)
    for k in ks:
        i = (k * stride_records) % n_records
        rb = rec_base + i * RECORD_BYTES
        for off in field_offsets:
            yield rb + (off % RECORD_BYTES), "extract"


# =============================================================================
# Stage 3: Feature Aggregation
# =============================================================================

def stage_aggregation(layout: Layout, n_records: int, agg_entries: int,
                       agg_batch: int, rng: random.Random):
    """For every `agg_batch` input records streamed past, touch one
    aggregation-state entry (small, hot, reused array)."""
    rec_base = layout["records"]
    agg_base = layout["agg_state"]
    entry_bytes = 8
    n_entries = agg_entries
    for i in range(n_records):
        rb = rec_base + i * RECORD_BYTES
        yield rb, "agg_input"
        if i % agg_batch == 0:
            slot = rng.randrange(n_entries)
            yield agg_base + slot * entry_bytes, "agg_state"


# =============================================================================
# Stage 4: Lookup & Scoring
# =============================================================================

def stage_lookup(layout: Layout, lookup_count: int, index_entries: int,
                  p_random: float, regular_period: int, rng: random.Random):
    """Mix of pseudo-random index accesses and a periodic, partially
    predictable regular component (recurring regularities)."""
    idx_base = layout["index"]
    entry_bytes = 32
    regular_cursor = 0
    for _ in range(lookup_count):
        if rng.random() < p_random:
            slot = rng.randrange(index_entries)
        else:
            slot = regular_cursor % index_entries
            regular_cursor += regular_period
        yield idx_base + slot * entry_bytes, "lookup"


# =============================================================================
# Stage 5: Result Generation -- dependent chain vs independent streams
# =============================================================================

def build_chain_permutation(chain_entries: int, rng: random.Random):
    """A random cyclic permutation over `chain_entries` slots: visiting it
    in order models pointer-chasing (each 'next' address is unpredictable
    from the current one, and cannot be known before the current load
    completes)."""
    order = list(range(chain_entries))
    rng.shuffle(order)
    return order


def stage_result_dependent(layout: Layout, chain_entries: int, steps: int,
                            permutation):
    base = layout["chain"]
    entry_bytes = 64  # one line per node
    for s in range(steps):
        slot = permutation[s % chain_entries]
        yield base + slot * entry_bytes, "resgen_dep"


def stage_result_independent(layout: Layout, k_streams: int, steps_per_stream: int,
                              chain_entries_per_stream: int, rng: random.Random):
    """K mutually-independent pointer-chase chains, round-robin interleaved
    one step per stream per round. Accesses WITHIN one stream are still a
    dependent chain (each is a genuine "next useful step" of that stream's
    own computation) -- what makes the streams "independent" is that stream
    k's next access never waits on stream j's outstanding request, so up to
    K requests (one per stream) can be truly outstanding at once. This is
    what makes memory-level parallelism here bounded by K, not unbounded --
    exactly what the blocking-vs-non-blocking / MSHR experiment needs to
    show a genuine plateau."""
    base = layout["streams"]
    entry_bytes = 64
    stream_span = chain_entries_per_stream * entry_bytes
    perms = []
    for _ in range(k_streams):
        p = list(range(chain_entries_per_stream))
        rng.shuffle(p)
        perms.append(p)
    for r in range(steps_per_stream):
        for k in range(k_streams):
            slot = perms[k][r % chain_entries_per_stream]
            yield base + k * stream_span + slot * entry_bytes, f"resgen_indep_{k}"


# =============================================================================
# Config + full-pipeline / combined-pressure drivers
# =============================================================================

@dataclass
class WorkloadConfig:
    n_records: int = 120_000
    metadata_touches: int = 2

    extract_count: int = 90_000
    extract_stride_records: int = 1
    extract_fields: int = 3
    extract_forward: bool = True

    agg_entries: int = 512
    agg_batch: int = 4

    index_entries: int = 300_000
    lookup_count: int = 90_000
    lookup_p_random: float = 0.6
    lookup_regular_period: int = 7

    chain_entries: int = 60_000
    resgen_steps: int = 60_000
    k_streams: int = 8

    seed: int = 42


def make_layout(cfg: WorkloadConfig) -> Layout:
    lay = Layout()
    lay.alloc("records", cfg.n_records * RECORD_BYTES)
    lay.alloc("metadata", METADATA_BYTES)
    lay.alloc("agg_state", cfg.agg_entries * 8)
    lay.alloc("index", cfg.index_entries * 32)
    lay.alloc("chain", cfg.chain_entries * 64)
    lay.alloc("streams", cfg.k_streams * cfg.resgen_steps * 64 * 2 + 4096)
    return lay


def full_pipeline_stream(cfg: WorkloadConfig, resgen_variant: str = "independent"):
    """Yields (addr, stream_id, stage) for the complete five-stage pipeline,
    stage by stage, in order -- WITHOUT clearing cache state between
    stages (so later stages inherit whatever residency earlier stages left
    behind, as specified)."""
    rng = random.Random(cfg.seed)
    lay = make_layout(cfg)

    for addr, sid in stage_ingestion(lay, cfg.n_records, cfg.metadata_touches):
        yield addr, sid, "1_ingestion"
    for addr, sid in stage_extraction(lay, cfg.n_records, cfg.extract_count,
                                       cfg.extract_stride_records, cfg.extract_fields,
                                       cfg.extract_forward):
        yield addr, sid, "2_extraction"
    for addr, sid in stage_aggregation(lay, cfg.n_records, cfg.agg_entries,
                                        cfg.agg_batch, rng):
        yield addr, sid, "3_aggregation"
    for addr, sid in stage_lookup(lay, cfg.lookup_count, cfg.index_entries,
                                   cfg.lookup_p_random, cfg.lookup_regular_period, rng):
        yield addr, sid, "4_lookup"
    if resgen_variant == "independent":
        steps_per_stream = cfg.resgen_steps // cfg.k_streams
        chain_per_stream = max(2, cfg.chain_entries // cfg.k_streams)
        for addr, sid in stage_result_independent(lay, cfg.k_streams, steps_per_stream,
                                                    chain_per_stream, rng):
            yield addr, sid, "5_result_gen"
    else:
        perm = build_chain_permutation(cfg.chain_entries, rng)
        for addr, sid in stage_result_dependent(lay, cfg.chain_entries, cfg.resgen_steps, perm):
            yield addr, sid, "5_result_gen"


def combined_pressure_stream(cfg: WorkloadConfig, pressure: int, max_pressure: int = 64):
    """Ingestion + Extraction + Aggregation, ROUND-ROBIN interleaved at
    record granularity (rather than run sequentially), so continuously
    arriving input data genuinely competes, cycle by cycle, with the
    frequently-reused aggregation state for cache residency. `pressure`
    controls how many FRESH, never-before-touched foreign lines (drawn
    from a dedicated, monotonically-advancing filler region -- distinct
    from any bounded, wrap-around array) are injected between successive
    aggregation-state touches: this directly and monotonically controls
    the reuse DISTANCE separating one visit to the hot state from the
    next, with no risk of an accidental short address-cycle (e.g. a
    stride sharing a factor with a bounded array's length) creating
    spurious extra reuse at some pressure levels and not others."""
    rng = random.Random(cfg.seed)
    lay = make_layout(cfg)
    rec_base = lay["records"]
    agg_base = lay["agg_state"]
    filler_base = lay.alloc("pressure_filler", max_pressure * cfg.n_records * 64 + 4096)
    n_records = cfg.n_records
    agg_batch = max(1, cfg.agg_batch)
    cursor = 0

    for i in range(n_records):
        rb = rec_base + i * RECORD_BYTES
        yield rb, "ingest_records"
        yield rb + 64, "ingest_records"
        for _ in range(pressure):
            yield filler_base + cursor * 64, "extract"
            cursor += 1
        if i % agg_batch == 0:
            slot = rng.randrange(cfg.agg_entries)
            yield agg_base + slot * 8, "agg_state"
