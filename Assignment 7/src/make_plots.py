"""Simple matplotlib summaries (no fancy dependencies)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

C = {"ROB": "#1f77b4", "PRF": "#d62728", "IQ": "#2ca02c", "LQ": "#9467bd", "SQ": "#8c564b", "CKPT": "#ff7f0e"}


def _series(res, f):
    return [f(r) for r in res.cycles], [r.cycle for r in res.cycles]


def _shade(ax, res):
    for r in res.cycles:
        if r.alloc_stalled:
            ax.axvspan(r.cycle - .5, r.cycle + .5, color=C[r.stall_resource], alpha=.12, lw=0)


def make_plots(R, grid, out):
    # 1. long-latency timeline
    res = R["inv3_longlat"]
    fig, ax = plt.subplots(figsize=(9, 5))
    y, x = _series(res, lambda r: r.rob_occ); ax.plot(x, y, label="ROB occupancy", color=C["ROB"], lw=2)
    y, _ = _series(res, lambda r: r.done_unretired); ax.plot(x, y, "--", label="completed but unretired", color="gray")
    y, _ = _series(res, lambda r: res.cfg.prf_size - r.free_pregs); ax.plot(x, y, label="physical regs in use", color=C["PRF"])
    y, _ = _series(res, lambda r: r.iq_occ); ax.plot(x, y, label="IQ occupancy", color=C["IQ"])
    _shade(ax, res)
    ax.axvline(22, color="k", ls=":"); ax.text(22.3, 1, "I0 LOAD completes", fontsize=8)
    ax.axhline(24, color=C["ROB"], ls=":", lw=1)
    ax.set_xlabel("cycle"); ax.set_ylabel("entries")
    ax.set_title("Inv 3: long-latency load at the ROB head (shaded = allocation stalled on ROB)")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(out / "01_inv3_longlat_timeline.png", dpi=150); plt.close(fig)

    # 2. ROB headroom when allocation stalls on something else
    cases = [("inv2a_loads_LQ", "LOAD x10\n(LQ=6)"), ("inv2b_stores_SQ", "STORE x8\n(SQ=4)"),
             ("inv2c_dependents_IQ", "LOAD + dependents\n(IQ=12)"), ("final_ckpt", "load-dependent\nbranches (CKPT=2)")]
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (n, lab) in enumerate(cases):
        r = R[n]; f = next(c for c in r.cycles if c.alloc_stalled)
        ax.bar(i, r.cfg.rob_size, color="#dddddd", edgecolor="k")
        ax.bar(i, f.rob_occ, color=C[f.stall_resource], edgecolor="k")
        ax.text(i, f.rob_occ + .4, f"{f.rob_occ}/{r.cfg.rob_size} used\nstall: {f.stall_resource}", ha="center", fontsize=8)
    ax.set_xticks(range(len(cases))); ax.set_xticklabels([c[1] for c in cases], fontsize=8)
    ax.set_ylabel("ROB entries"); ax.set_title("Inv 2/Final: ROB has free entries at the first allocation stall")
    fig.tight_layout(); fig.savefig(out / "02_rob_headroom_at_stall.png", dpi=150); plt.close(fig)

    # 3. retirement width
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
    for ax, (w, title) in zip(axs, [("longlat", "long-latency load workload"), ("indep", "independent-ALU workload")]):
        for rw, col in ((4, "tab:blue"), (2, "tab:red")):
            res = R[f"inv4_{w}_ret{rw}"]
            y, x = _series(res, lambda r: r.rob_occ); ax.plot(x, y, color=col, lw=2, label=f"ROB occ, retire={rw}")
            y, _ = _series(res, lambda r: r.done_unretired); ax.plot(x, y, color=col, ls="--", label=f"completed-unretired, retire={rw}")
        ax.set_title(title); ax.set_xlabel("cycle"); ax.legend(fontsize=7)
    axs[0].set_ylabel("entries"); fig.suptitle("Inv 4: retirement width 4 vs 2")
    fig.tight_layout(); fig.savefig(out / "03_inv4_retire_width.png", dpi=150); plt.close(fig)

    # 4. grid
    robs = sorted({g["rob"] for g in grid}); prfs = sorted({g["prf"] for g in grid})
    fig, ax = plt.subplots(figsize=(8, 4))
    m = np.array([[next(g for g in grid if g["rob"] == a and g["prf"] == b)["cycles"] for b in prfs] for a in robs])
    ax.imshow(m, cmap="YlOrRd", vmin=45, vmax=75, aspect="auto")
    for i, a in enumerate(robs):
        for j, b in enumerate(prfs):
            g = next(g for g in grid if g["rob"] == a and g["prf"] == b)
            ax.text(j, i, f"{g['cycles']} cyc\n1st: {g['first_stall_resource']}\nmain: {g['dominant']}", ha="center", va="center", fontsize=7)
    ax.set_xticks(range(len(prfs))); ax.set_xticklabels(prfs); ax.set_yticks(range(len(robs))); ax.set_yticklabels(robs)
    ax.set_xlabel("physical registers"); ax.set_ylabel("ROB entries")
    ax.set_title("Inv 5: total cycles and limiting resource (long-latency workload)")
    fig.tight_layout(); fig.savefig(out / "04_inv5_bottleneck_grid.png", dpi=150); plt.close(fig)

    # 5. preg lifetimes
    fig, axs = plt.subplots(1, 2, figsize=(12, 3.8), sharex=True)
    for ax, n in zip(axs, ["inv6a_short_lifetime", "inv6b_long_lifetime"]):
        res = R[n]; end = res.total_cycles
        for k, v in enumerate(res.versions):
            f = v["free_c"] if v["free_c"] is not None else end
            ax.barh(k, f - v["alloc_c"], left=v["alloc_c"], color="tab:red" if v["arch"] == "R1" else "tab:gray", edgecolor="k")
            ax.text(v["alloc_c"] + .1, k, f"P{v['preg']} ({v['arch']}, {v['writer']})", va="center", fontsize=8, color="w")
        ax.set_yticks([]); ax.set_xlabel("cycle"); ax.set_title(n)
    fig.suptitle("Inv 6: physical-register lifetimes (alloc -> reclaim; open-ended = architectural state)")
    fig.tight_layout(); fig.savefig(out / "05_inv6_preg_lifetimes.png", dpi=150); plt.close(fig)

    # 6. recovery
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for n, col in (("inv7_mispredict", "tab:red"), ("inv7_correct", "tab:green")):
        res = R[n]
        y, x = _series(res, lambda r: r.rob_occ); ax.plot(x, y, color=col, lw=2, marker="o", label=f"{n}: ROB occ")
        y, _ = _series(res, lambda r: res.cfg.prf_size - r.free_pregs); ax.plot(x, y, color=col, ls="--", label=f"{n}: pregs in use")
    sq = [r.cycle for r in R["inv7_mispredict"].cycles if r.squashed]
    for c in sq: ax.axvline(c, color="k", ls=":"); ax.text(c + .1, 1, "squash+recover", fontsize=8)
    ax.set_xlabel("cycle"); ax.set_ylabel("entries"); ax.legend(fontsize=7); ax.set_title("Inv 7: wrong-path state appears, is squashed, and the correct path refills")
    fig.tight_layout(); fig.savefig(out / "06_inv7_recovery.png", dpi=150); plt.close(fig)

    # 7. final: checkpoints
    res = R["final_ckpt"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for lab, f, col in (("ROB occupancy", lambda r: r.rob_occ, C["ROB"]), ("checkpoints used", lambda r: r.ckpt_used, C["CKPT"]),
                        ("physical regs in use", lambda r: res.cfg.prf_size - r.free_pregs, C["PRF"]), ("IQ occupancy", lambda r: r.iq_occ, C["IQ"])):
        y, x = _series(res, f); ax.plot(x, y, label=lab, color=col, lw=2)
    _shade(ax, res); ax.axvline(22, color="k", ls=":"); ax.text(22.3, 10, "I0 LOAD completes", fontsize=8)
    ax.set_xlabel("cycle"); ax.set_ylabel("entries"); ax.legend(fontsize=8)
    ax.set_title("Final: load-dependent branches exhaust checkpoints (shaded = CKPT stall)")
    fig.tight_layout(); fig.savefig(out / "07_final_ckpt.png", dpi=150); plt.close(fig)

    # 8. rename pressure
    res = R["inv1b_rename_x5"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    y, x = _series(res, lambda r: res.cfg.prf_size - r.free_pregs); ax.plot(x, y, color=C["PRF"], lw=2, label="physical regs in use")
    y, _ = _series(res, lambda r: r.rob_occ); ax.plot(x, y, color=C["ROB"], label="ROB occupancy")
    n_arch = len({d.st.dst for d in res.dyn if d.st.dst})
    ax.axhline(n_arch, color="k", ls="--", label=f"architectural registers written ({n_arch})")
    _shade(ax, res); ax.set_xlabel("cycle"); ax.set_ylabel("entries"); ax.legend(fontsize=8)
    ax.set_title("Inv 1: repeated renaming of 5 arch regs needs far more physical regs")
    fig.tight_layout(); fig.savefig(out / "08_inv1_rename_pressure.png", dpi=150); plt.close(fig)
