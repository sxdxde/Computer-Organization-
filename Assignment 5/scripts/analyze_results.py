#!/usr/bin/env python3
"""Exp05 - aggregate raw run CSV into summary tables + plots."""
import csv
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent.parent
RAW = HERE / "results" / "results.csv"
OUT_CSV = HERE / "results" / "summary.csv"
PLOTS = HERE / "results" / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

MODE_LABEL = {
    "baseline": "Baseline (private only)",
    "true_sharing": "Shared-data (true sharing)",
    "false_sharing": "False sharing (packed)",
    "false_sharing_free": "False-sharing-free (padded)",
    "redesigned": "Redesigned",
}
MODE_ORDER = ["baseline", "true_sharing", "false_sharing", "false_sharing_free", "redesigned"]
COLORS = {
    "baseline": "#4C78A8",
    "true_sharing": "#E45756",
    "false_sharing": "#F58518",
    "false_sharing_free": "#54A24B",
    "redesigned": "#B279A2",
}

rows = []
with open(RAW) as f:
    for r in csv.DictReader(f):
        for k in ("nthreads", "nevents", "grand_count", "group_count",
                   "counter_total", "cas_retries", "maxrss_kb", "page_reclaims",
                   "page_faults", "voluntary_cs", "involuntary_cs",
                   "instructions_retired", "cycles_elapsed", "peak_footprint"):
            r[k] = int(float(r[k]))
        for k in ("wall_s", "grand_sum", "group_sum", "real_s", "user_s", "sys_s"):
            r[k] = float(r[k])
        rows.append(r)

groups = defaultdict(list)
for r in rows:
    groups[(r["mode"], r["nthreads"])].append(r)

summary = []
for (mode, nt), rs in groups.items():
    wall = [r["wall_s"] for r in rs]
    ics = [r["involuntary_cs"] for r in rs]
    instr = [r["instructions_retired"] for r in rs]
    cyc = [r["cycles_elapsed"] for r in rs]
    retries = [r["cas_retries"] for r in rs]
    summary.append(dict(
        mode=mode, nthreads=nt, n=len(rs),
        wall_mean=st.mean(wall), wall_std=st.pstdev(wall) if len(wall) > 1 else 0.0,
        wall_median=st.median(wall),
        wall_min=min(wall),
        wall_max=max(wall),
        ipc_mean=st.mean(i / c for i, c in zip(instr, cyc)),
        cycles_mean=st.mean(cyc),
        ics_mean=st.mean(ics),
        retries_mean=st.mean(retries),
    ))

# speedup relative to that mode's own 1-thread wall time. Uses best-of-N (min), the
# standard microbenchmarking convention for a shared/unpinned host: OS scheduling noise
# (background daemons, P/E-core placement) can only ever ADD latency to a run, never
# remove it, so the minimum across repetitions converges toward the noise-free time as
# reps increase, while mean/median stay biased upward -- see report §2.1.
base_t1 = {m: s["wall_min"] for s in summary for m in [s["mode"]] if s["nthreads"] == 1}
for s in summary:
    s["speedup"] = base_t1[s["mode"]] / s["wall_min"]

summary.sort(key=lambda s: (MODE_ORDER.index(s["mode"]), s["nthreads"]))

with open(OUT_CSV, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["mode", "nthreads", "reps", "wall_mean_s", "wall_std_s", "wall_median_s",
                "wall_min_s", "wall_max_s", "speedup_vs_1core_minbasis", "ipc_mean", "cycles_mean",
                "involuntary_cs_mean", "cas_retries_mean"])
    for s in summary:
        w.writerow([s["mode"], s["nthreads"], s["n"],
                    f"{s['wall_mean']:.6f}", f"{s['wall_std']:.6f}", f"{s['wall_median']:.6f}",
                    f"{s['wall_min']:.6f}", f"{s['wall_max']:.6f}",
                    f"{s['speedup']:.3f}",
                    f"{s['ipc_mean']:.4f}", f"{int(s['cycles_mean'])}",
                    f"{s['ics_mean']:.1f}", f"{int(s['retries_mean'])}"])

print(f"wrote {OUT_CSV}")

# ---- Plot 1: execution time vs cores ----
plt.figure(figsize=(6.5, 4.5))
for mode in MODE_ORDER:
    xs = sorted(s["nthreads"] for s in summary if s["mode"] == mode)
    ys = [next(s["wall_median"] for s in summary if s["mode"] == mode and s["nthreads"] == x) for x in xs]
    ys_min = [next(s["wall_min"] for s in summary if s["mode"] == mode and s["nthreads"] == x) for x in xs]
    plt.plot(xs, ys_min, marker="o", label=MODE_LABEL[mode], color=COLORS[mode])
    plt.plot(xs, ys, linestyle=":", linewidth=1, color=COLORS[mode], alpha=0.5)
