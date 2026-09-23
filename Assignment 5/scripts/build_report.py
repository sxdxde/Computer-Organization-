#!/usr/bin/env python3
"""Exp05 - fill report_template.md placeholders with real results, then
produce two named per-student Markdown files ready for pandoc -> PDF."""
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SUMMARY = HERE / "results" / "summary.csv"
TEMPLATE = HERE / "report" / "report_template.md"

MODE_LABEL = {
    "baseline": "Baseline (private only)",
    "true_sharing": "Shared-data (true sharing)",
    "false_sharing": "False sharing (packed)",
    "false_sharing_free": "False-sharing-free (padded)",
    "redesigned": "Redesigned",
}
MODE_ORDER = ["baseline", "true_sharing", "false_sharing", "false_sharing_free", "redesigned"]
THREADS = [1, 2, 4, 8, 10]

rows = {}
with open(SUMMARY) as f:
    for r in csv.DictReader(f):
        rows[(r["mode"], int(r["nthreads"]))] = r


def cell(mode, nt, key, fmt="{:.4f}"):
    r = rows[(mode, nt)]
    return fmt.format(float(r[key]))


# ---- Table: Part A scaling (best-of-7 wall time (ms) + speedup, all variants) ----
lines = []
lines.append("| Variant | " + " | ".join(f"{n}c time (ms)" for n in THREADS) + " | " +
              " | ".join(f"{n}c speedup" for n in THREADS) + " |")
lines.append("|---" * (1 + 2 * len(THREADS)) + "|")
for mode in MODE_ORDER:
    times = [f"{float(rows[(mode, n)]['wall_min_s'])*1000:.1f}" for n in THREADS]
    sps = [f"{float(rows[(mode, n)]['speedup_vs_1core_minbasis']):.2f}x" for n in THREADS]
    lines.append(f"| {MODE_LABEL[mode]} | " + " | ".join(times) + " | " + " | ".join(sps) + " |")
lines.append("")
lines.append("*Best-of-7 (minimum wall time across 7 repetitions) per cell; a fixed synthetic "
              "80,000,000-event stream per run. Best-of-N is used rather than mean/median because OS "
              "scheduling noise on this shared, unpinned host can only add latency, never remove it — "
              "see the noise-disclosure table and discussion in §2.2. Speedup is each variant's own "
              "time relative to its own 1-core time (so a variant's 1c speedup is by definition 1.00x — "
              "this isolates each variant's scaling shape rather than comparing absolute per-variant "
              "single-thread cost, which differs because e.g. `true_sharing` and `redesigned` do strictly "
              "more work per event than `baseline`).*")
SCALING_TABLE = "\n".join(lines)

# ---- Table: measurement-noise disclosure (mean/median/min/std) for one representative variant ----
lines = []
lines.append("| Variant | Cores | mean (ms) | median (ms) | min (ms) | std dev (ms) | max/min ratio |")
lines.append("|---|---|---|---|---|---|---|")
for mode in ("baseline", "true_sharing", "false_sharing"):
    for nt in THREADS:
        r = rows[(mode, nt)]
        mean_ms = float(r["wall_mean_s"]) * 1000
        med_ms = float(r["wall_median_s"]) * 1000
        min_ms = float(r["wall_min_s"]) * 1000
        max_ms = float(r["wall_max_s"]) * 1000
        std_ms = float(r["wall_std_s"]) * 1000
        lines.append(f"| {MODE_LABEL[mode]} | {nt} | {mean_ms:.1f} | {med_ms:.1f} | {min_ms:.1f} | "
                      f"{std_ms:.1f} | {max_ms / max(min_ms, 0.001):.2f}x |")
NOISE_TABLE = "\n".join(lines)

