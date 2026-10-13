"""Metrics, traces, dependency-chain explanations, ready-but-unselected cases and the 'crime scene' freezer."""
from .config import CLASSES, LATENCY, Machine, INF
from .simulator import simulate

SHOW = lambda n: "inf" if n >= INF else str(n)


def occ_len(cfg, cls):
    return 1 if cls in cfg.pipelined else LATENCY[cls]


def parts_of(res):
    for u in res.uops:
        for p in u.parts:
            yield u, p


def plabel(u, p):
    return u.name + (("." + p.cls) if len(u.parts) > 1 else "")


def unit_state(res, cls, t):
    """(free before select at t, busy after issue at t) for a resource class."""
    n, occ = min(res.cfg.units(cls), 64), occ_len(res.cfg, cls)
    before = sum(1 for _, p in parts_of(res) if p.cls == cls and p.issue_c is not None and p.issue_c <= t - 1 and p.issue_c + occ > t)
    after = sum(1 for _, p in parts_of(res) if p.cls == cls and p.issue_c is not None and p.issue_c <= t < p.issue_c + occ)
    return n - before, after


# ------------------------------------------------------------------------------------------------
def metrics(res):
    cfg, T = res.cfg, res.total
    cyc = [c for c in res.cycles]
    last_issue = max(p.issue_c for _, p in parts_of(res))
    act = [c for c in cyc if c.t <= last_issue]
    cnt = res.cls_count()
    m = dict(run=res.name, config=cfg.short() + (f" PIPE={'+'.join(cfg.pipelined)}" if cfg.pipelined else ""),
             uops=len(res.uops), parts=sum(cnt.values()), cycles=T,
             ipc=round(len(res.uops) / T, 3), last_issue_cycle=last_issue,
             peak_sched=max(c.sched_occ for c in cyc), avg_sched=round(sum(c.sched_occ for c in act) / len(act), 2),
             peak_ready=max(c.ready_uops for c in cyc), avg_ready=round(sum(c.ready_uops for c in act) / len(act), 2),
             avg_waiting=round(sum(c.waiting_uops for c in act) / len(act), 2),
             issue_rate_active=round(sum(len(c.issued) for c in act) / len(act), 3),
             issue_rate_total=round(sum(len(c.issued) for c in cyc) / (T + 1), 3),
             dispatch_blocked_cycles=sum(1 for c in cyc if c.dispatch_blocked),
             dispatch_done_cycle=max(u.dispatch_c for u in res.uops),
             starved_cycles=sum(1 for c in act if c.sched_occ > 0 and c.ready_uops == 0),
             width_trim_events=sum(len(c.sel_not_issued) for c in cyc),
             wake_deferred=sum(c.wake_deferred for c in cyc),
             ready_unselected_total=sum(len(c.unselected) for c in cyc),
             multi_ready_cycles=sum(1 for c in cyc if c.ready_uops >= 2))
    for cl in CLASSES:
        n = min(cfg.units(cl), 64)
        busy = sum(occ_len(cfg, cl) for _, p in parts_of(res) if p.cls == cl)
        m[f"util_{cl}"] = round(busy / (n * (T + 1)), 3) if cfg.units(cl) < INF else 0
        m[f"unsel_{cl}"] = sum(1 for c in cyc for lab, _ in c.unselected if _cls_of(res, lab) == cl)
    # stranded capacity: some other class had an idle unit while a ready uop of a different class waited (Case B)
    stranded, idle_slots = 0, 0
    for c in cyc:
        if not c.unselected:
            continue
        waiting_cls = {_cls_of(res, lab) for lab, _ in c.unselected}
        idle = {cl: unit_state(res, cl, c.t)[0] - len(c.unit_use[cl]) for cl in CLASSES if cl not in waiting_cls}
        idle = {k: v for k, v in idle.items() if 0 < v < INF}
        if idle:
            stranded += 1
            idle_slots += sum(idle.values())
    m["stranded_cycles"], m["stranded_idle_unit_slots"] = stranded, idle_slots
    return m


