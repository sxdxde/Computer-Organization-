"""
Reads results/results.json (produced by simulator.py) and emits a LaTeX
file (report/tables.tex) containing \\input-able tables built from the
ACTUAL simulation numbers, so the report can never drift from the code.
"""

import json
import os

HERE = os.path.dirname(__file__)
RESULTS_PATH = os.path.join(HERE, "..", "results", "results.json")
OUT_PATH = os.path.join(HERE, "..", "report", "tables.tex")


def esc(s):
    return str(s).replace("_", r"\_")


def pct(x):
    return f"{100 * x:.2f}\\%"


ROW_FMT = (
    "{label} & {acc} & {lookups} & {hits} & {misses} & {hitr} & {missr} "
    "& {cold} & {conflict} & {capacity} \\\\\n"
)


def table_block(caption, label, rows):
    """rows: list of (row_label, stats_dict)"""
    out = []
    out.append(r"\begin{table}[H]")
    out.append(r"\centering")
    out.append(r"\resizebox{\textwidth}{!}{%")
    out.append(r"\begin{tabular}{lrrrrrrrrr}")
    out.append(r"\toprule")
    out.append(
        r"Cache / Case & Acc. & Lookups & Hits & Misses & Hit\% & Miss\% "
        r"& Cold & Conflict & Capacity \\"
    )
    out.append(r"\midrule")
    for row_label, s in rows:
        out.append(
            ROW_FMT.format(
                label=esc(row_label),
                acc=s["accesses"],
                lookups=s["lookups"],
                hits=s["hits"],
                misses=s["misses"],
                hitr=pct(s["hit_rate"]),
                missr=pct(s["miss_rate"]),
                cold=s["cold_misses"],
                conflict=s["conflict_misses"],
                capacity=s["capacity_misses"],
            ).rstrip("\n")
        )
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}%")
    out.append(r"}")
    out.append(f"\\caption{{{caption}}}")
    out.append(f"\\label{{{label}}}")
    out.append(r"\end{table}")
    return "\n".join(out)


def main():
    with open(RESULTS_PATH) as f:
        R = json.load(f)

    blocks = []

    # ---- Sequential ----
    rows = [
        ("I-Cache (sequential)", R["sequential"]["instruction"]),
        ("D-Cache (sequential)", R["sequential"]["data"]),
    ]
    blocks.append(
        table_block(
            "Sequential access pattern -- I-Cache and D-Cache results",
            "tab:sequential",
            rows,
        )
    )

    # ---- Repeated ----
    rows = [
        ("I-Cache (working set fits in cache)", R["repeated"]["fits_in_cache"]["instruction"]),
        ("D-Cache (working set fits in cache)", R["repeated"]["fits_in_cache"]["data"]),
        ("I-Cache (working set $>$ cache capacity)", R["repeated"]["exceeds_cache"]["instruction"]),
        ("D-Cache (working set $>$ cache capacity)", R["repeated"]["exceeds_cache"]["data"]),
    ]
    blocks.append(
        table_block(
            "Repeated (temporal locality) access pattern -- I-Cache and D-Cache results",
            "tab:repeated",
            rows,
        )
    )

    # ---- Strided ----
    rows = []
    for stride in ("2", "4", "16"):
        rows.append((f"I-Cache (stride = {stride})", R["strided"][stride]["instruction"]))
        rows.append((f"D-Cache (stride = {stride})", R["strided"][stride]["data"]))
    blocks.append(
        table_block(
            "Strided access pattern (stride = 2, 4, 16 words) -- I-Cache and D-Cache results",
            "tab:strided",
            rows,
        )
    )

    rows = [
        ("I-Cache (index-aliasing conflict demo)", R["strided"]["conflict_demo"]["instruction"]),
        ("D-Cache (index-aliasing conflict demo)", R["strided"]["conflict_demo"]["data"]),
    ]
    blocks.append(
        table_block(
            "Strided access, conflict-demonstration case -- 4 addresses exactly one "
            "cache-size (2048 words) apart, round-robined 256 times",
            "tab:conflict-demo",
            rows,
        )
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write("\n\n".join(blocks) + "\n")

    print(f"Wrote {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()
