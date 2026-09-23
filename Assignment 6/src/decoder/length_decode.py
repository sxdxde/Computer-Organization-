"""Stage 1-4 of the decode pipeline: instruction boundary/length detection,
prefix processing (incl. REX), opcode decoding, and operand/address-field
decoding (ModRM / SIB / displacement / immediate).

This module deliberately does NOT decide instruction class or uop count --
that is stage 5/6, handled in uop_rules.py. Keeping these separate mirrors
the lab's requirement that decode() must not be a single black-box call.
"""

from dataclasses import dataclass, field
from typing import Optional

from .isa_table import ONE_BYTE, TWO_BYTE, GRP1_EXT, JCC_ONE_BYTE, STRING_OPCODES

REG64 = ["RAX", "RCX", "RDX", "RBX", "RSP", "RBP", "RSI", "RDI",
         "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]


class DecodeError(Exception):
    pass


@dataclass
class Prefixes:
    lock: bool = False
    rep: bool = False
    rex_present: bool = False
    rex_w: bool = False
    rex_r: bool = False
    rex_x: bool = False
    rex_b: bool = False
    nbytes: int = 0


@dataclass
class ModRM:
    mod: int
    reg: int          # 3-bit field, REX.R NOT yet applied
    rm: int            # 3-bit field, REX.B NOT yet applied
    reg_full: int       # with REX.R applied
    rm_full: int         # with REX.B applied (meaningless if SIB/mem)
    is_register_operand: bool   # mod == 0b11


@dataclass
class SIB:
    scale: int
    index: int    # with REX.X applied
    base: int     # with REX.B applied
    has_index: bool   # false when index field == 0b100 and no REX.X (no index register)


@dataclass
class DecodedInstruction:
    raw_bytes: bytes
    length: int
    mnemonic: str
    op_kind: str                 # alu_rr / alu_mi / cmp / test / mov_load / mov_store / lea / jcc / special
    prefixes: Prefixes
    opcode_bytes: bytes
    modrm: Optional[ModRM] = None
    sib: Optional[SIB] = None
    disp: Optional[int] = None
    disp_size: int = 0
    imm: Optional[int] = None
    imm_size: int = 0
    operand_text: str = ""       # human-readable operands, for the decoder trace
    is_two_byte_opcode: bool = False
    is_jcc: bool = False
    rel8: Optional[int] = None


def _reg_name(index: int) -> str:
    return REG64[index]


def decode_one_instruction(stream: bytes, offset: int) -> DecodedInstruction:
    """Decode exactly one instruction starting at stream[offset:].
    Implements boundary detection (by construction: we return as soon as we
    know the instruction's true length) + prefix/opcode/operand decoding.
    """
    pos = offset
    pfx = Prefixes()

    # ---- Stage 2: prefix processing (incl. REX) ----
    while pos < len(stream):
        b = stream[pos]
        if b == 0xF0:
            pfx.lock = True
            pfx.nbytes += 1
            pos += 1
        elif b == 0xF3:
            pfx.rep = True
            pfx.nbytes += 1
            pos += 1
        elif 0x40 <= b <= 0x4F:
            pfx.rex_present = True
            pfx.rex_w = bool(b & 0x08)
            pfx.rex_r = bool(b & 0x04)
            pfx.rex_x = bool(b & 0x02)
            pfx.rex_b = bool(b & 0x01)
            pfx.nbytes += 1
            pos += 1
            break  # REX must immediately precede the opcode
        else:
            break

    if pos >= len(stream):
        raise DecodeError(f"truncated instruction at offset {offset}: only prefixes found")

    # ---- Stage 3: opcode decoding ----
    opcode_start = pos
    b0 = stream[pos]
    pos += 1

    # REP + string opcode (e.g. F3 A4 = REP MOVSB) -- no ModRM, no immediate
    if pfx.rep and b0 in STRING_OPCODES:
        mnemonic = "REP " + STRING_OPCODES[b0]
        length = pos - offset
        return DecodedInstruction(
            raw_bytes=stream[offset:pos], length=length, mnemonic=mnemonic,
            op_kind="special", prefixes=pfx, opcode_bytes=stream[opcode_start:pos],
            operand_text="[RDI], [RSI]  (REP-prefixed string move)",
        )

    # Two-byte opcode escape (0F xx)
    if b0 == 0x0F:
        if pos >= len(stream):
            raise DecodeError(f"truncated two-byte opcode at offset {offset}")
        b1 = stream[pos]
        pos += 1
        info = TWO_BYTE.get(b1)
        if info is None:
            raise DecodeError(f"unsupported two-byte opcode 0F {b1:02X} at offset {offset}")
        opcode_bytes = stream[opcode_start:pos]

        if info.has_modrm:
            modrm, sib, disp, disp_size, pos = _decode_modrm_sib_disp(stream, pos)
            operand_text = _format_rr_operands(info, modrm, pfx)
            mnemonic = ("LOCK " if pfx.lock else "") + info.mnemonic
            length = pos - offset
            return DecodedInstruction(
                raw_bytes=stream[offset:pos], length=length, mnemonic=mnemonic,
                op_kind=info.op_kind, prefixes=pfx, opcode_bytes=opcode_bytes,
                modrm=modrm, sib=sib, disp=disp, disp_size=disp_size,
                operand_text=operand_text, is_two_byte_opcode=True,
            )
        else:
            length = pos - offset
            return DecodedInstruction(
                raw_bytes=stream[offset:pos], length=length, mnemonic=info.mnemonic,
                op_kind=info.op_kind, prefixes=pfx, opcode_bytes=opcode_bytes,
                operand_text="", is_two_byte_opcode=True,
            )

    # One-byte short-form Jcc (0x70-0x7F): opcode + rel8, no ModRM
    if b0 in JCC_ONE_BYTE:
        if pos >= len(stream):
            raise DecodeError(f"truncated Jcc rel8 at offset {offset}")
        rel8 = stream[pos]
        if rel8 >= 0x80:
            rel8 -= 0x100
        pos += 1
        length = pos - offset
        return DecodedInstruction(
            raw_bytes=stream[offset:pos], length=length, mnemonic=JCC_ONE_BYTE[b0],
            op_kind="jcc", prefixes=pfx, opcode_bytes=stream[opcode_start:opcode_start + 1],
            operand_text=f"rel8={rel8:+d}", is_jcc=True, rel8=rel8,
        )

    info = ONE_BYTE.get(b0)
    if info is None:
        raise DecodeError(f"unsupported opcode 0x{b0:02X} at offset {offset}")
    opcode_bytes = stream[opcode_start:pos]

    # ENTER imm16, imm8 -- no ModRM, two immediates (3 bytes total)
    if info.op_kind == "special" and info.mnemonic == "ENTER":
        if pos + 3 > len(stream):
            raise DecodeError(f"truncated ENTER operands at offset {offset}")
        imm16 = stream[pos] | (stream[pos + 1] << 8)
        imm8 = stream[pos + 2]
        pos += 3
        length = pos - offset
        return DecodedInstruction(
            raw_bytes=stream[offset:pos], length=length, mnemonic="ENTER",
            op_kind="special", prefixes=pfx, opcode_bytes=opcode_bytes,
            imm=imm16, imm_size=2, operand_text=f"0x{imm16:x}, {imm8}",
        )

    if not info.has_modrm:
        length = pos - offset
        return DecodedInstruction(
            raw_bytes=stream[offset:pos], length=length, mnemonic=info.mnemonic,
            op_kind=info.op_kind, prefixes=pfx, opcode_bytes=opcode_bytes,
        )

    modrm, sib, disp, disp_size, pos = _decode_modrm_sib_disp(stream, pos)

    mnemonic = info.mnemonic
    imm = None
    imm_size = 0
    if info.reg_is_opcode_ext:
        # GRP1 (0x83): ModRM.reg selects ADD/SUB/CMP/...; imm8 (sign-extended) follows
        mnemonic = GRP1_EXT.get(modrm.reg, f"GRP1_{modrm.reg:03b}")
        if pos >= len(stream):
            raise DecodeError(f"truncated imm8 at offset {offset}")
        raw_imm8 = stream[pos]
        imm = raw_imm8 - 0x100 if raw_imm8 >= 0x80 else raw_imm8
        imm_size = 1
        pos += 1

    operand_text = _format_operands(info, mnemonic, modrm, sib, disp, imm, pfx)
    length = pos - offset
    return DecodedInstruction(
        raw_bytes=stream[offset:pos], length=length, mnemonic=mnemonic,
        op_kind=info.op_kind, prefixes=pfx, opcode_bytes=opcode_bytes,
        modrm=modrm, sib=sib, disp=disp, disp_size=disp_size,
        imm=imm, imm_size=imm_size, operand_text=operand_text,
    )


def _decode_modrm_sib_disp(stream: bytes, pos: int):
    """Stage 4 (address side): ModRM -> optional SIB -> optional displacement."""
    if pos >= len(stream):
        raise DecodeError("truncated ModRM byte")
    m = stream[pos]
    pos += 1
    mod = (m >> 6) & 0b11
    reg = (m >> 3) & 0b111
    rm = m & 0b111

    modrm = ModRM(mod=mod, reg=reg, rm=rm, reg_full=reg, rm_full=rm,
                  is_register_operand=(mod == 0b11))

    sib = None
    disp = None
    disp_size = 0

    if mod != 0b11 and rm == 0b100:
        # SIB byte follows
        if pos >= len(stream):
            raise DecodeError("truncated SIB byte")
        s = stream[pos]
        pos += 1
        scale = (s >> 6) & 0b11
        index = (s >> 3) & 0b111
        base = s & 0b111
        sib = SIB(scale=scale, index=index, base=base, has_index=(index != 0b100))

    if mod == 0b01:
        if pos >= len(stream):
            raise DecodeError("truncated disp8")
        raw = stream[pos]
        disp = raw - 0x100 if raw >= 0x80 else raw
        disp_size = 1
        pos += 1
    elif mod == 0b10:
        if pos + 4 > len(stream):
            raise DecodeError("truncated disp32")
        raw = int.from_bytes(stream[pos:pos + 4], "little", signed=False)
        disp = raw - 0x1_0000_0000 if raw >= 0x8000_0000 else raw
        disp_size = 4
        pos += 4
    # mod == 0b00: no displacement for the addressing forms used in this lab
    # (we do not encode the RIP-relative / disp32-no-base special case).

    return modrm, sib, disp, disp_size, pos


def _mem_operand_text(modrm: ModRM, sib: Optional[SIB], disp: Optional[int]) -> str:
    if modrm.is_register_operand:
        return _reg_name(modrm.rm_full)
    if sib is not None:
        base = _reg_name(sib.base)
        parts = [base]
        if sib.has_index:
            parts.append(f"{_reg_name(sib.index)}*{1 << sib.scale}")
        text = "+".join(parts)
        if disp:
            text += f"{disp:+d}"
        return f"[{text}]"
    base = _reg_name(modrm.rm_full)
    if disp:
        return f"[{base}{disp:+d}]"
    return f"[{base}]"


def _format_rr_operands(info, modrm: ModRM, pfx: Prefixes) -> str:
    reg = _reg_name(modrm.reg_full)
    rm = _mem_operand_text(modrm, None, None)
    return f"{rm}, {reg}"


def _format_operands(info, mnemonic, modrm: ModRM, sib, disp, imm, pfx) -> str:
    reg = _reg_name(modrm.reg_full)
    rm_text = _mem_operand_text(modrm, sib, disp)
    if info.op_kind == "lea":
        return f"{reg}, {rm_text}"
    if info.op_kind == "mov_load":
        return f"{reg}, {rm_text}"
    if info.op_kind == "mov_store":
        return f"{rm_text}, {reg}"
    if info.op_kind == "cmp" or info.op_kind == "test":
        return f"{rm_text}, {reg}"
    if info.op_kind == "alu_mi":
        return f"{rm_text}, {imm}"
    # default: alu_rr, dest is r/m, src is reg (Intel r/m,reg encoding used throughout this table)
    return f"{rm_text}, {reg}"
