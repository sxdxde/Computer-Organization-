"""Machine configuration for the Exp07 out-of-order backend model."""
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class MachineConfig:
    decode_width: int = 6
    alloc_width: int = 6
    retire_width: int = 4
    rob_size: int = 24
    prf_size: int = 32
    iq_size: int = 12
    lq_size: int = 6
    sq_size: int = 4
    ckpt_size: int = 2
    # Not specified by the assignment; chosen so they are never the interesting limit.
    decode_queue: int = 12   # buffer between decode and rename (frontend backpressure lives here)
    issue_width: int = 6     # execution slots per cycle (= alloc width)
    latency: tuple = (("ADD", 1), ("MUL", 4), ("LOAD", 20), ("STORE", 1), ("BRANCH", 1))

    def lat(self, op):
        return dict(self.latency)[op]

    def but(self, **kw):
        return replace(self, **kw)

    def short(self):
        return (f"ROB={self.rob_size} PRF={self.prf_size} IQ={self.iq_size} LQ={self.lq_size} "
                f"SQ={self.sq_size} CKPT={self.ckpt_size} RET={self.retire_width}")
