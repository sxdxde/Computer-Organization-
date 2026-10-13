"""Machine configuration for the Exp08 scheduler/wakeup/select/execute model."""
from dataclasses import dataclass, replace

INF = 10_000  # "unbounded" for counterfactual relaxations

# execution-resource classes, in display order
CLASSES = ("ALU", "IMUL", "FADD", "FMUL", "LOAD", "STA", "STD", "BR")

# opcode -> list of (resource class) parts. STORE is two parts sharing one scheduler entry.
OP_CLASS = {
    "ADD": ("ALU",), "SUB": ("ALU",), "AND": ("ALU",), "OR": ("ALU",), "XOR": ("ALU",),
    "IMUL": ("IMUL",), "FADD": ("FADD",), "VADD": ("FADD",), "FMUL": ("FMUL",), "VMUL": ("FMUL",),
    "LOAD": ("LOAD",), "STORE": ("STA", "STD"), "BR": ("BR",),
}
LATENCY = {"ALU": 1, "IMUL": 4, "FADD": 3, "FMUL": 4, "LOAD": 5, "STA": 1, "STD": 1, "BR": 1}


@dataclass(frozen=True)
class Machine:
    dispatch_width: int = 6
    sched_size: int = 24
    issue_width: int = 6
    wakeup_width: int = 6
    alu: int = 3
    imul: int = 1
    fadd: int = 2
    fmul: int = 2
    load: int = 2
    sta: int = 1
    std: int = 1
    br: int = 1
    # classes whose units accept a new uop every cycle even while an older one is still executing.
    # Default () = a unit is OCCUPIED from issue until completion (the simplified model of the brief).
    pipelined: tuple = ()

    def units(self, cls):
        return getattr(self, cls.lower())

    def but(self, **kw):
        return replace(self, **kw)

    def short(self):
        return (f"SCHED={self.sched_size} DISP={self.dispatch_width} ISSUE={self.issue_width} WAKE={self.wakeup_width} "
                f"ALU={self.alu} MUL={self.imul} FADD={self.fadd} FMUL={self.fmul} LD={self.load}")
