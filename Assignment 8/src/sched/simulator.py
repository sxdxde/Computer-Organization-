"""Cycle-level model of dispatch -> scheduler -> wakeup -> select -> issue -> execute -> complete.

Per-cycle order (documented in the report):
  1. dispatch   in order, up to dispatch_width, only while the scheduler has a free entry.
                A uop dispatched in cycle t can first be selected in t+1.
  2. select     every ready part competes for the units of its class (oldest first)  -> "selected"
  3. issue      selected parts are trimmed to issue_width (oldest first)             -> "issued"
                issue frees the scheduler entry (usable by dispatch from t+1)
  4. wakeup     producers whose broadcast time has arrived wake consumer source operands,
                at most wakeup_width operands per cycle (oldest consumer first)
  5. complete   bookkeeping of uops whose result is ready this cycle

A producer that issues at s with latency L broadcasts its tag at s+L-1; a woken operand is usable in the
next cycle, so a 1-cycle ALU result can be consumed in s+1 (back-to-back) when wakeup bandwidth is free.
"""
import re
from dataclasses import dataclass, field

from .config import OP_CLASS, LATENCY, CLASSES, Machine

REG = re.compile(r"[RF]\d+")


@dataclass
class Part:
    cls: str
    srcs: list                       # architectural source registers
    prod: list                       # producer uop id (or None = live-in) per source
    ready_at: list                   # cycle each source operand becomes usable (None = not yet known)
    wake_c: list                     # cycle the wakeup was granted (None = live-in / captured at dispatch)
    first_sel_c: int = None
    issue_c: int = None
    unit: str = None

    def operand_ready_c(self):
        return None if any(r is None for r in self.ready_at) else max(self.ready_at, default=0)


@dataclass
class Uop:
    uid: int
    text: str
    op: str
    dst: str
    parts: list
    dispatch_c: int = None
    complete_c: int = None
    bcast_c: int = None              # tag broadcast cycle (issue + latency - 1)
    avail_c: int = None              # cycle the result can be consumed
    done_parts: int = 0

    @property
    def name(self):
        return f"U{self.uid:02d}"

    @property
    def deps(self):
        return sorted({p for pt in self.parts for p in pt.prod if p is not None})

    @property
    def issue_c(self):
        return None if any(p.issue_c is None for p in self.parts) else max(p.issue_c for p in self.parts)

    @property
    def operand_ready_c(self):
        v = [max(p.operand_ready_c() or 0, self.dispatch_c + 1) for p in self.parts]
        return max(v)

    @property
    def classes(self):
        return [p.cls for p in self.parts]


@dataclass
class CycleRec:
    t: int
    dispatched: list
    sched_occ: int
    free_entries: int
    ready_parts: list
    ready_uops: int
    waiting_uops: int
    selected: list
    issued: list
    unselected: list                 # (part label, reason)
    sel_not_issued: list             # (part label, reason)
    unit_use: dict                   # class -> list of part labels issued this cycle
    wake_granted: int
    wake_demand: int
    wake_deferred: int
    completed: list
    in_flight: int
    dispatch_blocked: bool
    snapshot: dict = field(default_factory=dict)


def parse_line(text):
    """'ADD R20, R1, R2' / 'LOAD R10, [R20 + 0]' / 'STORE [R41 + 0], R18' / 'BR R55' -> (op, dst, [parts' srcs])."""
    text = text.split(";")[0].strip()
    op = text.split()[0].upper()
    regs = REG.findall(text)
    if op == "LOAD":
        return op, regs[0], [[regs[1]]]
    if op == "STORE":
        return op, None, [[regs[0]], [regs[1]]]          # STA <- address reg, STD <- data reg
    if op == "BR":
        return op, None, [[regs[0]]]
    return op, regs[0], [regs[1:]]


