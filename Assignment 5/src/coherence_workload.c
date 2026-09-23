/*
 * Exp05 - Cache Coherence: Finding the Hidden Cost of Sharing
 *
 * A single parallel analytics pipeline (event-stream feature processing +
 * aggregation + lookup/scoring + reduction) that can be reconfigured at
 * runtime to exhibit five different sharing behaviours:
 *
 *   baseline     - private-only work + read-only shared model/lookup data
 *   true         - + true write sharing on a small contended group_stats[] table
 *   false        - + false sharing: one int64 counter per worker packed on shared lines
 *   false_free   - same as 'false' but each counter padded to its own cache line
 *   redesigned   - per-thread local accumulation + single-threaded final reduction
 *                  (eliminates the cross-thread cache-line ownership traffic that
 *                  'true' and 'false' introduce)
 *
 * This is the same pipeline in every mode -- only the shared-data access pattern
 * changes -- so all five rows of the required experimental comparison table come
 * from one binary.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <math.h>

#define MODEL_PARAMS_SIZE   256
#define LOOKUP_TABLE_SIZE   4096
#define NUM_GROUPS          16
#define CACHE_LINE          64
#define MAX_THREADS         256

typedef enum {
    MODE_BASELINE = 0,
    MODE_TRUE_SHARING,
    MODE_FALSE_SHARING,
    MODE_FALSE_SHARING_FREE,
    MODE_REDESIGNED
} run_mode_t;

static const char *mode_name(run_mode_t m) {
    switch (m) {
        case MODE_BASELINE: return "baseline";
        case MODE_TRUE_SHARING: return "true_sharing";
        case MODE_FALSE_SHARING: return "false_sharing";
        case MODE_FALSE_SHARING_FREE: return "false_sharing_free";
        case MODE_REDESIGNED: return "redesigned";
    }
    return "?";
}

/* ---- Input event stream (Data Partitioning stage input) ---- */
typedef struct {
    double value;
    int group_id;
    int lookup_key;
} event_t;

/* ---- True-shared aggregation target: group_statistics[group_id] ---- */
typedef struct {
    _Atomic double  sum;
    _Atomic int64_t count;
} group_stat_t;

/* ---- False-sharing-free counter: padded to its own cache line ---- */
typedef struct {
    _Atomic int64_t value;
    char pad[CACHE_LINE - sizeof(_Atomic int64_t)];
} padded_counter_t;

typedef struct {
    int tid;
    int nthreads;
    const event_t *events;
    long start_idx, end_idx;

    /* Feature Processing stage: read-only shared structures */
    const double *model_params;
    const int    *lookup_table;

    /* Shared Aggregation / Concurrent Lookup & Scoring stage: mode-dependent */
    group_stat_t     *group_stats;        /* mode == true_sharing (global, contended) */
    _Atomic int64_t  *packed_counters;     /* mode == false_sharing (global, contended lines) */
    padded_counter_t *padded_counters;     /* mode == false_sharing_free (global, isolated lines) */
    group_stat_t     *local_group_stats;   /* mode == redesigned (private, size NUM_GROUPS) */

    run_mode_t mode;

    /* Feature Processing stage: private per-worker buffer */
    double *temporary_buffer;   /* worker[tid].temporary_buffer, private */
    long    buffer_cap;

    /* outputs (private, written once at join) */
    double local_sum;
    long   local_count;
    long   cas_retries;         /* evidence: how many times an atomic RMW lost the race
                                    to another core -> cache line was stolen from us */
} worker_arg_t;

static double atomic_double_add(_Atomic double *slot, double delta, long *retries) {
    double old = atomic_load_explicit(slot, memory_order_relaxed);
    double newv;
    for (;;) {
        newv = old + delta;
        if (atomic_compare_exchange_weak_explicit(slot, &old, newv,
                memory_order_relaxed, memory_order_relaxed)) {
            return newv;
        }
        (*retries)++;
    }
}

