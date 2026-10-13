# d_counterexample
LOAD R1, [R1 + 0]         ; I00
LOAD R2, [R1 + 0]         ; I01
LOAD R3, [R2 + 0]         ; I02
LOAD R4, [R3 + 0]         ; I03
LOAD R5, [R4 + 0]         ; I04
LOAD R6, [R5 + 0]         ; I05
LOAD R7, [R6 + 0]         ; I06
LOAD R8, [R7 + 0]         ; I07
ADD R30, R8, R31          ; I08
ADD R32, R30, R33         ; I09
STORE [R32 + 0], R8       ; I10
