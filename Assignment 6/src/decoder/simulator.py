"""The six-wide Golden Cove legacy decode simulator.

Each cycle:
  1. Up to 32 fresh bytes become available for decode (the "legacy decode
     window").
  2. Starting from the current stream position, instructions are decoded
     one at a time (boundary detection -> prefixes -> opcode -> ModRM/SIB/
     disp/imm -> classification -> uop generation) and packed into decoder
     lanes D0-D5 in program order.
  3. A lane can be used only if BOTH (a) fewer than 6 instructions have been
     placed this cycle, and (b) the instruction's bytes fit within the
     32-byte window budget for this cycle.
  4. If a decoded instruction is MSROM-class, it is placed in the current
     lane and the cycle closes immediately afterward: no further lane is
     used this cycle, modeling the hand-off from the legacy 6-wide decoders
     to the single-issue MSROM sequencer.
  5. Macro-fusion (CMP/TEST + Jcc): if a CMP/TEST decoded in lane k is
     immediately followed, in program order, by a Jcc that lands in lane
     k+1 of the SAME cycle, the pair is fused into the CMP/TEST's single
     uop and the Jcc contributes zero additional uops. If the Jcc instead
     falls in a different cycle (e.g. because the CMP/TEST was the last
     instruction packed into D5, or the byte budget closed the cycle),
     fusion does not occur -- the pair is decoded as two independent
     1-uop instructions.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .length_decode import decode_one_instruction, DecodedInstruction
from .uop_rules import classify, UopInfo

NUM_LANES = 6
BYTES_PER_CYCLE = 32


@dataclass
class LaneResult:
    lane: int
    insn: Optional[DecodedInstruction]
    uop: Optional[UopInfo]
    fused_with_prev: bool = False   # this lane's instruction (a Jcc) was fused into lane-1
    uops_this_lane: int = 0          # uops actually credited to this lane after fusion adjustment


@dataclass
class CycleResult:
    cycle: int
    lanes: List[LaneResult]
    bytes_available: int
    bytes_consumed: int
    instructions_decoded: int
    uops_generated: int
    fusion_events: int
    msrom_events: int


@dataclass
class SimResult:
    name: str
    stream: bytes
    cycles: List[CycleResult]

    @property
    def total_instructions(self):
        return sum(c.instructions_decoded for c in self.cycles)

    @property
    def total_bytes(self):
        return sum(c.bytes_consumed for c in self.cycles)

    @property
    def total_uops(self):
        return sum(c.uops_generated for c in self.cycles)

    @property
    def total_fusion_events(self):
        return sum(c.fusion_events for c in self.cycles)

    @property
    def total_msrom_events(self):
        return sum(c.msrom_events for c in self.cycles)

    @property
    def num_cycles(self):
        return len(self.cycles)


def run_simulation(name: str, stream: bytes) -> SimResult:
    pos = 0
    cycle_idx = 0
    cycles: List[CycleResult] = []
    pending_fusion_source = None  # (cycle_idx, lane_idx) of an as-yet-unresolved CMP/TEST

    while pos < len(stream):
        window_end = pos + BYTES_PER_CYCLE
        bytes_used = 0
        lanes: List[LaneResult] = []
        cycle_fusion_events = 0
        cycle_msrom_events = 0
        msrom_closed_cycle = False

        while len(lanes) < NUM_LANES and pos < len(stream) and not msrom_closed_cycle:
            try:
                insn = decode_one_instruction(stream, pos)
            except Exception as e:
                raise RuntimeError(f"[{name}] decode failed at byte offset {pos}: {e}")

            if bytes_used + insn.length > BYTES_PER_CYCLE:
                break  # doesn't fit in this cycle's 32-byte window; deferred to next cycle

            uop = classify(insn)
            lane_idx = len(lanes)
            lr = LaneResult(lane=lane_idx, insn=insn, uop=uop, uops_this_lane=uop.uop_count)

            # --- macro-fusion resolution ---
            if lanes and lanes[-1].insn is not None and lanes[-1].uop.is_fusion_source and uop.is_jcc:
                lanes[-1].fused_with_prev = False  # (the CMP/TEST itself is not "fused into"; it stays)
                lr.fused_with_prev = True
                lr.uops_this_lane = 0
                cycle_fusion_events += 1

            if uop.is_msrom:
                cycle_msrom_events += 1
                msrom_closed_cycle = True  # this is the last lane used this cycle

            lanes.append(lr)
            bytes_used += insn.length
            pos += insn.length

        instructions_decoded = len(lanes)
        uops_generated = sum(l.uops_this_lane for l in lanes)

        # pad remaining lanes as idle
        for idle_lane in range(len(lanes), NUM_LANES):
            lanes.append(LaneResult(lane=idle_lane, insn=None, uop=None))

        cycles.append(CycleResult(
            cycle=cycle_idx, lanes=lanes, bytes_available=BYTES_PER_CYCLE,
            bytes_consumed=bytes_used, instructions_decoded=instructions_decoded,
            uops_generated=uops_generated, fusion_events=cycle_fusion_events,
            msrom_events=cycle_msrom_events,
        ))
        cycle_idx += 1

    return SimResult(name=name, stream=stream, cycles=cycles)


def format_trace(result: SimResult) -> str:
    out = []
    for c in result.cycles:
        out.append(f"Cycle {c.cycle}")
        out.append("-" * 60)
        out.append(f"Bytes available : {c.bytes_available}")
        for lr in c.lanes:
            tag = f"D{lr.lane}"
            if lr.insn is None:
                out.append(f"{tag} : idle")
                continue
            hexs = " ".join(f"{b:02X}" for b in lr.insn.raw_bytes)
            operands = f" {lr.insn.operand_text}" if lr.insn.operand_text else ""
            if lr.fused_with_prev:
                out.append(f"{tag} : {hexs:<24} {lr.insn.mnemonic}{operands} -> fused (with D{lr.lane-1})")
            elif lr.uop.is_msrom:
                out.append(f"{tag} : {hexs:<24} {lr.insn.mnemonic}{operands} -> MSROM, {lr.uops_this_lane} uops")
            else:
                out.append(f"{tag} : {hexs:<24} {lr.insn.mnemonic}{operands} -> {lr.uops_this_lane} uop"
                            f"{'s' if lr.uops_this_lane != 1 else ''}")
        out.append(f"Instructions decoded : {c.instructions_decoded}")
        out.append(f"Bytes consumed       : {c.bytes_consumed}")
        out.append(f"uops generated        : {c.uops_generated}")
        out.append(f"Fusion events         : {c.fusion_events}")
        out.append(f"MSROM events          : {c.msrom_events}")
        out.append("-" * 60)
        out.append("")
    return "\n".join(out)
