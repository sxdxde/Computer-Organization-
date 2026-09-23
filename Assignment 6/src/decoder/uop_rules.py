"""Stage 5-6 of the decode pipeline: instruction classification and uop
generation.

These rules are NOT published by Intel at this level of detail; per the
assignment brief, where Intel does not publicly specify an internal
implementation detail, the rules defined here are the educational model for
this lab. They are deliberately simple and are documented in the report:

  * Register-register ALU ops (ADD/SUB/XOR reg,reg and reg,imm8)  -> 1 uop.
  * A load (MOV reg, [mem])                                        -> 1 uop.
  * A store (MOV [mem], reg)                                       -> 1 uop.
  * LEA                                                             -> 1 uop
    (address-generation only, never touches memory/regfile beyond the AGU,
    so it never expands regardless of ModRM/SIB/disp complexity).
  * A memory read-modify-write ALU op (ADD [mem], reg)              -> 2 uops
    (micro-fused load+op, plus a separate store -- this is the lab's
    concrete example of "uop expansion" for W4).
  * CMP / TEST (register-register)                                 -> 1 uop,
    and is a *fusion candidate* for a following Jcc.
  * Jcc                                                             -> 1 uop
    normally; 0 additional uops if the decoder fuses it with an
    immediately preceding CMP/TEST in the same cycle (see simulator.py).
  * MSROM-class instructions (CPUID, RDTSC, ENTER, REP-prefixed string ops,
    LOCK'd atomic read-modify-write) -> a fixed multi-uop count, and force
    the decode group to close early (no further lane in that cycle can be
    used) once the MSROM instruction is decoded, matching Intel's public
    description of the MSROM engine as a distinct, single-issue sequencer
    that the front-end hands off to.
"""

from dataclasses import dataclass

from .length_decode import DecodedInstruction

MSROM_UOP_COUNTS = {
    "CPUID": 4,
    "RDTSC": 2,
    "ENTER": 3,
    "REP MOVSB": 4,   # symbolic: real count is data-dependent on RCX at runtime,
                        # decode-time cost is modeled as this fixed short-string estimate
    "LOCK XADD": 5,
}

MSROM_MNEMONICS = set(MSROM_UOP_COUNTS.keys())


@dataclass
class UopInfo:
    instr_class: str      # short label used in the trace / tables
    uop_count: int          # baseline uop count, before any fusion adjustment
    is_msrom: bool
    is_fusion_source: bool   # True for register-register CMP/TEST
    is_jcc: bool


def classify(insn: DecodedInstruction) -> UopInfo:
    mnemonic = insn.mnemonic
    kind = insn.op_kind

    if mnemonic in MSROM_MNEMONICS:
        return UopInfo(instr_class=f"MSROM:{mnemonic}", uop_count=MSROM_UOP_COUNTS[mnemonic],
                        is_msrom=True, is_fusion_source=False, is_jcc=False)

    if kind == "jcc":
        return UopInfo(instr_class="BRANCH", uop_count=1, is_msrom=False,
                        is_fusion_source=False, is_jcc=True)

    if kind in ("cmp", "test"):
        return UopInfo(instr_class=kind.upper(), uop_count=1, is_msrom=False,
                        is_fusion_source=True, is_jcc=False)

    if kind == "lea":
        return UopInfo(instr_class="LEA", uop_count=1, is_msrom=False,
                        is_fusion_source=False, is_jcc=False)

    if kind == "mov_load":
        return UopInfo(instr_class="LOAD", uop_count=1, is_msrom=False,
                        is_fusion_source=False, is_jcc=False)

    if kind == "mov_store":
        return UopInfo(instr_class="STORE", uop_count=1, is_msrom=False,
                        is_fusion_source=False, is_jcc=False)

    if kind in ("alu_rr", "alu_mi"):
        is_mem_dest = insn.modrm is not None and not insn.modrm.is_register_operand
        if is_mem_dest:
            return UopInfo(instr_class="ALU-RMW(mem)", uop_count=2, is_msrom=False,
                            is_fusion_source=False, is_jcc=False)
        return UopInfo(instr_class="ALU-RR" if kind == "alu_rr" else "ALU-IMM",
                        uop_count=1, is_msrom=False, is_fusion_source=False, is_jcc=False)

    # Should not be reached for the opcode set this lab supports.
    return UopInfo(instr_class="UNKNOWN", uop_count=1, is_msrom=False,
                    is_fusion_source=False, is_jcc=False)
