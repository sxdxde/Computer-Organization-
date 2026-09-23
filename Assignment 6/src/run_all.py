#!/usr/bin/env python3
"""Runs every workload through the six-wide decoder simulator and writes:
  - results/traces/<workload>.txt        (per-cycle decoder trace)
  - results/per_cycle.csv                (one row per cycle, all workloads)
  - results/per_instruction.csv          (one row per decoded instruction)
  - results/summary.csv                  (one row per workload, aggregated)
  - results/plots/*.png                  (simple matplotlib summary charts)
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decoder.simulator import run_simulation, format_trace
from workloads import WORKLOADS

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"
TRACES = RESULTS / "traces"
PLOTS = RESULTS / "plots"
for d in (RESULTS, TRACES, PLOTS):
    d.mkdir(parents=True, exist_ok=True)


def main():
    per_cycle_rows = []
    per_instruction_rows = []
    summary_rows = []

    for name, stream in WORKLOADS.items():
        result = run_simulation(name, stream)

        (TRACES / f"{name}.txt").write_text(format_trace(result))

        for c in result.cycles:
            per_cycle_rows.append({
                "workload": name, "cycle": c.cycle,
                "bytes_available": c.bytes_available, "bytes_consumed": c.bytes_consumed,
                "instructions_decoded": c.instructions_decoded,
                "uops_generated": c.uops_generated,
                "fusion_events": c.fusion_events, "msrom_events": c.msrom_events,
                "lanes_idle": sum(1 for l in c.lanes if l.insn is None),
            })
            for lr in c.lanes:
                if lr.insn is None:
                    continue
                per_instruction_rows.append({
                    "workload": name, "cycle": c.cycle, "lane": f"D{lr.lane}",
                    "bytes_hex": " ".join(f"{b:02X}" for b in lr.insn.raw_bytes),
                    "length": lr.insn.length, "mnemonic": lr.insn.mnemonic,
                    "operands": lr.insn.operand_text,
                    "class": lr.uop.instr_class,
                    "uops": lr.uops_this_lane,
                    "fused": lr.fused_with_prev,
                    "msrom": lr.uop.is_msrom,
                })

        n_cycles = result.num_cycles
        summary_rows.append({
            "workload": name,
            "total_instructions": result.total_instructions,
            "total_bytes": result.total_bytes,
            "total_uops": result.total_uops,
            "cycles_used": n_cycles,
            "instructions_per_cycle": result.total_instructions / n_cycles,
            "bytes_per_cycle": result.total_bytes / n_cycles,
            "uops_per_cycle": result.total_uops / n_cycles,
            "uops_per_instruction": result.total_uops / result.total_instructions,
            "fusion_events": result.total_fusion_events,
            "msrom_events": result.total_msrom_events,
        })

        print(f"{name}: {result.total_instructions} instr, {result.total_bytes} bytes, "
              f"{result.total_uops} uops, {n_cycles} cycles, "
              f"fusion={result.total_fusion_events}, msrom={result.total_msrom_events}")

    _write_csv(RESULTS / "per_cycle.csv", per_cycle_rows)
    _write_csv(RESULTS / "per_instruction.csv", per_instruction_rows)
    _write_csv(RESULTS / "summary.csv", summary_rows)

    make_plots(summary_rows)
    print("\nDone. Traces in results/traces/, tables in results/*.csv, plots in results/plots/.")


def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def make_plots(summary_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names = [r["workload"] for r in summary_rows]
    short = [n.split("_")[0] for n in names]
    ipc = [r["instructions_per_cycle"] for r in summary_rows]
    bpc = [r["bytes_per_cycle"] for r in summary_rows]
    upc = [r["uops_per_cycle"] for r in summary_rows]
    upi = [r["uops_per_instruction"] for r in summary_rows]
    fusion = [r["fusion_events"] for r in summary_rows]
    msrom = [r["msrom_events"] for r in summary_rows]

    x = np.arange(len(names))

    # 1. instructions/cycle vs uops/cycle, against the 6-wide ceiling
    fig, ax = plt.subplots(figsize=(8, 5))
    w = 0.35
    ax.bar(x - w / 2, ipc, w, label="Instructions decoded / cycle")
    ax.bar(x + w / 2, upc, w, label="uops generated / cycle")
    ax.axhline(6, color="gray", linestyle="--", linewidth=1, label="6-wide ceiling")
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("count / cycle")
    ax.set_title("Decoder throughput vs. the 6-wide ceiling, per workload")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "01_throughput_vs_ceiling.png", dpi=150)
    plt.close(fig)

    # 2. bytes/cycle vs 32B budget
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x, bpc, color="tab:orange")
    ax.axhline(32, color="gray", linestyle="--", linewidth=1, label="32-byte/cycle budget")
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("bytes consumed / cycle")
    ax.set_title("Legacy-decode byte bandwidth utilization, per workload")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "02_bytes_per_cycle.png", dpi=150)
    plt.close(fig)

    # 3. uops per instruction (expansion ratio)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x, upi, color="tab:green")
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=1, label="1 uop / instruction (no expansion)")
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("uops / instruction")
    ax.set_title("uop-expansion ratio, per workload")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "03_uop_expansion_ratio.png", dpi=150)
    plt.close(fig)

    # 4. fusion vs msrom events
    fig, ax = plt.subplots(figsize=(8, 5))
    w = 0.35
    ax.bar(x - w / 2, fusion, w, label="Fusion events", color="tab:blue")
    ax.bar(x + w / 2, msrom, w, label="MSROM events", color="tab:red")
    ax.set_xticks(x)
    ax.set_xticklabels(short)
    ax.set_ylabel("event count")
    ax.set_title("Fusion and MSROM events, per workload")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "04_fusion_msrom_events.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