def build_program(lines):
    """Resolve RAW producers (rename removes WAR/WAW; initial register values are live-in and ready)."""
    last_writer, uops = {}, []
    for i, line in enumerate(lines):
        op, dst, part_srcs = parse_line(line)
        parts = []
        for cls, srcs in zip(OP_CLASS[op], part_srcs):
            parts.append(Part(cls, srcs, [last_writer.get(s) for s in srcs], [None] * len(srcs), [None] * len(srcs)))
        uops.append(Uop(i, line.split(";")[0].strip(), op, dst, parts))
        if dst:
            last_writer[dst] = i
    return uops


@dataclass
class Result:
    name: str
    cfg: Machine
    uops: list
    cycles: list
    total: int                       # last completion cycle (= execution time)

    def cls_count(self):
        n = {c: 0 for c in CLASSES}
        for u in self.uops:
            for p in u.parts:
                n[p.cls] += 1
        return n


def simulate(name, lines, cfg=Machine(), max_cycles=5000):
    uops = build_program(lines)
    n = len(uops)
    sched = []                       # uop ids currently holding a scheduler entry (in dispatch order)
    next_disp = 0
    cycles = []
    pending = []                     # [uop id, part idx, src idx] awaiting a wakeup grant
    free_at = {c: [0] * min(cfg.units(c), 64) for c in CLASSES}   # unit k is free when t >= free_at[c][k]
    holder = {c: [None] * min(cfg.units(c), 64) for c in CLASSES}  # (label, issue cycle) of current occupant
    t = 0
    while t < max_cycles:
        # ---- 1. dispatch -------------------------------------------------------------------
        disp = []
        blocked = False
        while next_disp < n and len(disp) < cfg.dispatch_width:
            if len(sched) >= cfg.sched_size:
                blocked = True
                break
            u = uops[next_disp]
            u.dispatch_c = t
            for pi, pt in enumerate(u.parts):
                for si, prod in enumerate(pt.prod):
                    if prod is None:
                        pt.ready_at[si] = 0
                    else:
                        pu = uops[prod]
                        if pu.bcast_c is not None and pu.bcast_c < t:      # tag already went by: read value
                            pt.ready_at[si] = max(t + 1, pu.avail_c)
                        else:
                            pending.append([u.uid, pi, si])
            sched.append(u.uid)
            disp.append(u.uid)
            next_disp += 1
        occ = len(sched)

        # ---- 2. ready set / selection -----------------------------------------------------
        ready = []                   # (uid, part idx)
        for uid in sched:
            u = uops[uid]
            if u.dispatch_c >= t:
                continue
            for pi, pt in enumerate(u.parts):
                if pt.issue_c is None and pt.operand_ready_c() is not None and pt.operand_ready_c() <= t:
                    ready.append((uid, pi))
        label = lambda uid, pi: uops[uid].name + (("." + uops[uid].parts[pi].cls) if len(uops[uid].parts) > 1 else "")
        ready.sort()
        ready_uops = len({r[0] for r in ready})
        selected, unselected, taken = [], [], {c: 0 for c in CLASSES}
        nfree = {c: sum(1 for f in free_at[c] if f <= t) for c in CLASSES}
        for uid, pi in ready:
            c = uops[uid].parts[pi].cls
            if taken[c] < nfree[c]:
                taken[c] += 1
                selected.append((uid, pi))
                pt = uops[uid].parts[pi]
                if pt.first_sel_c is None:
                    pt.first_sel_c = t
            else:
                occ_by = []
                for k, f in enumerate(free_at[c]):
                    if f > t and holder[c][k]:
                        occ_by.append(f"{c}{k}:{holder[c][k][0]}(issued c{holder[c][k][1]}, free c{f})")
                older = [label(a, b) for a, b in selected if uops[a].parts[b].cls == c]
                why = f"no free {c} unit"
                if occ_by:
                    why += " - occupied: " + "; ".join(occ_by)
                if older:
                    why += ("; " if occ_by else " - ") + "taken this cycle by older " + ",".join(older)
                unselected.append((label(uid, pi), why))
        # ---- 3. issue (global width) ------------------------------------------------------
        selected.sort()
        issuing, sel_not_issued = selected[:cfg.issue_width], selected[cfg.issue_width:]
        sni = []
        issued_by = [label(*x) for x in issuing]
        for uid, pi in sel_not_issued:
            sni.append((label(uid, pi), f"selected but issue width {cfg.issue_width} exhausted by older {','.join(issued_by)}"))
        unit_use = {c: [] for c in CLASSES}
        for uid, pi in issuing:
            u, pt = uops[uid], uops[uid].parts[pi]
            pt.issue_c = t
            lat = LATENCY[pt.cls]
            k = next(i for i, f in enumerate(free_at[pt.cls]) if f <= t)
            pt.unit = f"{pt.cls}{k}"
            free_at[pt.cls][k] = t + (1 if pt.cls in cfg.pipelined else lat)
            holder[pt.cls][k] = (label(uid, pi), t)
            unit_use[pt.cls].append(label(uid, pi))
            if u.dst and u.parts[0] is pt:
                u.bcast_c, u.avail_c = t + lat - 1, t + lat
            if u.issue_c is not None:
                u.complete_c = max(p.issue_c + LATENCY[p.cls] for p in u.parts)
                if u.dst is None:
                    u.bcast_c = u.avail_c = None
        sched = [uid for uid in sched if uops[uid].issue_c is None]
        # ---- 4. wakeup --------------------------------------------------------------------
        due = [e for e in pending if uops[uops[e[0]].parts[e[1]].prod[e[2]]].bcast_c is not None
               and uops[uops[e[0]].parts[e[1]].prod[e[2]]].bcast_c <= t]
        due.sort(key=lambda e: (uops[uops[e[0]].parts[e[1]].prod[e[2]]].bcast_c, e[0], e[1], e[2]))
        granted = due[:cfg.wakeup_width]
        for e in granted:
            pt = uops[e[0]].parts[e[1]]
            prod = uops[pt.prod[e[2]]]
            pt.ready_at[e[2]] = max(t + 1, prod.avail_c)
            pt.wake_c[e[2]] = t
            pending.remove(e)
        # ---- 5. completions / bookkeeping ---------------------------------------------------
        completed = [u.name for u in uops if u.complete_c == t]
        in_flight = sum(1 for u in uops if u.issue_c is not None and u.issue_c <= t < u.complete_c)
        nwait = occ - ready_uops
        cycles.append(CycleRec(t, [uops[i].name for i in disp], occ, cfg.sched_size - occ, [label(*r) for r in ready],
                               ready_uops, nwait, [label(*x) for x in selected], issued_by, unselected, sni,
                               unit_use, len(granted), len(due), len(due) - len(granted), completed, in_flight, blocked))
        # frozen copy of everything needed for a "crime scene"
        cycles[-1].snapshot = dict(
            sched=[uops[i].name for i in sched] + [uops[x[0]].name for x in issuing
                                                  if uops[x[0]].issue_c == t and uops[x[0]].name not in [uops[i].name for i in sched]],
            granted=[(uops[e[0]].name, e[1], e[2]) for e in granted])
        t += 1
        if next_disp >= n and all(u.issue_c is not None for u in uops):
            break
    total = max(u.complete_c for u in uops)
    # extend per-cycle records to the last completion cycle so trailing drain cycles are visible
    while len(cycles) <= total:
        t = len(cycles)
        cycles.append(CycleRec(t, [], 0, cfg.sched_size, [], 0, 0, [], [], [], [], {c: [] for c in CLASSES}, 0, 0, 0,
                               [u.name for u in uops if u.complete_c == t],
                               sum(1 for u in uops if u.issue_c <= t < u.complete_c), False))
    return Result(name, cfg, uops, cycles, total)
