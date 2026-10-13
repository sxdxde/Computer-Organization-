| wl | issue/wake | T | issue rate | avg rdy | sel-not-issued | wakes deferred | lost | LOAD util | limiter |
|---|---|---|---|---|---|---|---|---|---|
| 1x | I2/W2 | 41 | 1.342 | 2.03 | 12 | 23 | 14 | 0.714 | mix: issue, wake, LOAD |
| 1x | I3/W3 | 37 | 1.457 | 2.31 | 4 | 4 | 27 | 0.789 | dataflow |
| 1x | I3/W6 | 37 | 1.457 | 2.34 | 4 | 0 | 28 | 0.789 | dataflow |
| 1x | I6/W3 | 37 | 1.5 | 2.82 | 0 | 1 | 45 | 0.789 | dataflow |
| 1x | I4/W4 | 37 | 1.5 | 2.82 | 0 | 0 | 45 | 0.789 | dataflow |
| 1x | I6/W6 | 37 | 1.5 | 2.82 | 0 | 0 | 45 | 0.789 | dataflow |
| x4 | I2/W2 | 128 | 1.594 | 4.8 | 88 | 105 | 323 | 0.93 | mix: LOAD, issue, wake |
| x4 | I3/W3 | 124 | 1.645 | 5.7 | 16 | 6 | 489 | 0.96 | mix: LOAD, issue |
| x4 | I3/W6 | 124 | 1.645 | 5.72 | 19 | 0 | 488 | 0.96 | mix: LOAD, issue |
| x4 | I6/W3 | 123 | 1.659 | 5.85 | 0 | 12 | 515 | 0.968 | LOAD |
| x4 | I4/W4 | 123 | 1.659 | 5.96 | 8 | 2 | 522 | 0.968 | LOAD |
| x4 | I6/W6 | 123 | 1.659 | 6.1 | 0 | 0 | 546 | 0.968 | LOAD |
