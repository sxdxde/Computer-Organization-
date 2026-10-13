# d_inv4_A
ADD R20, R1, R2           ; I00
LOAD R10, [R20 + 0]       ; I01
FMUL F10, F1, F2          ; I02
ADD R21, R10, R3          ; I03
FADD F11, F10, F3         ; I04
LOAD R11, [R21 + 0]       ; I05
FMUL F12, F11, F4         ; I06
IMUL R22, R11, R4         ; I07
FADD F13, F12, F5         ; I08
ADD R23, R22, R5          ; I09
FMUL F14, F13, F6         ; I10
LOAD R12, [R23 + 0]       ; I11
FADD F15, F14, F7         ; I12
IMUL R24, R12, R6         ; I13
FMUL F16, F15, F8         ; I14
ADD R25, R24, R7          ; I15
FADD F17, F16, F9         ; I16
LOAD R13, [R25 + 0]       ; I17
ADD R26, R13, R8          ; I18
LOAD R14, [R26 + 0]       ; I19
STORE [R26 + 0], F17      ; I20
ADD R27, R14, R9          ; I21
