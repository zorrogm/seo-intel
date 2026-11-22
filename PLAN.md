# Build plan

Order follows the data flow. Each step is tested before the next starts.

| Step | Part | What gets built | Status |
|---|---|---|---|
| 1 | A1 | Google style robots.txt parser, Google's tests ported | done, 22 tests pass |
| 2 | A | URL rules, SQLite crawl store, polite async fetcher, resume after kill | done, 31 tests pass |
| 3 | A | Redirect and canonical chains, meta refresh, X-Robots-Tag, soft 404s | next |
| 4 | A | Spider trap detection with reported patterns | |
| 5 | A | Render decision without rendering everything, headless browser on 15% max | |
| 6 | A | Incremental rerun with ETag, Last-Modified, content hash, change report | |
| 7 | B | Template learning across pages, main content extraction | |
| 8 | B | Tokeniser for English, Hindi, Hinglish; MinHash and LSH duplicates | |
| 9 | C | Local embeddings, intent model, sub-quadratic grouping, severity score, gaps | |
| 10 | D | Link graph, PageRank, link optimiser compared to a better method | |
| 11 | E | Claim schema, code verifier, tool-using agent, judge harness with kappa | |
| 12 | all | BENCHMARKS.md, DECISIONS.md, ablation table, README | |

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
