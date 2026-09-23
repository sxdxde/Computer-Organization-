"""Workload byte streams for Exp06 (Golden Cove decoder lab).

Every stream below was hand-encoded against the x86-64 ISA and independently
verified with Capstone (see report for the verification note) before being
fed to our own simulator, so any decode discrepancy in later stages is a bug
in the lab's simulator, not in the input encodings.
"""

WORKLOADS = {
    "W1_dense_simple": bytes.fromhex(
        "48 01 D8 "   # ADD RAX, RBX
        "48 01 C8 "   # ADD RAX, RCX
        "48 31 D8 "   # XOR RAX, RBX
        "48 01 F0 "   # ADD RAX, RSI
        "48 29 D8 "   # SUB RAX, RBX
        "48 01 C1 "   # ADD RCX, RAX
        "48 31 C9 "   # XOR RCX, RCX
        "48 01 CA"    # ADD RDX, RCX
        .replace(" ", "")
    ),

    "W2_variable_length": bytes.fromhex(
        "48 8B 44 8B 10 "          # MOV RAX, [RBX+RCX*4+0x10]
        "48 83 C0 08 "             # ADD RAX, 8
        "48 01 D8 "                # ADD RAX, RBX
        "48 8B 84 8B 20 01 00 00 "  # MOV RAX, [RBX+RCX*4+0x120]
        "48 39 D8 "                # CMP RAX, RBX
        "48 83 E8 04 "             # SUB RAX, 4
        "48 89 44 8B 10"           # MOV [RBX+RCX*4+0x10], RAX
        .replace(" ", "")
    ),

    "W3_fusion": bytes.fromhex(
        "48 39 D8 75 05 "   # CMP RAX,RBX ; JNE +5   (fusion pair)
        "48 39 C8 74 05 "   # CMP RAX,RCX ; JE  +5   (fusion pair)
        "48 85 C0 75 05 "   # TEST RAX,RAX ; JNE +5  (fusion pair)
        "48 39 F0 74 05"    # CMP RAX,RSI ; JE  +5   (fusion pair)
        .replace(" ", "")
    ),

    "W4_uop_expansion_msrom": bytes.fromhex(
        "48 01 03 "          # ADD [RBX], RAX      -- ordinary, memory RMW (2 uops)
        "48 8D 04 8B "       # LEA RAX, [RBX+RCX*4] -- ordinary, AGU-only (1 uop, complex address)
        "0F A2 "             # CPUID                -- MSROM
        "0F 31 "             # RDTSC                -- MSROM
        "C8 10 00 00 "       # ENTER 0x10, 0        -- MSROM
        "F3 A4 "             # REP MOVSB            -- MSROM (fast-string)
        "F0 48 0F C1 03"     # LOCK XADD [RBX], RAX -- MSROM (locked atomic RMW)
        .replace(" ", "")
    ),

    "W5_mixed_realistic": bytes.fromhex(
        "48 01 D8 "          # ADD RAX, RBX                  (short, reg-reg)
        "48 8B 44 8B 10 "    # MOV RAX,[RBX+RCX*4+0x10]      (long, memory load)
        "48 83 C0 08 "       # ADD RAX, 8                    (immediate)
        "48 39 D8 75 05 "    # CMP RAX,RBX ; JNE +5          (fusion)
        "48 01 03 "          # ADD [RBX], RAX                (uop expansion, RMW)
        "0F A2 "             # CPUID                          (MSROM)
        "48 89 44 8B 10 "    # MOV [RBX+RCX*4+0x10], RAX      (store)
        "48 31 C9"           # XOR RCX, RCX                   (short, reg-reg)
        .replace(" ", "")
    ),

    # ---- Own investigation stream (Section 8) ----
    # Same CMP;JNE pair as in W3, but preceded by exactly five 3-byte
    # ADD instructions so that the CMP lands in D5 (the last lane of the
    # first cycle) and JNE is forced into D0 of the *next* cycle.
    "CUSTOM_fusion_across_cycle": bytes.fromhex(
        "48 01 D8 "   # ADD RAX, RBX   -> D0
        "48 01 C8 "   # ADD RAX, RCX   -> D1
        "48 01 F0 "   # ADD RAX, RSI   -> D2
        "48 01 C1 "   # ADD RCX, RAX   -> D3
        "48 01 CA "   # ADD RDX, RCX   -> D4
        "48 39 D8 "   # CMP RAX, RBX   -> D5 (last lane of cycle 0)
        "75 05"       # JNE +5         -> spills to D0 of cycle 1: no same-cycle partner
        .replace(" ", "")
    ),
}
