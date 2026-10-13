#!/usr/bin/env python3
"""Static predictions, computed from the program text only (no scheduling is simulated).

predicted time  = max(dataflow critical path, max over classes of ceil(sum of unit-occupancy / units))
predicted limit = the term that attains the max.
These are written to results/predictions.csv BEFORE run_all.py is executed; the report then scores them.
"""
import csv
from pathlib import Path
from sched.workloads import BASE_BR, repeat, MACHINES, EXTRA, MA
from sched.analysis import static_bounds

OUT = Path(__file__).resolve().parent.parent / "results"
OUT.mkdir(exist_ok=True)
rows = []
for wname, lines in (("base", BASE_BR), ("base_x4", repeat(BASE_BR, 4))):
    for mname, cfg in MACHINES.items():
        cp, b = static_bounds(lines, cfg)
        lim = max(b, key=b.get)
        pred_T, pred = (cp, "dataflow") if cp >= b[lim] else (b[lim], lim)
        rows.append(dict(workload=wname, machine=mname, critical_path=cp, **{f"bound_{k}": v for k, v in b.items()},
                         predicted_T=pred_T, predicted_limit=pred))
for wname in ("s_counterexample", "d_counterexample"):
    for mname in ("A_orig", "E_load3", "J_loadpipe"):
        cp, b = static_bounds(EXTRA[wname], MACHINES[mname])
        lim = max(b, key=b.get)
        pred_T, pred = (cp, "dataflow") if cp >= b[lim] else (b[lim], lim)
        rows.append(dict(workload=wname, machine=mname, critical_path=cp, **{f"bound_{k}": v for k, v in b.items()},
                         predicted_T=pred_T, predicted_limit=pred))
with open(OUT / "predictions.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
for r in rows:
    print(f"{r['workload']:<18}{r['machine']:<22}CP={r['critical_path']:<4} T_pred={r['predicted_T']:<4} limit={r['predicted_limit']}")
