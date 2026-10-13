# base_x4
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
ADD R20, R1, R2           ; I49
ADD R21, R3, R4           ; I50
LOAD R10, [R20 + 0]       ; I51
LOAD R11, [R21 + 0]       ; I52
FMUL F10, F2, F3          ; I53
FADD F11, F4, F5          ; I54
ADD R22, R20, R6          ; I55
IMUL R23, R22, R7         ; I56
ADD R24, R8, R9           ; I57
LOAD R12, [R24 + 0]       ; I58
FMUL F12, F10, F6         ; I59
FADD F13, F11, F7         ; I60
ADD R25, R22, R26         ; I61
LOAD R14, [R25 + 0]       ; I62
IMUL R27, R25, R28        ; I63
ADD R29, R27, R30         ; I64
LOAD R15, [R29 + 0]       ; I65
FMUL F14, F12, F8         ; I66
FADD F15, F13, F9         ; I67
ADD R31, R15, R32         ; I68
LOAD R16, [R31 + 0]       ; I69
IMUL R33, R31, R34        ; I70
ADD R35, R33, R36         ; I71
FADD F16, F14, F15        ; I72
LOAD R17, [R35 + 0]       ; I73
FMUL F17, F16, F10        ; I74
ADD R37, R35, R38         ; I75
LOAD R18, [R37 + 0]       ; I76
FADD F18, F17, F11        ; I77
IMUL R39, R37, R40        ; I78
ADD R41, R39, R42         ; I79
STORE [R41 + 0], R18      ; I80
ADD R43, R20, R44         ; I81
ADD R45, R24, R46         ; I82
LOAD R19, [R43 + 0]       ; I83
LOAD R20, [R45 + 0]       ; I84
FMUL F19, F18, F12        ; I85
FADD F20, F19, F16        ; I86
ADD R47, R43, R48         ; I87
IMUL R49, R47, R50        ; I88
LOAD R21, [R49 + 0]       ; I89
FADD F21, F20, F17        ; I90
ADD R51, R49, R52         ; I91
LOAD R22, [R51 + 0]       ; I92
FMUL F22, F21, F19        ; I93
ADD R53, R51, R54         ; I94
STORE [R53 + 0], R22      ; I95
ADD R55, R55, R56         ; I96
BR R55                    ; I97
ADD R20, R1, R2           ; I98
ADD R21, R3, R4           ; I99
LOAD R10, [R20 + 0]       ; I100
LOAD R11, [R21 + 0]       ; I101
FMUL F10, F2, F3          ; I102
FADD F11, F4, F5          ; I103
ADD R22, R20, R6          ; I104
IMUL R23, R22, R7         ; I105
ADD R24, R8, R9           ; I106
LOAD R12, [R24 + 0]       ; I107
FMUL F12, F10, F6         ; I108
FADD F13, F11, F7         ; I109
ADD R25, R22, R26         ; I110
LOAD R14, [R25 + 0]       ; I111
IMUL R27, R25, R28        ; I112
ADD R29, R27, R30         ; I113
LOAD R15, [R29 + 0]       ; I114
FMUL F14, F12, F8         ; I115
FADD F15, F13, F9         ; I116
ADD R31, R15, R32         ; I117
LOAD R16, [R31 + 0]       ; I118
IMUL R33, R31, R34        ; I119
ADD R35, R33, R36         ; I120
FADD F16, F14, F15        ; I121
LOAD R17, [R35 + 0]       ; I122
FMUL F17, F16, F10        ; I123
ADD R37, R35, R38         ; I124
LOAD R18, [R37 + 0]       ; I125
FADD F18, F17, F11        ; I126
IMUL R39, R37, R40        ; I127
ADD R41, R39, R42         ; I128
STORE [R41 + 0], R18      ; I129
ADD R43, R20, R44         ; I130
ADD R45, R24, R46         ; I131
LOAD R19, [R43 + 0]       ; I132
LOAD R20, [R45 + 0]       ; I133
FMUL F19, F18, F12        ; I134
FADD F20, F19, F16        ; I135
ADD R47, R43, R48         ; I136
IMUL R49, R47, R50        ; I137
LOAD R21, [R49 + 0]       ; I138
FADD F21, F20, F17        ; I139
ADD R51, R49, R52         ; I140
LOAD R22, [R51 + 0]       ; I141
FMUL F22, F21, F19        ; I142
ADD R53, R51, R54         ; I143
STORE [R53 + 0], R22      ; I144
ADD R55, R55, R56         ; I145
BR R55                    ; I146
ADD R20, R1, R2           ; I147
ADD R21, R3, R4           ; I148
LOAD R10, [R20 + 0]       ; I149
LOAD R11, [R21 + 0]       ; I150
FMUL F10, F2, F3          ; I151
FADD F11, F4, F5          ; I152
ADD R22, R20, R6          ; I153
IMUL R23, R22, R7         ; I154
ADD R24, R8, R9           ; I155
LOAD R12, [R24 + 0]       ; I156
FMUL F12, F10, F6         ; I157
FADD F13, F11, F7         ; I158
ADD R25, R22, R26         ; I159
LOAD R14, [R25 + 0]       ; I160
IMUL R27, R25, R28        ; I161
ADD R29, R27, R30         ; I162
LOAD R15, [R29 + 0]       ; I163
FMUL F14, F12, F8         ; I164
FADD F15, F13, F9         ; I165
ADD R31, R15, R32         ; I166
LOAD R16, [R31 + 0]       ; I167
IMUL R33, R31, R34        ; I168
ADD R35, R33, R36         ; I169
FADD F16, F14, F15        ; I170
LOAD R17, [R35 + 0]       ; I171
FMUL F17, F16, F10        ; I172
ADD R37, R35, R38         ; I173
LOAD R18, [R37 + 0]       ; I174
FADD F18, F17, F11        ; I175
IMUL R39, R37, R40        ; I176
ADD R41, R39, R42         ; I177
STORE [R41 + 0], R18      ; I178
ADD R43, R20, R44         ; I179
ADD R45, R24, R46         ; I180
LOAD R19, [R43 + 0]       ; I181
LOAD R20, [R45 + 0]       ; I182
FMUL F19, F18, F12        ; I183
FADD F20, F19, F16        ; I184
ADD R47, R43, R48         ; I185
IMUL R49, R47, R50        ; I186
LOAD R21, [R49 + 0]       ; I187
FADD F21, F20, F17        ; I188
ADD R51, R49, R52         ; I189
LOAD R22, [R51 + 0]       ; I190
FMUL F22, F21, F19        ; I191
ADD R53, R51, R54         ; I192
STORE [R53 + 0], R22      ; I193
ADD R55, R55, R56         ; I194
BR R55                    ; I195
