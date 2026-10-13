---
title: "Exp08 --- When Ready Is Not Enough: Inside the OOO Backend"
subtitle: "Computer Organization --- Scheduling, Wakeup, Selection and Execution Resources"
author: "Sudarshan Sudhakar (Roll Number: CS23B2007)"
date: "October 2026"
geometry: margin=2.2cm
fontsize: 10pt
---

## 1. Objective and Machine

A uop that is *in the scheduler* is not a uop that *executes*. Between "all operands arrived" and "starts on a unit" there
are three more gates: **select** (a unit of the right class must be free), **issue** (an issue slot must be free) and,
earlier, **wakeup** (a tag broadcast must be delivered). This report uses a cycle-level Python model (`src/sched/`) to
answer: *a uop is ready, units exist, so why did it not execute?* Every number below is read from the simulator output in
`results/` (traces, CSVs, plots); the cycle and uop IDs are the ones in `results/traces/`.

| Parameter | Machine A (baseline) |
|---|---|
| Dispatch / issue / wakeup width | 6 uops / 6 uops / 6 source operands per cycle |
| Scheduler | 24 entries |
| Units | 3 ALU, 1 IMUL, 2 FADD, 2 FMUL, 2 LOAD/AGU, 1 STA, 1 STD, 1 BR |
| Latency | ALU 1, IMUL 4, FADD 3, FMUL 4, LOAD 5, STORE 1, BRANCH 1 |

## 2. The Simulator

**Per-cycle order:** (1) *dispatch* in order, up to 6, while a scheduler entry is free; a uop dispatched in cycle *t*
can first be selected in *t+1*. (2) *select*: every ready uop competes for the free units of **its own class**, oldest
(lowest ID) first. (3) *issue*: the selected set is trimmed to the issue width, oldest first; issue frees the scheduler
entry (usable by dispatch from *t+1*). (4) *wakeup*: producers whose tag broadcast is due wake consumer source operands,
at most `wakeup_width` per cycle. (5) *complete* bookkeeping.
A producer that issues at *s* with latency *L* broadcasts at *s+L-1*; the woken operand is usable one cycle later, so a
1-cycle ALU result feeds a consumer in *s+1*. If the wakeup budget is exhausted the operand is woken a cycle later and the
consumer is "data-available but not ready" -- this is how wakeup bandwidth becomes visible.

**Events kept separate** (`results/per_uop.csv`): dispatch, operand-ready (last source usable), *first selected*, issue,
complete. Ready, selected and issued are three different per-cycle counts (`results/per_cycle.csv`): "selected" = won the
class arbitration; "issued" = also fit in the issue width. A selected-but-not-issued uop is reported separately.

**Modelling choices not in the brief** (fixed before any experiment, never tuned):

* **A unit is occupied from issue until completion** (so a LOAD holds a LOAD/AGU for 5 cycles, an IMUL holds the multiplier
  for 4). This is the simplest reading of "the resource is occupied"; a fully pipelined sensitivity run is in Section 10.3.
* A STORE is one scheduler entry with two parts, STA (address operand) and STD (data operand), each issuing on its own
  unit; the store completes when both are done. Issue width counts parts.
* Registers are renamed, so only RAW dependences exist; initial register values are live-in and ready at dispatch.
* The workload is extended with **I48 `BR R55`** (a loop-closing branch on the last ADD) so that the Branch unit is
  exercised. The 48 given instructions are unchanged. `I<n>` and `U<n>` are the same thing (one uop per instruction).
* Because the 49-uop stream is short, some experiments also use `base_x4`: four back-to-back copies (196 uops; copies
  share only live-ins and the R55 chain). The brief allows extending the stream; both are reported everywhere.

Files: `inputs/base.asm`, `inputs/*.asm` (all streams), `results/traces/<run>.txt` (cycle-by-cycle), `results/*.csv`,
`results/plots/`, `results/plots_sudarshan/`, code in `src/`.

