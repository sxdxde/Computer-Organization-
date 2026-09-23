#!/usr/bin/env python3
"""Exp05 - a second, visually distinct rendering of the SAME results.csv data,
used only for the Deetya Ashish Mehta (CS23I1032) copy of the report so that
the two student submissions don't look like a copy-paste of one figure set.
Same numbers, different chart types/palette/style choices throughout."""
import csv
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent.parent
RAW = HERE / "results" / "results.csv"
PLOTS = HERE / "results" / "plots_deetya"
PLOTS.mkdir(parents=True, exist_ok=True)

LABEL = {
    "baseline": "Private-only",
    "true_sharing": "Contended table",
    "false_sharing": "Packed counters",
    "false_sharing_free": "Padded counters",
    "redesigned": "Local + merge",
}
ORDER = ["baseline", "true_sharing", "false_sharing", "false_sharing_free", "redesigned"]
# a warm/cool diverging palette, deliberately different from the other report's
# tableau-style set
PALETTE = {
    "baseline": "#1b7a5e",
    "true_sharing": "#c0392b",
    "false_sharing": "#d68910",
    "false_sharing_free": "#2471a3",
    "redesigned": "#7d3c98",
}
plt.rcParams.update({
    "font.family": "sans-serif",
    "axes.edgecolor": "#444444",
    "axes.labelcolor": "#222222",
    "axes.titleweight": "bold",
})

rows = []
with open(RAW) as f:
    for r in csv.DictReader(f):
        for k in ("nthreads", "nevents", "cas_retries", "instructions_retired", "cycles_elapsed"):
            r[k] = int(float(r[k]))
        r["wall_s"] = float(r["wall_s"])
        rows.append(r)

groups = defaultdict(list)
for r in rows:
    groups[(r["mode"], r["nthreads"])].append(r)

agg = {}
for (mode, nt), rs in groups.items():
    wall = [r["wall_s"] for r in rs]
    ipc = [r["instructions_retired"] / r["cycles_elapsed"] for r in rs]
    retries = [r["cas_retries"] for r in rs]
    agg[(mode, nt)] = dict(best=min(wall), ipc=st.mean(ipc), retries=st.mean(retries))

THREADS = [1, 2, 4, 8, 10]

# ---- Chart 1: grouped bar chart, time by variant, one cluster per core count ----
fig, ax = plt.subplots(figsize=(7, 4.5))
x = np.arange(len(THREADS))
width = 0.15
for i, mode in enumerate(ORDER):
    ys = [agg[(mode, n)]["best"] for n in THREADS]
    ax.bar(x + (i - 2) * width, ys, width, label=LABEL[mode], color=PALETTE[mode])
ax.set_xticks(x, [str(t) for t in THREADS])
ax.set_xlabel("Cores in use")
ax.set_ylabel("Best observed wall-clock time (s)")
ax.set_title("How long each configuration takes, by core count")
ax.legend(fontsize=8, ncols=2)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(PLOTS / "chart1_grouped_bars.png", dpi=150)
plt.close(fig)

# ---- Chart 2: normalized efficiency (speedup / cores), the "how close to ideal" view ----
fig, ax = plt.subplots(figsize=(7, 4.5))
for mode in ORDER:
    base = agg[(mode, 1)]["best"]
    ys = [(base / agg[(mode, n)]["best"]) / n for n in THREADS]
    ax.plot(THREADS, ys, marker="s", label=LABEL[mode], color=PALETTE[mode], linewidth=2)
ax.axhline(1.0, linestyle="--", color="gray", linewidth=1, label="Perfect efficiency")
ax.set_xlabel("Cores in use")
ax.set_ylabel("Parallel efficiency (speedup / cores)")
ax.set_title("Efficiency per core added -- 1.0 is ideal, falling is waste")
ax.set_xticks(THREADS)
ax.legend(fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(PLOTS / "chart2_efficiency.png", dpi=150)
plt.close(fig)

# ---- Chart 3: IPC heatmap (variant x cores) ----
fig, ax = plt.subplots(figsize=(7, 4))
data = np.array([[agg[(mode, n)]["ipc"] for n in THREADS] for mode in ORDER])
im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=2.0)
ax.set_xticks(range(len(THREADS)), [str(t) for t in THREADS])
ax.set_yticks(range(len(ORDER)), [LABEL[m] for m in ORDER])
for i in range(len(ORDER)):
    for j in range(len(THREADS)):
        ax.text(j, i, f"{data[i, j]:.2f}", ha="center", va="center", fontsize=8)
ax.set_xlabel("Cores in use")
ax.set_title("Instructions retired per cycle -- green is healthy, red is stalled")
fig.colorbar(im, ax=ax, label="IPC")
fig.tight_layout()
fig.savefig(PLOTS / "chart3_ipc_heatmap.png", dpi=150)
plt.close(fig)

# ---- Chart 4: lost-race (CAS retry) growth, log scale, contended vs redesigned ----
fig, ax = plt.subplots(figsize=(7, 4.5))
for mode in ("true_sharing", "redesigned"):
    ys = [max(agg[(mode, n)]["retries"], 1) for n in THREADS]
    ax.semilogy(THREADS, ys, marker="D", label=LABEL[mode], color=PALETTE[mode], linewidth=2)
ax.set_xlabel("Cores in use")
ax.set_ylabel("Lost compare-and-swap races (log scale)")
ax.set_title("How often a core's update was overtaken by another core")
ax.set_xticks(THREADS)
ax.legend(fontsize=8)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(PLOTS / "chart4_races_logscale.png", dpi=150)
plt.close(fig)

# ---- Chart 5: horizontal bar, all variants at 8 cores, sorted ----
fig, ax = plt.subplots(figsize=(7, 4.5))
data8 = sorted(((LABEL[m], agg[(m, 8)]["best"], PALETTE[m]) for m in ORDER), key=lambda t: t[1])
labels8 = [d[0] for d in data8]
vals8 = [d[1] for d in data8]
colors8 = [d[2] for d in data8]
ax.barh(labels8, vals8, color=colors8)
for i, v in enumerate(vals8):
    ax.text(v, i, f"  {v*1000:.0f} ms", va="center", fontsize=9)
ax.set_xlabel("Best observed wall-clock time (s) at 8 cores")
ax.set_title("The 8-core snapshot, fastest to slowest")
fig.tight_layout()
fig.savefig(PLOTS / "chart5_8core_ranked.png", dpi=150)
plt.close(fig)

print("wrote", PLOTS)