plt.xlabel("Worker threads (cores)")
plt.ylabel("Execution time (s) — solid: best-of-7, dotted: median-of-7")
plt.title("Exp05: Execution time vs. core count")
plt.xticks([1, 2, 4, 8, 10])
plt.grid(alpha=0.3)
plt.legend(fontsize=8)
plt.tight_layout()
plt.savefig(PLOTS / "01_time_vs_cores.png", dpi=150)
plt.close()

# ---- Plot 2: speedup vs cores (with ideal line) ----
plt.figure(figsize=(6.5, 4.5))
xs_ideal = [1, 2, 4, 8, 10]
plt.plot(xs_ideal, xs_ideal, linestyle="--", color="gray", label="Ideal linear speedup")
for mode in MODE_ORDER:
    xs = sorted(s["nthreads"] for s in summary if s["mode"] == mode)
    ys = [next(s["speedup"] for s in summary if s["mode"] == mode and s["nthreads"] == x) for x in xs]
    plt.plot(xs, ys, marker="o", label=MODE_LABEL[mode], color=COLORS[mode])
plt.xlabel("Worker threads (cores)")
plt.ylabel("Speedup vs. 1 core (same mode)")
plt.title("Exp05: Speedup vs. core count")
plt.xticks([1, 2, 4, 8, 10])
plt.grid(alpha=0.3)
plt.legend(fontsize=8)
plt.tight_layout()
plt.savefig(PLOTS / "02_speedup_vs_cores.png", dpi=150)
plt.close()

# ---- Plot 3: IPC vs cores (evidence of stalling on coherence traffic) ----
plt.figure(figsize=(6.5, 4.5))
for mode in MODE_ORDER:
    xs = sorted(s["nthreads"] for s in summary if s["mode"] == mode)
    ys = [next(s["ipc_mean"] for s in summary if s["mode"] == mode and s["nthreads"] == x) for x in xs]
    plt.plot(xs, ys, marker="o", label=MODE_LABEL[mode], color=COLORS[mode])
plt.xlabel("Worker threads (cores)")
plt.ylabel("Instructions retired per cycle (IPC)")
plt.title("Exp05: IPC vs. core count (per-thread avg)")
plt.xticks([1, 2, 4, 8, 10])
plt.grid(alpha=0.3)
plt.legend(fontsize=8)
plt.tight_layout()
plt.savefig(PLOTS / "03_ipc_vs_cores.png", dpi=150)
plt.close()

# ---- Plot 4: CAS retries vs cores (direct evidence of cache-line ownership contention) ----
plt.figure(figsize=(6.5, 4.5))
for mode in ("true_sharing", "redesigned"):
    xs = sorted(s["nthreads"] for s in summary if s["mode"] == mode)
    ys = [next(s["retries_mean"] for s in summary if s["mode"] == mode and s["nthreads"] == x) for x in xs]
    plt.plot(xs, ys, marker="o", label=MODE_LABEL[mode], color=COLORS[mode])
plt.xlabel("Worker threads (cores)")
plt.ylabel("Atomic CAS retries (total across threads)")
plt.title("Exp05: Lost coherence races (CAS retries) vs. cores")
plt.xticks([1, 2, 4, 8, 10])
plt.grid(alpha=0.3)
plt.legend(fontsize=8)
plt.tight_layout()
plt.savefig(PLOTS / "04_cas_retries_vs_cores.png", dpi=150)
plt.close()

# ---- Plot 5: bar chart at 8 cores comparing all 5 variants (the required comparison) ----
plt.figure(figsize=(6.5, 4.5))
xs = list(range(len(MODE_ORDER)))
ys = [next(s["wall_min"] for s in summary if s["mode"] == m and s["nthreads"] == 8) for m in MODE_ORDER]
errs = [next(s["wall_std"] for s in summary if s["mode"] == m and s["nthreads"] == 8) for m in MODE_ORDER]
plt.bar(xs, ys, yerr=errs, color=[COLORS[m] for m in MODE_ORDER], capsize=4)
plt.xticks(xs, [MODE_LABEL[m].replace(" (", "\n(") for m in MODE_ORDER], fontsize=7)
plt.ylabel("Execution time (s) at 8 cores, best-of-7")
plt.title("Exp05: All variants compared at 8 cores")
plt.tight_layout()
plt.savefig(PLOTS / "05_variant_comparison_8cores.png", dpi=150)
plt.close()

print("wrote plots to", PLOTS)

# Print the required comparison table (Section 13) to stdout for the report
print("\n=== Required Experimental Comparison Table ===")
header = f'{"Variant":28s} ' + " ".join(f"{c:>10}c" for c in xs_ideal)
print(header)
for mode in MODE_ORDER:
    cells = []
    for nt in xs_ideal:
        s = next(s for s in summary if s["mode"] == mode and s["nthreads"] == nt)
        cells.append(f"{s['wall_min']*1000:8.1f}ms")
    print(f"{MODE_LABEL[mode]:28s} " + " ".join(f"{c:>11}" for c in cells))