def _cls_of(res, lab):
    uid = int(lab[1:3])
    if "." in lab:
        return lab.split(".")[1]
    return res.uops[uid].parts[0].cls


# ------------------------------------------------------------------------------------------------
def fmt_trace(res):
    cfg = res.cfg
    out = [f"# {res.name}   [{cfg.short()}{' PIPE=' + '+'.join(cfg.pipelined) if cfg.pipelined else ''}]",
           f"# total execution time (last completion) = {res.total} cycles", ""]
    for c in res.cycles:
        out.append(f"=== cycle {c.t} ===")
        out.append(f"dispatch  : {' '.join(c.dispatched) or '-'}" + ("   <-- BLOCKED: scheduler full" if c.dispatch_blocked else ""))
        out.append(f"scheduler : {c.sched_occ}/{cfg.sched_size} occupied | ready {c.ready_uops} | waiting {c.waiting_uops}")
        out.append(f"ready     : {' '.join(c.ready_parts) or '-'}")
        out.append(f"selected  : {' '.join(c.selected) or '-'}")
        out.append(f"issued    : {' '.join(c.issued) or '-'}   ({len(c.issued)}/{SHOW(cfg.issue_width)} slots)")
        for lab, why in c.unselected:
            out.append(f"  ready-not-selected {lab}: {why}")
        for lab, why in c.sel_not_issued:
            out.append(f"  selected-not-issued {lab}: {why}")
        use = []
        for cl in CLASSES:
            fr, bz = unit_state(res, cl, c.t)
            use.append(f"{cl} {bz}/{SHOW(cfg.units(cl))}")
        out.append("units busy: " + "  ".join(use))
        out.append(f"wakeup    : {c.wake_granted}/{SHOW(cfg.wakeup_width)} used, demand {c.wake_demand}, deferred {c.wake_deferred}")
        out.append(f"completed : {' '.join(c.completed) or '-'}   in-flight(executing) {c.in_flight}")
        out.append("")
    out.append("--- per-uop table ---")
    out.append(f"{'uop':<4} {'op':<6} {'text':<26} {'res':<9} {'deps':<14} {'disp':>4} {'opRdy':>5} {'sel':>4} {'issue':>5} {'done':>4}")
    for u in res.uops:
        sel = min(p.first_sel_c for p in u.parts)
        out.append(f"{u.name:<4} {u.op:<6} {u.text:<26} {'+'.join(u.classes):<9} {','.join('U%02d' % d for d in u.deps) or '-':<14} "
                   f"{u.dispatch_c:>4} {u.operand_ready_c:>5} {sel:>4} {u.issue_c:>5} {u.complete_c:>4}")
    return "\n".join(out)


def uop_rows(res):
    rows = []
    for u in res.uops:
        rows.append(dict(run=res.name, uop=u.name, text=u.text, op=u.op, dst=u.dst or "",
                         srcs=" ".join(s for p in u.parts for s in p.srcs), producers=" ".join("U%02d" % d for d in u.deps),
                         resource="+".join(u.classes), sched_entry_from=u.dispatch_c, dispatch_c=u.dispatch_c,
                         operand_ready_c=u.operand_ready_c, first_selected_c=min(p.first_sel_c for p in u.parts),
                         issue_c=u.issue_c, complete_c=u.complete_c, wait_ready_to_issue=u.issue_c - u.operand_ready_c))
    return rows


def cycle_rows(res):
    rows = []
    for c in res.cycles:
        r = dict(run=res.name, cycle=c.t, sched_occ=c.sched_occ, ready=c.ready_uops, waiting=c.waiting_uops,
                 selected=len(c.selected), issued=len(c.issued), ready_unselected=len(c.unselected),
                 selected_not_issued=len(c.sel_not_issued), dispatched=len(c.dispatched), dispatch_blocked=int(c.dispatch_blocked),
                 wake_used=c.wake_granted, wake_demand=c.wake_demand, wake_deferred=c.wake_deferred,
                 completed=len(c.completed), executing=c.in_flight)
        for cl in CLASSES:
            r[f"busy_{cl}"] = unit_state(res, cl, c.t)[1]
        r["issued_uops"] = " ".join(c.issued)
        r["ready_uops"] = " ".join(c.ready_parts)
        rows.append(r)
    return rows