# ---- Table: Part D coherence evidence (IPC, CAS retries, involuntary CS) ----
lines = []
lines.append("| Variant | Cores | IPC (instr/cycle) | CAS retries (total) | Involuntary context switches |")
lines.append("|---|---|---|---|---|")
for mode in ("baseline", "true_sharing", "redesigned"):
    for nt in THREADS:
        r = rows[(mode, nt)]
        lines.append(f"| {MODE_LABEL[mode]} | {nt} | {float(r['ipc_mean']):.3f} | "
                      f"{int(float(r['cas_retries_mean'])):,} | {float(r['involuntary_cs_mean']):.1f} |")
COHERENCE_EVIDENCE_TABLE = "\n".join(lines)
COHERENCE_EVIDENCE_TABLE += ("\n\n*`false_sharing`/`false_sharing_free` do not use the CAS-loop path "
                              "(they use a hardware `fetch_add`, which cannot \"retry\" in the same "
                              "instrumented sense) — their coherence cost shows up directly in wall time "
                              "and IPC instead (§3), which is why this table focuses on the "
                              "`true_sharing`/`redesigned` pair, where the CAS-retry counter applies.*")

# ---- Table: Part E true vs false sharing, side by side ----
lines = []
lines.append("| Cores | true_sharing (ms) | false_sharing (ms) | false_sharing_free (ms) | "
              "false_sharing / free ratio | true_sharing / baseline ratio |")
lines.append("|---|---|---|---|---|---|")
for nt in THREADS:
    t_true = float(rows[("true_sharing", nt)]["wall_min_s"]) * 1000
    t_false = float(rows[("false_sharing", nt)]["wall_min_s"]) * 1000
    t_free = float(rows[("false_sharing_free", nt)]["wall_min_s"]) * 1000
    t_base = float(rows[("baseline", nt)]["wall_min_s"]) * 1000
    lines.append(f"| {nt} | {t_true:.1f} | {t_false:.1f} | {t_free:.1f} | "
                  f"{t_false / t_free:.2f}x | {t_true / t_base:.2f}x |")
TRUE_VS_FALSE_TABLE = "\n".join(lines)

# ---- Figures (relative paths from report/ to results/plots/) ----
FIG = lambda fname, cap: f"![{cap}](../results/plots/{fname})\n\n*{cap}*"
FIG_TIME = FIG("01_time_vs_cores.png", "Execution time vs. core count, all five variants.")
FIG_SPEEDUP = FIG("02_speedup_vs_cores.png", "Speedup vs. core count (each variant relative to its own 1-core time), with ideal linear speedup shown for reference.")
FIG_IPC = FIG("03_ipc_vs_cores.png", "Instructions-retired-per-cycle vs. core count. A falling IPC under constant per-event instruction count is evidence of off-core stalling.")
FIG_RETRIES = FIG("04_cas_retries_vs_cores.png", "Total atomic CAS retries (lost ownership races) vs. core count, true_sharing vs. redesigned.")

template = TEMPLATE.read_text()
template = (template
            .replace("__SCALING_TABLE__", SCALING_TABLE)
            .replace("__NOISE_TABLE__", NOISE_TABLE)
            .replace("__COHERENCE_EVIDENCE_TABLE__", COHERENCE_EVIDENCE_TABLE)
            .replace("__TRUE_VS_FALSE_TABLE__", TRUE_VS_FALSE_TABLE)
            .replace("__FIG_TIME__", FIG_TIME)
            .replace("__FIG_SPEEDUP__", FIG_SPEEDUP)
            .replace("__FIG_IPC__", FIG_IPC)
            .replace("__FIG_RETRIES__", FIG_RETRIES))

STUDENTS = [
    ("Sudarshan Sudhakar", "CS23B2007", "report_Sudarshan_Sudhakar_CS23B2007.md"),
    ("Deetya Ashish Mehta", "CS23I1032", "report_Deetya_Ashish_Mehta_CS23I1032.md"),
]

for name, roll, fname in STUDENTS:
    out = template.replace("__STUDENT_NAME__", name).replace("__ROLL_NUMBER__", roll)
    (HERE / "report" / fname).write_text(out)
    print("wrote", fname)
