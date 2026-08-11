"""
Direct-Mapped Cache model + 3C (Compulsory / Conflict / Capacity) miss classifier.

System parameters (fixed by the assignment):
    Main memory  : 64K words  (2^16 words)
    Cache size   : 2K words   (2^11 words)
    Block size   : 16 words   (2^4 words)
    Word size    : 32 bits
    Address size : 32 bits (word address -- byte offset within a word is ignored,
                   i.e. addresses below refer to WORD numbers, not byte numbers)

Derived geometry:
    Lines in cache   = cache_size / block_size = 2048 / 16 = 128 lines
    Offset bits      = log2(block_size)        = 4 bits
    Index bits       = log2(num_lines)         = 7 bits
    Tag bits         = addr_bits - index - off  = 32 - 7 - 4 = 21 bits
"""

from dataclasses import dataclass, field


WORD_BITS = 32
MAIN_MEMORY_WORDS = 64 * 1024          # 64K words
CACHE_WORDS = 2 * 1024                 # 2K words
BLOCK_WORDS = 16                       # 16 words / block

NUM_LINES = CACHE_WORDS // BLOCK_WORDS                 # 128 lines
OFFSET_BITS = BLOCK_WORDS.bit_length() - 1              # 4
INDEX_BITS = NUM_LINES.bit_length() - 1                 # 7
TAG_BITS = WORD_BITS - INDEX_BITS - OFFSET_BITS          # 21


def decompose(addr: int):
    """Split a 32-bit word address into (tag, index, offset)."""
    offset = addr & (BLOCK_WORDS - 1)
    index = (addr >> OFFSET_BITS) & (NUM_LINES - 1)
    tag = addr >> (OFFSET_BITS + INDEX_BITS)
    return tag, index, offset


def block_number(addr: int) -> int:
    """The memory block (line-sized chunk of main memory) an address belongs to."""
    return addr >> OFFSET_BITS


@dataclass
class MissBreakdown:
    cold: int = 0
    conflict: int = 0
    capacity: int = 0

    @property
    def total(self):
        return self.cold + self.conflict + self.capacity


@dataclass
class CacheStats:
    name: str
    accesses: int = 0
    hits: int = 0
    misses: int = 0
    lookups: int = 0
    miss_breakdown: MissBreakdown = field(default_factory=MissBreakdown)

    @property
    def hit_rate(self):
        return self.hits / self.accesses if self.accesses else 0.0

    @property
    def miss_rate(self):
        return self.misses / self.accesses if self.accesses else 0.0


class DirectMappedCache:
    """A single direct-mapped cache (used independently for I-cache and D-cache)."""

    def __init__(self, name: str):
        self.name = name
        self.valid = [False] * NUM_LINES
        self.tag = [0] * NUM_LINES
        self.stats = CacheStats(name=name)

    def access(self, addr: int) -> bool:
        """Perform one lookup. Returns True on hit, False on miss."""
        tag, index, _ = decompose(addr)
        self.stats.accesses += 1
        self.stats.lookups += 1  # one tag comparison per direct-mapped access
        if self.valid[index] and self.tag[index] == tag:
            self.stats.hits += 1
            return True
        # miss -> load the block (allocate on miss)
        self.valid[index] = True
        self.tag[index] = tag
        self.stats.misses += 1
        return False


class FullyAssociativeLRUCache:
    """
    Reference model with the SAME capacity (in blocks) as the direct-mapped
    cache, but fully associative with true LRU replacement. Used only to
    separate capacity misses from conflict misses (Hill & Smith 3C method).
    """

    def __init__(self, capacity_blocks: int):
        self.capacity = capacity_blocks
        self._order = []      # list of block numbers, most-recently-used at end
        self._set = set()

    def access(self, blk: int) -> bool:
        if blk in self._set:
            self._order.remove(blk)
            self._order.append(blk)
            return True
        # miss
        if len(self._order) >= self.capacity:
            evict = self._order.pop(0)
            self._set.discard(evict)
        self._order.append(blk)
        self._set.add(blk)
        return False


class ThreeCClassifier:
    """
    Classifies every miss of a direct-mapped cache access stream into
    Cold (Compulsory) / Conflict / Capacity, following the standard
    3C model:

      - Cold miss     : the block has never been referenced before
                         (would miss even in an infinite cache).
      - Fully-assoc LRU cache of the SAME capacity is run in parallel:
          * miss in fully-assoc LRU cache AND not cold -> Capacity miss
            (would still miss even with full associativity, i.e. purely
            because the working set exceeds cache capacity)
      - Conflict miss : miss in the direct-mapped cache that is
                         neither cold nor capacity, i.e. a fully
                         associative cache of equal size would have hit
                         (the miss is caused solely by index collisions).
    """

    def __init__(self, capacity_blocks: int):
        self.seen_blocks = set()
        self.lru_ref = FullyAssociativeLRUCache(capacity_blocks)
        self.breakdown = MissBreakdown()

    def classify(self, addr: int, dm_hit: bool):
        blk = block_number(addr)
        is_cold = blk not in self.seen_blocks
        self.seen_blocks.add(blk)
        lru_hit = self.lru_ref.access(blk)

        if dm_hit:
            return  # no miss to classify

        if is_cold:
            self.breakdown.cold += 1
        elif not lru_hit:
            self.breakdown.capacity += 1
        else:
            self.breakdown.conflict += 1


def run_stream(name: str, addresses):
    """Run an address stream through a fresh direct-mapped cache and
    classify every miss into cold/conflict/capacity. Returns CacheStats."""
    cache = DirectMappedCache(name)
    classifier = ThreeCClassifier(NUM_LINES)

    for addr in addresses:
        hit = cache.access(addr)
        classifier.classify(addr, hit)

    cache.stats.miss_breakdown = classifier.breakdown
    assert cache.stats.miss_breakdown.total == cache.stats.misses, (
        f"3C classification mismatch for {name}: "
        f"{cache.stats.miss_breakdown.total} != {cache.stats.misses}"
    )
    return cache.stats
