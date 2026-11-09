"""EXP-10 analysis: producer->consumer result delivery on Golden Cove.

Everything is derived from two Intel documents:
  * Optimization Reference Manual Vol.1 rev 050, Table 2-5 (bypass delay, p.2-14, PDF p.58)
  * Golden Cove Instruction Throughput and Latency (350392-002, tpt_lat-glc-client.json)

Run:  python3 src/exp10.py      (writes results/*.csv and results/summary.txt)
"""
import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"

# --------------------------------------------------------------------------
# Intel Table 2-5, transcribed from the rendered page (not from text extraction)
# --------------------------------------------------------------------------
T25_COLS = ["SIMD/0,1/1", "FMA/0,1/4", "MUL/0,1/4", "FastAdder/1,5/3",
            "SIMD/5/1,3", "SHUF/1,5/1,3", "V2I/0/3"]
T25 = {  # FROM row -> bypass delay to each TO column, in T25_COLS order
    "SIMD/0,1/1":      [0, 1, 1, 1, 0, 0, 0],
    "FMA/0,1/4":       [1, 0, 1, 0, 0, 0, 0],
    "MUL/0,1/4":       [1, 0, 1, 0, 0, 0, 0],
    "FastAdder/0,1/3": [1, 0, 1, -1, 0, 0, 0],   # row label printed "0,1" in the manual
    "SIMD/5/1,3":      [0, 1, 1, 1, 0, 0, 0],
    "SHUF/1,5/1,3":    [0, 0, 1, 0, 0, 0, 0],
    "V2I/0/3":         [0, 0, 1, 0, 0, 0, 0],
    "I2V/5/1":         [0, 1, 1, 0, 0, 0, 0],
}
# category -> (Table 2-5 row label, Table 2-5 column label)
CAT = {
    "FA":   ("FastAdder/0,1/3", "FastAdder/1,5/3"),
    "FMA":  ("FMA/0,1/4", "FMA/0,1/4"),
    "MUL":  ("MUL/0,1/4", "MUL/0,1/4"),
    "SHUF": ("SHUF/1,5/1,3", "SHUF/1,5/1,3"),
}


def bypass(pcat, ccat):
    return T25[CAT[pcat][0]][T25_COLS.index(CAT[ccat][1])]


# --------------------------------------------------------------------------
# Instruction -> unit / ports / latency, from Intel's Golden Cove JSON (ymm, reg-reg forms)
#   uop_lat : latency of the uop on its unit (the number in the Table 2-5 label)
#   csv_lat : the "Latency" column of the Throughput&Latency file (a measured, whole-instruction figure)
# --------------------------------------------------------------------------
ISA = {
    "vaddps":      dict(cat="FA",   ports=(5, 1), uop_lat=3, csv_lat=2, tput=0.5),
    "vmulps":      dict(cat="MUL",  ports=(0, 1), uop_lat=4, csv_lat=4, tput=0.5),
    "vfmadd231ps": dict(cat="FMA",  ports=(0, 1), uop_lat=4, csv_lat=4, tput=0.5),
    "vshufps":     dict(cat="SHUF", ports=(5, 1), uop_lat=1, csv_lat=1, tput=0.5),
}

# latency models used throughout (edge delay = producer-issue -> earliest consumer-issue)
MODELS = {
    "M1": "uop latency + Table 2-5 bypass (primary)",
    "M2": "uop latency only (bypass ignored)",
    "M3": "Intel 'Latency' column only",
    "M4": "Intel 'Latency' + bypass (mixes conventions; shown as a warning)",
}


def lat_of(ins, model):
    return ins.csv_lat if model in ("M3", "M4") else ins.uop_lat


def edge_delay(p, c, model):
    b = bypass(p.cat, c.cat) if model in ("M1", "M4") else 0
    return lat_of(p, model) + b


# --------------------------------------------------------------------------
@dataclass
class Ins:
    stream: str
    idx: int
    text: str
    mnem: str
    dst: str
    srcs: list           # [(reg, role)]
    group: str
    cat: str = ""
    ports: tuple = ()
    uop_lat: int = 0
    csv_lat: int = 0
    deps: list = field(default_factory=list)   # [(producer idx, reg, role)]

    @property
    def id(self):
        return f"{self.stream}#{self.idx}"

    @property
    def short(self):
        return f"{self.mnem} {self.dst}"


