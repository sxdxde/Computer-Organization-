"""Formatting + derived tables built purely from a simulation Result."""
from .simulator import RES_ORDER


def stall_runs(res):
    """Collapse consecutive allocation-stall cycles that share (resource, blocked uop, root cause)."""
    runs, cur = [], None
    for c in res.cycles:
        if not c.alloc_stalled:
            cur = None
            continue
        key = (c.stall_resource, "bw" if "bandwidth-bound" in c.stall_root else c.stall_root)
        if cur and cur["key"] == key and cur["end"] == c.cycle - 1:
            cur["end"] = c.cycle
            cur["rob_max"] = max(cur["rob_max"], c.rob_occ)
        else:
            cur = dict(key=key, start=c.cycle, end=c.cycle, resource=c.stall_resource, all=c.stall_all,
                       instr=c.stall_instr, reason=c.stall_reason, root=c.stall_root,
                       avail=c.stall_avail, rob_max=c.rob_occ)
            runs.append(cur)
    return runs


def fmt_dyn_table(res):
    hdr = (f"{'seq':>3} {'id':<4} {'instruction':<26} {'arch srcs -> phys srcs':<28} {'dst':<8} {'old':<5} "
           f"{'ROB':>3} {'dec':>3} {'alloc':>5} {'issue':>5} {'cmplt':>5} {'retire':>6} {'squash':>6} {'reclaim':>7}")
    out = [hdr, "-" * len(hdr)]
    for d in res.dyn:
        if d.alloc_c is None:
            continue
        srcs = ", ".join(f"{a}->{'ARF' if p is None else 'P' + str(p)}" for a, p in d.psrcs) or "-"
        dst = f"{d.st.dst}->P{d.pdst}" if d.pdst is not None else "-"
        old = ("-" if d.pdst is None else ("ARF" if d.pold is None else f"P{d.pold}"))
        f = lambda v: "-" if v is None else str(v)
        out.append(f"{d.seq:>3} {d.label:<4} {d.st.text:<26} {srcs:<28} {dst:<8} {old:<5} {f(d.rob_idx):>3} "
                   f"{f(d.decode_c):>3} {f(d.alloc_c):>5} {f(d.issue_c):>5} {f(d.complete_c):>5} "
                   f"{f(d.retire_c):>6} {f(d.squash_c):>6} {f(d.reclaim_c):>7}"
                   + ("  [WRONG-PATH]" if d.wrong_path else ""))
    return "\n".join(out)


def lifetimes(res):
    """One row per physical-register version (a value produced by one renamed write)."""
    rows = []
    for v in res.versions:
        readers = v["readers"]
        last_issue = max([r.issue_c for r in readers if r.issue_c is not None], default=None)
        last_retire = max([r.retire_c for r in readers if r.retire_c is not None], default=None)
        rows.append(dict(preg=f"P{v['preg']}", arch=v["arch"], writer=v["writer"],
                         alloc_c=v["alloc_c"], ready_c=v["ready_c"],
                         readers=" ".join(r.label for r in readers) or "-",
                         last_read_issue_c=last_issue, last_reader_retire_c=last_retire,
                         freed_c=v["free_c"], freed_by=v["free_reason"] or "still live (architectural state)",
                         lifetime=(None if v["free_c"] is None else v["free_c"] - v["alloc_c"]),
                         wrong_path=v["wrong_path"]))
    return rows


def fmt_lifetimes(res):
    rows = lifetimes(res)
    h = (f"{'preg':<5}{'arch':<5}{'writer':<7}{'alloc':>6}{'ready':>6}  {'readers':<18}{'lastRdIss':>9}"
         f"{'lastRdRet':>10}{'freed@':>7}{'life':>5}  freed by")
    out = [h, "-" * len(h)]
    f = lambda v: "-" if v is None else str(v)
    for r in rows:
        out.append(f"{r['preg']:<5}{r['arch']:<5}{r['writer']:<7}{f(r['alloc_c']):>6}{f(r['ready_c']):>6}  "
                   f"{r['readers']:<18}{f(r['last_read_issue_c']):>9}{f(r['last_reader_retire_c']):>10}"
                   f"{f(r['freed_c']):>7}{f(r['lifetime']):>5}  {r['freed_by']}")
    return "\n".join(out)


def fmt_arch_timeline(res, arch):
    """Evolution of one architectural register through its physical registers."""
    vs = [v for v in res.versions if v["arch"] == arch]
    out = [f"Evolution of {arch}:"]
    for v in vs:
        readers = ", ".join(f"{r.label}@issue{r.issue_c}" for r in v["readers"]) or "no readers"
        free = f"reclaimed @cycle {v['free_c']} ({v['free_reason']})" if v["free_c"] is not None else "still the architectural mapping"
        out.append(f"  {v['writer']:<4} renames {arch} -> P{v['preg']}  (alloc {v['alloc_c']}, ready {v['ready_c']}); "
                   f"read by: {readers}; {free}")
    return "\n".join(out)


