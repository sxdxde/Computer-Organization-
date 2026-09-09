"""
Exp-03: Multi-Level Cache Design -- single-file simulator.

Everything needed for the experiment lives in this one file:

  1. A generic N-way set-associative LRU cache model (`Cache`).
  2. A three-level hierarchical cache (`MultiLevelCache`) that enforces
     strict CPU -> L1 -> L2 -> L3 -> DRAM lookup order, with data
     filled back into every level above the one where it was found
     (or from DRAM into all three, on a full miss).
  3. Four workload-phase address-stream generators (embedding lookup,
     matrix multiply, activation streaming, output projection) that
     together model one four-phase "inference-like" workload.
  4. An experiment driver that runs the complete four-phase workload,
     WITHOUT clearing cache state between phases, through three
     different associativity configurations, collecting per-phase and
     per-configuration statistics.
  5. Output: JSON + CSV result tables, matplotlib PNG plots, and a
     LaTeX table fragment (results/tables.tex) that the report
     \\input{}s directly, so every number in the PDF is reproduced
     verbatim from an actual run of this script.

Run with:  python3 cache_sim.py
System parameters (fixed by the assignment):
    Address size    : 26 bits          -> 64 MB addressable
    DRAM latency    : 100 cycles
    Cache line size : 64 B (all levels, fixed for the whole experiment)
    L1 : 32 KB,  baseline 1-way (direct mapped), 1 cycle
    L2 : 256 KB, baseline 2-way,                 5 cycles
    L3 : 2 MB,   baseline 4-way,                 20 cycles
"""

from __future__ import annotations

import csv
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# =============================================================================
# 1. System / cache-hierarchy constants (fixed for the whole experiment)
# =============================================================================

ADDRESS_BITS = 26
ADDRESS_SPACE_BYTES = 1 << ADDRESS_BITS          # 64 MB
DRAM_LATENCY = 100                                # cycles

LINE_SIZE = 64                                    # bytes, all levels

L1_SIZE = 32 * 1024
L2_SIZE = 256 * 1024
L3_SIZE = 2 * 1024 * 1024

L1_LATENCY = 1
L2_LATENCY = 5
L3_LATENCY = 20

RESULTS_DIR = Path(__file__).parent / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
SEED = 42                                         # fixed, for reproducibility


# =============================================================================
# 2. Generic N-way set-associative LRU cache
# =============================================================================

class Cache:
    """One N-way set-associative cache level with true LRU replacement.

    `access(addr)` is a genuine demand access: it counts as a hit or a
    miss and, on a miss, allocates the line in this cache (standard
    allocate-on-miss policy).

    `fill(addr)` inserts a line WITHOUT touching the hit/miss counters.
    It models the "fill upper levels" step of the hierarchy diagram:
    when a request is satisfied by a lower level (or by DRAM), the
    block is written into this level as a side effect of that access,
    not as a new demand access of its own.
    """

    __slots__ = (
        "name", "ways", "num_sets", "set_mask", "offset_bits", "index_bits",
        "latency", "tags", "lru", "clock", "hits", "misses",
    )

    def __init__(self, name: str, size_bytes: int, line_size: int, ways: int, latency: int):
        self.name = name
        self.ways = ways
        num_lines = size_bytes // line_size
        self.num_sets = num_lines // ways
        assert self.num_sets & (self.num_sets - 1) == 0, "num_sets must be a power of two"
        self.set_mask = self.num_sets - 1
        self.offset_bits = line_size.bit_length() - 1
        self.index_bits = self.num_sets.bit_length() - 1
        self.latency = latency

        self.tags = [[-1] * ways for _ in range(self.num_sets)]
        self.lru = [[0] * ways for _ in range(self.num_sets)]
        self.clock = 0
        self.hits = 0
        self.misses = 0

    def _insert(self, idx: int, tag: int) -> None:
        set_tags = self.tags[idx]
        set_lru = self.lru[idx]
        victim = 0
        min_stamp = set_lru[0]
        if set_tags[0] == -1:
            set_tags[0] = tag
            set_lru[0] = self.clock
            return
        for w in range(1, self.ways):
            t = set_tags[w]
            if t == -1:
                set_tags[w] = tag
                set_lru[w] = self.clock
                return
            stamp = set_lru[w]
            if stamp < min_stamp:
                min_stamp = stamp
                victim = w
        set_tags[victim] = tag
        set_lru[victim] = self.clock

    def access(self, addr: int) -> bool:
        self.clock += 1
        line = addr >> self.offset_bits
        idx = line & self.set_mask
        tag = line >> self.index_bits
        set_tags = self.tags[idx]
        for w in range(self.ways):
            if set_tags[w] == tag:
                self.lru[idx][w] = self.clock
                self.hits += 1
                return True
        self.misses += 1
        self._insert(idx, tag)
        return False

    def fill(self, addr: int) -> None:
        self.clock += 1
        line = addr >> self.offset_bits
        idx = line & self.set_mask
        tag = line >> self.index_bits
        for w in range(self.ways):
            if self.tags[idx][w] == tag:
                self.lru[idx][w] = self.clock
                return
        self._insert(idx, tag)

    def snapshot(self) -> tuple[int, int]:
        return self.hits, self.misses


