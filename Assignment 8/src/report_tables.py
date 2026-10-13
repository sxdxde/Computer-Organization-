#!/usr/bin/env python3
"""Turns results/*.csv into markdown table fragments (results/tables/*.md) that the reports include verbatim."""
import csv
from pathlib import Path

R = Path(__file__).resolve().parent.parent / "results"
T = R / "tables"
T.mkdir(exist_ok=True)
S = {r["run"]: r for r in csv.DictReader(open(R / "summary.csv"))}
AT = {r["run"]: r for r in csv.DictReader(open(R / "bottleneck_attribution.csv"))}
CY = {}
for r in csv.DictReader(open(R / "per_cycle.csv")):
    CY.setdefault(r["run"], []).append(r)


def md(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def sh(x):
    for a, b in (("dataflow (critical path)", "dataflow"), ("co-limited: ", "mix: "), ("scheduler capacity", "window"), ("LOAD/AGU", "LOAD"),
                 ("wakeup bandwidth", "wake"), ("issue width", "issue"), (" + ", ", ")):
        x = x.replace(a, b)
    return x


def wlab(x):
    return {"base": "1x", "base_x4": "x4"}.get(x, x)


def w(name, text):
    (T / f"{name}.md").write_text(text)


# per-cycle table
rows = []
for r in CY["base__A_orig"]:
    rows.append([r["cycle"], r["sched_occ"], r["waiting"], r["ready"], r["selected"], r["issued"], r["ready_unselected"],
                 r["issued_uops"] or "-", f"{r['busy_ALU']}/{r['busy_IMUL']}/{r['busy_FADD']}/{r['busy_FMUL']}/{r['busy_LOAD']}"])
w("percycle", md(["cyc", "occ", "wait", "rdy", "sel", "iss", "lost", "issued", "busy"], rows))

dem = list(csv.DictReader(open(R / "inv3_class_demand.csv")))
w("demand", md(["resource", "uops", "units", "lat", "unit-cycles demanded", "cycles if perfectly spread"],
               [[d["resource"], d["parts"], d["units"], d["latency"], d["unit_cycles_demanded"], d["min_cycles_if_perfectly_spread"]] for d in dem]))


def cmp_rows(a, b, keys):
    return [[lab, S[a][k], S[b][k]] for lab, k in keys]


KEYS4 = [("execution time (cycles)", "cycles"), ("avg scheduler occupancy", "avg_sched"), ("peak scheduler occupancy", "peak_sched"),
         ("avg ready uops / cycle", "avg_ready"), ("peak ready uops", "peak_ready"), ("issue rate (uops/cycle, active)", "issue_rate_active"),
         ("IPC (uops / T)", "ipc"), ("cycles with entries but 0 ready", "starved_cycles"), ("ready-but-unselected uop-cycles", "ready_unselected_total"),
         ("ALU util", "util_ALU"), ("IMUL util", "util_IMUL"), ("FADD util", "util_FADD"), ("FMUL util", "util_FMUL"), ("LOAD util", "util_LOAD")]
for k in ("s", "d"):
    w(f"inv4_{k}", md(["metric", "Version A (dependent)", "Version B (independent)"], cmp_rows(f"{k}_inv4_A__A_orig", f"{k}_inv4_B__A_orig", KEYS4)))

# inv5
rows = []
for wl in ("base", "base_x4"):
    for s in (6, 12, 24, 48, 96):
        r = S[f"{wl}__sched{s}"]
        rows.append([wlab(wl), s, r["cycles"], r["avg_sched"], r["peak_sched"], r["dispatch_blocked_cycles"], r["avg_ready"], r["peak_ready"],
                     r["ready_unselected_total"], r["issue_rate_active"], r["util_LOAD"], r["util_IMUL"], sh(AT[f"{wl}__sched{s}"]["bottleneck"])])
w("inv5", md(["wl", "sched", "T", "avg occ", "peak occ", "disp-blocked", "avg rdy", "peak rdy", "lost", "issue rate", "LOAD util", "IMUL util", "limiter"], rows))

# inv6
rows = []
for wl in ("base", "base_x4"):
    for k in ("issue2_wake2", "issue3_wake3", "issue3_wake6", "issue6_wake3", "issue4_wake4", "issue6_wake6"):
        r = S[f"{wl}__{k}"]
        rows.append([wlab(wl), k.replace("issue", "I").replace("_wake", "/W"), r["cycles"], r["issue_rate_active"], r["avg_ready"], r["width_trim_events"], r["wake_deferred"],
                     r["ready_unselected_total"], r["util_LOAD"], sh(AT[f"{wl}__{k}"]["bottleneck"])])
w("inv6", md(["wl", "issue/wake", "T", "issue rate", "avg rdy", "sel-not-issued", "wakes deferred", "lost", "LOAD util", "limiter"], rows))

# inv7
ms = ["A_orig", "B_sched48", "C_alu4", "D_imul2", "E_load3", "F_issue8", "G_load3_imul2", "H_load4", "I_load3_imul2_fmul3", "J_loadpipe", "K_allpipe"]
P = {(r["workload"], r["machine"]): r for r in csv.DictReader(open(R / "predictions.csv"))}
rows = []
for m in ms:
    a, b = S[f"base__{m}"], S[f"base_x4__{m}"]
    p = P[("base_x4", m)]
    g = AT[f"base_x4__{m}"]
    gains = ", ".join(sh(f"{k[5:]}") + f" -{v}" for k, v in g.items() if k.startswith("gain_") and int(v) > 0) or "none"
    rows.append([m.replace('_', ' '), a["cycles"], b["cycles"], p["predicted_T"], p["predicted_limit"], sh(g["bottleneck"]), gains])
w("inv7", md(["machine", "T 1x", "T x4", "pred. T x4", "pred. limiter", "actual limiter", "gain if relaxed (x4)"], rows))

# counterexamples
rows = []
for k in ("s_counterexample", "d_counterexample"):
    for m in ("A_orig", "E_load3", "J_loadpipe", "D_imul2", "G_load3_imul2"):
        r = S[f"{k}__{m}"]
        rows.append([k, m, r["cycles"], r["util_LOAD"], r["util_IMUL"], r["ready_unselected_total"], r["avg_ready"], sh(AT[f"{k}__{m}"]["bottleneck"])])
w("counterexample", md(["workload", "machine", "T", "LOAD util", "IMUL util", "ready-unsel", "avg ready", "limiter"], rows))

for key, k in (("counterexample_s", "s_counterexample"), ("counterexample_d", "d_counterexample")):
    rows = []
    for m in ("A_orig", "E_load3", "J_loadpipe", "D_imul2", "G_load3_imul2"):
        r = S[f"{k}__{m}"]
        rows.append([m.replace("_", " "), r["cycles"], r["util_LOAD"], r["util_IMUL"], r["ready_unselected_total"], r["avg_ready"], sh(AT[f"{k}__{m}"]["bottleneck"])])
    w(key, md(["machine", "T", "LOAD util", "IMUL util", "lost", "avg rdy", "limiter"], rows))

# static prediction table
rows = []
for (wl, m), p in P.items():
    if wl in ("base", "base_x4") and m in ("A_orig", "E_load3"):
        rows.append([wlab(wl), m.replace("_", " "), p["critical_path"], p["bound_LOAD"], p["bound_IMUL"], p["bound_FMUL"], p["bound_FADD"], p["bound_ALU"], p["predicted_T"], p["predicted_limit"], S[f"{wl}__{m}"]["cycles"]])
w("bounds", md(["wl", "machine", "crit. path", "LOAD", "IMUL", "FMUL", "FADD", "ALU", "pred. T", "pred. limiter", "sim. T"], rows))

# stranded capacity
rows = [[wlab(wl), S[f"{wl}__A_orig"]["stranded_cycles"], S[f"{wl}__A_orig"]["stranded_idle_unit_slots"], S[f"{wl}__A_orig"]["ready_unselected_total"], S[f"{wl}__A_orig"]["multi_ready_cycles"]] for wl in ("base", "base_x4")]
w("stranded", md(["wl", "cycles with idle units elsewhere while a ready uop waited", "idle unit-slots", "lost uop-cycles", "cycles with >=2 ready"], rows))
# pipelined sensitivity
w("pipelined", md(["machine", "T 1x", "T x4", "lost (x4)"], [[m.replace("_", " "), S[f"base__{m}"]["cycles"], S[f"base_x4__{m}"]["cycles"], S[f"base_x4__{m}"]["ready_unselected_total"]] for m in ("A_orig", "J_loadpipe", "K_allpipe")]))
print("tables written:", sorted(p.name for p in T.glob("*.md")))

# dependency chains (Investigation 1)
import re
ch = {}
for r in csv.DictReader(open(R / "inv1_chains.csv")):
    ch.setdefault(r["chain"], []).append(r)
names = {"FP chain": "chain_fp", "integer address -> multiply chain": "chain_int", "second address chain (R43/R49/R51)": "chain_addr2"}
for cname, key in names.items():
    rows = []
    for r in ch[cname]:
        why = "-"
        if int(r["delay"]) > 0:
            holders = sorted(set(re.findall(r"U\d\d", r["delay_cause"].split("-", 1)[1] if "-" in r["delay_cause"] else r["delay_cause"])))
            res = "LOAD" if "LOAD" in r["delay_cause"] else "IMUL"
            why = f"{res} unit(s) occupied by {', '.join(holders)}"
        rows.append([r["uop"], r["text"], r["eligible_c"], r["eligible_because"], r["issue_c"], r["complete_c"], r["delay"], why])
    w(key, md(["uop", "instruction", "eligible (operand-ready) c", "because", "issue c", "complete c", "wait", "why it waited"], rows))
print("chain tables done")