## 3. The Workload and Its Resource Mix

{{tbl:demand}}

51 issue parts from 49 uops (the 2 stores split). `LOAD` is the most heavily demanded class: 60 unit-cycles on 2 units
means **at least 30 cycles of load-unit time**, against the 37-cycle run. IMUL (20 cycles on one unit) is second.

## 4. Investigation 1 -- Where Does the Parallelism Come From?

Complete per-cycle state of Machine A (`occ` = scheduler entries after dispatch, `wait` = occupied minus ready, `sel` =
winners of class arbitration, `iss` = issued, `lost` = ready parts that lost arbitration, `busy` = units busy after issue as ALU/IMUL/FADD/FMUL/LOAD):

{{tbl:percycle}}

*Reading it.* The scheduler fills to 24/24 at **cycle 5** and stays full to cycle 13 (dispatch blocked 9 cycles; the
last uop, U48, enters at cycle 14). The average number of *ready* uops is only **2.82** against **12.0 waiting** per
cycle, and the average issue rate is **1.5** per cycle (peak 4). 49 uops are "in flight" in the scheduler at once but at
most 6 (cycle 7) can execute. Six cycles (**8, 10, 19, 21, 25, 26**) have 2--3 ready uops and issue *nothing*: every ready uop needs
a unit class that is full (cycle 8: U34, U35 need LOAD; cycle 10: U34, U35 need LOAD, U39 needs IMUL; cycles 25--26: U24, U27 need LOAD).

![In-flight vs ready vs issued (Machine A)](../results/plots/01_base_cycle_profile.png){width=88%}

### Three dependency chains (from `results/inv1_chains.csv`)

**Chain 1 -- FP chain, the critical path.** `U04 FMUL -> U10 FMUL -> U17 FMUL -> U23 FADD -> U25 FMUL -> U28 FADD -> U36 FMUL -> U37 FADD -> U41 FADD -> U44 FMUL`

{{tbl:chain_fp}}

Every link issues in the cycle it becomes eligible (wait 0): *nothing but the producer's latency* prevents an earlier
start. The chain's latencies 4+4+4+3+4+3+4+3+3+4 = 36 plus the first-issue cycle give the run length **T = 37**; U44
completes at cycle 37. This chain, not any resource, sets execution time on Machine A.

**Chain 2 -- integer address -> multiply -> load chain.** `U00 -> U06 -> U12 -> U14 (IMUL) -> U15 -> U16 (LOAD) -> U19 -> U21 (IMUL) -> U22 -> U26 -> U29 (IMUL) -> U30 -> U31 (STORE)`

{{tbl:chain_int}}

Here U14 becomes eligible at **cycle 4** (U12 completes) but issues at **cycle 7**: the single IMUL is held by U07 (issued
cycle 3). This three-cycle resource delay pushes U15, U16 and U19 later; the chain still finishes (U31 completes cycle 33)
before the FP chain (37), so it does not set T.

**Chain 3 -- second address chain.** `U00 -> U32 -> U38 -> U39 (IMUL) -> {U40 LOAD, U42 -> U43 LOAD, U45} -> U46 (STORE)`

{{tbl:chain_addr2}}

U39 waits 1 cycle for the multiplier (held by U14, cycles 7--11); U40 waits 2 and U43 waits **6 cycles** for a LOAD unit.

**Independent work that executes while a chain waits.** While the FP chain sits in U17's 4-cycle latency (cycles 9--13),
the machine issues U38 (cycle 9), U15 and U39 (cycle 11), U16 and U34 (cycle 12): work from chains 2 and 3. While chain 2
waits for U14 (cycles 4--6), the machine issues U11 (cycle 4), U10 (cycle 5), and U32, U33 (cycle 6). *In flight* (49
entries over the run, up to 24 at once) is therefore very different from *can execute now* (2.82 on average).