# =============================================================================
# 3. Three-level hierarchical cache
# =============================================================================

class MultiLevelCache:
    """CPU -> L1 -> L2 -> L3 -> DRAM, strictly in that order.

    Latency model: cumulative / serial probing, i.e. an access that
    misses in L1 and hits in L2 costs L1_LATENCY + L2_LATENCY cycles
    (the L1 tag check is not free just because it missed). This is a
    simplifying but standard assumption for a simulator of this kind;
    it is stated explicitly here and in the report rather than left
    implicit.
    """

    def __init__(self, l1_ways: int, l2_ways: int, l3_ways: int):
        self.l1 = Cache("L1", L1_SIZE, LINE_SIZE, l1_ways, L1_LATENCY)
        self.l2 = Cache("L2", L2_SIZE, LINE_SIZE, l2_ways, L2_LATENCY)
        self.l3 = Cache("L3", L3_SIZE, LINE_SIZE, l3_ways, L3_LATENCY)
        self.dram_accesses = 0
        self.total_cycles = 0
        self.total_accesses = 0

    def access(self, addr: int) -> None:
        self.total_accesses += 1
        l1, l2, l3 = self.l1, self.l2, self.l3

        if l1.access(addr):
            self.total_cycles += l1.latency
            return
        if l2.access(addr):
            l1.fill(addr)
            self.total_cycles += l1.latency + l2.latency
            return
        if l3.access(addr):
            l2.fill(addr)
            l1.fill(addr)
            self.total_cycles += l1.latency + l2.latency + l3.latency
            return
        l3.fill(addr)
        l2.fill(addr)
        l1.fill(addr)
        self.dram_accesses += 1
        self.total_cycles += l1.latency + l2.latency + l3.latency + DRAM_LATENCY

    def snapshot(self) -> dict:
        return {
            "l1_hits": self.l1.hits, "l1_misses": self.l1.misses,
            "l2_hits": self.l2.hits, "l2_misses": self.l2.misses,
            "l3_hits": self.l3.hits, "l3_misses": self.l3.misses,
            "dram_accesses": self.dram_accesses,
            "total_cycles": self.total_cycles,
            "total_accesses": self.total_accesses,
        }


# =============================================================================
# 4. Workload phases
#
# All four phases share the same 26-bit / 64 MB address space (that is
# the entire address space available on this system -- Phase 1's
# embedding table alone occupies all 64 MB of it, so Phases 2-4
# necessarily reuse addresses Phase 1 already touched, exactly as a
# real allocator would reuse heap space after the embedding lookup
# stage is done with it). Within each phase, arrays are placed at
# fixed, non-overlapping offsets so that phase-internal access
# patterns are unambiguous.
#
# Where a loop body naturally exposes a loop-invariant memory location
# to a compiler (e.g. C[i][j] across the k-loop, or Y[b][o] across the
# k-loop), we model the standard register-allocated behaviour: the
# accumulator lives in a register across the inner loop and is written
# back once. This keeps the address-stream size tractable without
# changing any of the spatial/strided/temporal properties the
# experiment cares about (those live entirely in the A/B/X/W traffic).
# =============================================================================

# ---- Phase 1: Embedding / Lookup -------------------------------------------
EMBED_ENTRIES = 1_048_576
EMBED_VALUES_PER_ENTRY = 16
EMBED_BYTES_PER_VALUE = 4
ENTRY_BYTES = EMBED_VALUES_PER_ENTRY * EMBED_BYTES_PER_VALUE   # 64 B == 1 line
assert EMBED_ENTRIES * ENTRY_BYTES == ADDRESS_SPACE_BYTES

