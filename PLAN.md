# Build plan

Order follows the data flow. Each step is tested before the next starts.

| Stage | Part | Built and tested | Measured by |
|---|---|---|---|
| Robots | A1 | Google rules, Google's 21 tests ported | `tests/test_robots_google.py` |
| Crawler | A | Polite, resumable, sitemaps, traps refused with patterns | `tests/test_crawl.py`, `tests/test_part_a.py` |
| Redirects | A4 | 3xx chains and loops, meta refresh, script redirects, canonical chains, header rules | `tests/test_part_a.py` |
| Soft 404 | A5 | Missing page probe, wording and empty checks | `tests/test_part_a.py` |
| Rendering | A3 | Raw HTML hints and template samples, polite browser | `benchmarks/rendering.py` |
| Rerun | A6 | Kill safe, conditional requests, change report | `tests/test_part_a.py` |
| Extraction | B | Template learned from repeats and link heavy positions | `benchmarks/extraction.py` |
| Duplicates | B | MinHash, banding, exact check; Hindi and Hinglish tokens | `benchmarks/duplicates.py`, `tests/test_text.py` |
| Cannibalization | C | Two matching channels, intent, healthy pair rules, severity | `benchmarks/cannibalization.py` |
| Gaps | C | Shared topic space, numeric depth rule, language filter | full runs |
| Links | D | PageRank, exact greedy plus swaps, anchor sentences | `benchmarks/link_methods.py`, `tests/test_graph.py` |
| Agent | E | Tools, claim verifier, live recheck, rejection log, cache | `tests/test_pipeline.py`, `tests/test_live.py` |
| Judge | E | Fixed checks, LLM judge, Cohen's kappa | `tests/test_judge.py`; needs 40 human labels |

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

## Still needs a person

- 40 recommendations labelled sound or unsound, for the judge's kappa.
- Review of cannibalization groups and gaps by SEOs.
- Hand marked main content on real pages for a real F1 number.
