| uop | instruction | eligible (operand-ready) c | because | issue c | complete c | wait | why it waited |
|---|---|---|---|---|---|---|---|
| U00 | ADD R20, R1, R2 | 1 | live-in/dispatch | 1 | 2 | 0 | - |
| U32 | ADD R43, R20, R44 | 6 | U00->R20 | 6 | 7 | 0 | - |
| U38 | ADD R47, R43, R48 | 9 | U32->R43 | 9 | 10 | 0 | - |
| U39 | IMUL R49, R47, R50 | 10 | U38->R47 | 11 | 15 | 1 | IMUL unit(s) occupied by U14 |
| U40 | LOAD R21, [R49 + 0] | 15 | U39->R49 | 17 | 22 | 2 | LOAD unit(s) occupied by U16, U34 |
| U42 | ADD R51, R49, R52 | 15 | U39->R49 | 15 | 16 | 0 | - |
| U43 | LOAD R22, [R51 + 0] | 16 | U42->R51 | 22 | 27 | 6 | LOAD unit(s) occupied by U16, U34 |
| U45 | ADD R53, R51, R54 | 16 | U42->R51 | 16 | 17 | 0 | - |
| U46 | STORE [R53 + 0], R22 | 27 | U43->R22 | 27 | 28 | 0 | - |
