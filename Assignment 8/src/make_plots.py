import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from sched.config import CLASSES
from sched import analysis as A

COL = {"ALU": "#4c78a8", "IMUL": "#e45756", "FADD": "#72b7b2", "FMUL": "#54a24b", "LOAD": "#f58518",
       "STA": "#b279a2", "STD": "#9d755d", "BR": "#bab0ac"}
WARM = {"ALU": "#264653", "IMUL": "#e76f51", "FADD": "#2a9d8f", "FMUL": "#8ab17d", "LOAD": "#e9c46a",
        "STA": "#f4a261", "STD": "#6d597a", "BR": "#b5b5b5"}


def gantt(res, ax, pal, label_every=1):
    rows = []
    for u in res.uops:
        for p in u.parts:
            rows.append((u, p))
    for i, (u, p) in enumerate(rows):
        rdy = max(p.operand_ready_c() or 0, u.dispatch_c + 1)
        ax.barh(i, max(0, p.issue_c - rdy), left=rdy,
                color="none", edgecolor="black", hatch="////", linewidth=0.3, height=0.8)
        ax.barh(i, A.occ_len(res.cfg, p.cls), left=p.issue_c, color=pal[p.cls], height=0.8, edgecolor="white", linewidth=0.3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([A.plabel(u, p) for u, p in rows], fontsize=5)
    ax.invert_yaxis()
    ax.set_xlabel("cycle")
    h = [Patch(color=pal[c], label=c) for c in CLASSES] + [Patch(facecolor="none", edgecolor="black", hatch="////", label="ready, waiting")]
    ax.legend(handles=h, fontsize=6, ncol=3, loc="lower right")


def profile(res, ax, pal):
    t = [c.t for c in res.cycles]
    ax.step(t, [c.sched_occ for c in res.cycles], where="mid", label="scheduler occupied", color=pal[0], lw=2)
    ax.step(t, [c.ready_uops for c in res.cycles], where="mid", label="ready", color=pal[1], lw=1.5)
    ax.bar(t, [len(c.issued) for c in res.cycles], color=pal[2], alpha=0.6, label="issued")
    ax.plot(t, [len(c.unselected) for c in res.cycles], "x", color=pal[3], label="ready but unselected")
    ax.set_xlabel("cycle"); ax.legend(fontsize=7)


def make_plots(results, summary, attrib, R):
    P, S, D = R / "plots", R / "plots_sudarshan", R / "plots_deetya"
    base = results["base__A_orig"]
    S_by = {r["run"]: r for r in summary}
    # 01 profile + 02 gantt
    fig, ax = plt.subplots(figsize=(9, 3.6)); profile(base, ax, ["#1f4e79", "#c0392b", "#7fb3d5", "#7d3c98"])
    ax.set_title("Machine A, base workload: in flight vs ready vs issued"); fig.tight_layout(); fig.savefig(P / "01_base_cycle_profile.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 9)); gantt(base, ax, COL); ax.set_title("Execution timeline (hatched = ready but not yet issued)")
    fig.tight_layout(); fig.savefig(P / "02_base_gantt.png", dpi=150); plt.close(fig)
    # 03 class demand
    fig, ax = plt.subplots(figsize=(8, 3.6)); cnt = base.cls_count()
    vals = [cnt[c] * A.LATENCY[c] / base.cfg.units(c) for c in CLASSES]
    ax.bar(CLASSES, vals, color=[COL[c] for c in CLASSES]); ax.axhline(base.total, ls="--", c="k"); ax.text(0.02, base.total + 0.8, f"actual T = {base.total}", fontsize=8)
    ax.set_ylabel("unit-cycles demanded / units"); ax.set_title("Per-resource demand (cycles if perfectly spread)")
    fig.tight_layout(); fig.savefig(P / "03_class_demand.png", dpi=150); plt.close(fig)
    # 04 scheduler capacity
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, wl in zip(axs, ("base", "base_x4")):
        sz = [6, 12, 24, 48, 96]; T = [S_by[f"{wl}__sched{s}"]["cycles"] for s in sz]
        un = [S_by[f"{wl}__sched{s}"]["ready_unselected_total"] for s in sz]
        ax.plot(range(5), T, "o-", c="#1f4e79"); ax.set_xticks(range(5)); ax.set_xticklabels(sz); ax.set_xlabel("scheduler entries"); ax.set_ylabel("execution time (cycles)")
        a2 = ax.twinx(); a2.bar(range(5), un, alpha=0.25, color="#c0392b"); a2.set_ylabel("ready-but-unselected uop-cycles", color="#c0392b"); ax.set_title(wl)
    fig.tight_layout(); fig.savefig(P / "04_inv5_scheduler.png", dpi=150); plt.close(fig)
    # 05 issue/wake
    fig, ax = plt.subplots(figsize=(8, 3.4)); cfgs = ["issue2_wake2", "issue3_wake3", "issue4_wake4", "issue6_wake6"]
    for wl, c in (("base", "#1f4e79"), ("base_x4", "#c0392b")):
        ax.plot(cfgs, [S_by[f"{wl}__{k}"]["cycles"] for k in cfgs], "o-", c=c, label=wl)
    ax.set_ylabel("execution time"); ax.legend(); ax.set_title("Issue/wakeup width sweep")
    fig.tight_layout(); fig.savefig(P / "05_inv6_issue_wakeup.png", dpi=150); plt.close(fig)
    # 06 machines
    ms = ["A_orig", "B_sched48", "C_alu4", "D_imul2", "E_load3", "F_issue8", "G_load3_imul2", "H_load4", "J_loadpipe", "K_allpipe"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, wl in zip(axs, ("base", "base_x4")):
        v = [S_by[f"{wl}__{m}"]["cycles"] for m in ms]
        ax.bar(range(len(ms)), v, color=["#555"] + ["#1f4e79"] * (len(ms) - 1)); ax.set_xticks(range(len(ms))); ax.set_xticklabels([m.split("_")[0] for m in ms])
        for i, x in enumerate(v): ax.text(i, x + 0.5, str(x), ha="center", fontsize=7)
        ax.set_title(f"{wl}: execution time per machine"); ax.set_ylim(0, max(v) * 1.12)
    fig.tight_layout(); fig.savefig(P / "06_inv7_machines.png", dpi=150); plt.close(fig)
    # 07 inv4
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.6))
    for ax, k, pal in zip(axs, ("s", "d"), (COL, WARM)):
        for j, v in enumerate(("A", "B")):
            r = results[f"{k}_inv4_{v}__A_orig"]; ax.plot([c.t for c in r.cycles], [c.ready_uops for c in r.cycles], label=f"{v}: ready", lw=2)
            ax.plot([c.t for c in r.cycles], [c.sched_occ for c in r.cycles], "--", label=f"{v}: scheduler occ")
        ax.legend(fontsize=7); ax.set_xlabel("cycle"); ax.set_title(f"{k.upper()} kernel: A (dependent) vs B (independent)")
    fig.tight_layout(); fig.savefig(P / "07_inv4_dependency.png", dpi=150); plt.close(fig)

    # ---- Sudarshan: crime-scene resource board at cycle 4 + proposal / counterexample bars
    fig, ax = plt.subplots(figsize=(8, 3.4)); c4 = results["base__A_orig"]
    t = 4; cfg = c4.cfg; names = []; used = []; free = []
    for cl in CLASSES:
        n = cfg.units(cl); b = A.unit_state(c4, cl, t)[1]; names.append(cl); used.append(b); free.append(n - b)
    ax.bar(names, used, color="#c0392b", label="busy"); ax.bar(names, free, bottom=used, color="#d5dbdb", label="idle")
    ax.set_title("Cycle 4: unit state (LOAD and IMUL full, ALU idle while loads wait)"); ax.legend(); ax.set_ylabel("units")
    fig.tight_layout(); fig.savefig(S / "s1_cycle4_unit_state.png", dpi=150); plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.6))
    for ax, wl, ms2, ttl in ((axs[0], "base_x4", ["A_orig", "E_load3", "G_load3_imul2"], "base x4 (load-bound)"),
                              (axs[1], "s_counterexample", ["A_orig", "E_load3", "D_imul2", "G_load3_imul2"], "IMUL-bound counterexample")):
        v = [S_by[f"{wl}__{m}"]["cycles"] for m in ms2]; ax.bar([m.split("_")[0] + "\n" + "_".join(m.split("_")[1:]) for m in ms2], v, color=["#555", "#1f4e79", "#2e86c1", "#85c1e9"][:len(v)])
        for i, x in enumerate(v): ax.text(i, x + .5, str(x), ha="center")
        ax.set_title(ttl); ax.set_ylabel("cycles")
    fig.tight_layout(); fig.savefig(S / "s2_proposal_vs_counterexample.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.2)); r = results["s_counterexample__E_load3"]; gantt(r, ax, COL); ax.set_title("Counterexample on Machine E (3 LOAD): IMULs serialise on the one multiplier")
    fig.tight_layout(); fig.savefig(S / "s3_counterexample_gantt.png", dpi=150); plt.close(fig)

    # ---- Deetya: busy-unit heatmap, pipelined-load comparison, pointer chase timeline
    import numpy as np
    fig, ax = plt.subplots(figsize=(10, 3.2))
    mat = np.array([[A.unit_state(base, cl, c.t)[1] / min(base.cfg.units(cl), 64) for c in base.cycles] for cl in CLASSES])
    im = ax.imshow(mat, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1); ax.set_yticks(range(len(CLASSES))); ax.set_yticklabels(CLASSES)
    ax.set_xlabel("cycle"); ax.set_title("Fraction of units busy per class and cycle (Machine A, base)"); fig.colorbar(im, ax=ax, label="busy fraction")
    fig.tight_layout(); fig.savefig(D / "d1_busy_heatmap.png", dpi=150); plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.6))
    ms3 = ["A_orig", "J_loadpipe", "E_load3", "H_load4"]
    v = [S_by[f"base_x4__{m}"]["cycles"] for m in ms3]; axs[0].barh(ms3, v, color=["#264653", "#e76f51", "#e9c46a", "#8ab17d"])
    for i, x in enumerate(v): axs[0].text(x + 1, i, str(x), va="center")
    axs[0].set_title("base x4: Load/AGU options"); axs[0].set_xlabel("cycles")
    ms4 = ["A_orig", "J_loadpipe", "E_load3", "D_imul2"]
    v = [S_by[f"d_counterexample__{m}"]["cycles"] for m in ms4]; axs[1].barh(ms4, v, color="#6d597a")
    for i, x in enumerate(v): axs[1].text(x + .5, i, str(x), va="center")
    axs[1].set_title("pointer-chase counterexample"); axs[1].set_xlabel("cycles")
    fig.tight_layout(); fig.savefig(D / "d2_proposal_vs_chase.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.2)); gantt(results["d_counterexample__J_loadpipe"], ax, WARM); ax.set_title("Pointer chase with pipelined Load/AGU: each load still waits for its predecessor")
    fig.tight_layout(); fig.savefig(D / "d3_chase_gantt.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.4)); b17 = results["base__A_orig"]
    c = b17.cycles[17]; labs = ["ready parts", "selected", "issued", "ready-unselected"]; vals = [len(c.ready_parts), len(c.selected), len(c.issued), len(c.unselected)]
    ax.bar(labs, vals, color=["#264653", "#2a9d8f", "#e9c46a", "#e76f51"]); ax.set_title("Cycle 17 funnel: ready -> selected -> issued")
    fig.tight_layout(); fig.savefig(D / "d4_cycle17_funnel.png", dpi=150); plt.close(fig)
