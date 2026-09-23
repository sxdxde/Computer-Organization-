"""Opcode table for the x86-64 subset used in this lab's workloads.

Only the opcodes that actually appear in W1-W5 (and the custom stream) are
modeled. This is intentional: the lab is about exposing the decode *pipeline*
(boundary detection -> prefixes -> opcode -> ModRM/SIB/disp/imm -> class ->
uops), not about building a general-purpose x86 disassembler.

Each entry describes, for a given one- or two-byte opcode, how to keep
decoding (does it need ModRM? an immediate? of what width?) and what
architectural operation it represents.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OpcodeInfo:
    mnemonic: str
    has_modrm: bool
    imm_bytes: int          # 0, 1, 4 (imm8 / imm32); resolved per-instruction for group opcodes
    op_kind: str             # "alu_rr", "alu_mi", "mov_load", "mov_store", "lea", "cmp", "test", "special"
    reg_is_opcode_ext: bool = False   # ModRM.reg selects the operation (opcode-extension groups, e.g. 0x83)


# --- one-byte opcodes ------------------------------------------------------
ONE_BYTE = {
    0x01: OpcodeInfo("ADD", True, 0, "alu_rr"),      # ADD r/m64, r64
    0x29: OpcodeInfo("SUB", True, 0, "alu_rr"),      # SUB r/m64, r64
    0x31: OpcodeInfo("XOR", True, 0, "alu_rr"),      # XOR r/m64, r64
    0x39: OpcodeInfo("CMP", True, 0, "cmp"),         # CMP r/m64, r64
    0x85: OpcodeInfo("TEST", True, 0, "test"),       # TEST r/m64, r64
    0x89: OpcodeInfo("MOV", True, 0, "mov_store"),   # MOV r/m64, r64   (reg -> r/m)
    0x8B: OpcodeInfo("MOV", True, 0, "mov_load"),    # MOV r64, r/m64   (r/m -> reg)
    0x8D: OpcodeInfo("LEA", True, 0, "lea"),         # LEA r64, m
    0x83: OpcodeInfo("GRP1", True, 1, "alu_mi", reg_is_opcode_ext=True),  # ADD/SUB/... r/m64, imm8 (sign-extended)
    0xC8: OpcodeInfo("ENTER", False, 3, "special"),  # ENTER imm16, imm8  (3 immediate bytes total, no ModRM)
}

# GRP1 (/opcode 0x83) ModRM.reg extension -> mnemonic
GRP1_EXT = {
    0b000: "ADD",
    0b101: "SUB",
    0b111: "CMP",
}

# Jcc tttn (one-byte short form 0x70-0x7F), each: opcode + rel8
JCC_ONE_BYTE = {
    0x74: "JE",
    0x75: "JNE",
}

# --- two-byte opcodes (0F xx) ----------------------------------------------
TWO_BYTE = {
    0xA2: OpcodeInfo("CPUID", False, 0, "special"),
    0x31: OpcodeInfo("RDTSC", False, 0, "special"),
    0xC1: OpcodeInfo("XADD", True, 0, "special"),    # 0F C1 /r  XADD r/m64, r64 (with LOCK prefix)
}

# String instruction opcode (used with REP/F3 prefix)
STRING_OPCODES = {
    0xA4: "MOVSB",
}
