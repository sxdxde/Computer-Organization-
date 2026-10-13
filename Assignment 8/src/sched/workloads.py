"""Instruction streams for Exp08. Each is written to ../inputs/<name>.asm so the exact input is a deliverable."""
from pathlib import Path

INPUTS = Path(__file__).resolve().parent.parent.parent / "inputs"

BASE = """ADD R20, R1, R2
ADD R21, R3, R4
LOAD R10, [R20 + 0]
LOAD R11, [R21 + 0]
FMUL F10, F2, F3
FADD F11, F4, F5
ADD R22, R20, R6
IMUL R23, R22, R7
ADD R24, R8, R9
LOAD R12, [R24 + 0]
FMUL F12, F10, F6
FADD F13, F11, F7
ADD R25, R22, R26
LOAD R14, [R25 + 0]
IMUL R27, R25, R28
ADD R29, R27, R30
LOAD R15, [R29 + 0]
FMUL F14, F12, F8
FADD F15, F13, F9
ADD R31, R15, R32
LOAD R16, [R31 + 0]
IMUL R33, R31, R34
ADD R35, R33, R36
FADD F16, F14, F15
LOAD R17, [R35 + 0]
FMUL F17, F16, F10
ADD R37, R35, R38
LOAD R18, [R37 + 0]
FADD F18, F17, F11
IMUL R39, R37, R40
ADD R41, R39, R42
STORE [R41 + 0], R18
ADD R43, R20, R44
ADD R45, R24, R46
LOAD R19, [R43 + 0]
LOAD R20, [R45 + 0]
FMUL F19, F18, F12
FADD F20, F19, F16
ADD R47, R43, R48
IMUL R49, R47, R50
LOAD R21, [R49 + 0]
FADD F21, F20, F17
ADD R51, R49, R52
LOAD R22, [R51 + 0]
FMUL F22, F21, F19
ADD R53, R51, R54
STORE [R53 + 0], R22
ADD R55, R55, R56""".splitlines()

# Extension (allowed by the brief): a loop-closing conditional branch on the last ADD so the Branch unit is exercised.
BASE_BR = BASE + ["BR R55"]


def repeat(lines, k):
    """k back-to-back copies (renaming removes WAW/WAR; iterations only share live-ins and the R55 chain)."""
    return list(lines) * k


WORKLOADS = {"base": BASE_BR, "base_x4": repeat(BASE_BR, 4)}


def write_inputs(extra=None):
    INPUTS.mkdir(parents=True, exist_ok=True)
    allw = dict(WORKLOADS)
    allw.update(extra or {})
    for name, lines in allw.items():
        body = "\n".join(f"{l:<26}; I{i:02d}" for i, l in enumerate(lines))
        (INPUTS / f"{name}.asm").write_text(f"# {name}\n{body}\n")


# ----------------------------------------------------------------------------------------------------------
# Machines used by Investigation 7 (each changes exactly one thing relative to Machine A).
from .config import Machine

MA = Machine()
MACHINES = {
    "A_orig": MA,
    "B_sched48": MA.but(sched_size=48),
    "C_alu4": MA.but(alu=4),
    "D_imul2": MA.but(imul=2),
    "E_load3": MA.but(load=3),
    "F_issue8": MA.but(issue_width=8),
    # my own follow-ups (the bottleneck-moving chain and the load-port variants)
    "G_load3_imul2": MA.but(load=3, imul=2),
    "H_load4": MA.but(load=4),
    "I_load3_imul2_fmul3": MA.but(load=3, imul=2, fmul=3),
    "J_loadpipe": MA.but(pipelined=("LOAD",)),
    "K_allpipe": MA.but(pipelined=("ALU", "IMUL", "FADD", "FMUL", "LOAD")),
}


# ----------------------------------------------------------------------------------------------------------
def decouple(lines):
    """Version B of Investigation 4: same opcodes, same destinations, but every source becomes a fresh live-in
    register, so no uop consumes another uop's result (operation mix is identical by construction)."""
    from .simulator import parse_line
    out, n = [], [100, 100]
    for l in lines:
        op, dst, parts = parse_line(l)
        def fresh(r):
            k = 1 if r.startswith("F") else 0
            n[k] += 1
            return f"{'F' if k else 'R'}{n[k]}"
        if op == "LOAD":
            out.append(f"LOAD {dst}, [{fresh('R')} + 0]")
        elif op == "STORE":
            out.append(f"STORE [{fresh('R')} + 0], {fresh(parts[1][0])}")
        elif op == "BR":
            out.append(f"BR {fresh('R')}")
        else:
            out.append(f"{op} {dst}, " + ", ".join(fresh(s) for s in parts[0]))
    return out


# Investigation 4 kernels (one per author, different mixes). A = dependency-heavy, B = decoupled copy of A.
S_INV4_A = """ADD R20, R1, R2
ADD R21, R20, R3
LOAD R10, [R21 + 0]
ADD R22, R10, R4
LOAD R11, [R22 + 0]
FMUL F10, F2, F3
FADD F11, F10, F4
FMUL F12, F11, F5
FADD F13, F12, F6
IMUL R23, R11, R7
ADD R24, R23, R8
LOAD R12, [R24 + 0]
FMUL F14, F13, F7
FADD F15, F14, F8
ADD R25, R12, R9
IMUL R26, R25, R13
ADD R27, R26, R14
STORE [R27 + 0], F15
FADD F16, F15, F9
ADD R28, R27, R15""".splitlines()

D_INV4_A = """ADD R20, R1, R2
LOAD R10, [R20 + 0]
FMUL F10, F1, F2
ADD R21, R10, R3
FADD F11, F10, F3
LOAD R11, [R21 + 0]
FMUL F12, F11, F4
IMUL R22, R11, R4
FADD F13, F12, F5
ADD R23, R22, R5
FMUL F14, F13, F6
LOAD R12, [R23 + 0]
FADD F15, F14, F7
IMUL R24, R12, R6
FMUL F16, F15, F8
ADD R25, R24, R7
FADD F17, F16, F9
LOAD R13, [R25 + 0]
ADD R26, R13, R8
LOAD R14, [R26 + 0]
STORE [R26 + 0], F17
ADD R27, R14, R9""".splitlines()

# Final challenge counterexamples.
# S: a 3rd Load/AGU cannot help a stream whose long pole is the single integer multiplier.
S_CX = []
for k in range(8):
    S_CX.append(f"LOAD R{10 + k}, [R{40 + k} + 0]")
for k in range(10):
    S_CX.append(f"IMUL R{60 + k}, R{80 + k}, R{90 + k}")
for k in range(4):
    S_CX.append(f"ADD R{120 + k}, R{60 + 2 * k}, R{61 + 2 * k}")
# D: pipelining the Load/AGU cannot help a pointer-chasing chain (each load needs the previous load's value).
D_CX = ["LOAD R1, [R1 + 0]"] * 1 + [f"LOAD R{2 + k}, [R{1 + k} + 0]" for k in range(7)] + \
       ["ADD R30, R8, R31", "ADD R32, R30, R33", "STORE [R32 + 0], R8"]

EXTRA = {"s_inv4_A": S_INV4_A, "s_inv4_B": decouple(S_INV4_A), "d_inv4_A": D_INV4_A, "d_inv4_B": decouple(D_INV4_A),
         "s_counterexample": S_CX, "d_counterexample": D_CX}