## 5. Investigation 2 -- The Ready-uop Problem

All 27 cycles with >=2 ready uops are in `results/inv2_multi_ready_cycles.csv`. Three are analysed in full.

**Case 1 -- Cycle 4** (scheduler 20/24)

| Field | Value |
|---|---|
| Ready uops | U09 LOAD, U11 FADD, U13 LOAD, U14 IMUL |
| Selected | U11 |
| Ready but unselected | U09, U13, U14 |
| Required / available resource | LOAD x2 needed, **0 free** (both held by U02, U03 until cycle 7). IMUL needed, **0 free** (held by U07 until cycle 7). FADD needed, 2 free |
| Issue slots | 1 of 6 used (5 free) |
| Wakeup availability | 6 per cycle, 2 used (no pressure) |

Why each stayed: **U09** -- LOAD0/LOAD1 are occupied by U02 and U03, issued cycle 2, each holding a unit 5 cycles, free at
cycle 7. **U13** -- same two units, same reason. **U14** -- IMUL0 is occupied by U07 (issued cycle 3, 4-cycle latency,
free at cycle 7). None of these was beaten by a priority decision: no unit of their class existed to give. Meanwhile ALU
had 3 idle units and 5 issue slots were unused.

**Case 2 -- Cycle 7** (scheduler 24/24, dispatch blocked)

| Field | Value |
|---|---|
| Ready uops | U09, U13, U34, U35 (all LOAD); U14 IMUL; U18 FADD |
| Selected | U09, U13, U14, U18 |
| Ready but unselected | U34, U35 |
| Required / available resource | LOAD needed by 4, **2 free** (U02/U03 complete at 7). IMUL 1 free (U07 completes at 7), FADD 2 free (U11 completes at 7), ALU 3 free |
| Issue slots | 4 used, 2 remaining |
| Wakeup availability | 6 available, 0 used |

U34 and U35 became ready at cycle 7 together with U09 and U13, but only two LOAD units came free. The tie-break (oldest
first) gave them to U09 and U13; the *condition* behind the loss is that **four loads wanted a two-unit class in the same
cycle**. Because a load then holds its unit for 5 cycles, U34 and U35 are blocked again at cycles 8--11. Two issue slots
were left unused -- slots were not the constraint.

**Case 3 -- Cycle 12** (scheduler 24/24)

| Field | Value |
|---|---|
| Ready uops | U16, U34, U35 (all LOAD) |
| Selected | U16, U34 |
| Ready but unselected | U35 |
| Required / available resource | LOAD x3, **2 free** (U09/U13 complete at 12). ALU 3, FADD 2, FMUL 1 free but unrequested |
| Issue slots | 2 used, 4 remaining |
| Wakeup availability | 6 available, 1 used |

U35 had been ready since cycle 7 yet loses to **U16, which became ready only this cycle**: select orders by program
order, not by waiting time. U35 then waits until cycle 17 (10 cycles ready-to-issue) because U16 and U34 occupy both units
from 12 to 17.

## 6. Investigation 3 -- Execution-Resource Contention

Classification is the table in Section 3. **LOAD is the most demanded resource**: 41 of the 45 ready-but-unselected
uop-cycles in the whole run are loads (the other 4 are U14 waiting for the multiplier). Utilization over 38 cycles: LOAD
78.9%, IMUL 52.6%, FMUL 31.6%, FADD 27.6%, ALU 14.0%, STA/STD 5.3%, BR 2.6%.

**Case A -- many ready uops, one resource.** Cycle 7 above: four loads for two units; also cycle 16 (U35, U40, U43 vs the
two units held by U16/U34 until 17).

