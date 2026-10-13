| wl | machine | crit. path | LOAD | IMUL | FMUL | FADD | ALU | pred. T | pred. limiter | sim. T |
|---|---|---|---|---|---|---|---|---|---|---|
| 1x | A orig | 37 | 30 | 20 | 12 | 11 | 6 | 37 | dataflow | 37 |
| 1x | E load3 | 37 | 20 | 20 | 12 | 11 | 6 | 37 | dataflow | 37 |
| x4 | A orig | 37 | 120 | 80 | 48 | 42 | 22 | 120 | LOAD | 123 |
| x4 | E load3 | 37 | 80 | 80 | 48 | 42 | 22 | 80 | IMUL | 96 |
