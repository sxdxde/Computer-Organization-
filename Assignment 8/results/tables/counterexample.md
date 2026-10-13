| workload | machine | T | LOAD util | IMUL util | ready-unsel | avg ready | limiter |
|---|---|---|---|---|---|---|---|
| s_counterexample | A_orig | 42 | 0.465 | 0.93 | 232 | 6.51 | IMUL |
| s_counterexample | E_load3 | 42 | 0.31 | 0.93 | 207 | 5.87 | IMUL |
| s_counterexample | J_loadpipe | 42 | 0.093 | 0.93 | 184 | 5.28 | IMUL |
| s_counterexample | D_imul2 | 22 | 0.87 | 0.87 | 132 | 8.11 | mix: dispatch width, IMUL |
| s_counterexample | G_load3_imul2 | 22 | 0.58 | 0.87 | 107 | 6.79 | mix: IMUL, dispatch width |
| d_counterexample | A_orig | 44 | 0.444 | 0.0 | 0 | 0.27 | dataflow |
| d_counterexample | E_load3 | 44 | 0.296 | 0.0 | 0 | 0.27 | dataflow |
| d_counterexample | J_loadpipe | 44 | 0.089 | 0.0 | 0 | 0.27 | dataflow |
| d_counterexample | D_imul2 | 44 | 0.444 | 0.0 | 0 | 0.27 | dataflow |
| d_counterexample | G_load3_imul2 | 44 | 0.296 | 0.0 | 0 | 0.27 | dataflow |