**Case B -- units idle while ready work waits.** **Cycle 4**: U09/U13/U14 wait while **3 ALUs, 1 FADD, 1 FMUL, STA, STD,
BR are free**. Across the run, in **23 of 38 cycles** some other class had idle units while a ready uop waited, with 192
idle unit-slots in those cycles (`results/tables/stranded.md`). Total execution capacity is therefore a poor predictor: the
machine has 13 units and 6 issue slots, but the work that is *ready* is made of loads, and "a unit is available" (an ALU is
idle) is not "a unit **capable of executing this uop** is available" (a LOAD/AGU is). Integer ALUs cannot execute IMUL
or LOAD; FP units cannot execute address arithmetic.

![Per-class demand: unit-cycles / units](../results/plots/03_class_demand.png){width=70%}

## 7. Investigation 4 -- Dependency Structure

Kernel (20 uops: 7 ADD, 3 LOAD, 2 IMUL, 3 FMUL, 4 FADD, 1 STORE). **Version A** keeps long producer-consumer chains
(`inputs/s_inv4_A.asm`); **Version B** (`s_inv4_B.asm`) keeps the *same opcodes and destinations* but every source is a
fresh live-in, so no uop depends on another.

```
A:  ADD R20,R1,R2 ; ADD R21,R20,R3 ; LOAD R10,[R21] ; ADD R22,R10,R4 ; LOAD R11,[R22] ; FMUL F10,F2,F3 ;
    FADD F11,F10,F4 ; FMUL F12,F11,F5 ; FADD F13,F12,F6 ; IMUL R23,R11,R7 ; ADD R24,R23,R8 ; LOAD R12,[R24] ;
    FMUL F14,F13,F7 ; FADD F15,F14,F8 ; ADD R25,R12,R9 ; IMUL R26,R25,R13 ; ADD R27,R26,R14 ;
    STORE [R27],F15 ; FADD F16,F15,F9 ; ADD R28,R27,R15
```

{{tbl:inv4_s}}

*What changed.* In A the ready pool never exceeds **2 uops** and **15 of 31 cycles** have waiting uops but none ready;
every issue is a single link of a chain (e.g. cycles 2, 3, 5: U01, U02, U06 issue one per cycle). Nothing ever competes
(0 ready-but-unselected), so units sit idle and execution time is the sum of chain latencies, **31 cycles**. In B, 6
uops issue at cycle 1 and the ready pool reaches **7**: now the units matter. Contention appears (12 ready-unselected
uop-cycles, e.g. cycle 3: U14, U16, U17.STA, U17.STD issue but others queue; cycle 4: six ready, only U19 issues, the
other five need busy LOAD/IMUL units) and time falls to **11 cycles**. Scheduler occupancy *dropped* (9.35 -> 7.43) because B
drains its entries instead of holding them: a fuller scheduler (A) is *worse*, not better. Independence turned latency-bound
execution into resource-bound execution.

![Ready and occupancy, A vs B](../results/plots/07_inv4_dependency.png){width=88%}

## 8. Investigation 5 -- Scheduler Capacity

**Predictions (static analysis, Section 10.1).** *Base:* the run is bound by the 37-cycle FP chain; a 12-entry scheduler
will delay dispatch of later (in-order) uops a little, 48 entries will not help. *Base x4:* the window is not the limit;
LOAD capacity is (120-cycle bound), so 48 entries should help little, while 12 will hurt.

{{tbl:inv5}}

(`1x` = the 49-uop kernel, `x4` = four copies; `lost` = ready-but-unselected uop-cycles; `window` = scheduler capacity; `mix:` = no single constraint buys more than half of the gap to the dataflow bound.)

* **More useful work enters the scheduler?** Only because dispatch finishes sooner: on base, 48 entries gives 0 dispatch-blocked
  cycles (vs 9) and peak occupancy 34. On base_x4 average occupancy goes 20.6 -> 33.2.