def parse(stream):
    path = ROOT / "inputs" / f"stream_{stream}.asm"
    out, group = [], stream
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            group = line[1:].strip().split(":")[0].split()[0]
            continue
        mnem, rest = line.split(None, 1)
        ops = [o.strip() for o in rest.split(",")]
        regs = [o for o in ops if re.fullmatch(r"ymm\d+", o)]
        dst = regs[0]
        srcs = [(r, f"src{i+1}") for i, r in enumerate(regs[1:])]
        if mnem == "vfmadd231ps":          # dst = src1*src2 + dst  -> dst is also read
            srcs.append((dst, "acc"))
        info = ISA[mnem]
        out.append(Ins(stream, len(out), line, mnem, dst, srcs, group,
                       info["cat"], info["ports"], info["uop_lat"], info["csv_lat"]))
    link_raw(out)
    return out


def link_raw(ins):
    """True (RAW) dependences from register names, program order = sequential semantics."""
    last = {}
    for i in ins:
        seen = set()
        for reg, role in i.srcs:
            if reg in last and reg not in seen:
                i.deps.append((last[reg], reg, role))
                seen.add(reg)
        last[i.dst] = i.idx


def name_deps(ins):
    """WAR / WAW name dependences (removed by register renaming), for the report."""
    war = waw = 0
    last_w, readers = {}, defaultdict(list)
    for i in ins:
        for reg, _ in i.srcs:
            readers[reg].append(i.idx)
        if i.dst in last_w:
            waw += 1
        war += sum(1 for r in readers[i.dst] if r < i.idx and r != i.idx)
        last_w[i.dst] = i.idx
        readers[i.dst] = []
    return war, waw


def asap(ins, model, only_groups=False):
    """Earliest issue cycle with unlimited ports/scheduler: issue = max(producer issue + delay)."""
    t = {}
    for i in ins:
        t[i.idx] = max([0] + [t[p] + edge_delay(ins[p], i, model)
                              for p, _, _ in i.deps
                              if not only_groups or ins[p].group == i.group])
    return t


def finish(ins, t, model):
    return max(t[i.idx] + lat_of(i, model) for i in ins)


def list_schedule(nodes, order=None):
    """Port-constrained greedy list scheduler.
    nodes: list of dict(cat, ports, lat, deps=[(pred_index, delay)]).  1 uop / port / cycle,
    oldest-first, scheduler/ROB/front-end unbounded, renaming ideal.  Model, not hardware."""
    n = len(nodes)
    issue = [None] * n
    pending = list(range(n)) if order is None else list(order)
    t = 0
    while pending:
        used, still = set(), []
        for k in pending:
            nd = nodes[k]
            ok = all(issue[p] is not None and issue[p] + d <= t for p, d in nd["deps"])
            if ok:
                for p in nd["ports"]:
                    if p not in used:
                        used.add(p)
                        issue[k] = t
                        break
            if issue[k] is None:
                still.append(k)
        pending = still
        t += 1
    done = max(issue[k] + nodes[k]["lat"] for k in range(n))
    return issue, done


def nodes_from(ins, model="M1", only_groups=False):
    ns = []
    for i in ins:
        ns.append(dict(cat=i.cat, ports=i.ports, lat=lat_of(i, model),
                       deps=[(p, edge_delay(ins[p], i, model)) for p, _, _ in i.deps
                             if not only_groups or ins[p].group == i.group]))
    return ns