static void *worker_fn(void *arg_) {
    worker_arg_t *w = (worker_arg_t *)arg_;
    double local_sum = 0.0;
    long   local_count = 0;
    long   cas_retries = 0;
    long   buf_pos = 0;

    for (long i = w->start_idx; i < w->end_idx; i++) {
        const event_t *e = &w->events[i];

        /* --- Feature Processing: read shared, read-mostly structures --- */
        double mp = w->model_params[e->lookup_key % MODEL_PARAMS_SIZE];
        int    lk = w->lookup_table[e->lookup_key % LOOKUP_TABLE_SIZE];
        double transformed = e->value * mp + (double)(lk & 0xFF) * 0.001;

        /* --- Data Partitioning result: private per-worker buffer --- */
        w->temporary_buffer[buf_pos % w->buffer_cap] = transformed;
        buf_pos++;
        local_sum += transformed;
        local_count++;

        /* --- Shared Aggregation / Concurrent Lookup & Scoring --- */
        switch (w->mode) {
        case MODE_TRUE_SHARING: {
            group_stat_t *g = &w->group_stats[e->group_id % NUM_GROUPS];
            atomic_double_add(&g->sum, transformed, &cas_retries);
            atomic_fetch_add_explicit(&g->count, 1, memory_order_relaxed);
            break;
        }
        case MODE_FALSE_SHARING: {
            /* one int64 slot per worker, packed contiguously: 8 slots/64B line */
            atomic_fetch_add_explicit(&w->packed_counters[w->tid], 1, memory_order_relaxed);
            break;
        }
        case MODE_FALSE_SHARING_FREE: {
            atomic_fetch_add_explicit(&w->padded_counters[w->tid].value, 1, memory_order_relaxed);
            break;
        }
        case MODE_REDESIGNED: {
            /* private per-thread partial table -> no cross-thread traffic here */
            group_stat_t *g = &w->local_group_stats[e->group_id % NUM_GROUPS];
            atomic_double_add(&g->sum, transformed, &cas_retries);
            atomic_fetch_add_explicit(&g->count, 1, memory_order_relaxed);
            break;
        }
        case MODE_BASELINE:
        default:
            break;
        }
    }

    w->local_sum = local_sum;
    w->local_count = local_count;
    w->cas_retries = cas_retries;
    return NULL;
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static run_mode_t parse_mode(const char *s) {
    if (!strcmp(s, "baseline")) return MODE_BASELINE;
    if (!strcmp(s, "true")) return MODE_TRUE_SHARING;
    if (!strcmp(s, "false")) return MODE_FALSE_SHARING;
    if (!strcmp(s, "false_free")) return MODE_FALSE_SHARING_FREE;
    if (!strcmp(s, "redesigned")) return MODE_REDESIGNED;
    fprintf(stderr, "unknown mode '%s'\n", s);
    exit(2);
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr,
            "usage: %s <mode:baseline|true|false|false_free|redesigned> "
            "<nthreads> <nevents> [seed]\n", argv[0]);
        return 2;
    }
    run_mode_t mode = parse_mode(argv[1]);
    int nthreads = atoi(argv[2]);
    long nevents = atol(argv[3]);
    unsigned seed = (argc > 4) ? (unsigned)atoi(argv[4]) : 42u;

    if (nthreads < 1 || nthreads > MAX_THREADS) {
        fprintf(stderr, "nthreads out of range\n");
        return 2;
    }

    /* ---- Build read-only shared structures (model params, lookup table) ---- */
    double *model_params = malloc(sizeof(double) * MODEL_PARAMS_SIZE);
    int    *lookup_table = malloc(sizeof(int) * LOOKUP_TABLE_SIZE);
    srand(seed);
    for (int i = 0; i < MODEL_PARAMS_SIZE; i++)
        model_params[i] = 0.5 + (double)(rand() % 1000) / 1000.0;
    for (int i = 0; i < LOOKUP_TABLE_SIZE; i++)
        lookup_table[i] = rand();

    /* ---- Build input event stream ---- */
    event_t *events = malloc(sizeof(event_t) * nevents);
    for (long i = 0; i < nevents; i++) {
        events[i].value = (double)(rand() % 10000) / 100.0;
        events[i].group_id = rand() % NUM_GROUPS;
        events[i].lookup_key = rand();
    }

    /* ---- Mode-specific shared structures ---- */
    group_stat_t *group_stats = calloc(NUM_GROUPS, sizeof(group_stat_t));
    _Atomic int64_t *packed_counters = calloc(nthreads, sizeof(_Atomic int64_t));
    padded_counter_t *padded_counters = calloc(nthreads, sizeof(padded_counter_t));

    /* ---- Per-thread private buffers (worker[i].temporary_buffer) ---- */
    long buf_cap = 4096;
    double **buffers = malloc(sizeof(double *) * nthreads);
    for (int t = 0; t < nthreads; t++)
        buffers[t] = malloc(sizeof(double) * buf_cap);

    /* ---- Redesign: private per-thread group-stat tables, reduced at the end ---- */
    group_stat_t *local_group_stats_all = NULL;
    if (mode == MODE_REDESIGNED)
        local_group_stats_all = calloc((size_t)nthreads * NUM_GROUPS, sizeof(group_stat_t));

    pthread_t threads[MAX_THREADS];
    worker_arg_t wargs[MAX_THREADS];

    long chunk = nevents / nthreads;
    double t0 = now_sec();

    for (int t = 0; t < nthreads; t++) {
        wargs[t].tid = t;
        wargs[t].nthreads = nthreads;
        wargs[t].events = events;
        wargs[t].start_idx = (long)t * chunk;
        wargs[t].end_idx = (t == nthreads - 1) ? nevents : (long)(t + 1) * chunk;
        wargs[t].model_params = model_params;
        wargs[t].lookup_table = lookup_table;
        wargs[t].group_stats = group_stats;
        wargs[t].packed_counters = packed_counters;
        wargs[t].padded_counters = padded_counters;
        wargs[t].local_group_stats = local_group_stats_all
            ? &local_group_stats_all[(size_t)t * NUM_GROUPS] : NULL;
        wargs[t].mode = mode;
        wargs[t].temporary_buffer = buffers[t];
        wargs[t].buffer_cap = buf_cap;
        pthread_create(&threads[t], NULL, worker_fn, &wargs[t]);
    }
    for (int t = 0; t < nthreads; t++)
        pthread_join(threads[t], NULL);

    /* ---- Final Reduction stage ---- */
    double grand_sum = 0.0;
    long grand_count = 0;
    long total_cas_retries = 0;
    for (int t = 0; t < nthreads; t++) {
        grand_sum += wargs[t].local_sum;
        grand_count += wargs[t].local_count;
        total_cas_retries += wargs[t].cas_retries;
    }
    if (mode == MODE_REDESIGNED) {
        for (int t = 0; t < nthreads; t++)
            for (int g = 0; g < NUM_GROUPS; g++) {
                group_stat_t *src = &local_group_stats_all[(size_t)t * NUM_GROUPS + g];
                atomic_fetch_add_explicit(&group_stats[g].sum,
                    atomic_load_explicit(&src->sum, memory_order_relaxed), memory_order_relaxed);
                atomic_fetch_add_explicit(&group_stats[g].count,
                    atomic_load_explicit(&src->count, memory_order_relaxed), memory_order_relaxed);
            }
    }
    long counter_total = 0;
    for (int t = 0; t < nthreads; t++)
        counter_total += (mode == MODE_FALSE_SHARING_FREE)
            ? atomic_load_explicit(&padded_counters[t].value, memory_order_relaxed)
            : atomic_load_explicit(&packed_counters[t], memory_order_relaxed);

    double t1 = now_sec();
    double wall = t1 - t0;

    double group_sum_check = 0.0;
    long group_count_check = 0;
    for (int g = 0; g < NUM_GROUPS; g++) {
        group_sum_check += atomic_load_explicit(&group_stats[g].sum, memory_order_relaxed);
        group_count_check += atomic_load_explicit(&group_stats[g].count, memory_order_relaxed);
    }

    /* CSV: mode,nthreads,nevents,wall_seconds,grand_sum,grand_count,group_sum,group_count,counter_total,cas_retries */
    printf("%s,%d,%ld,%.6f,%.6f,%ld,%.6f,%ld,%ld,%ld\n",
        mode_name(mode), nthreads, nevents, wall,
        grand_sum, grand_count, group_sum_check, group_count_check,
        counter_total, total_cas_retries);

    for (int t = 0; t < nthreads; t++) free(buffers[t]);
    free(buffers); free(events); free(model_params); free(lookup_table);
    free(group_stats); free((void*)packed_counters); free(padded_counters);
    free(local_group_stats_all);
    return 0;
}
