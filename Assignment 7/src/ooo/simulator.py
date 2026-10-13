"""Cycle-level model of decode -> rename/allocate -> execute -> complete -> retire -> reclaim,
plus misprediction -> squash -> recovery -> redirect -> decode.

Per-cycle stage order (each stage sees the state the previous stage left):
    1 ALLOCATE   rename + take ROB/PRF/IQ/LQ/SQ/CKPT, in order, up to alloc_width
    2 COMPLETE   results written back (complete_c == now); branches resolve; mispredict -> recovery
    3 RETIRE     in order, up to retire_width, only entries completed in an EARLIER cycle; reclaim
    4 ISSUE      oldest-first from the IQ, operands ready, up to issue_width; IQ entry freed here
    5 DECODE     fill the decode queue (frontend); blocked while the queue is full / redirecting
Because ALLOCATE runs before RETIRE/ISSUE, a resource freed in cycle t is first usable in t+1.

Timing conventions: issue at cycle s, complete at s+latency, dependants may issue at the complete
cycle, retirement is possible from complete+1. Allocation happens one cycle after decode.
"""
from collections import deque
from dataclasses import dataclass, field

from .config import MachineConfig
from .isa import NEEDS

RES_ORDER = ["ROB", "PRF", "IQ", "LQ", "SQ", "CKPT"]


@dataclass
class Dyn:
    seq: int
    st: object
    wrong_path: bool = False
    state: str = "DECODED"       # DECODED IQ EXEC DONE RETIRED SQUASHED
    decode_c: int = None
    alloc_c: int = None
    issue_c: int = None
    complete_c: int = None
    retire_c: int = None
    squash_c: int = None
    reclaim_c: int = None        # cycle at which the *old* mapping of the dest was returned to the free list
    rob_idx: int = None
    psrcs: list = field(default_factory=list)   # [(arch, preg|None)]  None = architectural file
    pdst: int = None
    pold: int = None
    ckpt: dict = None
    resolve_note: str = ""

    @property
    def label(self):
        return self.st.label

    @property
    def op(self):
        return self.st.op


@dataclass
class CycleRecord:
    cycle: int
    rob_occ: int = 0
    free_pregs: int = 0
    iq_occ: int = 0
    lq_occ: int = 0
    sq_occ: int = 0
    ckpt_used: int = 0
    decodeq_occ: int = 0
    decoded: int = 0
    allocated: int = 0
    issued: int = 0
    completed: int = 0
    retired: int = 0
    squashed: int = 0
    flushed_frontend: int = 0
    done_unretired: int = 0
    issue_slots_free: int = 0
    alloc_stalled: bool = False
    stall_resource: str = ""       # primary blocking resource
    stall_all: str = ""            # every resource the blocked uop was missing
    stall_instr: str = ""
    stall_reason: str = ""         # why that resource is unavailable
    stall_root: str = ""           # earlier event that created the pressure
    stall_avail: str = ""          # resource availability at the moment of the stall
    alloc_idle: bool = False       # nothing to allocate (frontend starved / draining)
    fe_stalled: bool = False
    fe_reason: str = ""
    actions: list = field(default_factory=list)


@dataclass
class Result:
    name: str
    cfg: MachineConfig
    program: list
    cycles: list
    dyn: list
    versions: list
    snapshots: list
    events: list

    @property
    def total_cycles(self):
        return len(self.cycles)

    @property
    def retired(self):
        return [d for d in self.dyn if d.state == "RETIRED"]

    @property
    def squashed(self):
        return [d for d in self.dyn if d.state == "SQUASHED"]


