"""Figures for EXP-10. Run after exp10.py:  python3 src/make_plots.py"""
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp10 as X  # noqa: E402

OUT = X.RES / "plots"
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2de"
CATCOL = {"FA": "#2a78d6", "MUL": "#eb6834", "FMA": "#1baf7a", "SHUF": "#e87ba4"}
CATNAME = {"FA": "Fast Adder (vaddps)", "MUL": "MUL (vmulps)", "FMA": "FMA (vfmadd231ps)",
           "SHUF": "Shuffle (vshufps)"}
CROSS = "#6250d6"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.edgecolor": GRID, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
})


def cat_legend(ax, cats, **kw):
    ax.legend(handles=[Patch(color=CATCOL[c], label=CATNAME[c]) for c in cats],
              frameon=False, ncol=len(cats), fontsize=8, **kw)


# ---------------------------------------------------------------- Fig 1: A and B
def fig_AB():
    fig, axes = plt.subplots(2, 1, figsize=(9, 7.2), sharex=True)
    for ax, s in zip(axes, "AB"):
        ins = X.parse(s)
        t = X.asap(ins, "M1")
        for i in ins:
            y = len(ins) - 1 - i.idx
            ax.barh(y, i.uop_lat, left=t[i.idx], height=0.62, color=CATCOL[i.cat])
            ax.text(t[i.idx] + i.uop_lat / 2, y, f"{i.uop_lat}", ha="center", va="center",
                    color="white" if i.cat != "SHUF" else INK, fontsize=8, fontweight="bold")
            for p_idx, _, _ in i.deps:
                p = ins[p_idx]
                b = X.bypass(p.cat, i.cat)
                if b > 0:
                    ax.barh(y, b, left=t[i.idx] - b, height=0.62, color="none", edgecolor=INK,
                            hatch="////", linewidth=0.8)
                    ax.text(t[i.idx] - b / 2, y + 0.5, f"+{b}", ha="center", va="bottom",
                            fontsize=7.5, color=INK)
        ax.set_yticks(range(len(ins)))
        ax.set_yticklabels([f"{i.id}  {i.mnem} {i.dst}" for i in reversed(ins)], fontsize=8)
        end = X.finish(ins, t, "M1")
        ax.axvline(end, color=INK2, lw=0.8, ls=":")
        ax.text(end + 0.3, len(ins) - 0.6, f"last result at cycle {end}", fontsize=8, color=INK2, va="top")
        ax.set_title(f"Stream {s}: earliest feasible schedule, unlimited ports (model M1)",
                     loc="left", fontsize=10, color=INK)
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
    axes[1].set_xlabel("cycle  (bar = producer uop latency; hatched = Table 2-5 bypass delay, +1)")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    cat_legend(fig, ["FA", "FMA", "MUL", "SHUF"], loc="lower center")
    fig.savefig(OUT / "01_AB_schedule.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- helpers for graphs
def node(ax, x, y, ins, w=0.8, h=0.62, label=None):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=CATCOL[ins.cat], ec="none", alpha=0.95, zorder=3))
    txt = label or f"{ins.id}\n{ins.mnem.replace('vfmadd231ps', 'vfmadd')}\n{ins.dst}"
    ax.text(x, y, txt, ha="center", va="center", fontsize=7.2, zorder=4,
            color=INK if ins.cat == "SHUF" else "white", fontweight="bold", linespacing=1.05)


def arrow(ax, p0, p1, color=INK2, ls="-", rad=0.0, lw=1.1, z=2):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=9, color=color, ls=ls,
                                 lw=lw, connectionstyle=f"arc3,rad={rad}", zorder=z, shrinkA=0, shrinkB=0))