# --------------------------------------------------------------------------
def write_csv(name, header, rows):
    with open(RES / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def interpret(p, c, b):
    L = p.uop_lat
    if b > 0:
        return f"+{b}: consumer issues {L}+{b}={L + b} cyc after producer (1 extra cyc vs. latency alone)"
    if b < 0:
        return f"{b}: consumer issues {L}{b}={L + b} cyc after producer (faster than {L}-cyc latency; Fast Adder back-to-back)"
    return f"0: no extra delay; consumer issues {L} cyc after producer (= producer uop latency)"


def stream_AB(summary):
    rows, pair_sets = [], {}
    for s in "AB":
        ins = parse(s)
        pairs = set()
        for c in ins:
            for p_idx, reg, role in c.deps:
                p = ins[p_idx]
                b = bypass(p.cat, c.cat)
                pairs.add((p.cat, c.cat))
                rows.append([f"{p.id} {p.text}", f"{c.id} {c.text}", p.cat, c.cat, reg, role,
                             CAT[p.cat][0], CAT[c.cat][1], p.uop_lat, p.csv_lat, b,
                             "zero" if b == 0 else ("positive" if b > 0 else "negative"),
                             p.uop_lat + b, interpret(p, c, b)])
        pair_sets[s] = pairs
        res = {}
        for m in MODELS:
            t = asap(ins, m)
            res[m] = finish(ins, t, m)
        summary[f"{s}_critical_path"] = res
        summary[f"{s}_nonzero_edges"] = sum(1 for c in ins for p, _, _ in c.deps
                                            if bypass(ins[p].cat, c.cat) != 0)
        summary[f"{s}_bypass_sum"] = sum(bypass(ins[p].cat, c.cat) for c in ins for p, _, _ in c.deps)
        summary[f"{s}_war_waw"] = name_deps(ins)
    summary["pairs_A_only"] = sorted(pair_sets["A"] - pair_sets["B"])
    summary["pairs_B_only"] = sorted(pair_sets["B"] - pair_sets["A"])
    summary["pairs_common"] = sorted(pair_sets["A"] & pair_sets["B"])
    write_csv("timing_table_AB.csv",
              ["producer", "consumer", "producer_cat", "consumer_cat", "reg", "operand_role",
               "table25_row", "table25_col", "producer_uop_latency", "producer_intel_csv_latency",
               "bypass_delay", "bypass_class", "issue_to_issue_delay_M1", "timing_interpretation"], rows)
    # schedule file
    srows = []
    for s in "AB":
        ins = parse(s)
        for m in MODELS:
            t = asap(ins, m)
            for i in ins:
                srows.append([s, m, i.id, i.text, i.cat, t[i.idx], t[i.idx] + lat_of(i, m)])
    write_csv("schedule_AB.csv", ["stream", "model", "id", "instruction", "cat", "issue", "complete"], srows)


def stream_C(summary):
    ins = parse("C")
    # transitive ancestors
    anc = {}
    for i in ins:
        a = set()
        for p, _, _ in i.deps:
            a |= {p} | anc[p]
        anc[i.idx] = a
    c1 = {i.idx for i in ins if i.group == "C1"}
    c2 = {i.idx for i in ins if i.group == "C2"}
    rows, cross = [], []
    t_w = asap(ins, "M1")
    t_i = asap(ins, "M1", only_groups=True)
    port_w, done_w = list_schedule(nodes_from(ins))
    port_i, done_i = list_schedule(nodes_from(ins, only_groups=True))
    for i in ins:
        prods = ";".join(f"{ins[p].id}({ins[p].group}) via {r}[{role}]" for p, r, role in i.deps) or "(none: all sources are initial values)"
        dep_c1 = bool(anc[i.idx] & c1) if i.group != "C1" else None
        dep_c2 = bool(anc[i.idx] & c2) if i.group != "C2" else None
        for p, r, role in i.deps:
            if ins[p].group != i.group:
                cross.append((ins[p].id, ins[p].group, i.id, i.group, r))
        rows.append([i.id, i.group, i.text, i.cat, "/".join(map(str, i.ports)), prods,
                     "" if dep_c1 is None else dep_c1, "" if dep_c2 is None else dep_c2,
                     t_w[i.idx], t_i[i.idx], port_w[i.idx], port_i[i.idx]])
    write_csv("stream_C_deps.csv",
             ["id", "group", "instruction", "cat", "ports", "true_RAW_producers",
              "depends_on_chain1", "depends_on_chain2", "asap_asWritten", "asap_intendedIndependent",
              "portsched_asWritten", "portsched_intendedIndependent"], rows)
    chain_alone = {}
    for g in ("C1", "C2", "C3"):
        sub = [i for i in ins if i.group == g]
        t = {}
        for i in sub:
            t[i.idx] = max([0] + [t[p] + edge_delay(ins[p], i, "M1") for p, _, _ in i.deps if p in t])
        chain_alone[g] = max(t[i.idx] + i.uop_lat for i in sub)
    summary["C_chain_alone_asap"] = chain_alone
    summary["C_cross_edges"] = cross
    summary["C_asap_asWritten"] = finish(ins, t_w, "M1")
    summary["C_asap_intended"] = finish(ins, t_i, "M1")
    summary["C_port_asWritten"] = done_w
    summary["C_port_intended"] = done_i
    summary["C_war_waw"] = name_deps(ins)
    summary["C_dep_c1"] = [i.id for i in ins if i.group != "C1" and not (anc[i.idx] & c1)]
    summary["C_indep_of_c1"] = [i.id for i in ins if i.group != "C1" and not (anc[i.idx] & c1)]
    summary["C_dep_on_c1"] = [i.id for i in ins if i.group != "C1" and (anc[i.idx] & c1)]
    # sum of three standalone chains vs overlapped
    summary["C_sum_alone"] = sum(chain_alone.values())


def stream_D(summary):
    ins = parse("D")
    n = len(ins)
    # adjacent-pair table
    rows = []
    for k in range(1, n):
        p, c = ins[k - 1], ins[k]
        b = bypass(p.cat, c.cat)
        rows.append([p.id, c.id, p.mnem, c.mnem, c.deps and c.deps[0][2], p.cat, c.cat, p.uop_lat, b,
                     p.uop_lat + b])
    # check every instruction has exactly the previous one as producer through ymm0
    assert all(i.deps and i.deps[0][0] == i.idx - 1 for i in ins[1:]), "D is not a pure chain"
    write_csv("stream_D_pairs.csv",
              ["producer", "consumer", "producer_mnem", "consumer_mnem", "operand_role", "producer_cat",
               "consumer_cat", "producer_uop_latency", "bypass", "issue_to_issue_M1"], rows)
    res = {}
    for m in MODELS:
        t = asap(ins, m)
        # loop-carried: ymm0 produced by last instruction feeds first of next copy
        wrap = edge_delay(ins[-1], ins[0], m)
        res[m] = dict(issue_last=t[n - 1], complete=finish(ins, t, m),
                      period=t[n - 1] + wrap, wrap=wrap)
    summary["D_models"] = res
    t = asap(ins, "M1")
    write_csv("schedule_D.csv", ["id", "instruction", "cat", "issue_M1", "complete_M1"],
              [[i.id, i.text, i.cat, t[i.idx], t[i.idx] + i.uop_lat] for i in ins])
    cnt = defaultdict(int)
    for i in ins:
        cnt[i.cat] += 1
    summary["D_mix"] = dict(cnt)
    # edge-type census for D
    census = defaultdict(int)
    for k in range(1, n):
        census[(ins[k - 1].cat, ins[k].cat)] += 1
    summary["D_census"] = dict(census)

    # --- independent work: k copies of the D chain, R repetitions each --------
    R = 20
    out = []
    one = parse("D")
    for k in (1, 2, 3, 4, 6, 8, 10, 11, 12, 16, 24):
        nodes, order = [], []
        # layout: index = ((rep*n)+pos)*k + copy  (round-robin interleave by program position)
        for rep in range(R):
            for pos in range(n):
                for cp in range(k):
                    ins_ = one[pos]
                    deps = []
                    if rep * n + pos > 0:
                        pp = (rep * n + pos - 1) * k + cp
                        prod = one[(pos - 1) % n]
                        deps.append((pp, edge_delay(prod, ins_, "M1")))
                    nodes.append(dict(cat=ins_.cat, ports=ins_.ports, lat=ins_.uop_lat, deps=deps))
        _, done = list_schedule(nodes)
        out.append([k, len(nodes), done, round(len(nodes) / done, 3)])
    # fully independent (no deps) with the same mix
    nodes = []
    for _ in range(R * 12):
        for i in one:
            nodes.append(dict(cat=i.cat, ports=i.ports, lat=i.uop_lat, deps=[]))
    _, done = list_schedule(nodes)
    summary["D_independent_ipc"] = round(len(nodes) / done, 3)
    write_csv("ipc_vs_chains.csv", ["independent_chains", "uops", "cycles", "uops_per_cycle"], out)
    summary["D_ipc_curve"] = out
    # port-feasible lower bound for the mix: p0 only MUL/FMA, p5 only FA/SHUF, p1 anything
    mf = cnt["MUL"] + cnt["FMA"]
    fa = cnt["FA"] + cnt["SHUF"]
    best = min(T for T in range(1, 100) if mf <= 2 * T and fa <= 2 * T and mf + fa <= 3 * T)
    summary["D_port_bound_cycles_per_20"] = best


def main():
    RES.mkdir(exist_ok=True)
    summary = {}
    stream_AB(summary)
    stream_C(summary)
    stream_D(summary)
    lines = []
    for k, v in summary.items():
        lines.append(f"{k}: {v}")
    (RES / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