* **More uops become ready?** Yes: base_x4 average ready 6.1 -> 10.4, peak 10 -> 19.
* **More issue opportunities?** No: issue rate stays **1.659** at 24, 48 and 96 entries.
* **Better utilisation?** No: LOAD utilisation is **96.8% at every size** from 24 up: already saturated.
* **Another bottleneck?** The bottleneck was already LOAD/AGU: 1073 uop-cycles of ready-unselected waiting at 48 entries
  vs 546 at 24, but the same 123 cycles.

**Little-improvement case:** base_x4, 24 -> 48 -> 96 entries: **123, 123, 123 cycles**. The extra entries hold *more ready
loads* (ready-unselected doubles) but there are still only 2 LOAD units, each busy 5 cycles per load. **The only
improvements are on the downside**: 12 entries cost +2 cycles (base) and +13 (x4); 6 entries cost +5 and +33. The 12-entry
base run slows because dispatch is in order: the second address chain U32...U46 is dispatched at cycles 17--28 instead of 5--14, U43 issues at
33 instead of 22 and U46 completes at **39**, overtaking the FP chain (37) as the longest path. The window turned a non-critical chain critical.

## 9. Investigation 6 -- Issue and Wakeup Limits

**Prediction:** the workload averages 1.5 issues/cycle with a peak of 4, so 3-wide issue/wakeup should cost 0--1 cycles.

{{tbl:inv6}}

Configuration A (3/3) vs B (6/6): **37 vs 37 cycles** on base, **124 vs 123** on x4. The extra bandwidth is used in only a
handful of cycles. With width 3, `selected-not-issued` fires 4 times: cycle 1 (U05 loses to U00, U01, U04), cycle 2 (U06 and
U08 lose to U02, U03, U05) and cycle 12 (U39). With wakeup 3, cycle 4 has 6 operands to wake and only 3 are granted (3
deferred) and cycle 26 defers 1. They delay a few uops by one cycle (U06, U08 issue at cycle 3 instead of 2, so U07 starts
at 4 instead of 3), but none of them is on the FP critical path. Only at **2/2** does the machine slow (41 / 128 cycles,
12 selected-not-issued, 23 deferred wakeups). **Next limiting resource:** on base the FP chain (critical path); on x4 the
two LOAD/AGU units (96.8% busy). The workload does not contain enough *executable* work to use 6 issue slots: only 6 cycles
issue more than 2 uops.

![Issue/wakeup sweep](../results/plots/05_inv6_issue_wakeup.png){width=70%}

## 10. Investigation 7 -- The Bottleneck Moves

### 10.1 How predictions were made

`src/predict.py` computes, from the program text alone, the dataflow critical path and for each class
`ceil(sum of unit-occupancy / units)`; predicted time = the larger, predicted limiter = whichever attains it.
`results/predictions.csv` was produced before `run_all.py`. The actual limiter is found by *relaxing each constraint
one at a time* (infinite scheduler, issue width, wakeup, each unit class) and seeing which relaxation buys cycles
(`results/bottleneck_attribution.csv`). If no relaxation helps, execution is dataflow-bound.

{{tbl:bounds}}

### 10.2 The machines (A--F required, plus follow-ups G--K)

{{tbl:inv7}}

| Machine | Prediction | Outcome | Bottleneck moved? |
|---|---|---|---|
| **B** sched 48 | no gain; scheduler not limiting | base 37, x4 123 | No: LOAD/AGU stays limiting |
| **C** 4 ALUs | no gain; ALU util is 14% | 37 / 123 | No: ALU was never contended |
| **D** 2 IMUL | base: no gain (dataflow); x4: no gain, LOAD limits | 37 / 123 | No. IMUL gain only appears once LOAD is fixed (G) |
| **E** 3 LOAD | x4 -> 80 cycles, limiter becomes IMUL | 37 / **96**, ready-unsel 546 -> 135 | **Yes**, but to scheduler window + IMUL, not IMUL alone |
| **F** issue 8 | no gain; 1.66 issues/cycle vs 6 | 37 / 123 | No |
| **G** 3 LOAD + 2 IMUL | x4 -> 80, limiter LOAD | 37 / **90** | **Yes**: scheduler window (-5) and LOAD (-3) |