# ---------------------------------------------------------------- Fig 2: Stream C graph
def fig_C():
    ins = X.parse("C")
    pos = {}
    rowy = {"C1": 2.0, "C2 ": 0.0}
    ycoord = {"C1": 2.2, "C2": 0.9, "C3": -0.4}
    cnt = {"C1": 0, "C2": 0, "C3": 0}
    xs3 = [0, 1, 2, 4]
    for i in ins:
        k = cnt[i.group]
        cnt[i.group] += 1
        x = xs3[k] if i.group == "C3" else k
        pos[i.idx] = (x * 1.35, ycoord[i.group])
    fig, ax = plt.subplots(figsize=(10, 4.9))
    ax.set_xlim(-1.55, 7.6)
    ax.set_ylim(-1.15, 3.0)
    ax.axis("off")
    # edges first
    for c in ins:
        for p_idx, reg, _ in c.deps:
            p = ins[p_idx]
            (x0, y0), (x1, y1) = pos[p_idx], pos[c.idx]
            if p.group == c.group:
                arrow(ax, (x0 + 0.42, y0), (x1 - 0.42, y1))
                b = X.bypass(p.cat, c.cat)
                if b:
                    ax.text((x0 + x1) / 2, y0 + 0.2, f"+{b}", ha="center", fontsize=7.5, color=INK)
            elif y0 - y1 < 1.5:     # adjacent rows
                arrow(ax, (x0, y0 - 0.33), (x1, y1 + 0.33), CROSS, "--", lw=1.3)
            else:                   # C1 -> C3 skips a row: bow out to the right
                arrow(ax, (x0 + 0.4, y0 - 0.2), (x1 + 0.4, y1 + 0.2), CROSS, "--", rad=-0.3, lw=1.3)
    for i in ins:
        node(ax, *pos[i.idx], i)
    for g, lab in (("C1", "Chain 1"), ("C2", "Chain 2"), ("C3", "Group C3")):
        ax.text(-1.5, ycoord[g], lab, ha="left", va="center", fontsize=9, color=INK, fontweight="bold")
    summ = {}
    X.stream_C(summ)
    ax.text(-1.5, ycoord["C1"] - 0.45, f"alone: {summ['C_chain_alone_asap']['C1']} cyc", fontsize=8, color=INK2)
    ax.text(-1.5, ycoord["C2"] - 0.45, f"alone: {summ['C_chain_alone_asap']['C2']} cyc", fontsize=8, color=INK2)
    ax.text(-1.5, ycoord["C3"] - 0.45, f"alone: {summ['C_chain_alone_asap']['C3']} cyc", fontsize=8, color=INK2)
    ax.legend(handles=[plt.Line2D([], [], color=INK2, lw=1.2, label="true RAW inside a chain"),
                       plt.Line2D([], [], color=CROSS, lw=1.3, ls="--", label="true RAW between chains (found from the register operands)")] +
              [Patch(color=CATCOL[c], label=CATNAME[c]) for c in ("FA", "FMA", "MUL", "SHUF")],
              frameon=False, ncol=3, fontsize=7.8, loc="upper center", bbox_to_anchor=(0.5, 1.07))
    fig.tight_layout()
    fig.savefig(OUT / "02_C_dependency_graph.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- Fig 3: D graph
def fig_D_graph():
    ins = X.parse("D")
    fig, ax = plt.subplots(figsize=(10, 2.9))
    ax.set_xlim(-0.7, 10.0)
    ax.set_ylim(-0.6, 2.4)
    ax.axis("off")
    pos = {i.idx: ((i.idx % 10) * 1.0, 1.3 if i.idx < 10 else -0.1) for i in ins}
    for k in range(1, len(ins)):
        p, c = ins[k - 1], ins[k]
        b = X.bypass(p.cat, c.cat)
        (x0, y0), (x1, y1) = pos[k - 1], pos[k]
        lab = f"{p.uop_lat}+{b}" if b >= 0 else f"{p.uop_lat}{b}"
        if y0 == y1:
            arrow(ax, (x0 + 0.4, y0), (x1 - 0.4, y1), lw=1.2)
            ax.text((x0 + x1) / 2, y0 + 0.43, lab, ha="center", fontsize=7.6,
                    color=INK, fontweight="bold" if b else "normal")
        else:  # wrap from end of row 1 to start of row 2
            arrow(ax, (x0, y0 - 0.33), (x1, y1 + 0.33), rad=0.0, lw=1.2)
            ax.text(4.5, (y0 + y1) / 2, f"{lab}  (node 9 -> node 10, carried through ymm0)", ha="center",
                    va="center", fontsize=7.6, color=INK2, zorder=5,
                    bbox=dict(fc=SURF, ec="none", pad=2))
    for i in ins:
        node(ax, *pos[i.idx], i, w=0.78, h=0.6, label=f"{i.idx}\n{ {'FA':'add','FMA':'fma','MUL':'mul','SHUF':'shuf'}[i.cat]}")
    ax.text(-0.65, 2.35, "edge label = producer uop latency + Table 2-5 bypass  (issue-to-issue cycles)",
            fontsize=8, color=INK2, va="top")
    fig.tight_layout()
    fig.savefig(OUT / "03_D_dependency_graph.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- Fig 4: D staircase
def fig_D_schedule():
    ins = X.parse("D")
    t = X.asap(ins, "M1")
    fig, ax = plt.subplots(figsize=(9, 5.6))
    for i in ins:
        y = len(ins) - 1 - i.idx
        ax.barh(y, i.uop_lat, left=t[i.idx], height=0.62, color=CATCOL[i.cat])
        if i.idx:
            b = X.bypass(ins[i.idx - 1].cat, i.cat)
            if b > 0:
                ax.barh(y, b, left=t[i.idx] - b, height=0.62, color="none", edgecolor=INK, hatch="////", lw=0.8)
    ax.set_yticks(range(len(ins)))
    ax.set_yticklabels([f"{i.idx:>2}  {i.mnem} ymm0" for i in reversed(ins)], fontsize=7.5)
    end = X.finish(ins, t, "M1")
    ax.axvline(end, color=INK2, lw=0.8, ls=":")
    ax.text(end - 0.5, len(ins) - 0.5, f"{end} cycles for 20 instructions\n(3.75 cyc/instr, 0.27 IPC)",
            ha="right", va="top", fontsize=8.5, color=INK)
    ax.set_xlabel("cycle  (only one uop is ever in flight; hatched = +1 bypass on add -> mul)")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Stream D: earliest feasible schedule (model M1)", loc="left", fontsize=10)
    ax.legend(handles=[Patch(color=CATCOL[c], label=CATNAME[c]) for c in ("FA", "FMA", "MUL")],
              frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0.02, 0.06))
    fig.tight_layout()
    fig.savefig(OUT / "04_D_schedule.png", dpi=170)
    plt.close(fig)


# ---------------------------------------------------------------- Fig 5: independent chains
def fig_ipc():
    rows = list(csv.DictReader(open(X.RES / "ipc_vs_chains.csv")))
    k = [int(r["independent_chains"]) for r in rows]
    v = [float(r["uops_per_cycle"]) for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(k, v, color=CATCOL["FA"], lw=2, marker="o", ms=5)
    ax.axhline(3.0, color=INK2, lw=0.9, ls="--")
    ax.text(24, 3.04, "port limit: 3 vector ports (p0, p1, p5) = 3 uops/cycle", ha="right", va="bottom",
            fontsize=8, color=INK2)
    ax.axvline(75 / (20 / 3), color=INK2, lw=0.9, ls=":")
    ax.text(75 / (20 / 3) + 0.3, 0.35, "k* = 75 / 6.67 = 11.25\n(chain period / port-bound time)",
            fontsize=8, color=INK2, va="bottom")
    ax.annotate(f"k = 1: {v[0]:.2f}\n(the D recurrence)", (k[0], v[0]), xytext=(3.4, 0.18),
                fontsize=8, color=INK, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_xlabel("independent copies of the D recurrence, interleaved in program order")
    ax.set_ylabel("vector uops per cycle")
    ax.set_ylim(0, 3.4)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "05_ipc_vs_independent_chains.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_AB()
    fig_C()
    fig_D_graph()
    fig_D_schedule()
    fig_ipc()
    print("ok")
