# Build plan

Order follows the data flow. Each step is tested before the next starts.

| Stage | Part | Thin version working today | Still to deepen |
|---|---|---|---|
| Robots | A1 | Google rules, Google's tests ported | nothing |
| Crawler | A | Polite, resumable, sitemaps, 3xx chains recorded | traps, rendering, meta and JS redirects, soft 404s, nofollow |
| Rerun | A6 | Finished crawl is frozen, rerun reuses it | ETag and hash revalidation, change report |
| Extraction | B | Template learned from repeated blocks | DOM path statistics, F1 measurement |
| Duplicates | B | MinHash and LSH, exact overlap check | planted pair recall, Hinglish tests |
| Topics | C | Hashed TF-IDF vectors, seeded k-means, word list intent | real embeddings, LLM on 2% of pages, language handling in gaps |
| Cannibalization | C | Groups, healthy pair rules, severity score | precision review, ablation table |
| Links | D | Graph, PageRank, greedy optimiser, anchor sentences | exact gains, comparison with a better method |
| Agent | E | Gemini with tools, claim verifier, rejection log, disk cache | live recheck of cited pages, judge harness with kappa |
| Outputs | all | Seven files, byte identical on rerun | BENCHMARKS.md, DECISIONS.md, README |

## Rules for the code

- All settings live in `src/seo_intel/config.py`.
- No site-specific rules or hard-coded selectors.
- Comments stay short and plain.
- Same input and seed must give byte-identical output.

## Decisions made

- Scale against time: the crawl is capped by time (60 of the 90 minutes), so
  about 10,500 fetches per host at 3 requests per second. The frontier still
  holds up to 50,000 URLs per site. Chosen by the user on 2026-11-23.
- LLM: Gemini, key read from `.env` (never committed).
- Python 3.9 is the minimum version.
