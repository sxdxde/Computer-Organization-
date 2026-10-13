| machine | T 1x | T x4 | pred. T x4 | pred. limiter | actual limiter | gain if relaxed (x4) |
|---|---|---|---|---|---|---|
| A orig | 37 | 123 | 120 | LOAD | LOAD | LOAD -28 |
| B sched48 | 37 | 123 | 120 | LOAD | LOAD | LOAD -36 |
| C alu4 | 37 | 123 | 120 | LOAD | LOAD | LOAD -28 |
| D imul2 | 37 | 123 | 120 | LOAD | LOAD | LOAD -36 |
| E load3 | 37 | 96 | 80 | IMUL | mix: window, IMUL, LOAD | window -9, IMUL -6, LOAD -1 |
| F issue8 | 37 | 123 | 120 | LOAD | LOAD | LOAD -28 |
| G load3 imul2 | 37 | 90 | 80 | LOAD | mix: window, LOAD | window -5, LOAD -3 |
| H load4 | 37 | 96 | 80 | IMUL | mix: IMUL, window, LOAD | window -6, IMUL -9, LOAD -1 |
| I load3 imul2 fmul3 | 37 | 90 | 80 | LOAD | mix: window, LOAD | window -5, LOAD -5 |
| J loadpipe | 37 | 95 | 80 | IMUL | mix: window, IMUL | window -8, IMUL -8 |
| K allpipe | 37 | 85 | 37 | dataflow | mix: window, IMUL | window -22, IMUL -1 |