PHASE1_LOOKUPS = 50_000
PHASE1_HOT_POOL_SIZE = 64
PHASE1_HOT_PROB = 0.35
PHASE1_REPEAT_PROB = 0.05


def phase1_indices(rng: random.Random) -> list[int]:
    """Irregular, non-sequential index stream with weak spatial locality
    between lookups, but deliberate temporal reuse via a small 'hot'
    pool of indices and occasional immediate repeats -- e.g. the kind
    of pattern shown in the spec: 17, 2048, 91, 17, 8192, 2048, 503, 91..."""
    hot_pool = rng.sample(range(EMBED_ENTRIES), PHASE1_HOT_POOL_SIZE)
    seq = []
    prev = None
    for _ in range(PHASE1_LOOKUPS):
        r = rng.random()
        if prev is not None and r < PHASE1_REPEAT_PROB:
            idx = prev
        elif r < PHASE1_REPEAT_PROB + PHASE1_HOT_PROB:
            idx = rng.choice(hot_pool)
        else:
            idx = rng.randrange(EMBED_ENTRIES)
        seq.append(idx)
        prev = idx
    return seq


def phase1_addresses(rng: random.Random):
    for idx in phase1_indices(rng):
        base = idx * ENTRY_BYTES
        for v in range(EMBED_VALUES_PER_ENTRY):
            yield base + v * EMBED_BYTES_PER_VALUE


# ---- Phase 2: Matrix / Tensor Computation (C = A x B, ijk order) ----------
MAT_N = 256
MAT_A_BASE = 0
MAT_B_BASE = MAT_N * MAT_N * 4
MAT_C_BASE = 2 * MAT_N * MAT_N * 4


def phase2_addresses():
    N = MAT_N
    a_base, b_base, c_base = MAT_A_BASE, MAT_B_BASE, MAT_C_BASE
    for i in range(N):
        iN = i * N
        for j in range(N):
            for k in range(N):
                yield a_base + (iN + k) * 4        # A[i][k]: sequential in k
                yield b_base + (k * N + j) * 4      # B[k][j]: strided, stride = N*4
            yield c_base + (iN + j) * 4             # C[i][j]: one write-back per (i,j)


# ---- Phase 3: Activation Processing (streaming) ----------------------------
ACT_N = 1_048_576
ACT_INPUT_BASE = 0
ACT_OUTPUT_BASE = ACT_N * 4


def phase3_addresses():
    in_base, out_base = ACT_INPUT_BASE, ACT_OUTPUT_BASE
    for i in range(ACT_N):
        off = i * 4
        yield in_base + off
        yield out_base + off


# ---- Phase 4: Output / Projection (Y = X . W, batched) ---------------------
PROJ_BATCH = 512
PROJ_IN = 128
PROJ_OUT = 32
PROJ_X_BASE = 0
PROJ_W_BASE = PROJ_BATCH * PROJ_IN * 4
PROJ_Y_BASE = PROJ_W_BASE + PROJ_IN * PROJ_OUT * 4


def phase4_addresses():
    B, IN, OUT = PROJ_BATCH, PROJ_IN, PROJ_OUT
    x_base, w_base, y_base = PROJ_X_BASE, PROJ_W_BASE, PROJ_Y_BASE
    for b in range(B):
        bIN = b * IN
        for o in range(OUT):
            oIN = o * IN
            for k in range(IN):
                yield x_base + (bIN + k) * 4        # X[b][k]: sequential, reused across o
                yield w_base + (oIN + k) * 4        # W[o][k]: sequential, reused across b
            yield y_base + (b * OUT + o) * 4        # Y[b][o]: strided write-back


PHASES = [
    ("Embedding", phase1_addresses, True),   # True => generator needs rng
    ("Matrix", phase2_addresses, False),
    ("Activation", phase3_addresses, False),
    ("Projection", phase4_addresses, False),
]


# =============================================================================
# 5. Experiment driver
# =============================================================================

CONFIGS = [
    # (label, l1_ways, l2_ways, l3_ways, rationale)
    ("A_baseline", 1, 2, 4,
     "Assignment baseline: L1 direct-mapped, L2 2-way, L3 4-way."),
    ("B_high_assoc", 2, 4, 8,
     "Raise associativity at every level relative to baseline, to test "
     "whether conflict misses observed in A are actually reduced when "
     "every level gets more ways."),
    ("C_L1_focus", 4, 4, 8,
     "Same L2/L3 as B, but push L1 to 4-way. Isolates whether L1 "
     "associativity specifically matters, given L1 is by far the "
     "highest-traffic, lowest-latency, smallest level."),
]