class Simulator:
    def __init__(self, name, program, cfg=None, max_cycles=5000):
        self.name, self.prog = name, program
        self.cfg = cfg or MachineConfig()
        self.max_cycles = max_cycles
        c = self.cfg
        self.rat = {}                                  # arch reg -> preg (absent = still in ARF)
        self.free = deque(range(c.prf_size))
        self.preg_ready = [None] * c.prf_size
        self.preg_ver = [None] * c.prf_size            # current version record per preg
        self.versions = []
        self.rob = deque()
        self.rob_head = 0
        self.iq, self.lq, self.sq, self.ckpts = [], [], [], []
        self.decodeq = deque()
        self.pending = {}
        self.pc = 0
        self.wrong = None                              # (branch Dyn, next index) while on wrong path
        self.redirect_c = 0
        self.seq = 0
        self.dyn, self.cycles, self.snapshots, self.events = [], [], [], []
        self.t = 0

    # ------------------------------------------------------------------ helpers
    def _log(self, rec, msg):
        rec.actions.append(msg)

    def _name(self, p):
        return "ARF" if p is None else f"P{p}"

    def _src_ready(self, p):
        return p is None or (self.preg_ready[p] is not None and self.preg_ready[p] <= self.t)

    def _unready_producer(self, d):
        """Younger-to-older walk: the in-flight instruction whose result d is waiting for."""
        for arch, p in d.psrcs:
            if not self._src_ready(p):
                ver = self.preg_ver[p]
                return ver["writer_dyn"]
        return None

    def _chain(self, d, depth=0):
        """Human-readable: why instruction d has not completed, followed back to an executing root."""
        if d.state == "EXEC":
            return f"{d.label} ({d.op}) is executing, completes at cycle {d.complete_c}"
        if d.state == "DONE":
            return f"{d.label} ({d.op}) completed at cycle {d.complete_c} but is waiting to retire in order"
        if d.state == "IQ":
            p = self._unready_producer(d)
            if p is None:
                return f"{d.label} ({d.op}) is ready to issue (allocated one cycle earlier)"
            return f"{d.label} ({d.op}) waits in the IQ for {p.label} -> " + self._chain(p, depth + 1)
        return f"{d.label} is {d.state}"

    def _head_root(self):
        if not self.rob:
            return "ROB empty"
        h = self.rob[0]
        if h.state == "DONE":
            nd = sum(1 for e in self.rob if e.state == "DONE")
            if nd > self.cfg.retire_width:
                return (f"retirement is bandwidth-bound: {nd} completed entries drain at "
                        f"{self.cfg.retire_width}/cycle (head {h.label} completed at cycle {h.complete_c})")
            return (f"head {h.label} completed at cycle {h.complete_c} and retires this cycle; the freed entry "
                    f"is first usable by allocation next cycle")
        return f"retirement blocked by oldest instruction: {self._chain(h)}"

    def _explain(self, res):
        """(reason the resource is unavailable, earlier root event)"""
        c = self.cfg
        if res == "ROB":
            nd = sum(1 for e in self.rob if e.state == "DONE")
            return (f"ROB full ({len(self.rob)}/{c.rob_size}); {nd} entries completed-but-unretired",
                    self._head_root())
        if res == "PRF":
            held_new = len([e for e in self.rob if e.pdst is not None])
            superseded = len([e for e in self.rob if e.pdst is not None and e.pold is not None])
            return (f"free list empty: {c.prf_size - len(self.free)}/{c.prf_size} pregs in use, "
                    f"{held_new} are in-flight dest versions, {superseded} older versions cannot be "
                    f"reclaimed until their overwriter retires",
                    self._head_root())
        if res == "IQ":
            wait = [e for e in self.iq if not all(self._src_ready(p) for _, p in e.psrcs) or e.alloc_c >= self.t]
            root = "IQ entries are all ready but issue width is saturated"
            for e in self.iq:
                prod = self._unready_producer(e)
                if prod is not None:
                    root = f"oldest waiting entry: {self._chain(e)}"
                    break
            return (f"IQ full ({len(self.iq)}/{c.iq_size}); {len(wait)} entries are waiting on source operands "
                    f"(entries free only when a uop issues)", root)
        if res in ("LQ", "SQ"):
            q = self.lq if res == "LQ" else self.sq
            cap = c.lq_size if res == "LQ" else c.sq_size
            o = q[0]
            return (f"{res} full ({len(q)}/{cap}); entries are held from allocation until retirement; "
                    f"oldest holder {o.label} ({o.op}) is {o.state}",
                    f"oldest holder: {self._chain(o)}" if o.state != "DONE" and o is not self.rob[0]
                    else self._head_root())
        if res == "CKPT":
            o = self.ckpts[0]
            return (f"checkpoints exhausted ({len(self.ckpts)}/{c.ckpt_size}); a checkpoint is held until its "
                    f"branch resolves; unresolved: {', '.join(b.label for b in self.ckpts)}",
                    f"oldest unresolved branch: {self._chain(o)}")
        return ("", "")

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, title):
        c = self.cfg
        lines = [f"--- {title} (cycle {self.t}) ---"]
        lines.append("RAT  : " + (", ".join(f"{a}->P{p}" for a, p in sorted(self.rat.items(), key=lambda x: int(x[0][1:])))
                                  or "(empty)"))
        lines.append(f"FREE : {len(self.free)}/{c.prf_size}  [" + ", ".join(f"P{p}" for p in self.free) + "]")
        lines.append(f"ROB  : {len(self.rob)}/{c.rob_size}")
        for e in self.rob:
            tag = "WRONG-PATH" if e.wrong_path else ""
            lines.append(f"   #{e.rob_idx:<2} {e.label:<4} {e.st.text:<26} {e.state:<5} "
                         f"dst={self._name(e.pdst) if e.pdst is not None else '-':<4} {tag}")
        lines.append(f"IQ   : {len(self.iq)}/{c.iq_size}  [" + ", ".join(e.label for e in self.iq) + "]")
        lines.append(f"LQ   : {len(self.lq)}/{c.lq_size}  [" + ", ".join(e.label for e in self.lq) + "]")
        lines.append(f"SQ   : {len(self.sq)}/{c.sq_size}  [" + ", ".join(e.label for e in self.sq) + "]")
        lines.append(f"CKPT : {len(self.ckpts)}/{c.ckpt_size}  [" + ", ".join(e.label for e in self.ckpts) + "]")
        lines.append(f"DECQ : {len(self.decodeq)}/{c.decode_queue}  [" + ", ".join(e.label for e in self.decodeq) + "]")
        self.snapshots.append((self.t, title, "\n".join(lines)))

    # ------------------------------------------------------------------ stages
    def _allocate(self, rec):
        c = self.cfg
        n = 0
        while n < c.alloc_width and self.decodeq:
            d = self.decodeq[0]
            need = NEEDS[d.op]
            missing = []
            if len(self.rob) >= c.rob_size:
                missing.append("ROB")
            if "PRF" in need and not self.free:
                missing.append("PRF")
            if len(self.iq) >= c.iq_size:
                missing.append("IQ")
            if "LQ" in need and len(self.lq) >= c.lq_size:
                missing.append("LQ")
            if "SQ" in need and len(self.sq) >= c.sq_size:
                missing.append("SQ")
            if "CKPT" in need and len(self.ckpts) >= c.ckpt_size:
                missing.append("CKPT")
            if missing:
                rec.alloc_stalled = True
                rec.stall_resource = missing[0]
                rec.stall_all = "+".join(missing)
                rec.stall_instr = d.label
                rec.stall_reason, rec.stall_root = self._explain(missing[0])
                rec.stall_avail = (f"ROB {len(self.rob)}/{c.rob_size}, PRF free {len(self.free)}, "
                                   f"IQ {len(self.iq)}/{c.iq_size}, LQ {len(self.lq)}/{c.lq_size}, "
                                   f"SQ {len(self.sq)}/{c.sq_size}, CKPT {len(self.ckpts)}/{c.ckpt_size}")
                self._log(rec, f"ALLOC-STALL {d.label} ({d.st.text}) blocked on {rec.stall_all}")
                break
            self.decodeq.popleft()
            d.alloc_c = self.t
            d.psrcs = [(a, self.rat.get(a)) for a in d.st.srcs]
            d.rob_idx = (self.rob_head + len(self.rob)) % c.rob_size
            if "PRF" in need:
                d.pdst = self.free.popleft()
                d.pold = self.rat.get(d.st.dst)
                self.rat[d.st.dst] = d.pdst
                self.preg_ready[d.pdst] = None
                v = dict(preg=d.pdst, writer=d.label, writer_dyn=d, arch=d.st.dst, alloc_c=self.t,
                         ready_c=None, free_c=None, free_reason="", readers=[], prev_preg=d.pold,
                         wrong_path=d.wrong_path)
                self.preg_ver[d.pdst] = v
                self.versions.append(v)
            for a, p in d.psrcs:
                if p is not None and d not in self.preg_ver[p]["readers"]:
                    self.preg_ver[p]["readers"].append(d)
            if d.op == "BRANCH":
                d.ckpt = dict(self.rat)
                self.ckpts.append(d)
            if d.op == "LOAD":
                self.lq.append(d)
            if d.op == "STORE":
                self.sq.append(d)
            self.rob.append(d)
            self.iq.append(d)
            d.state = "IQ"
            n += 1
            srcs = ", ".join(f"{a}({self._name(p)})" for a, p in d.psrcs) or "-"
            dst = (f" {d.st.dst}->P{d.pdst} (old {self._name(d.pold)})" if d.pdst is not None else "")
            self._log(rec, f"ALLOC  {d.label:<4} {d.st.text:<24} reads[{srcs}]{dst} ROB#{d.rob_idx}"
                           + (" [WRONG-PATH]" if d.wrong_path else ""))
        rec.allocated = n
        if not rec.alloc_stalled and not self.decodeq and n == 0:
            rec.alloc_idle = True

    def _complete(self, rec):
        for d in sorted(self.pending.pop(self.t, []), key=lambda x: x.seq):
            if d.state != "EXEC":
                continue                      # squashed while executing
            d.state = "DONE"
            d.complete_c = self.t
            rec.completed += 1
            if d.pdst is not None:
                self.preg_ready[d.pdst] = self.t
                self.preg_ver[d.pdst]["ready_c"] = self.t
            self._log(rec, f"COMPLETE {d.label} ({d.op})" + (f" -> P{d.pdst} ready" if d.pdst is not None else ""))
            if d.op == "BRANCH":
                if d.st.mispredicted:
                    self._recover(d, rec)
                else:
                    self.ckpts.remove(d)
                    self._log(rec, f"RESOLVE {d.label}: predicted correctly, checkpoint released")

    def _recover(self, b, rec):
        c = self.cfg
        self._log(rec, f"MISPREDICT {b.label} ({b.st.bid}): predicted {'T' if b.st.pred_taken else 'NT'}, "
                       f"actual {'T' if b.st.actual_taken else 'NT'}")
        self.events.append((self.t, "MISPREDICT", f"{b.label} detected"))
        self.snapshot(f"BEFORE RECOVERY ({b.label} mispredict detected)")
        victims = [e for e in self.rob if e.seq > b.seq]
        for e in reversed(victims):
            self.rob.pop()                                  # youngest first
            if e in self.iq: self.iq.remove(e)
            if e in self.lq: self.lq.remove(e)
            if e in self.sq: self.sq.remove(e)
            if e in self.ckpts: self.ckpts.remove(e)
            if e.pdst is not None:
                v = self.preg_ver[e.pdst]
                v["free_c"], v["free_reason"] = self.t, f"squash of {e.label}"
                self.free.append(e.pdst)
            e.state, e.squash_c = "SQUASHED", self.t
            rec.squashed += 1
            self._log(rec, f"SQUASH {e.label:<4} {e.st.text:<24} was {('executing' if e.issue_c is not None else 'waiting')}"
                           + (f", frees P{e.pdst}" if e.pdst is not None else ""))
        flushed = len(self.decodeq)
        for e in self.decodeq:
            e.state, e.squash_c = "SQUASHED", self.t
        rec.flushed_frontend += flushed
        self.decodeq.clear()
        self.rat = dict(b.ckpt)
        self.ckpts.remove(b)
        self.wrong = None
        self.redirect_c = self.t + 1
        self._log(rec, f"RECOVER rename state restored from {b.label}'s checkpoint; {len(victims)} ROB entries and "
                       f"{flushed} decode-queue uops discarded")
        self._log(rec, f"REDIRECT frontend re-steered to the correct path (fetch resumes at cycle {self.redirect_c})")
        self.events.append((self.t, "SQUASH/RECOVER", f"{len(victims)} squashed"))
        self.events.append((self.redirect_c, "REDIRECT", "correct-path decode resumes"))
        self.snapshot(f"AFTER RECOVERY ({b.label})")

    def _retire(self, rec):
        for _ in range(self.cfg.retire_width):
            if not self.rob:
                break
            h = self.rob[0]
            if h.state != "DONE" or h.complete_c >= self.t:
                break
            self.rob.popleft()
            self.rob_head = (self.rob_head + 1) % self.cfg.rob_size
            h.state, h.retire_c = "RETIRED", self.t
            rec.retired += 1
            msg = f"RETIRE {h.label:<4} {h.st.text:<24}"
            if h.pdst is not None and h.pold is not None:
                v = self.preg_ver[h.pold]
                v["free_c"], v["free_reason"] = self.t, f"reclaimed at retire of {h.label}"
                self.free.append(h.pold)
                h.reclaim_c = self.t
                msg += f" -> RECLAIM P{h.pold} (old {h.st.dst})"
            if h in self.lq: self.lq.remove(h)
            if h in self.sq: self.sq.remove(h)
            self._log(rec, msg)

    def _issue(self, rec):
        n = 0
        for d in list(self.iq):
            if n >= self.cfg.issue_width:
                break
            if d.alloc_c >= self.t:
                continue
            if all(self._src_ready(p) for _, p in d.psrcs):
                self.iq.remove(d)
                d.state, d.issue_c = "EXEC", self.t
                d.complete_c = self.t + self.cfg.lat(d.op)
                self.pending.setdefault(d.complete_c, []).append(d)
                n += 1
                self._log(rec, f"ISSUE  {d.label:<4} {d.op:<6} completes @{d.complete_c}")
        rec.issued = n
        rec.issue_slots_free = self.cfg.issue_width - n

    def _decode(self, rec):
        c = self.cfg
        if self.t < self.redirect_c:
            rec.fe_stalled, rec.fe_reason = True, "recovery/redirect bubble after misprediction"
            return
        def remaining():
            if self.wrong:
                return len(self.wrong[0].st.wrong_path) - self.wrong[1]
            return len(self.prog) - self.pc
        space = c.decode_queue - len(self.decodeq)
        n = 0
        while n < c.decode_width and space > 0 and remaining() > 0:
            if self.wrong:
                st = self.wrong[0].st.wrong_path[self.wrong[1]]
                self.wrong = (self.wrong[0], self.wrong[1] + 1)
                wp = True
            else:
                st = self.prog[self.pc]
                self.pc += 1
                wp = False
            d = Dyn(self.seq, st, wrong_path=wp, decode_c=self.t)
            self.seq += 1
            self.dyn.append(d)
            self.decodeq.append(d)
            space -= 1
            n += 1
            if st.op == "BRANCH":
                if st.mispredicted and not wp:
                    self.wrong = (d, 0)               # fetch follows the (wrong) predicted path
                if st.pred_taken:
                    break                             # a predicted-taken branch ends the fetch group
        rec.decoded = n
        if remaining() > 0 and n < c.decode_width and space == 0:
            rec.fe_stalled = True
            rec.fe_reason = "decode queue full" + (f" (allocation stalled on {rec.stall_resource})"
                                                    if rec.alloc_stalled else "")

    def _finish(self, rec):
        c = self.cfg
        rec.rob_occ, rec.free_pregs = len(self.rob), len(self.free)
        rec.iq_occ, rec.lq_occ, rec.sq_occ = len(self.iq), len(self.lq), len(self.sq)
        rec.ckpt_used, rec.decodeq_occ = len(self.ckpts), len(self.decodeq)
        rec.done_unretired = sum(1 for e in self.rob if e.state == "DONE")

    def _done(self):
        fe_done = (self.pc >= len(self.prog)) and self.wrong is None
        return fe_done and not self.decodeq and not self.rob and self.t >= self.redirect_c

    def run(self):
        while True:
            rec = CycleRecord(self.t)
            self._allocate(rec)
            self._complete(rec)
            self._retire(rec)
            self._issue(rec)
            self._decode(rec)
            self._finish(rec)
            self.cycles.append(rec)
            if self._done():
                break
            self.t += 1
            if self.t > self.max_cycles:
                raise RuntimeError(f"{self.name}: no forward progress")
        # conservation: with the ROB empty every preg is either free or the current mapping of an arch reg
        in_use = self.cfg.prf_size - len(self.free)
        assert in_use == len(set(self.rat.values())), (in_use, self.rat)
        assert len(set(self.free)) == len(self.free)
        return Result(self.name, self.cfg, self.prog, self.cycles, self.dyn, self.versions,
                      self.snapshots, self.events)


def simulate(name, program, cfg=None):
    return Simulator(name, program, cfg).run()