# ------------------------------------------------------------------------------------------------
def _crit_src(res, u):
    """Which producer set the operand-ready cycle of uop u (None if dispatch-limited / live-in)."""
    best, who = u.dispatch_c + 1, None
    for p in u.parts:
        for s, prod, r in zip(p.srcs, p.prod, p.ready_at):
            if prod is not None and r is not None and r >= best:
                best, who = r, (prod, s, p)
    return who


def backtrace(res, uid, why_text="did not execute"):
    """Walk backward: why wasn't uop U executing earlier? resource wait -> holder -> its producer -> ..."""
    lines, seen = [], set()
    u = res.uops[uid]
    while u.uid not in seen:
        seen.add(u.uid)
        rdy = u.operand_ready_c
        wait = u.issue_c - rdy
        who = _crit_src(res, u)
        lines.append(f"{u.name} ({u.text}): operand-ready c{rdy}, issued c{u.issue_c}, wait {wait}"
                     + (f" [resource {'+'.join(u.classes)} busy]" if wait else " [issued as soon as ready]"))
        if who is None:
            lines.append(f"   -> sources are live-in; only dispatch (c{u.dispatch_c}) limited it")
            break
        prod, reg, pt = who
        pu = res.uops[prod]
        lines.append(f"   -> last operand {reg} came from {pu.name} ({pu.text}), issued c{pu.issue_c}, result c{pu.avail_c}")
        u = pu
    return "\n".join(lines)


def explain_chain(res, ids):
    """Table for a dependency chain: when each link became eligible and what delayed it past that point."""
    out = []
    for i in ids:
        u = res.uops[i]
        who = _crit_src(res, u)
        by = "live-in/dispatch" if who is None else f"{res.uops[who[0]].name}->{who[1]}"
        sel_rdy = u.operand_ready_c
        delay = u.issue_c - sel_rdy
        cause = "none (issued the cycle it became ready)"
        if delay > 0:
            c = res.cycles[sel_rdy]
            hit = [why for lab, why in res.cycles[sel_rdy].unselected if lab.startswith(u.name)]
            cause = hit[0] if hit else f"waited {delay} cycles for {'+'.join(u.classes)} unit"
        out.append(dict(uop=u.name, text=u.text, eligible_c=sel_rdy, eligible_because=by, issue_c=u.issue_c,
                        complete_c=u.complete_c, delay=delay, delay_cause=cause))
    return out


def ready_cases(res, min_ready=2):
    """Cycles with >=min_ready ready uops, with the structured fields the assignment asks for."""
    cases = []
    for c in res.cycles:
        if c.ready_uops >= min_ready:
            cases.append(c)
    return cases


