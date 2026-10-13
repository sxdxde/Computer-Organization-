"""Instruction streams for Exp07. Each is written to ../inputs/<name>.asm so the exact input is a deliverable."""
from pathlib import Path

INPUTS = Path(__file__).resolve().parent.parent / "inputs"


def _ll_body(reps):
    """Long-latency workload: LOAD first, then `reps` copies of the 6-instruction independent body."""
    out = ["LOAD R1, [A]"]
    body = ["ADD R2, R10, R11", "ADD R3, R12, R13", "MUL R4, R14, R15",
            "ADD R5, R16, R17", "ADD R6, R18, R19", "ADD R7, R20, R21"]
    return out + body * reps


def _ind_body(reps):
    body = ["ADD R2, R10, R11", "ADD R3, R12, R13", "MUL R4, R14, R15",
            "ADD R5, R16, R17", "ADD R6, R18, R19", "ADD R7, R20, R21"]
    return body * reps


INV1 = ["ADD R1, R20, R21", "ADD R2, R22, R23", "MUL R4, R1, R2", "ADD R1, R5, R6",
        "ADD R8, R1, R9", "ADD R2, R10, R11", "ADD R3, R2, R4", "ADD R1, R3, R8",
        "MUL R4, R1, R1", "ADD R2, R4, R1", "ADD R8, R2, R3", "ADD R1, R8, R2"]

WORKLOADS = {
    "inv1_rename": INV1,
    "inv1b_rename_x5": INV1 * 5,
    "inv2a_loads_LQ": [f"LOAD R{k}, [A{k}]" for k in range(1, 11)],
    "inv2b_stores_SQ": [f"STORE [S{k}], R{20 + k}" for k in range(1, 9)],
    "inv2c_dependents_IQ": ["LOAD R1, [A]"] + [f"ADD R{2 + k % 8}, R1, R10" for k in range(20)],
    "inv3_longlat": _ll_body(20),
    "inv4_independent": _ind_body(20),
    "inv6a_short_lifetime": ["ADD R1, R2, R3", "ADD R1, R4, R5", "ADD R6, R1, R7"],
    "inv6b_long_lifetime": ["ADD R1, R2, R3", "LOAD R6, [R1]", "ADD R1, R4, R5", "ADD R8, R1, R9"],
    "inv6c_one_reg_many_versions": ["LOAD R9, [A]"] + ["ADD R1, R2, R3"] * 40,
    "inv7_mispredict": """
ADD R1, R2, R3
ADD R4, R5, R6
BRANCH B1 pred=T actual=NT
ADD R7, R1, R8
ADD R9, R4, R10
MUL R11, R7, R12
ADD R13, R14, R15
WRONGPATH B1
ADD R7, R16, R17
MUL R9, R7, R18
LOAD R12, [B]
STORE [C], R9
ADD R13, R7, R19
END
""",
    "inv7_correct": """
ADD R1, R2, R3
ADD R4, R5, R6
BRANCH B1 pred=NT actual=NT
ADD R7, R1, R8
ADD R9, R4, R10
MUL R11, R7, R12
ADD R13, R14, R15
""",
    "inv7b_late_resolve": """
LOAD R1, [A]
ADD R4, R5, R6
BRANCH B1 pred=T actual=NT src=R1
ADD R7, R1, R8
ADD R9, R4, R10
MUL R11, R7, R12
ADD R13, R14, R15
WRONGPATH B1
ADD R7, R16, R17
MUL R9, R7, R18
LOAD R12, [B]
STORE [C], R9
ADD R13, R7, R19
ADD R2, R7, R9
ADD R3, R2, R7
END
""",
    "final_sq_behind_load": ["LOAD R1, [A]"] + ["STORE [S%d], R%d" % (k, 20 + k) if i == 0 else
                             "ADD R%d, R%d, R%d" % (2 + (3 * k + i) % 6, 10 + i, 12 + i)
                             for k in range(1, 7) for i in range(3)],
    "final_ckpt": """
LOAD R1, [A]
ADD R2, R10, R11
BRANCH B1 pred=NT actual=NT src=R1
ADD R3, R12, R13
ADD R4, R14, R15
BRANCH B2 pred=NT actual=NT src=R1
ADD R5, R16, R17
BRANCH B3 pred=NT actual=NT src=R1
ADD R6, R18, R19
ADD R7, R20, R21
ADD R8, R10, R12
ADD R9, R11, R13
""",
}
# 'inv5' runs reuse inv3_longlat; 'inv4' also reuses it (see run_all.py)


def write_inputs():
    INPUTS.mkdir(exist_ok=True)
    for name, body in WORKLOADS.items():
        text = body if isinstance(body, str) else "\n".join(body)
        (INPUTS / f"{name}.asm").write_text(f"# {name}\n" + text.strip() + "\n")


def load(name):
    from ooo.isa import parse_program
    body = WORKLOADS[name]
    return parse_program(body if isinstance(body, str) else "\n".join(body))