**Result for E (the central one).** Prediction 80 cycles was **wrong** (actual 96). The static bound ignores that after
the third load unit the 24-entry in-order window and the single multiplier together keep the pipeline from refilling: relaxing the
scheduler would give -9, an unlimited IMUL -6, an unlimited LOAD only -1. The bottleneck moved from *LOAD/AGU* to a
*window + multiplier* limit. After G (add a second IMUL) the remaining gains come from scheduler capacity (-5) and LOAD (-3):
the limit is no longer one structure. Fully pipelined units (K, 85 cycles) leave the scheduler as the dominant limiter
(-22): once execution resources stop being the problem, window size is.

On the single-iteration workload **every machine A--K gives 37 cycles**: the FP chain is the only thing that matters, which
is why the bottleneck "moves" in secondary metrics only (E cuts ready-unselected uop-cycles 45 -> 9, utilisation of LOAD
78.9% -> 52.6%).

![Execution time per machine](../results/plots/06_inv7_machines.png){width=95%}

### 10.3 Pipelining sensitivity

{{tbl:pipelined}}

If every unit accepted a new uop each cycle the single-iteration time would be unchanged (37) while x4 falls 123 -> 85:
the model's "occupied for the whole latency" assumption is what makes the base stream contend at all.

## 11. The OOO Crime Scene -- Cycle 4

```
Cycle: 4
Scheduler: occupied 20/24, ready 4, waiting 16
Ready uops:    U09 LOAD R12,[R24]   U11 FADD F13,F11,F7   U13 LOAD R14,[R25]   U14 IMUL R27,R25,R28
Selected uops: U11
Execution resources:
  Available (free at select): ALU 3/3, FADD 2/2, FMUL 1/2, STA 1, STD 1, BR 1, IMUL 0/1, LOAD 0/2
  Busy: IMUL0 = U07 (issued c3, free c7)   LOAD0 = U02, LOAD1 = U03 (issued c2, free c7)
        FMUL0 = U04 (until c5)   FADD = U11 (selected now)
Issue slots: Used 1   Remaining 5
Wakeup: Available 6 operands/cycle   Used 2   (no deferral)
Waiting (16): U10, U15--U29 -- e.g. U15 waits on R27 from U14; U17 waits on F12 from U10 (ready c9)
```

**Why did U11 execute and not U09, U13, U14?**

```
U14 did not execute
  v  U14 requires the integer multiplier
  v  the only IMUL unit is occupied (IMUL0 busy until c7, 4-cycle non-pipelined)
  v  U07 was selected at cycle 3 and holds it
  v  U07 was the only IMUL-ready uop at cycle 3 (U14 became ready at cycle 4, one cycle later)
  v  U07 became ready at cycle 3 when U06 completed (U06: ADD R22, issued c2)
  v  U06 became ready at cycle 2 when U00 completed (U00: ADD R20, live-in sources, issued c1)
```

```
U09 and U13 did not execute
  v  both require LOAD/AGU;  v  both units occupied (U02, U03 issued c2, 5 cycles)
  v  U02/U03 were selected at cycle 2 when their address U00 completed
```

U11 won only because it needs FADD and two FADD units were free: **there was no priority decision at all**. The unsettling
part is that U07's result R23 and the loads' results R10, R11 (U02, U03), R12 (U09), R14 (U13) are *never read* by any later uop: in this
stream only 3 of the 12 loads (U16, U27, U43) feed anything. The oldest-ready work, much of it dead, occupied the units that the live
chain uop U14 needed, and later dead loads (U34, U35, U40) delayed the live load U43 by 6 cycles. The scheduler orders by
program order and readiness; it cannot see which result matters.

## 12. One Architecture I Would Change: LOAD/AGU 2 -> 3

