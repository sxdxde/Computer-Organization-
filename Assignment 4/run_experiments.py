"""
Exp-04: When Cache Optimizations Make the Processor Slower -- experiment
driver. Runs the seven experiment groups (A-G) described in the report,
writes CSV/JSON results, matplotlib PNG plots, an append-only master
ledger, and a LaTeX tables fragment (`results/tables.tex`) that the report
\\input{}s directly.

Run with:  python3 run_experiments.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import cache_core
import workload
import mlp_model

RESULTS_DIR = Path(__file__).parent / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
SEED = 42


# =============================================================================
# 0. Workload configurations
# =============================================================================

DEFAULT_CFG = workload.WorkloadConfig(
    n_records=80_000, metadata_touches=2,
    extract_count=60_000, extract_stride_records=1, extract_fields=3, extract_forward=True,
    agg_entries=512, agg_batch=4,
    index_entries=200_000, lookup_count=60_000, lookup_p_random=0.6, lookup_regular_period=7,
    chain_entries=40_000, resgen_steps=40_000, k_streams=8,
    seed=SEED,
)

PRESSURE_CFG = workload.WorkloadConfig(
    n_records=40_000, metadata_touches=2,
    extract_count=1, extract_stride_records=1, extract_fields=1, extract_forward=True,
    agg_entries=256, agg_batch=4,
    index_entries=1_000, lookup_count=1, lookup_p_random=0.6, lookup_regular_period=7,
    chain_entries=1_000, resgen_steps=800, k_streams=8,
    seed=SEED,
)


# =============================================================================
# 1. Generic helpers
# =============================================================================

_COUNTER_KEYS = (
    "total_accesses", "l1_hits", "l1_misses", "vc_hits", "vc_misses",
    "l2_hits", "l2_misses", "llc_hits", "llc_misses", "dram_accesses",
    "dram_prefetch_accesses", "prefetch_issued", "prefetch_redundant",
    "prefetch_useful", "prefetch_timely", "prefetch_late",
    "prefetch_wasted_evicted", "useful_data_evictions", "clock",
)


def delta_snapshot(before: dict, after: dict) -> dict:
    d = {k: after[k] - before[k] for k in _COUNTER_KEYS}
    acc = d["total_accesses"]
    d["amat"] = d["clock"] / acc if acc else 0.0
    l1h, l1m = d["l1_hits"], d["l1_misses"]
    d["l1_miss_pct"] = 100.0 * l1m / (l1h + l1m) if (l1h + l1m) else 0.0
    l2h, l2m = d["l2_hits"], d["l2_misses"]
    d["l2_miss_pct"] = 100.0 * l2m / (l2h + l2m) if (l2h + l2m) else 0.0
    lh, lm = d["llc_hits"], d["llc_misses"]
    d["llc_miss_pct"] = 100.0 * lm / (lh + lm) if (lh + lm) else 0.0
    pi, pu, pt = d["prefetch_issued"], d["prefetch_useful"], d["prefetch_timely"]
    d["prefetch_accuracy_pct"] = 100.0 * pu / pi if pi else 0.0
    d["prefetch_timeliness_pct"] = 100.0 * pt / pu if pu else 0.0
    return d


def expected_stage_counts(cfg: workload.WorkloadConfig, resgen_variant: str) -> dict:
    ingest = cfg.n_records * (2 + cfg.metadata_touches)
    extract = cfg.extract_count * cfg.extract_fields
    agg = cfg.n_records + (cfg.n_records + cfg.agg_batch - 1) // cfg.agg_batch
    lookup = cfg.lookup_count
    if resgen_variant == "independent":
        steps_per_stream = cfg.resgen_steps // cfg.k_streams
        resgen = steps_per_stream * cfg.k_streams
    else:
        resgen = cfg.resgen_steps
    return {"1_ingestion": ingest, "2_extraction": extract, "3_aggregation": agg,
            "4_lookup": lookup, "5_result_gen": resgen}


def run_pipeline_staged(cfg: workload.WorkloadConfig, resgen_variant: str = "independent",
                         cold_frac: float = 0.2, **hkwargs_overrides):
    """Runs the complete 5-stage pipeline through one HierarchySim (state
    carried across stages, never reset), returning per-stage stats AND a
    cold(first `cold_frac`)-vs-steady(rest) split within each stage."""
    hkwargs = cache_core.baseline_kwargs(**hkwargs_overrides)
    sim = cache_core.HierarchySim(**hkwargs)
    expected = expected_stage_counts(cfg, resgen_variant)

    stage_rows, cold_rows = [], []
    last_stage = None
    stage_before = None
    stage_count = 0
    cold_target = None
    cold_snap = None

    def close_stage():
        after = sim.snapshot()
        row = {"stage": last_stage, "n_accesses_expected": expected[last_stage]}
        row.update(delta_snapshot(stage_before, after))
        stage_rows.append(row)
        if cold_snap is not None:
            r1 = {"stage": last_stage + "_cold_0-20pct"}
            r1.update(delta_snapshot(stage_before, cold_snap))
            r2 = {"stage": last_stage + "_steady_20-100pct"}
            r2.update(delta_snapshot(cold_snap, after))
            cold_rows.append(r1)
            cold_rows.append(r2)

    for addr, sid, stage in workload.full_pipeline_stream(cfg, resgen_variant):
        if stage != last_stage:
            if last_stage is not None:
                close_stage()
            last_stage = stage
            stage_before = sim.snapshot()
            stage_count = 0
            cold_target = max(1, round(cold_frac * expected[stage]))
            cold_snap = None
        sim.access(addr, sid)
        stage_count += 1
        if cold_snap is None and stage_count >= cold_target:
            cold_snap = sim.snapshot()
    close_stage()

    overall = sim.snapshot()
    return {"stages": stage_rows, "cold_steady": cold_rows, "overall": overall, "sim": sim}


def pct(n, d):
    return 100.0 * n / d if d else 0.0


# =============================================================================
# 2. Experiment A -- baseline characterization
# =============================================================================

def exp_a_baseline():
    print("\n=== Exp A: baseline characterization ===")
    res = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent")
    for row in res["stages"]:
        print(f"    {row['stage']:<14s} acc={row['total_accesses']:>8,d}  "
              f"L1miss%={row['l1_miss_pct']:5.2f}  L2miss%={row['l2_miss_pct']:5.2f}  "
              f"LLCmiss%={row['llc_miss_pct']:5.2f}  AMAT={row['amat']:6.2f}")
    print(f"    OVERALL clock={res['overall']['clock']:,}  AMAT={res['overall']['amat']:.2f}  "
          f"L1miss%={res['overall']['l1_miss_pct']:.2f}")
    return res


# =============================================================================
# 3. Experiment B -- victim cache
# =============================================================================

VC_SIZES = (0, 8, 16, 32, 64)


def exp_b_victim_cache():
    print("\n=== Exp B: victim cache sweep ===")
    rows = []
    for vc in VC_SIZES:
        res = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", victim_entries=vc)
        s = dict(res["overall"])
        s["victim_entries"] = vc
        s["extra_storage_bytes"] = vc * 64
        rows.append(s)
        print(f"    VC={vc:>3d} entries  clock={s['clock']:>10,d}  L1miss%={s['l1_miss_pct']:5.2f}  "
              f"vc_hits={s['vc_hits']:>7,d}  AMAT={s['amat']:.2f}")

    # comparable-storage alternative: L1 stays 12-way, but add 64 extra
    # LINES worth of capacity via one extra way (13-way) -- same +4096 B
    # as the 64-entry victim cache, so the two are a fair, equal-budget
    # comparison.
    l1_bigger = (cache_core.L1_SIZE + 64 * 64, cache_core.LINE_SIZE, 13, cache_core.L1_LATENCY)
    res_assoc = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", l1_cfg=l1_bigger)
    assoc_row = dict(res_assoc["overall"])
    assoc_row["label"] = "L1_13way_(+4KB, no VC)"
    print(f"    L1 13-way (+4KB, no VC): clock={assoc_row['clock']:,}  L1miss%={assoc_row['l1_miss_pct']:.2f}")

    return {"vc_sweep": rows, "assoc_compare": assoc_row}


def exp_b_conflict_microbench():
    """The full pipeline's misses are overwhelmingly cold/capacity misses on
    a streaming dataset far larger than any cache -- a poor showcase for a
    victim cache, which specifically targets CONFLICT misses (repeated
    thrashing among a *few* addresses that alias to the same set of a
    limited-associativity cache). This isolates that behaviour directly:
    N = L1_ways + 3 addresses, all mapping to the SAME L1 set, accessed in
    a round-robin loop -- a classic pathological pattern that guarantees
    every access misses once N exceeds the set's associativity, and that a
    victim cache of >= (N - ways) entries should almost fully absorb."""
    print("\n=== Exp B (supplementary): pathological same-set conflict microbenchmark ===")
    ways = cache_core.L1_WAYS
    num_sets = 64  # L1's num_sets at (48KB, 12-way, 64B lines)
    extra = 3
    N = ways + extra
    ROUNDS = 3000
    addrs = [(t * num_sets) * cache_core.LINE_SIZE for t in range(N)]
    rows = []
    for vc in (0, 1, 2, 3, 4, 8):
        sim = cache_core.HierarchySim(**cache_core.baseline_kwargs(victim_entries=vc))
        for _ in range(ROUNDS):
            for a in addrs:
                sim.access(a, "conflict_set0")
        snap = sim.snapshot()
        row = {"victim_entries": vc, "N_lines": N, "l1_ways": ways,
               "l1_miss_pct": snap["l1_miss_pct"], "clock": snap["clock"], "vc_hits": snap["vc_hits"]}
        rows.append(row)
        print(f"    VC={vc:>2d}  N={N} lines vs {ways}-way set  L1miss%={row['l1_miss_pct']:6.2f}  "
              f"clock={row['clock']:,}  vc_hits={row['vc_hits']:,}")
    return rows


# =============================================================================
# 4. Experiment C -- prefetcher comparison
# =============================================================================

PREFETCH_FACTORIES = (
    ("none", lambda: None),
    ("next_line", lambda: cache_core.NextLinePrefetcher()),
    ("stride_d1", lambda: cache_core.StridePrefetcher(distance=1)),
    ("stride_d4", lambda: cache_core.StridePrefetcher(distance=4)),
    ("stride_d8", lambda: cache_core.StridePrefetcher(distance=8)),
    ("stream_d4", lambda: cache_core.StreamPrefetcher(distance=4)),
    ("stream_d8", lambda: cache_core.StreamPrefetcher(distance=8)),
    ("stream_d16", lambda: cache_core.StreamPrefetcher(distance=16)),
)


def exp_c_prefetchers():
    print("\n=== Exp C: prefetcher comparison (full pipeline) ===")
    rows = []
    baseline_misses = None
    for label, factory in PREFETCH_FACTORIES:
        res = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", prefetcher=factory())
        s = dict(res["overall"])
        s["prefetcher"] = label
        if label == "none":
            baseline_misses = s["l1_misses"]
        s["baseline_l1_misses"] = baseline_misses
        s["coverage_pct"] = pct(s["prefetch_useful"], baseline_misses)
        rows.append(s)
        print(f"    {label:<12s} clock={s['clock']:>10,d}  L1miss%={s['l1_miss_pct']:5.2f}  "
              f"acc%={s['prefetch_accuracy_pct']:5.1f}  cov%={s['coverage_pct']:5.1f}  "
              f"timely%={s['prefetch_timeliness_pct']:5.1f}  issued={s['prefetch_issued']:>7,d}")
    return rows


# =============================================================================
# 5. Experiment D -- prefetch distance sweep & unintended slowdown
# =============================================================================

DISTANCES = (1, 2, 4, 8, 16, 32, 64)


def exp_d_distance_sweep():
    print("\n=== Exp D: prefetch distance sweep (full pipeline) ===")
    rows = []
    for kind in ("stride", "stream"):
        for dist in DISTANCES:
            pf = (cache_core.StridePrefetcher(distance=dist) if kind == "stride"
                  else cache_core.StreamPrefetcher(distance=dist))
            res = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", prefetcher=pf)
            s = dict(res["overall"])
            s["kind"] = kind
            s["distance"] = dist
            rows.append(s)
            print(f"    {kind:<7s} dist={dist:>3d}  clock={s['clock']:>10,d}  "
                  f"L1miss%={s['l1_miss_pct']:5.2f}  wasted_evicted={s['prefetch_wasted_evicted']:>6,d}  "
                  f"useful_evictions={s['useful_data_evictions']:>7,d}")

    # no-prefetch reference point (distance = 0)
    res0 = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", prefetcher=None)
    s0 = dict(res0["overall"])
    s0["kind"] = "none"
    s0["distance"] = 0
    rows.insert(0, s0)
    return rows


# =============================================================================
# 6. Experiment E -- pollution & thrashing (ingestion+extraction+aggregation,
#    genuinely interleaved so continuously arriving data competes with the
#    small reused aggregation state for cache residency)
# =============================================================================

PRESSURE_LEVELS = (1, 2, 4, 8, 16, 32)


def _run_pressure(pressure: int, victim_entries: int = 0, prefetcher=None):
    hkwargs = cache_core.baseline_kwargs(victim_entries=victim_entries, prefetcher=prefetcher)
    sim = cache_core.HierarchySim(**hkwargs)
    for addr, sid in workload.combined_pressure_stream(PRESSURE_CFG, pressure):
        sim.access(addr, sid)
    snap = sim.snapshot()
    agg = sim.stream_stats.get("agg_state", {"hits": 0, "misses": 0})
    agg_total = agg["hits"] + agg["misses"]
    agg_hit_pct = pct(agg["hits"], agg_total)
    return snap, agg_hit_pct, agg_total


def exp_e_pollution_thrashing():
    print("\n=== Exp E: cache pollution & thrashing (interleaved pipeline) ===")
    base_rows = []
    for p in PRESSURE_LEVELS:
        snap, agg_hit_pct, agg_total = _run_pressure(p)
        row = dict(snap)
        row["pressure"] = p
        row["agg_state_hit_pct"] = agg_hit_pct
        row["agg_state_accesses"] = agg_total
        row["config"] = "baseline"
        base_rows.append(row)
        print(f"    pressure={p:>3d}  agg_state_hit%={agg_hit_pct:6.2f}  overall_L1miss%={row['l1_miss_pct']:5.2f}")

    mitigated_rows = []
    hi_pressure = PRESSURE_LEVELS[-2:]  # the two highest-pressure points
    for p in hi_pressure:
        for label, kw in (
            ("+victim32", {"victim_entries": 32}),
            ("+stream_pf_d4", {"prefetcher": cache_core.StreamPrefetcher(distance=4)}),
            ("+victim32+stream_pf_d4", {"victim_entries": 32, "prefetcher": cache_core.StreamPrefetcher(distance=4)}),
        ):
            snap, agg_hit_pct, agg_total = _run_pressure(p, **kw)
            row = dict(snap)
            row["pressure"] = p
            row["agg_state_hit_pct"] = agg_hit_pct
            row["agg_state_accesses"] = agg_total
            row["config"] = label
            mitigated_rows.append(row)
            print(f"    pressure={p:>3d} {label:<24s} agg_state_hit%={agg_hit_pct:6.2f}  "
                  f"overall_L1miss%={row['l1_miss_pct']:5.2f}")

    return {"baseline": base_rows, "mitigation": mitigated_rows}


# =============================================================================
# 7. Experiment F -- blocking vs. non-blocking cache / MSHRs (Result Gen.)
# =============================================================================

MSHR_COUNTS = (1, 2, 4, 8, 16, 32, 64)
F_STEPS = 24_000
F_K = 8
F_CHAIN = 8_000


def exp_f_mshr():
    print("\n=== Exp F: blocking vs. non-blocking / MSHR sweep (Result Generation) ===")
    rng = random.Random(SEED)
    lay = workload.Layout()
    lay.alloc("records", 1)
    lay.alloc("metadata", 1)
    lay.alloc("agg_state", 1)
    lay.alloc("index", 1)
    lay.alloc("chain", F_CHAIN * 64)
    lay.alloc("streams", F_K * (F_STEPS // F_K) * 64 * 4 + 4096)

    perm = workload.build_chain_permutation(F_CHAIN, rng)
    dep_stream = list(workload.stage_result_dependent(lay, F_CHAIN, F_STEPS, perm))
    indep_stream = list(workload.stage_result_independent(
        lay, F_K, F_STEPS // F_K, max(2, F_CHAIN // F_K), rng))

    dep_lats, dep_sids, dep_snap, l1_lat = mlp_model.classify_stream(dep_stream, cache_core.baseline_kwargs())
    indep_lats, indep_sids, indep_snap, _ = mlp_model.classify_stream(indep_stream, cache_core.baseline_kwargs())

    print(f"    dependent chain:   {len(dep_lats):,} accesses, "
          f"L1 miss%={pct(dep_snap['l1_misses'], dep_snap['l1_hits'] + dep_snap['l1_misses']):.1f}")
    print(f"    independent streams: {len(indep_lats):,} accesses, "
          f"L1 miss%={pct(indep_snap['l1_misses'], indep_snap['l1_hits'] + indep_snap['l1_misses']):.1f}")

    rows = []
    for m in MSHR_COUNTS:
        # dep_sids is already a single constant stream id for every access
        # (stage_result_dependent tags everything "resgen_dep"), which by
        # itself forces full serialization regardless of `m` -- exactly the
        # dependent-chain behaviour we want to demonstrate.
        r_dep = mlp_model.simulate_mshr(dep_lats, dep_sids, m, l1_lat)
        r_indep = mlp_model.simulate_mshr(indep_lats, indep_sids, m, l1_lat)
        rows.append({"mshr": m, "variant": "dependent_chain", **r_dep})
        rows.append({"mshr": m, "variant": "independent_streams", **r_indep})
        print(f"    MSHR={m:>3d}  dependent={r_dep['total_cycles']:>10,d} cyc   "
              f"independent={r_indep['total_cycles']:>10,d} cyc")

    return rows


# =============================================================================
# 8. Experiment G -- final combined recommendation
# =============================================================================

def exp_g_final_recommendation(best_prefetcher_label: str, best_prefetcher_factory,
                                best_vc: int):
    print("\n=== Exp G: final configuration comparison ===")
    configs = [
        ("A_baseline", dict()),
        ("B_victim_only", dict(victim_entries=best_vc)),
        ("C_prefetch_only", dict(prefetcher=best_prefetcher_factory())),
        ("D_victim+prefetch (recommended)", dict(victim_entries=best_vc, prefetcher=best_prefetcher_factory())),
    ]
    rows = []
    for label, kw in configs:
        res = run_pipeline_staged(DEFAULT_CFG, resgen_variant="independent", **kw)
        s = dict(res["overall"])
        s["config"] = label
        rows.append(s)
        print(f"    {label:<34s} clock={s['clock']:>10,d}  AMAT={s['amat']:6.2f}  "
              f"L1miss%={s['l1_miss_pct']:5.2f}  dram_acc={s['dram_accesses']:>7,d}")
    return rows


# =============================================================================
# 9. Output: CSV / JSON / master ledger / LaTeX tables / plots
# =============================================================================

def write_csv(path: Path, rows, fieldnames=None) -> None:
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def append_master_ledger(entries) -> None:
    path = RESULTS_DIR / "master_ledger.csv"
    fields = ["timestamp", "experiment", "variant", "clock", "amat", "l1_miss_pct",
              "l2_miss_pct", "llc_miss_pct", "dram_accesses", "notes"]
    write_header = not path.exists()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        for e in entries:
            row = {"timestamp": ts, **e}
            w.writerow({k: row.get(k, "") for k in fields})


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    res_a = exp_a_baseline()
    write_csv(RESULTS_DIR / "expA_stages.csv", res_a["stages"])
    write_csv(RESULTS_DIR / "expA_cold_steady.csv", res_a["cold_steady"])
    with open(RESULTS_DIR / "expA_overall.json", "w") as f:
        json.dump(res_a["overall"], f, indent=2)

    res_b = exp_b_victim_cache()
    write_csv(RESULTS_DIR / "expB_victim_sweep.csv", res_b["vc_sweep"])
    with open(RESULTS_DIR / "expB_assoc_compare.json", "w") as f:
        json.dump(res_b["assoc_compare"], f, indent=2)

    res_b2 = exp_b_conflict_microbench()
    write_csv(RESULTS_DIR / "expB_conflict_microbench.csv", res_b2)

    res_c = exp_c_prefetchers()
    write_csv(RESULTS_DIR / "expC_prefetchers.csv", res_c)

    res_d = exp_d_distance_sweep()
    write_csv(RESULTS_DIR / "expD_distance_sweep.csv", res_d)

    res_e = exp_e_pollution_thrashing()
    write_csv(RESULTS_DIR / "expE_pressure_baseline.csv", res_e["baseline"])
    write_csv(RESULTS_DIR / "expE_pressure_mitigation.csv", res_e["mitigation"])

    res_f = exp_f_mshr()
    write_csv(RESULTS_DIR / "expF_mshr_sweep.csv", res_f)

    # pick the best prefetcher from Exp C by lowest overall clock (excluding "none")
    best_c = min((r for r in res_c if r["prefetcher"] != "none"), key=lambda r: r["clock"])
    best_label = best_c["prefetcher"]
    factory_map = dict(PREFETCH_FACTORIES)
    best_vc = min(res_b["vc_sweep"][1:], key=lambda r: r["clock"])["victim_entries"]
    print(f"\n[selection] best single prefetcher from Exp C: {best_label}   best VC size from Exp B: {best_vc}")

    res_g = exp_g_final_recommendation(best_label, factory_map[best_label], best_vc)
    write_csv(RESULTS_DIR / "expG_final_comparison.csv", res_g)

    ledger_entries = []
    for row in res_a["stages"]:
        ledger_entries.append({"experiment": "A_baseline", "variant": row["stage"], **row,
                                "notes": "baseline characterization"})
    for row in res_b["vc_sweep"]:
        ledger_entries.append({"experiment": "B_victim_cache", "variant": f"vc{row['victim_entries']}",
                                **row, "notes": "victim cache sweep"})
    for row in res_c:
        ledger_entries.append({"experiment": "C_prefetch", "variant": row["prefetcher"], **row,
                                "notes": "prefetcher comparison"})
    for row in res_d:
        ledger_entries.append({"experiment": "D_distance", "variant": f"{row['kind']}_d{row['distance']}",
                                **row, "notes": "prefetch distance sweep"})
    for row in res_g:
        ledger_entries.append({"experiment": "G_final", "variant": row["config"], **row,
                                "notes": "final recommendation comparison"})
    append_master_ledger(ledger_entries)

    write_latex_tables(res_a, res_b, res_b2, res_c, res_d, res_e, res_f, res_g, best_label, best_vc)
    make_plots(res_a, res_b, res_b2, res_c, res_d, res_e, res_f, res_g)

    with open(RESULTS_DIR / "raw_results.json", "w") as f:
        json.dump({
            "exp_a": {"stages": res_a["stages"], "cold_steady": res_a["cold_steady"], "overall": res_a["overall"]},
            "exp_b": res_b,
            "exp_b_conflict_microbench": res_b2,
            "exp_c": res_c,
            "exp_d": res_d,
            "exp_e": res_e,
            "exp_f": res_f,
            "exp_g": res_g,
            "selection": {"best_prefetcher": best_label, "best_vc": best_vc},
        }, f, indent=2, default=str)

    print(f"\nAll done in {time.time()-t_start:.1f}s. Results written to: {RESULTS_DIR}")


# =============================================================================
# 10. LaTeX table generation
# =============================================================================

def esc(s):
    return str(s).replace("_", r"\_")


def write_latex_tables(res_a, res_b, res_b2, res_c, res_d, res_e, res_f, res_g, best_label, best_vc) -> None:
    L = []

    L.append("%%SECTION:A%%")
    # --- Table: Exp A stage-wise baseline ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{lrrrrrr}\toprule")
    L.append(r"Stage & Accesses & L1 Miss\% & L2 Miss\% & LLC Miss\% & DRAM Acc. & AMAT \\ \midrule")
    for row in res_a["stages"]:
        L.append(f"{esc(row['stage'])} & {row['total_accesses']:,} & {row['l1_miss_pct']:.2f} & "
                  f"{row['l2_miss_pct']:.2f} & {row['llc_miss_pct']:.2f} & {row['dram_accesses']:,} & "
                  f"{row['amat']:.2f} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp A: baseline per-stage characterization (no victim cache, no prefetching).}")
    L.append(r"\label{tab:expA}\end{table}")
    L.append("")

    # --- Table: Exp A cold vs steady ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{lrrr}\toprule")
    L.append(r"Stage segment & Accesses & L1 Miss\% & AMAT \\ \midrule")
    for row in res_a["cold_steady"]:
        L.append(f"{esc(row['stage'])} & {row['total_accesses']:,} & {row['l1_miss_pct']:.2f} & {row['amat']:.2f} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp A: first 20\% (cold) vs. remaining 80\% (steady-state) of each stage.}")
    L.append(r"\label{tab:expA-cold}\end{table}")
    L.append("")

    L.append("%%SECTION:B%%")
    # --- Table: Exp B victim cache ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{rrrrrr}\toprule")
    L.append(r"VC entries & Extra bytes & Clock (cyc) & L1 Miss\% & VC hits & AMAT \\ \midrule")
    for row in res_b["vc_sweep"]:
        L.append(f"{row['victim_entries']} & {row['extra_storage_bytes']:,} & {row['clock']:,} & "
                  f"{row['l1_miss_pct']:.2f} & {row['vc_hits']:,} & {row['amat']:.2f} \\\\")
    a = res_b["assoc_compare"]
    L.append(rf"\midrule 13-way L1 (+4KB, no VC) & 4{{,}}096 & {a['clock']:,} & {a['l1_miss_pct']:.2f} & -- & {a['amat']:.2f} \\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp B: victim-cache size sweep vs. an equal-extra-storage associativity increase.}")
    L.append(r"\label{tab:expB}\end{table}")
    L.append("")

    L.append("%%SECTION:Bconflict%%")
    # --- Table: Exp B supplementary conflict microbenchmark ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{rrrr}\toprule")
    L.append(r"VC entries & L1 Miss\% & Clock (cyc) & VC hits \\ \midrule")
    for row in res_b2:
        L.append(f"{row['victim_entries']} & {row['l1_miss_pct']:.2f} & {row['clock']:,} & {row['vc_hits']:,} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    n_lines = res_b2[0]["N_lines"]; ways = res_b2[0]["l1_ways"]
    L.append(rf"\caption{{Exp B supplementary: {n_lines} addresses round-robin thrashing one {ways}-way L1 set.}}")
    L.append(r"\label{tab:expB-conflict}\end{table}")
    L.append("")

    L.append("%%SECTION:C%%")
    # --- Table: Exp C prefetchers ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{lrrrrrr}\toprule")
    L.append(r"Prefetcher & Clock (cyc) & L1 Miss\% & Accuracy\% & Coverage\% & Timeliness\% & Issued \\ \midrule")
    for row in res_c:
        L.append(f"{esc(row['prefetcher'])} & {row['clock']:,} & {row['l1_miss_pct']:.2f} & "
                  f"{row['prefetch_accuracy_pct']:.1f} & {row['coverage_pct']:.1f} & "
                  f"{row['prefetch_timeliness_pct']:.1f} & {row['prefetch_issued']:,} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp C: prefetch mechanism comparison, full pipeline.}")
    L.append(r"\label{tab:expC}\end{table}")
    L.append("")

    L.append("%%SECTION:D%%")
    # --- Table: Exp D distance sweep (condensed: min/max per kind) ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{lrrrrr}\toprule")
    L.append(r"Kind & Distance & Clock (cyc) & L1 Miss\% & Wasted-evicted PF & Useful-data evictions \\ \midrule")
    for row in res_d:
        L.append(f"{esc(row['kind'])} & {row['distance']} & {row['clock']:,} & {row['l1_miss_pct']:.2f} & "
                  f"{row['prefetch_wasted_evicted']:,} & {row['useful_data_evictions']:,} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp D: prefetch distance sweep, full pipeline (distance 0 = no prefetch).}")
    L.append(r"\label{tab:expD}\end{table}")
    L.append("")

    L.append("%%SECTION:E%%")
    # --- Table: Exp E pollution/thrashing ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{rrr}\toprule")
    L.append(r"Pressure level & Aggregation-state L1 hit\% & Overall L1 Miss\% \\ \midrule")
    for row in res_e["baseline"]:
        L.append(f"{row['pressure']} & {row['agg_state_hit_pct']:.2f} & {row['l1_miss_pct']:.2f} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp E: baseline aggregation-state residency under rising interleave pressure.}")
    L.append(r"\label{tab:expE-baseline}\end{table}")
    L.append("")

    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{rlrr}\toprule")
    L.append(r"Pressure & Mitigation & Aggregation-state L1 hit\% & Overall L1 Miss\% \\ \midrule")
    for row in res_e["mitigation"]:
        L.append(f"{row['pressure']} & {esc(row['config'])} & {row['agg_state_hit_pct']:.2f} & {row['l1_miss_pct']:.2f} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp E: does the victim cache and/or prefetching alleviate high-pressure thrashing?}")
    L.append(r"\label{tab:expE-mitigation}\end{table}")
    L.append("")

    L.append("%%SECTION:F%%")
    # --- Table: Exp F MSHR sweep ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{rrr}\toprule")
    L.append(r"MSHRs & Dependent chain (cyc) & Independent streams (cyc) \\ \midrule")
    dep = {r["mshr"]: r for r in res_f if r["variant"] == "dependent_chain"}
    ind = {r["mshr"]: r for r in res_f if r["variant"] == "independent_streams"}
    for m in sorted(dep):
        L.append(f"{m} & {dep[m]['total_cycles']:,} & {ind[m]['total_cycles']:,} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(r"\caption{Exp F: total Result-Generation execution cycles vs. MSHR count.}")
    L.append(r"\label{tab:expF}\end{table}")
    L.append("")

    L.append("%%SECTION:G%%")
    # --- Table: Exp G final ---
    L.append(r"\begin{table}[H]\centering\small")
    L.append(r"\begin{tabular}{lrrrr}\toprule")
    L.append(r"Configuration & Clock (cyc) & AMAT & L1 Miss\% & DRAM Acc. \\ \midrule")
    for row in res_g:
        L.append(f"{esc(row['config'])} & {row['clock']:,} & {row['amat']:.2f} & {row['l1_miss_pct']:.2f} & "
                  f"{row['dram_accesses']:,} \\\\")
    L.append(r"\bottomrule\end{tabular}")
    L.append(rf"\caption{{Exp G: final configuration comparison (selected prefetcher: {esc(best_label)}, "
              rf"selected victim-cache size: {best_vc} entries).}}")
    L.append(r"\label{tab:expG}\end{table}")

    with open(RESULTS_DIR / "tables.tex", "w") as f:
        f.write("\n".join(x for x in L if not x.startswith("%%SECTION:")) + "\n")

    tables_dir = RESULTS_DIR / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    current, buf = None, []
    for line in L:
        if line.startswith("%%SECTION:"):
            if current is not None:
                with open(tables_dir / f"tables_{current}.tex", "w") as f:
                    f.write("\n".join(buf) + "\n")
            current = line.split(":")[1].rstrip("%")
            buf = []
        else:
            buf.append(line)
    if current is not None:
        with open(tables_dir / f"tables_{current}.tex", "w") as f:
            f.write("\n".join(buf) + "\n")


# =============================================================================
# 11. Plots
# =============================================================================

def make_plots(res_a, res_b, res_b2, res_c, res_d, res_e, res_f, res_g) -> None:
    # Exp A: per-stage miss rate by level
    stages = [r["stage"] for r in res_a["stages"]]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = range(len(stages))
    w = 0.25
    ax.bar([i - w for i in x], [r["l1_miss_pct"] for r in res_a["stages"]], w, label="L1")
    ax.bar(list(x), [r["l2_miss_pct"] for r in res_a["stages"]], w, label="L2")
    ax.bar([i + w for i in x], [r["llc_miss_pct"] for r in res_a["stages"]], w, label="LLC")
    ax.set_xticks(list(x)); ax.set_xticklabels(stages, rotation=20, ha="right")
    ax.set_ylabel("Miss rate (%)"); ax.set_title("Exp A: baseline per-stage miss rate")
    ax.legend(); fig.tight_layout()
    fig.savefig(PLOTS_DIR / "expA_stage_miss_rates.png", dpi=150); plt.close(fig)

    # Exp B: victim cache
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    vc_sizes = [r["victim_entries"] for r in res_b["vc_sweep"]]
    ax1.plot(vc_sizes, [r["clock"] for r in res_b["vc_sweep"]], marker="o")
    ax1.axhline(res_b["assoc_compare"]["clock"], color="tab:red", linestyle="--",
                label="13-way L1 (+4KB, no VC)")
    ax1.set_xlabel("Victim cache entries"); ax1.set_ylabel("Total clock (cycles)")
    ax1.set_title("Execution cycles vs. VC size"); ax1.legend()
    ax2.plot(vc_sizes, [r["l1_miss_pct"] for r in res_b["vc_sweep"]], marker="o", color="tab:green")
    ax2.set_xlabel("Victim cache entries"); ax2.set_ylabel("L1 miss rate (%)")
    ax2.set_title("L1 miss rate vs. VC size")
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expB_victim_cache.png", dpi=150); plt.close(fig)

    # Exp B supplementary: conflict microbenchmark. L1 miss% is flat at
    # 100% by definition (a victim-cache hit is still an L1 miss) even
    # though the victim cache is doing all the work here, so plot the
    # metrics that actually show it: clock and victim-cache hits.
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    vcs = [r["victim_entries"] for r in res_b2]
    ax1.plot(vcs, [r["clock"] for r in res_b2], marker="o", color="tab:red")
    ax1.set_xlabel("Victim cache entries"); ax1.set_ylabel("Total clock (cycles)")
    ax1.set_title("Execution cycles vs. VC size")
    ax2.plot(vcs, [r["vc_hits"] for r in res_b2], marker="s", color="tab:blue")
    ax2.set_xlabel("Victim cache entries"); ax2.set_ylabel("Victim-cache hits (count)")
    ax2.set_title("Recovered accesses vs. VC size")
    fig.suptitle(f"Exp B supplementary: {res_b2[0]['N_lines']}-line thrash on one "
                 f"{res_b2[0]['l1_ways']}-way set (L1 miss rate stays 100% throughout "
                 f"by definition -- see clock instead)", fontsize=10)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expB_conflict_microbench.png", dpi=150); plt.close(fig)

    # Exp C: prefetcher comparison
    labels = [r["prefetcher"] for r in res_c]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ax1.bar(labels, [r["clock"] for r in res_c], color="tab:blue")
    ax1.set_ylabel("Total clock (cycles)"); ax1.set_title("Exp C: execution cycles by prefetcher")
    ax1.tick_params(axis="x", rotation=30)
    xi = range(len(labels))
    ax2.bar([i - 0.2 for i in xi], [r["prefetch_accuracy_pct"] for r in res_c], 0.2, label="Accuracy")
    ax2.bar(list(xi), [r["coverage_pct"] for r in res_c], 0.2, label="Coverage")
    ax2.bar([i + 0.2 for i in xi], [r["prefetch_timeliness_pct"] for r in res_c], 0.2, label="Timeliness")
    ax2.set_xticks(list(xi)); ax2.set_xticklabels(labels, rotation=30, ha="right")
    ax2.set_ylabel("%"); ax2.set_title("Accuracy / coverage / timeliness"); ax2.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expC_prefetchers.png", dpi=150); plt.close(fig)

    # Exp D: distance sweep
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    none_clock = next(r["clock"] for r in res_d if r["kind"] == "none")
    for kind, marker in (("stride", "o"), ("stream", "s")):
        pts = [r for r in res_d if r["kind"] == kind]
        ax1.plot([r["distance"] for r in pts], [r["clock"] for r in pts], marker=marker, label=kind)
    ax1.axhline(none_clock, color="gray", linestyle="--", label="no prefetch")
    ax1.set_xlabel("Prefetch distance"); ax1.set_ylabel("Total clock (cycles)")
    ax1.set_title("Exp D: execution cycles vs. distance"); ax1.legend(); ax1.set_xscale("log", base=2)
    for kind, marker in (("stride", "o"), ("stream", "s")):
        pts = [r for r in res_d if r["kind"] == kind]
        ax2.plot([r["distance"] for r in pts], [r["useful_data_evictions"] for r in pts],
                  marker=marker, label=f"{kind}: useful-data evictions")
    ax2.set_xlabel("Prefetch distance"); ax2.set_ylabel("Useful-data evictions (count)")
    ax2.set_title("Pollution vs. distance"); ax2.legend(fontsize=8); ax2.set_xscale("log", base=2)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expD_distance_sweep.png", dpi=150); plt.close(fig)

    # Exp E: pollution/thrashing
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot([r["pressure"] for r in res_e["baseline"]], [r["agg_state_hit_pct"] for r in res_e["baseline"]],
             marker="o", label="baseline")
    for label in sorted(set(r["config"] for r in res_e["mitigation"])):
        pts = [r for r in res_e["mitigation"] if r["config"] == label]
        ax.plot([r["pressure"] for r in pts], [r["agg_state_hit_pct"] for r in pts],
                 marker="s", linestyle="--", label=label)
    ax.set_xlabel("Pressure level (extraction stride / injected traffic)")
    ax.set_ylabel("Aggregation-state L1 hit rate (%)")
    ax.set_title("Exp E: hot aggregation-state residency under rising pressure")
    ax.legend(fontsize=8); ax.set_xscale("log", base=2)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expE_pollution_thrashing.png", dpi=150); plt.close(fig)

    # Exp F: MSHR sweep
    fig, ax = plt.subplots(figsize=(7, 4.5))
    dep = {r["mshr"]: r["total_cycles"] for r in res_f if r["variant"] == "dependent_chain"}
    ind = {r["mshr"]: r["total_cycles"] for r in res_f if r["variant"] == "independent_streams"}
    xs = sorted(dep)
    ax.plot(xs, [dep[m] for m in xs], marker="o", label="dependent chain")
    ax.plot(xs, [ind[m] for m in xs], marker="s", label="independent streams (K=8)")
    ax.axvline(8, color="gray", linestyle=":", label="K = 8 streams")
    ax.set_xlabel("MSHR count (outstanding misses)"); ax.set_ylabel("Total cycles (Result Generation)")
    ax.set_title("Exp F: blocking vs. non-blocking cache"); ax.legend(); ax.set_xscale("log", base=2)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expF_mshr_sweep.png", dpi=150); plt.close(fig)

    # Exp G: final comparison
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    labels = [r["config"] for r in res_g]
    ax1.bar(labels, [r["clock"] for r in res_g], color="tab:purple")
    ax1.set_ylabel("Total clock (cycles)"); ax1.set_title("Exp G: final configuration clock")
    ax1.tick_params(axis="x", rotation=20)
    ax2.bar(labels, [r["l1_miss_pct"] for r in res_g], color="tab:orange")
    ax2.set_ylabel("L1 miss rate (%)"); ax2.set_title("Exp G: final configuration L1 miss rate")
    ax2.tick_params(axis="x", rotation=20)
    fig.tight_layout(); fig.savefig(PLOTS_DIR / "expG_final.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
