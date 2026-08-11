"""
Top-level driver: runs the Sequential / Repeated / Strided access patterns
through independent I-Cache and D-Cache direct-mapped simulators, prints a
formatted report to stdout, and dumps the same results as JSON so the LaTeX
report can be generated from real simulation numbers.
"""

import json
import os

import cache
from cache import run_stream
from patterns import build_workloads


def fmt_pct(x):
    return f"{100 * x:.2f}%"


def stats_to_dict(stats):
    mb = stats.miss_breakdown
    return {
        "accesses": stats.accesses,
        "lookups": stats.lookups,
        "hits": stats.hits,
        "misses": stats.misses,
        "hit_rate": stats.hit_rate,
        "miss_rate": stats.miss_rate,
        "cold_misses": mb.cold,
        "conflict_misses": mb.conflict,
        "capacity_misses": mb.capacity,
    }


def print_row(stats):
    mb = stats.miss_breakdown
    print(f"    {stats.name:<22} "
          f"acc={stats.accesses:<7} lookups={stats.lookups:<7} "
          f"hits={stats.hits:<7} misses={stats.misses:<7} "
          f"hit%={fmt_pct(stats.hit_rate):<8} miss%={fmt_pct(stats.miss_rate):<8} "
          f"| cold={mb.cold:<5} conflict={mb.conflict:<5} capacity={mb.capacity:<5}")


def main():
    print("=" * 100)
    print("DIRECT-MAPPED CACHE SIMULATOR -- I-Cache / D-Cache")
    print(f"Main memory : {cache.MAIN_MEMORY_WORDS} words (64K)")
    print(f"Cache size  : {cache.CACHE_WORDS} words (2K)  |  Block size: {cache.BLOCK_WORDS} words "
          f"|  Lines: {cache.NUM_LINES}")
    print(f"Address split -> Tag: {cache.TAG_BITS} bits | Index: {cache.INDEX_BITS} bits "
          f"| Offset: {cache.OFFSET_BITS} bits  (32-bit word address)")
    print("=" * 100)

    workloads = build_workloads()
    results = {}

    # ---------------- Sequential ----------------
    print("\n[1] SEQUENTIAL ACCESS PATTERN (spatial locality)")
    results["sequential"] = {}
    for kind in ("instruction", "data"):
        cname = "I-Cache" if kind == "instruction" else "D-Cache"
        stats = run_stream(f"{cname} (sequential)", workloads["sequential"][kind])
        print_row(stats)
        results["sequential"][kind] = stats_to_dict(stats)

    # ---------------- Repeated ----------------
    print("\n[2] REPEATED ACCESS PATTERN (temporal locality)")
    results["repeated"] = {}
    for subcase, streams in workloads["repeated"].items():
        print(f"  -- {subcase} --")
        results["repeated"][subcase] = {}
        for kind in ("instruction", "data"):
            cname = "I-Cache" if kind == "instruction" else "D-Cache"
            stats = run_stream(f"{cname} (repeated/{subcase})", streams[kind])
            print_row(stats)
            results["repeated"][subcase][kind] = stats_to_dict(stats)

    # ---------------- Strided ----------------
    print("\n[3] STRIDED ACCESS PATTERN (varying stride)")
    results["strided"] = {}
    for stride, streams in workloads["strided"].items():
        print(f"  -- stride = {stride} --")
        results["strided"][str(stride)] = {}
        for kind in ("instruction", "data"):
            cname = "I-Cache" if kind == "instruction" else "D-Cache"
            stats = run_stream(f"{cname} (stride={stride})", streams[kind])
            print_row(stats)
            results["strided"][str(stride)][kind] = stats_to_dict(stats)

    print("\n" + "=" * 100)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