def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


def run_config(label: str, l1w: int, l2w: int, l3w: int) -> dict:
    mlc = MultiLevelCache(l1w, l2w, l3w)
    rng = random.Random(SEED)

    phase_rows = []
    prev_snap = mlc.snapshot()

    for phase_name, gen_fn, needs_rng in PHASES:
        t0 = time.perf_counter()
        gen = gen_fn(rng) if needs_rng else gen_fn()
        access = mlc.access
        for addr in gen:
            access(addr)
        elapsed = time.perf_counter() - t0

        snap = mlc.snapshot()
        d = {k: snap[k] - prev_snap[k] for k in snap}
        prev_snap = snap

        l1_acc = d["l1_hits"] + d["l1_misses"]
        l2_acc = d["l2_hits"] + d["l2_misses"]
        l3_acc = d["l3_hits"] + d["l3_misses"]
        phase_rows.append({
            "phase": phase_name,
            "l1_accesses": l1_acc, "l1_hits": d["l1_hits"], "l1_misses": d["l1_misses"],
            "l2_accesses": l2_acc, "l2_hits": d["l2_hits"], "l2_misses": d["l2_misses"],
            "l3_accesses": l3_acc, "l3_hits": d["l3_hits"], "l3_misses": d["l3_misses"],
            "l1_miss_pct": pct(d["l1_misses"], l1_acc),
            "l2_miss_pct": pct(d["l2_misses"], l2_acc),
            "l3_miss_pct": pct(d["l3_misses"], l3_acc),
            "dram_accesses": d["dram_accesses"],
            "cycles": d["total_cycles"],
            "cpu_accesses": d["total_accesses"],
            "amat": d["total_cycles"] / d["total_accesses"] if d["total_accesses"] else 0.0,
            "wall_seconds": elapsed,
        })
        print(f"    [{label}] phase {phase_name:<10s} "
              f"accesses={d['total_accesses']:>10,d}  "
              f"L1miss%={phase_rows[-1]['l1_miss_pct']:5.2f}  "
              f"L2miss%={phase_rows[-1]['l2_miss_pct']:5.2f}  "
              f"L3miss%={phase_rows[-1]['l3_miss_pct']:5.2f}  "
              f"DRAM={d['dram_accesses']:>9,d}  ({elapsed:5.2f}s)")

    overall = mlc.snapshot()
    l1_acc = overall["l1_hits"] + overall["l1_misses"]
    l2_acc = overall["l2_hits"] + overall["l2_misses"]
    l3_acc = overall["l3_hits"] + overall["l3_misses"]
    summary = {
        "config": label,
        "l1_ways": l1w, "l2_ways": l2w, "l3_ways": l3w,
        "l1_miss_pct": pct(overall["l1_misses"], l1_acc),
        "l2_miss_pct": pct(overall["l2_misses"], l2_acc),
        "l3_miss_pct": pct(overall["l3_misses"], l3_acc),
        "dram_accesses": overall["dram_accesses"],
        "cpu_accesses": overall["total_accesses"],
        "total_cycles": overall["total_cycles"],
        "amat": overall["total_cycles"] / overall["total_accesses"] if overall["total_accesses"] else 0.0,
    }
    return {"summary": summary, "phases": phase_rows}


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    for label, l1w, l2w, l3w, rationale in CONFIGS:
        print(f"\n=== Running configuration {label} "
              f"(L1={l1w}-way, L2={l2w}-way, L3={l3w}-way) ===")
        print(f"    rationale: {rationale}")
        res = run_config(label, l1w, l2w, l3w)
        res["rationale"] = rationale
        all_results.append(res)

    write_json(all_results)
    write_phase_csv(all_results)
    write_config_csv(all_results)
    append_master_ledger(all_results)
    write_latex_tables(all_results)
    make_plots(all_results)

    print(f"\nAll done. Results written to: {RESULTS_DIR}")


# =============================================================================
# 6. Output: JSON / CSV / master ledger / LaTeX tables / plots
# =============================================================================

def write_json(all_results: list[dict]) -> None:
    with open(RESULTS_DIR / "raw_results.json", "w") as f:
        json.dump(all_results, f, indent=2)


