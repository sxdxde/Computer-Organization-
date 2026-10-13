| machine | T | LOAD util | IMUL util | lost | avg rdy | limiter |
|---|---|---|---|---|---|---|
| A orig | 42 | 0.465 | 0.93 | 232 | 6.51 | IMUL |
| E load3 | 42 | 0.31 | 0.93 | 207 | 5.87 | IMUL |
| J loadpipe | 42 | 0.093 | 0.93 | 184 | 5.28 | IMUL |
| D imul2 | 22 | 0.87 | 0.87 | 132 | 8.11 | mix: dispatch width, IMUL |
| G load3 imul2 | 22 | 0.58 | 0.87 | 107 | 6.79 | mix: IMUL, dispatch width |
