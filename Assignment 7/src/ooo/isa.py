"""Tiny instruction-stream format + parser.

    ADD   Rd, Rs1, Rs2
    MUL   Rd, Rs1, Rs2
    LOAD  Rd, [X]            X = symbolic address (no dependency) or a register (dependency)
    STORE [X], Rs            sources = every register mentioned
    BRANCH Bn pred=T|NT actual=T|NT [src=Rx]
    WRONGPATH Bn ... END     instructions fetched when Bn is mispredicted (predicted path)

'#' starts a comment. Instructions are labelled I0, I1, ... by position; wrong-path ones W0, W1, ...
"""
import re
from dataclasses import dataclass, field

REG = re.compile(r"^R\d+$")

# resources required at allocation (Table in Section 4 of the assignment)
NEEDS = {
    "ADD":    ("ROB", "PRF", "IQ"),
    "MUL":    ("ROB", "PRF", "IQ"),
    "LOAD":   ("ROB", "PRF", "IQ", "LQ"),
    "STORE":  ("ROB", "IQ", "SQ"),
    "BRANCH": ("ROB", "IQ", "CKPT"),
}


@dataclass
class StaticInstr:
    label: str
    op: str
    dst: str = None
    srcs: list = field(default_factory=list)
    text: str = ""
    bid: str = None            # branch id
    pred_taken: bool = False
    actual_taken: bool = False
    wrong_path: list = field(default_factory=list)

    @property
    def mispredicted(self):
        return self.op == "BRANCH" and self.pred_taken != self.actual_taken


def _regs_in(tok):
    return [t for t in re.findall(r"R\d+", tok)]


def parse_program(text):
    prog, wp, cur = [], {}, None
    pending = []   # (static instr) for wrong path blocks
    lines = [l.split("#")[0].strip() for l in text.splitlines()]
    in_wp = None
    for ln in lines:
        if not ln:
            continue
        u = ln.upper()
        if u.startswith("WRONGPATH"):
            in_wp = ln.split()[1]
            wp[in_wp] = []
            continue
        if u == "END":
            in_wp = None
            continue
        target = wp[in_wp] if in_wp else prog
        label = ("W" if in_wp else "I") + str(len(target))
        target.append(_parse_line(ln, label))
    for s in prog:
        if s.op == "BRANCH" and s.bid in wp:
            s.wrong_path = wp[s.bid]
    for s in prog:
        if s.mispredicted and not s.wrong_path:
            raise ValueError(f"{s.label} mispredicts but has no WRONGPATH block")
    return prog


def _parse_line(ln, label):
    m = ln.split(None, 1)
    op = m[0].upper()
    rest = m[1] if len(m) > 1 else ""
    if op in ("ADD", "MUL"):
        parts = [p.strip() for p in rest.split(",")]
        return StaticInstr(label, op, parts[0], parts[1:], f"{op} {rest}")
    if op == "LOAD":
        d, a = [p.strip() for p in rest.split(",", 1)]
        return StaticInstr(label, op, d, _regs_in(a), f"{op} {rest}")
    if op == "STORE":
        a, s = rest.rsplit(",", 1)
        return StaticInstr(label, op, None, _regs_in(a) + _regs_in(s), f"{op} {rest}")
    if op == "BRANCH":
        toks = rest.split()
        kv = dict(t.split("=") for t in toks[1:])
        srcs = _regs_in(kv.get("src", ""))
        return StaticInstr(label, op, None, srcs, f"BRANCH {toks[0]}" + (f" ({kv['src']})" if srcs else ""),
                           bid=toks[0], pred_taken=kv.get("pred", "NT").upper() == "T",
                           actual_taken=kv.get("actual", "NT").upper() == "T")
    raise ValueError(f"cannot parse: {ln}")
