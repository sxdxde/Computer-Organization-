#!/usr/bin/env python3
"""Runs every Exp07 experiment and writes traces, CSVs and plots under ../results/."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ooo.config import MachineConfig
from ooo.simulator import simulate
from ooo.reporting import fmt_trace, fmt_arch_timeline, summarize, stall_runs, lifetimes
import workloads

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"
for d in (RESULTS, RESULTS / "traces", RESULTS / "plots"):
    d.mkdir(parents=True, exist_ok=True)

BASE = MachineConfig()

# (run name, workload, config) -- every run is logged; nothing is dropped.
RUNS = [
    ("inv1_rename", "inv1_rename", BASE),
    ("inv1b_rename_x5", "inv1b_rename_x5", BASE),
    ("inv2a_loads_LQ", "inv2a_loads_LQ", BASE),
    ("inv2b_stores_SQ", "inv2b_stores_SQ", BASE),
    ("inv2c_dependents_IQ", "inv2c_dependents_IQ", BASE),
    ("inv3_longlat", "inv3_longlat", BASE),
    ("inv4_longlat_ret4", "inv3_longlat", BASE.but(retire_width=4)),
    ("inv4_longlat_ret2", "inv3_longlat", BASE.but(retire_width=2)),
    ("inv4_indep_ret4", "inv4_independent", BASE.but(retire_width=4)),
    ("inv4_indep_ret2", "inv4_independent", BASE.but(retire_width=2)),
    ("inv5_rob24", "inv3_longlat", BASE.but(rob_size=24)),
    ("inv5_rob48", "inv3_longlat", BASE.but(rob_size=48)),
    ("inv5_rob96", "inv3_longlat", BASE.but(rob_size=96)),
    ("inv5_prf32", "inv3_longlat", BASE.but(prf_size=32)),
    ("inv5_prf48", "inv3_longlat", BASE.but(prf_size=48)),
    ("inv5_prf64", "inv3_longlat", BASE.but(prf_size=64)),
    ("inv6a_short_lifetime", "inv6a_short_lifetime", BASE),
    ("inv6b_long_lifetime", "inv6b_long_lifetime", BASE),
    ("inv6c_one_reg_many_versions", "inv6c_one_reg_many_versions", BASE.but(rob_size=64)),
    ("inv7_mispredict", "inv7_mispredict", BASE),
    ("inv7_correct", "inv7_correct", BASE),
    ("inv7b_late_resolve", "inv7b_late_resolve", BASE),
    ("final_ckpt", "final_ckpt", BASE),
    ("final_sq_behind_load", "final_sq_behind_load", BASE),
]
GRID_ROB = [24, 48, 96]
GRID_PRF = [32, 48, 64, 96, 128]


def write_csv(path, rows):
    if rows:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def main():
    workloads.write_inputs()
    results, summary, per_cycle, per_instr, stalls, life = {}, [], [], [], [], []
    for name, wl, cfg in RUNS:
        res = simulate(name, workloads.load(wl), cfg)
        results[name] = res
        (RESULTS / "traces" / f"{name}.txt").write_text(fmt_trace(res))
        summary.append(summarize(res))
        for r in res.cycles:
            per_cycle.append(dict(run=name, cycle=r.cycle, rob_occ=r.rob_occ, free_pregs=r.free_pregs,
                                  iq_occ=r.iq_occ, lq_occ=r.lq_occ, sq_occ=r.sq_occ, ckpt_used=r.ckpt_used,
                                  decodeq_occ=r.decodeq_occ, allocated=r.allocated, retired=r.retired,
                                  squashed=r.squashed, issued=r.issued, completed=r.completed,
                                  done_unretired=r.done_unretired, issue_slots_free=r.issue_slots_free,
                                  alloc_stalled=int(r.alloc_stalled), stall_resource=r.stall_resource,
                                  stall_all=r.stall_all, fe_stalled=int(r.fe_stalled), fe_reason=r.fe_reason))
        for d in res.dyn:
            if d.alloc_c is None:
                continue
            per_instr.append(dict(run=name, seq=d.seq, id=d.label, text=d.st.text, wrong_path=int(d.wrong_path),
                                  arch_dst=d.st.dst or "", arch_srcs=" ".join(d.st.srcs),
                                  phys_srcs=" ".join("ARF" if p is None else f"P{p}" for _, p in d.psrcs),
                                  phys_dst="" if d.pdst is None else f"P{d.pdst}",
                                  old_phys="" if d.pdst is None else ("ARF" if d.pold is None else f"P{d.pold}"),
                                  rob_entry=d.rob_idx, decode_c=d.decode_c, alloc_c=d.alloc_c, issue_c=d.issue_c,
                                  complete_c=d.complete_c, retire_c=d.retire_c, squash_c=d.squash_c,
                                  reclaim_c=d.reclaim_c, final_state=d.state))
        for s in stall_runs(res):
            stalls.append(dict(run=name, start=s["start"], end=s["end"], blocked_instr=s["instr"],
                               immediate_resource=s["resource"], all_missing=s["all"], availability=s["avail"],
                               why_unavailable=s["reason"], earlier_event=s["root"]))
        for l in lifetimes(res):
            life.append(dict(run=name, **l))
        print(f"{name:<30} cycles={res.total_cycles:<4} retired={len(res.retired):<4} squashed={len(res.squashed):<3} "
              f"first_stall={summary[-1]['first_stall_resource']}@{summary[-1]['first_stall_cycle']}")

    # Investigation 5 grid: ROB x PRF, long-latency workload
    grid = []
    for rob in GRID_ROB:
        for prf in GRID_PRF:
            res = simulate(f"grid_rob{rob}_prf{prf}", workloads.load("inv3_longlat"), BASE.but(rob_size=rob, prf_size=prf))
            s = summarize(res)
            sr = stall_runs(res)
            grid.append(dict(rob=rob, prf=prf, cycles=s["cycles"], ipc=s["ipc"],
                             first_stall_resource=s["first_stall_resource"], first_stall_cycle=s["first_stall_cycle"],
                             first_stall_rob_occ=s["first_stall_rob_occ"],
                             stall_cycles=s["alloc_stall_cycles"], stall_ROB=s["stall_ROB"], stall_PRF=s["stall_PRF"],
                             stall_IQ=s["stall_IQ"], peak_rob=s["peak_rob"], peak_prf_used=s["peak_prf_used"],
                             peak_iq=s["peak_iq"], dominant=max(["ROB", "PRF", "IQ"], key=lambda k: s[f"stall_{k}"])
                             if s["alloc_stall_cycles"] else "none"))

    write_csv(RESULTS / "summary.csv", summary)
    write_csv(RESULTS / "per_cycle.csv", per_cycle)
    write_csv(RESULTS / "per_instruction.csv", per_instr)
    write_csv(RESULTS / "stall_chains.csv", stalls)
    write_csv(RESULTS / "preg_lifetimes.csv", life)
    write_csv(RESULTS / "inv5_grid.csv", grid)

    # Derived text artifacts used directly by the report
    extra = []
    r1 = results["inv1_rename"]
    for a in ("R1", "R2", "R4"):
        extra.append(fmt_arch_timeline(r1, a))
        extra.append("")
    (RESULTS / "inv1_register_evolution.txt").write_text("\n".join(extra))
    ev = []
    for n in ("inv6a_short_lifetime", "inv6b_long_lifetime"):
        ev.append(f"[{n}]")
        ev.append(fmt_arch_timeline(results[n], "R1"))
        ev.append("")
    (RESULTS / "inv6_r1_evolution.txt").write_text("\n".join(ev))

    from make_plots import make_plots
    make_plots(results, grid, RESULTS / "plots")
    print("\nDone. Traces: results/traces/, tables: results/*.csv, plots: results/plots/")


if __name__ == "__main__":
    main()