**Poorly matched parameter:** the load/AGU count. **Workload characteristic:** a high density of loads (12 of 49 uops, 60
of 146 unit-cycles) that each hold a unit 5 cycles, many arriving at the same time. **Trace evidence**

* 41 of 45 ready-but-unselected uop-cycles are loads; U34 waits 5 cycles (ready c7, issue c12), U35 waits 10 (c7 -> c17),
  U43 waits 6 (c16 -> c22), U09 waits 4, U20 4, U24 4.
* LOAD utilisation is 78.9% on base and **96.8% on base_x4**; relaxing LOAD alone saves 28 of the 86 cycles above the
  critical path (x4).
* In cycles 4, 7, 12, 16, 18 the *other* units are idle (ALU 3/3 free at cycle 4).

**Result (Machine E):** base_x4 **123 -> 96 cycles (-22%)**, ready-but-unselected uop-cycles 546 -> 135, IPC 1.59 -> 2.04. On
base alone T stays **37** because the critical FP chain is untouched, but unselected load-cycles fall 41 -> 4 and the
integer chains finish earlier. I would not claim the benefit for latency-bound code.

## 13. Final Challenge -- A Workload Where the Third Load Unit Does Not Help

`inputs/s_counterexample.asm`: 8 independent loads, 10 independent IMULs, 4 ADDs that consume IMUL results.

{{tbl:counterexample_s}}

* Machine A: **42 cycles**. Machine E (3 LOAD/AGU): **42 cycles**: no change. LOAD utilisation falls 46.5% -> 31%,
  i.e. the extra unit is simply under-used. The single IMUL is **93% busy** (40 of 43 cycles): the 10 multiplies serialise
  at 4 cycles each; on average 6.5 uops are ready at once and 232 uop-cycles of ready work lose arbitration, mostly for the multiplier.
* The real limiter: Machine D (2 IMUL) gives **22 cycles**; G (3 LOAD + 2 IMUL) gives 22 as well.

![Counterexample on Machine E: the IMULs serialise on one multiplier](../results/plots_sudarshan/s3_counterexample_gantt.png){width=88%}

Adding load capacity helps only when loads are the limiting class **and** the loads are independent enough to use more
units. Here another resource and a different unit class determine performance.

## 14. Concise Technical Analysis

1. **Ready is not issued.** On Machine A the scheduler holds up to 24 uops but the average ready count is 2.82 and the
   average issue rate 1.5 (of 6). 27 of 38 cycles have >=2 ready uops; 45 uop-cycles of ready work lost class arbitration
   (41 loads, 4 IMUL). A uop's fate is set by *a unit of its class being free in that cycle*.
2. **Execution time is set by the longest dependency chain unless a unit class saturates.** On base, T = 37 equals the
   FP chain U04...U44 and *no* resource change (A--K) alters it; on base_x4 the 2 LOAD units (96.8% busy) set T.
3. **Idle capacity is not available capacity.** 23 of 38 cycles had idle units of another class while ready uops waited.
4. **Bigger structures often do nothing.** 48/96-entry scheduler: 123 cycles; 8-wide issue: 123; 4 ALUs: 123. They only
   enlarge the pool of waiting loads (ready-unselected 546 -> 1073).
5. **Bottlenecks interact.** Fixing LOAD moved the limit to window + IMUL (prediction 80 cycles, actual 96); a second IMUL
   gave 90; the static bound is within 3% on Machine A (120 vs 123) but 12--20% too optimistic once LOAD is fixed (80 vs 90 / 96), because it ignores refill of the in-order window.
6. **The scheduler is criticality-blind.** At cycle 4 the multiplier and both load units served uops (U07, U02, U03) whose
   results are never read, delaying U14, U09 and U13.
7. **Limitations.** Latency table and "occupied for full latency" are simplifications; no memory dependences, no
   branch misprediction, no cache misses; select is oldest-first.
