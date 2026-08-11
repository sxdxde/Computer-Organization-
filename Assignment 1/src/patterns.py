"""
Address-stream generators for the three memory access patterns required by
the assignment. Every pattern is generated twice, independently, with
addresses expressed as WORD numbers into the 64K-word (2^16) main memory:

  * an "instruction" stream  -> feeds the I-Cache
  * a  "data"        stream  -> feeds the D-Cache

The two streams for a given pattern use disjoint address regions purely so
that instruction and data traffic don't accidentally alias one another --
this mirrors a Harvard-style split between code and data segments and lets
the I-cache and D-cache results be interpreted independently.
"""

from cache import MAIN_MEMORY_WORDS, BLOCK_WORDS, CACHE_WORDS, NUM_LINES

# ----------------------------------------------------------------------
# Region layout inside the 64K-word address space (word addresses)
# ----------------------------------------------------------------------
CODE_BASE = 0x0000        # instruction streams live here
DATA_BASE = 0x8000        # data streams live here (32K words in)

assert DATA_BASE + 8192 <= MAIN_MEMORY_WORDS


# ----------------------------------------------------------------------
# 1) Sequential (spatial locality)
# ----------------------------------------------------------------------
def sequential(base: int, length: int):
    """base, base+1, base+2, ... base+length-1 -- straight-line code /
    linear array traversal."""
    return [base + i for i in range(length)]


# ----------------------------------------------------------------------
# 2) Repeated (temporal locality)
# ----------------------------------------------------------------------
def repeated(base: int, working_set: int, iterations: int):
    """Repeatedly sweep the same `working_set`-word window `iterations`
    times -- models a loop body (instructions) or loop-carried variables
    (data) being reused over and over."""
    block = [base + i for i in range(working_set)]
    return block * iterations


# ----------------------------------------------------------------------
# 3) Strided
# ----------------------------------------------------------------------
def strided(base: int, stride: int, count: int):
    """base, base+stride, base+2*stride, ... -- fixed-stride access,
    e.g. every 2nd / 4th / 16th word. Large strides relative to the
    16-word block defeat spatial locality and can also induce cache
    conflicts when stride is a multiple of the cache's line span."""
    return [base + i * stride for i in range(count)]


def conflicting_stride(base: int, num_streams: int, repeats: int):
    """
    Round-robins across `num_streams` addresses that are each exactly
    CACHE_WORDS (one full cache size) apart, so every one of them maps
    to the SAME direct-mapped index but carries a different tag.
    Repeated `repeats` times.

    A fully-associative cache only needs `num_streams` lines (a handful)
    to hold this whole working set, so a reference LRU cache of the same
    total capacity (128 lines) hits after the first sweep. The direct
    -mapped cache, however, can hold only ONE of these blocks at a time
    in that index/set, so it thrashes forever -> pure conflict misses.
    """
    addrs = [base + s * CACHE_WORDS for s in range(num_streams)]
    return addrs * repeats


# ----------------------------------------------------------------------
# Concrete workloads used by the simulator
# ----------------------------------------------------------------------
def build_workloads():
    """
    Returns a dict:
        pattern_name -> { 'instruction': [...addrs...], 'data': [...addrs...] }
    (strided is further split into sub-cases by stride value)
    """
    workloads = {}

    # ---- Sequential: 4096 consecutive words (= 4x the 128-line/16-word
    #      cache capacity of 2048 words) so we see cold misses dominate,
    #      with no reuse at all. ----
    SEQ_LEN = 4096
    workloads["sequential"] = {
        "instruction": sequential(CODE_BASE, SEQ_LEN),
        "data": sequential(DATA_BASE, SEQ_LEN),
    }

    # ---- Repeated: small working set, swept many times (fits in cache
    #      -> demonstrates temporal locality benefit / capacity NOT
    #      exceeded). ----
    # Instructions: a 32-word loop body (2 cache lines) executed 200 times.
    # Data: 16-word (1 line) accumulator/array reused 500 times.
    workloads["repeated"] = {
        "fits_in_cache": {
            "instruction": repeated(CODE_BASE, working_set=32, iterations=200),
            "data": repeated(DATA_BASE, working_set=16, iterations=500),
        },
        # ---- Repeated, but the working set is LARGER than the cache's
        #      2048-word / 128-line capacity -> forces capacity misses
        #      even though every access is, in isolation, a repeat. ----
        "exceeds_cache": {
            # 3072 words = 192 blocks > 128 lines -> 1.5x cache capacity
            "instruction": repeated(CODE_BASE, working_set=3072, iterations=4),
            # 4096 words = 256 blocks > 128 lines -> 2x cache capacity
            "data": repeated(DATA_BASE, working_set=4096, iterations=4),
        },
    }

    # ---- Strided: three stride values (2, 4, 16 words) over the same
    #      span, both for instructions and data -- shows spatial
    #      locality degrading as stride grows. ----
    STRIDE_COUNT = 1024
    strided_cases = {}
    for stride in (2, 4, 16):
        strided_cases[str(stride)] = {
            "instruction": strided(CODE_BASE, stride, STRIDE_COUNT),
            "data": strided(DATA_BASE, stride, STRIDE_COUNT),
        }

    # ---- Strided conflict demo: a handful of addresses exactly one
    #      cache-size apart, round-robined -- classic index-aliasing
    #      conflict-miss scenario (tiny working set, huge miss rate). ----
    strided_cases["conflict_demo"] = {
        "instruction": conflicting_stride(CODE_BASE, num_streams=4, repeats=256),
        "data": conflicting_stride(DATA_BASE, num_streams=4, repeats=256),
    }
    workloads["strided"] = strided_cases

    return workloads
