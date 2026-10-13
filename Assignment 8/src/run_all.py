#!/usr/bin/env python3
"""Runs every Exp08 experiment; writes traces, CSVs, text artefacts and (via make_plots) figures under ../results/."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sched.config import Machine, CLASSES, INF
from sched.simulator import simulate
from sched import workloads as W
from sched import analysis as A

HERE = Path(__file__).resolve().parent.parent
R = HERE / "results"
for d in ("traces", "plots", "plots_sudarshan", "plots_deetya"):
    (R / d).mkdir(parents=True, exist_ok=True)

M = W.MA
LOADS = dict(W.WORKLOADS)
LOADS.update(W.EXTRA)

# (run name, workload, machine) -- everything is logged, nothing dropped.
RUNS = []
for wl in ("base", "base_x4"):
    for mn, cfg in W.MACHINES.items():
        RUNS.append((f"{wl}__{mn}", wl, cfg))
    for s in (6, 12, 24, 48, 96):
        RUNS.append((f"{wl}__sched{s}", wl, M.but(sched_size=s)))
    for iw, ww in ((3, 3), (6, 6), (3, 6), (6, 3), (4, 4), (2, 2)):
        RUNS.append((f"{wl}__issue{iw}_wake{ww}", wl, M.but(issue_width=iw, wakeup_width=ww)))
for k in ("s_inv4_A", "s_inv4_B", "d_inv4_A", "d_inv4_B"):
    RUNS.append((f"{k}__A_orig", k, M))
    RUNS.append((f"{k}__sched12", k, M.but(sched_size=12)))
for k in ("s_counterexample", "d_counterexample"):
    for mn in ("A_orig", "E_load3", "J_loadpipe", "D_imul2", "G_load3_imul2"):
        RUNS.append((f"{k}__{mn}", k, W.MACHINES[mn]))
# extra bounded-loop example used by the crime scene / backtrace
seen, uniq = set(), []
for r in RUNS:
    if r[0] not in seen:
        seen.add(r[0])
        uniq.append(r)
RUNS = uniq


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    W.write_inputs(W.EXTRA)
    results, summary, attrib, cyc_rows, uop_rows = {}, [], [], [], []
    for name, wl, cfg in RUNS:
        res = simulate(name, LOADS[wl], cfg)
        results[name] = res
        (R / "traces" / f"{name}.txt").write_text(A.fmt_trace(res))
        m = A.metrics(res)
        m["workload"] = wl
        summary.append(m)
        cyc_rows += A.cycle_rows(res)
        uop_rows += A.uop_rows(res)
        at = A.attribution(LOADS[wl], cfg, res.total)
        attrib.append(dict(run=name, workload=wl, T=at["T"], dataflow_T=at["dataflow_T"], bottleneck=at["bottleneck"],
                           **{f"gain_{k}": v for k, v in at["gains"].items()}))
        print(f"{name:<34} T={res.total:<4} ipc={m['ipc']:<6} peak_sched={m['peak_sched']:<3} "
              f"disp_blocked={m['dispatch_blocked_cycles']:<3} unsel={m['ready_unselected_total']:<4} -> {at['bottleneck']}")
    write_csv(R / "summary.csv", summary)
    write_csv(R / "bottleneck_attribution.csv", attrib)
    write_csv(R / "per_cycle.csv", cyc_rows)
    write_csv(R / "per_uop.csv", uop_rows)

    base = results["base__A_orig"]
    # class demand table (Investigation 3)
    cnt = base.cls_count()
    dem = []
    for cl in CLASSES:
        n = M.units(cl)
        occ = cnt[cl] * A.LATENCY[cl]
        dem.append(dict(resource=cl, parts=cnt[cl], units=n, latency=A.LATENCY[cl], unit_cycles_demanded=occ,
                        min_cycles_if_perfectly_spread=round(occ / n, 1)))
    write_csv(R / "inv3_class_demand.csv", dem)
    # ready-case dump
    rc = []
    for c in A.ready_cases(base, 2):
        rc.append(dict(cycle=c.t, ready=" ".join(c.ready_parts), selected=" ".join(c.selected), issued=" ".join(c.issued),
                       unselected=" | ".join(f"{l}: {w}" for l, w in c.unselected), issue_slots=f"{len(c.issued)}/{M.issue_width}",
                       wake=f"{c.wake_granted}/{M.wakeup_width}"))
    write_csv(R / "inv2_multi_ready_cycles.csv", rc)
    # crime scenes at a few candidate cycles
    scenes = "\n\n".join(A.crime_scene(base, t) for t in (7, 12, 17, 18, 22, 27))
    (R / "crime_scenes_candidates.txt").write_text(scenes)
    # chains
    chains = {
        "FP chain": [4, 10, 17, 23, 25, 28, 36, 37, 41, 44],
        "integer address -> multiply chain": [0, 6, 12, 14, 15, 16, 19, 21, 22, 26, 29, 30, 31],
        "second address chain (R43/R49/R51)": [0, 32, 38, 39, 40, 42, 43, 45, 46],
        "load-use chain (R24)": [8, 9],
    }
    ch = []
    for cname, ids in chains.items():
        for r in A.explain_chain(base, ids):
            ch.append(dict(chain=cname, **r))
    write_csv(R / "inv1_chains.csv", ch)
    from make_plots import make_plots
    make_plots(results, summary, attrib, R)
    print("done")


if __name__ == "__main__":
    main()