def fmt_trace(res):
    c = res.cfg
    out = [f"=== {res.name} ===", f"Config: {c.short()}  decode={c.decode_width} alloc={c.alloc_width} "
           f"issue={c.issue_width} decodeQ={c.decode_queue}", ""]
    for r in res.cycles:
        out.append(f"Cycle {r.cycle}")
        out.append("-" * 78)
        for a in r.actions:
            out.append("  " + a)
        if r.decoded:
            out.append(f"  DECODE {r.decoded} uop(s) into decode queue")
        if r.fe_stalled:
            out.append(f"  FRONTEND STALL: {r.fe_reason}")
        if r.alloc_stalled:
            out.append(f"  >> alloc stall on {r.stall_all} at {r.stall_instr}: {r.stall_reason}")
            out.append(f"     avail: {r.stall_avail}")
            out.append(f"     root : {r.stall_root}")
        out.append(f"  STATE ROB {r.rob_occ}/{c.rob_size} (done-unretired {r.done_unretired}) | free pregs {r.free_pregs}/{c.prf_size} | "
                   f"IQ {r.iq_occ}/{c.iq_size} | LQ {r.lq_occ}/{c.lq_size} | SQ {r.sq_occ}/{c.sq_size} | "
                   f"CKPT {r.ckpt_used}/{c.ckpt_size} | DECQ {r.decodeq_occ}/{c.decode_queue}")
        out.append(f"  COUNT alloc={r.allocated} issue={r.issued} complete={r.completed} retire={r.retired} "
                   f"squash={r.squashed} | alloc_stalled={'YES(' + r.stall_resource + ')' if r.alloc_stalled else 'no'}")
        out.append("")
    out.append("ALLOCATION-STALL CAUSAL CHAINS (consecutive cycles with identical cause collapsed)")
    out.append("-" * 78)
    for s in stall_runs(res):
        rng = f"cycle {s['start']}" if s["start"] == s["end"] else f"cycles {s['start']}-{s['end']}"
        out.append(f"{rng}: {s['instr']} blocked on {s['all']}")
        out.append(f"    immediate resource : {s['resource']}   ({s['avail']})")
        out.append(f"    why unavailable    : {s['reason']}")
        out.append(f"    earlier event      : {s['root']}")
    if not stall_runs(res):
        out.append("(no allocation stalls)")
    if res.snapshots:
        out.append("")
        out.append("MACHINE-STATE SNAPSHOTS")
        out.append("=" * 78)
        for _, _, txt in res.snapshots:
            out.append(txt)
            out.append("")
    out += ["", "PER-INSTRUCTION TABLE", "=" * 78, fmt_dyn_table(res), "",
            "PHYSICAL-REGISTER VERSION TABLE", "=" * 78, fmt_lifetimes(res)]
    return "\n".join(out) + "\n"


def summarize(res, label=None):
    c = res.cfg
    cyc = res.cycles
    stalls = [r for r in cyc if r.alloc_stalled]
    by = {k: sum(1 for r in stalls if r.stall_resource == k) for k in RES_ORDER}
    first = stalls[0] if stalls else None
    retired = res.retired
    prf_used = [c.prf_size - r.free_pregs for r in cyc]
    return dict(
        run=res.name, config=c.short(), rob=c.rob_size, prf=c.prf_size, retire_width=c.retire_width,
        instrs_retired=len(retired), instrs_squashed=len(res.squashed), cycles=res.total_cycles,
        ipc=round(len(retired) / res.total_cycles, 3),
        first_stall_cycle=first.cycle if first else "", first_stall_resource=first.stall_resource if first else "none",
        first_stall_rob_occ=first.rob_occ if first else "",
        alloc_stall_cycles=len(stalls), **{f"stall_{k}": v for k, v in by.items()},
        fe_stall_cycles=sum(1 for r in cyc if r.fe_stalled),
        peak_rob=max(r.rob_occ for r in cyc), peak_prf_used=max(prf_used),
        min_free_pregs=min(r.free_pregs for r in cyc), peak_iq=max(r.iq_occ for r in cyc),
        peak_lq=max(r.lq_occ for r in cyc), peak_sq=max(r.sq_occ for r in cyc),
        peak_ckpt=max(r.ckpt_used for r in cyc), peak_done_unretired=max(r.done_unretired for r in cyc),
        retire_stall_note=label or "",
    )
