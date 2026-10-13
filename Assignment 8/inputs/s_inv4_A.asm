# s_inv4_A
ADD R20, R1, R2           ; I00
ADD R21, R20, R3          ; I01
LOAD R10, [R21 + 0]       ; I02
ADD R22, R10, R4          ; I03
LOAD R11, [R22 + 0]       ; I04
FMUL F10, F2, F3          ; I05
FADD F11, F10, F4         ; I06
FMUL F12, F11, F5         ; I07
FADD F13, F12, F6         ; I08
IMUL R23, R11, R7         ; I09
ADD R24, R23, R8          ; I10
LOAD R12, [R24 + 0]       ; I11
FMUL F14, F13, F7         ; I12
FADD F15, F14, F8         ; I13
ADD R25, R12, R9          ; I14
IMUL R26, R25, R13        ; I15
ADD R27, R26, R14         ; I16
STORE [R27 + 0], F15      ; I17
FADD F16, F15, F9         ; I18
ADD R28, R27, R15         ; I19
