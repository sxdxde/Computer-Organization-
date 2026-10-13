| uop | instruction | eligible (operand-ready) c | because | issue c | complete c | wait | why it waited |
|---|---|---|---|---|---|---|---|
| U00 | ADD R20, R1, R2 | 1 | live-in/dispatch | 1 | 2 | 0 | - |
| U06 | ADD R22, R20, R6 | 2 | U00->R20 | 2 | 3 | 0 | - |
| U12 | ADD R25, R22, R26 | 3 | U06->R22 | 3 | 4 | 0 | - |
| U14 | IMUL R27, R25, R28 | 4 | U12->R25 | 7 | 11 | 3 | IMUL unit(s) occupied by U07 |
| U15 | ADD R29, R27, R30 | 11 | U14->R27 | 11 | 12 | 0 | - |
| U16 | LOAD R15, [R29 + 0] | 12 | U15->R29 | 12 | 17 | 0 | - |
| U19 | ADD R31, R15, R32 | 17 | U16->R15 | 17 | 18 | 0 | - |
| U21 | IMUL R33, R31, R34 | 18 | U19->R31 | 18 | 22 | 0 | - |
| U22 | ADD R35, R33, R36 | 22 | U21->R33 | 22 | 23 | 0 | - |
| U26 | ADD R37, R35, R38 | 23 | U22->R35 | 23 | 24 | 0 | - |
| U29 | IMUL R39, R37, R40 | 24 | U26->R37 | 24 | 28 | 0 | - |
| U30 | ADD R41, R39, R42 | 28 | U29->R39 | 28 | 29 | 0 | - |
| U31 | STORE [R41 + 0], R18 | 32 | U27->R18 | 32 | 33 | 0 | - |
