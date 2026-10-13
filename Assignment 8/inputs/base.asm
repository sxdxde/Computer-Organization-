# base
ADD R20, R1, R2           ; I00
ADD R21, R3, R4           ; I01
LOAD R10, [R20 + 0]       ; I02
LOAD R11, [R21 + 0]       ; I03
FMUL F10, F2, F3          ; I04
FADD F11, F4, F5          ; I05
ADD R22, R20, R6          ; I06
IMUL R23, R22, R7         ; I07
ADD R24, R8, R9           ; I08
LOAD R12, [R24 + 0]       ; I09
FMUL F12, F10, F6         ; I10
FADD F13, F11, F7         ; I11
ADD R25, R22, R26         ; I12
LOAD R14, [R25 + 0]       ; I13
IMUL R27, R25, R28        ; I14
ADD R29, R27, R30         ; I15
LOAD R15, [R29 + 0]       ; I16
FMUL F14, F12, F8         ; I17
FADD F15, F13, F9         ; I18
ADD R31, R15, R32         ; I19
LOAD R16, [R31 + 0]       ; I20
IMUL R33, R31, R34        ; I21
ADD R35, R33, R36         ; I22
FADD F16, F14, F15        ; I23
LOAD R17, [R35 + 0]       ; I24
FMUL F17, F16, F10        ; I25
ADD R37, R35, R38         ; I26
LOAD R18, [R37 + 0]       ; I27
FADD F18, F17, F11        ; I28
IMUL R39, R37, R40        ; I29
ADD R41, R39, R42         ; I30
STORE [R41 + 0], R18      ; I31
ADD R43, R20, R44         ; I32
ADD R45, R24, R46         ; I33
LOAD R19, [R43 + 0]       ; I34
LOAD R20, [R45 + 0]       ; I35
FMUL F19, F18, F12        ; I36
FADD F20, F19, F16        ; I37
ADD R47, R43, R48         ; I38
IMUL R49, R47, R50        ; I39
LOAD R21, [R49 + 0]       ; I40
FADD F21, F20, F17        ; I41
ADD R51, R49, R52         ; I42
LOAD R22, [R51 + 0]       ; I43
FMUL F22, F21, F19        ; I44
ADD R53, R51, R54         ; I45
STORE [R53 + 0], R22      ; I46
ADD R55, R55, R56         ; I47
BR R55                    ; I48
