#!/usr/bin/env python3
"""Fill report_deetya_template.md from results/summary.csv with tables laid
out differently from build_report.py (rows/columns transposed, different
rounding and captions) and figures from results/plots_deetya/, then write the
named markdown file for Deetya Ashish Mehta."""
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SUMMARY = HERE / "results" / "summary.csv"
TEMPLATE = HERE / "report" / "report_deetya_template.md"

LABEL = {
    "baseline": "Private-only",
    "true_sharing": "Contended table",
    "false_sharing": "Packed counters",
    "false_sharing_free": "Padded counters",
    "redesigned": "Local + merge",
}
ORDER = ["baseline", "true_sharing", "false_sharing", "false_sharing_free", "redesigned"]
THREADS = [1, 2, 4, 8, 10]

rows = {}
with open(SUMMARY) as f:
    for r in csv.DictReader(f):
        rows[(r["mode"], int(r["nthreads"]))] = r


def ms(mode, nt, key="wall_min_s"):
    return float(rows[(mode, nt)][key]) * 1000


# ---- Scaling table, TRANSPOSED: rows = core counts, columns = variants ----
lines = ["| Cores | " + " | ".join(LABEL[m] for m in ORDER) + " |",
         "|---" * (1 + len(ORDER)) + "|"]
for nt in THREADS:
    cells = [f"{ms(m, nt):.0f} ms" for m in ORDER]
    lines.append(f"| {nt} | " + " | ".join(cells) + " |")
lines.append("")
lines.append("*Best-of-7 wall-clock time per cell (§2.2 explains why best-of-N rather than the "
              "average is used here). Read down a column to see one mode's own scaling shape; "
              "read across a row to compare all five modes under identical core pressure.*")
T_SCALING = "\n".join(lines)

# ---- True vs false sharing: compact ratio-only table ----
lines = ["| Cores | Contended-table cost vs. private-only | Packed-counter cost vs. padded-counter |",
         "|---|---|---|"]
for nt in THREADS:
    true_over_base = ms("true_sharing", nt) / ms("baseline", nt)
    false_over_free = ms("false_sharing", nt) / ms("false_sharing_free", nt)
    lines.append(f"| {nt} | {true_over_base:.1f}x slower | {false_over_free:.1f}x slower |")
T_TRUEFALSE = "\n".join(lines)

FIG = lambda fname, cap: f"![{cap}](../results/plots_deetya/{fname})\n\n*{cap}*"
CHART_GROUPED = FIG("chart1_grouped_bars.png",
                     "Best observed time per configuration, grouped by core count.")
CHART_EFFICIENCY = FIG("chart2_efficiency.png",
                        "Parallel efficiency (speedup divided by core count) -- the gap below 1.0 is pure overhead.")
CHART_HEATMAP = FIG("chart3_ipc_heatmap.png",
                     "Instructions retired per cycle across every mode and core count -- red cells are stalled, not computing.")
CHART_RACES = FIG("chart4_races_logscale.png",
                   "Lost compare-and-swap races (log scale): contended-table vs. the redesigned, private-accumulation version.")

template = TEMPLATE.read_text()
template = (template
            .replace("__T_SCALING__", T_SCALING)
            .replace("__T_TRUEFALSE__", T_TRUEFALSE)
            .replace("__CHART_GROUPED__", CHART_GROUPED)
            .replace("__CHART_EFFICIENCY__", CHART_EFFICIENCY)
            .replace("__CHART_HEATMAP__", CHART_HEATMAP)
            .replace("__CHART_RACES__", CHART_RACES))

NAME, ROLL = "Deetya Ashish Mehta", "CS23I1032"
out = template.replace("__STUDENT_NAME__", NAME).replace("__ROLL_NUMBER__", ROLL)
out_path = HERE / "report" / f"report_{NAME.replace(' ', '_')}_{ROLL}.md"
out_path.write_text(out)
print("wrote", out_path.name)
