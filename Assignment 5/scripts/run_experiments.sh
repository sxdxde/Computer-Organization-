#!/usr/bin/env bash
# Exp05 - runs the full experiment matrix (mode x threads x reps) and
# wraps each run with /usr/bin/time -l to capture instructions retired,
# cycles elapsed, and context-switch counts (the closest thing to hardware
# performance counters available in userspace on macOS/Apple Silicon,
# which does not expose perf_event_open or a CMN snoop-filter PMU).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$HERE/src/coherence_workload"
OUT="$HERE/results/results.csv"
NEVENTS=80000000
REPS=7
MODES=(baseline true false false_free redesigned)
THREADS=(1 2 4 8 10)

echo "mode,nthreads,nevents,wall_s,grand_sum,grand_count,group_sum,group_count,counter_total,cas_retries,real_s,user_s,sys_s,maxrss_kb,page_reclaims,page_faults,voluntary_cs,involuntary_cs,instructions_retired,cycles_elapsed,peak_footprint" > "$OUT"

run_one() {
  local mode=$1 nt=$2 rep=$3
  local tf
  tf=$(mktemp)
  local csv
  csv=$(/usr/bin/time -l "$BIN" "$mode" "$nt" "$NEVENTS" "$((42 + rep))" 2> "$tf")
  local real user sys maxrss reclaims faults vcs ics instr cycles peak
  # the "N.NN real  N.NN user  N.NN sys" triple lives on one line -> pull by position
  read -r real _ user _ sys _ < <(awk '/real/ && /user/ && /sys/{print $1, $2, $3, $4, $5, $6}' "$tf")
  maxrss=$(awk '/maximum resident set size/{print $1}' "$tf")
  reclaims=$(awk '/page reclaims/{print $1}' "$tf")
  faults=$(awk '/page faults/{print $1}' "$tf")
  vcs=$(awk '/voluntary context switches/ && !/involuntary/{print $1}' "$tf")
  ics=$(awk '/involuntary context switches/{print $1}' "$tf")
  instr=$(awk '/instructions retired/{print $1}' "$tf")
  cycles=$(awk '/cycles elapsed/{print $1}' "$tf")
  peak=$(awk '/peak memory footprint/{print $1}' "$tf")
  rm -f "$tf"
  echo "${csv},${real},${user},${sys},${maxrss},${reclaims},${faults},${vcs},${ics},${instr},${cycles},${peak}" >> "$OUT"
}

for mode in "${MODES[@]}"; do
  for nt in "${THREADS[@]}"; do
    for rep in $(seq 1 "$REPS"); do
      echo "running mode=$mode threads=$nt rep=$rep ..." >&2
      run_one "$mode" "$nt" "$rep"
    done
  done
done

echo "done -> $OUT" >&2