def write_phase_csv(all_results: list[dict]) -> None:
    path = RESULTS_DIR / "phase_wise_results.csv"
    fields = ["config", "phase", "l1_miss_pct", "l2_miss_pct", "l3_miss_pct",
              "dram_accesses", "cycles", "cpu_accesses", "amat", "wall_seconds"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for res in all_results:
            cfg = res["summary"]["config"]
            for row in res["phases"]:
                w.writerow({"config": cfg, **{k: row[k] for k in fields if k != "config"}})


def write_config_csv(all_results: list[dict]) -> None:
    path = RESULTS_DIR / "config_summary.csv"
    fields = ["config", "l1_ways", "l2_ways", "l3_ways", "l1_miss_pct", "l2_miss_pct",
              "l3_miss_pct", "dram_accesses", "cpu_accesses", "total_cycles", "amat"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for res in all_results:
            w.writerow(res["summary"])


def append_master_ledger(all_results: list[dict]) -> None:
    """Append-only run log: every run (config x phase) with a timestamp,
    never overwritten -- so successive script runs accumulate history
    instead of destroying it."""
    path = RESULTS_DIR / "master_ledger.csv"
    fields = ["timestamp", "config", "l1_ways", "l2_ways", "l3_ways", "phase",
              "l1_miss_pct", "l2_miss_pct", "l3_miss_pct", "dram_accesses",
              "cycles", "amat", "notes"]
    write_header = not path.exists()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        for res in all_results:
            s = res["summary"]
            for row in res["phases"]:
                w.writerow({
                    "timestamp": ts, "config": s["config"],
                    "l1_ways": s["l1_ways"], "l2_ways": s["l2_ways"], "l3_ways": s["l3_ways"],
                    "phase": row["phase"], "l1_miss_pct": f"{row['l1_miss_pct']:.3f}",
                    "l2_miss_pct": f"{row['l2_miss_pct']:.3f}", "l3_miss_pct": f"{row['l3_miss_pct']:.3f}",
                    "dram_accesses": row["dram_accesses"], "cycles": row["cycles"],
                    "amat": f"{row['amat']:.3f}", "notes": res["rationale"],
                })
            w.writerow({
                "timestamp": ts, "config": s["config"],
                "l1_ways": s["l1_ways"], "l2_ways": s["l2_ways"], "l3_ways": s["l3_ways"],
                "phase": "OVERALL", "l1_miss_pct": f"{s['l1_miss_pct']:.3f}",
                "l2_miss_pct": f"{s['l2_miss_pct']:.3f}", "l3_miss_pct": f"{s['l3_miss_pct']:.3f}",
                "dram_accesses": s["dram_accesses"], "cycles": s["total_cycles"],
                "amat": f"{s['amat']:.3f}", "notes": res["rationale"],
            })


def write_latex_tables(all_results: list[dict]) -> None:
    """Emit results/tables.tex: auto-generated LaTeX tables reproduced
    directly from this run's numbers, so the report never hand-transcribes
    a figure. \\input{} this file from the report."""
    lines = []

    # Table: phase-wise results (one sub-table per configuration)
    for res in all_results:
        cfg = res["summary"]["config"]
        lines.append(r"\begin{table}[H]")
        lines.append(r"\centering")
        lines.append(r"\begin{tabular}{lrrrrrr}")
        lines.append(r"\toprule")
        lines.append(r"Phase & L1 Miss\% & L2 Miss\% & L3 Miss\% & DRAM Accesses & Cycles & AMAT \\")
        lines.append(r"\midrule")
        for row in res["phases"]:
            lines.append(
                f"{row['phase']} & {row['l1_miss_pct']:.2f} & {row['l2_miss_pct']:.2f} & "
                f"{row['l3_miss_pct']:.2f} & {row['dram_accesses']:,} & {row['cycles']:,} & "
                f"{row['amat']:.2f} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        cfg_esc = cfg.replace("_", r"\_")
        lines.append(rf"\caption{{Phase-wise results, Configuration {cfg_esc}}}")
        lines.append(rf"\label{{tab:phase-{cfg}}}")
        lines.append(r"\end{table}")
        lines.append("")

    # Table: configuration comparison
    lines.append(r"\begin{table}[H]")
    lines.append(r"\centering")
    lines.append(r"\small")
    lines.append(r"\begin{tabular}{lcrrrrrr}")
    lines.append(r"\toprule")
    lines.append(r"Config & Ways (L1/L2/L3) & L1 Miss\% & L2 Miss\% & L3 Miss\% & DRAM Acc. & AMAT & Cycles \\")
    lines.append(r"\midrule")
    for res in all_results:
        s = res["summary"]
        cfg_esc = s["config"].replace("_", r"\_")
        lines.append(
            f"{cfg_esc} & {s['l1_ways']}/{s['l2_ways']}/{s['l3_ways']} & "
            f"{s['l1_miss_pct']:.2f} & {s['l2_miss_pct']:.2f} & {s['l3_miss_pct']:.2f} & "
            f"{s['dram_accesses']:,} & {s['amat']:.2f} & {s['total_cycles']:,} \\\\"
        )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\caption{Full-workload comparison across the three cache configurations}")
    lines.append(r"\label{tab:config-comparison}")
    lines.append(r"\end{table}")

    with open(RESULTS_DIR / "tables.tex", "w") as f:
        f.write("\n".join(lines) + "\n")


def make_plots(all_results: list[dict]) -> None:
    configs = [r["summary"]["config"] for r in all_results]
    phases = [row["phase"] for row in all_results[0]["phases"]]

    # --- Plot 1: per-phase, per-level miss rate, one subplot per config ---
    fig, axes = plt.subplots(1, len(all_results), figsize=(5 * len(all_results), 4), sharey=True)
    if len(all_results) == 1:
        axes = [axes]
    x = range(len(phases))
    width = 0.25
    for ax, res in zip(axes, all_results):
        l1 = [row["l1_miss_pct"] for row in res["phases"]]
        l2 = [row["l2_miss_pct"] for row in res["phases"]]
        l3 = [row["l3_miss_pct"] for row in res["phases"]]
        ax.bar([i - width for i in x], l1, width, label="L1")
        ax.bar(list(x), l2, width, label="L2")
        ax.bar([i + width for i in x], l3, width, label="L3")
        ax.set_xticks(list(x))
        ax.set_xticklabels(phases, rotation=30, ha="right")
        ax.set_title(res["summary"]["config"])
        ax.set_ylabel("Miss rate (%)")
    axes[0].legend()
    fig.suptitle("Per-phase miss rate by cache level and configuration")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "phase_miss_rates.png", dpi=150)
    plt.close(fig)

    # --- Plot 2: DRAM accesses per phase per config ---
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.8 / len(all_results)
    for ci, res in enumerate(all_results):
        vals = [row["dram_accesses"] for row in res["phases"]]
        offs = [i + (ci - (len(all_results) - 1) / 2) * width for i in range(len(phases))]
        ax.bar(offs, vals, width, label=res["summary"]["config"])
    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels(phases)
    ax.set_ylabel("DRAM accesses")
    ax.set_title("DRAM accesses per phase")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "dram_accesses_per_phase.png", dpi=150)
    plt.close(fig)

    # --- Plot 3: AMAT per phase per config ---
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for res in all_results:
        vals = [row["amat"] for row in res["phases"]]
        ax.plot(phases, vals, marker="o", label=res["summary"]["config"])
    ax.set_ylabel("AMAT (cycles/access)")
    ax.set_title("Per-phase AMAT across configurations")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "amat_per_phase.png", dpi=150)
    plt.close(fig)

    # --- Plot 4: overall config comparison (miss rates + AMAT) ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    l1 = [r["summary"]["l1_miss_pct"] for r in all_results]
    l2 = [r["summary"]["l2_miss_pct"] for r in all_results]
    l3 = [r["summary"]["l3_miss_pct"] for r in all_results]
    xs = range(len(configs))
    width = 0.25
    ax1.bar([i - width for i in xs], l1, width, label="L1")
    ax1.bar(list(xs), l2, width, label="L2")
    ax1.bar([i + width for i in xs], l3, width, label="L3")
    ax1.set_xticks(list(xs))
    ax1.set_xticklabels(configs, rotation=15)
    ax1.set_ylabel("Miss rate (%)")
    ax1.set_title("Overall miss rate by configuration")
    ax1.legend()

    amat = [r["summary"]["amat"] for r in all_results]
    ax2.bar(configs, amat, color="tab:purple")
    ax2.set_ylabel("AMAT (cycles/access)")
    ax2.set_title("Overall AMAT by configuration")
    ax2.set_xticklabels(configs, rotation=15)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "config_comparison.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