def crime_scene(res, t, focus=None):
    c, cfg = res.cycles[t], res.cfg
    # entries held at the start of select in cycle t: dispatched <= t and not yet fully issued before t
    occ = [u for u in res.uops if u.dispatch_c <= t and u.issue_c >= t]
    ready_ids = sorted({r.split(".")[0] for r in c.ready_parts})
    waiting = [u for u in occ if u.name not in ready_ids]
    L = [f"CYCLE {t}   ({cfg.short()})", "Scheduler:",
         f"  Occupied entries : {len(occ)}/{cfg.sched_size}",
         f"  Ready entries    : {len(ready_ids)}", f"  Waiting entries  : {len(waiting)}",
         "  Ready uops:"]
    for r in c.ready_parts:
        u = res.uops[int(r[1:3])]
        L.append(f"    {r:<8} {u.text:<26} needs {'+'.join(u.classes)}")
    L.append("  Selected uops:")
    for s in c.selected:
        L.append(f"    {s}")
    if not c.selected:
        L.append("    -")
    L.append("  Ready but NOT selected / NOT issued:")
    for lab, why in c.unselected + c.sel_not_issued:
        L.append(f"    {lab}: {why}")
    L.append("  Waiting entries (not ready) and what each waits for:")
    for u in waiting:
        pend = []
        for p in u.parts:
            for s, prod, r in zip(p.srcs, p.prod, p.ready_at):
                if prod is not None and (r is None or r > t):
                    pu = res.uops[prod]
                    pend.append(f"{s} from {pu.name}" + (f" (issued c{pu.issue_c}, ready c{r})" if pu.issue_c is not None and pu.issue_c < t else (f" (issues c{pu.issue_c})" if pu.issue_c is not None else "")))
        L.append(f"    {u.name} {u.text:<26} waits on {'; '.join(pend) or 'dispatch'}")
    L.append("Execution resources:")
    for cl in CLASSES:
        fr, bz = unit_state(res, cl, t)
        n = cfg.units(cl)
        issued_now = len(c.unit_use[cl])
        L.append(f"  {cl:<5} units {SHOW(n)}: free at select {fr}, issued now {issued_now}, busy after issue {bz}, idle {max(0, min(n, 64) - bz)}")
    L.append("Issue slots:")
    L.append(f"  Used: {len(c.issued)}   Remaining: {SHOW(cfg.issue_width) if cfg.issue_width >= INF else cfg.issue_width - len(c.issued)}   (width {SHOW(cfg.issue_width)})")
    L.append("Wakeup:")
    L.append(f"  Available bandwidth: {SHOW(cfg.wakeup_width)} operands/cycle   Used: {c.wake_granted}   Demand: {c.wake_demand}   Deferred: {c.wake_deferred}")
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------
# Counterfactual bottleneck attribution: relax one constraint at a time and see which one buys cycles.
RELAX = {
    "scheduler capacity": dict(sched_size=INF),
    "dispatch width": dict(dispatch_width=INF),
    "issue width": dict(issue_width=INF),
    "wakeup bandwidth": dict(wakeup_width=INF),
    "ALU": dict(alu=INF), "IMUL": dict(imul=INF), "FADD": dict(fadd=INF), "FMUL": dict(fmul=INF),
    "LOAD/AGU": dict(load=INF), "STA/STD": dict(sta=INF, std=INF),
}


def attribution(lines, cfg, base_T=None):
    T = base_T or simulate("t", lines, cfg).total
    gains = {}
    for name, kw in RELAX.items():
        gains[name] = T - simulate("t", lines, cfg.but(**kw)).total
    allrel = cfg.but(sched_size=INF, dispatch_width=INF, issue_width=INF, wakeup_width=INF, alu=INF, imul=INF,
                     fadd=INF, fmul=INF, load=INF, sta=INF, std=INF, br=INF)
    t_df = simulate("t", lines, allrel).total
    top = max(gains, key=gains.get)
    gap = T - t_df
    pos = [k for k, v in sorted(gains.items(), key=lambda kv: -kv[1]) if v > 0]
    if gap == 0:
        label = "dataflow (critical path)"
    elif gains[top] * 2 >= gap or len(pos) == 1:
        label = top
    elif pos:
        label = "co-limited: " + " + ".join(pos[:3])
    else:
        label = "combination of limits"
    return dict(T=T, dataflow_T=t_df, gains=gains, bottleneck=label)


def static_bounds(lines, cfg):
    """Prediction tool: dataflow critical path and per-class occupancy bound, computed WITHOUT scheduling."""
    res = simulate("static", lines, cfg.but(sched_size=INF, dispatch_width=INF, issue_width=INF, wakeup_width=INF,
                                           alu=INF, imul=INF, fadd=INF, fmul=INF, load=INF, sta=INF, std=INF, br=INF))
    cp = res.total
    b = {}
    for cl in CLASSES:
        tot = sum(occ_len(cfg, cl) for u in res.uops for p in u.parts if p.cls == cl)
        n = cfg.units(cl)
        b[cl] = 0 if n >= INF else -(-tot // n)
    return cp, b
