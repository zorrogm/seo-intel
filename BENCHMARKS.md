# Benchmarks

Every number below was measured, and each has the command that produced it.
Where something could not be measured properly, it says so.

## Machines

| Name | What it is |
|---|---|
| Laptop | MacBook, 10 cores, 16 GB, Python 3.9.6 |
| Container | Docker on the same laptop, Linux, limited to 4 CPUs and a hard 2 GB memory cap, Python 3.12.16, cloned fresh from GitHub |

The brief's machine is 4 cores and 8 GB. The container is stricter on
memory (2 GB) so that the 2 GB limit is proven, not estimated.

## The three site pairs

| Pair | Target | Competitor | Why this pair |
|---|---|---|---|
| 1 | python.org | ruby-lang.org | Large, many languages, old redirects |
| 2 | livehindustan.com | amarujala.com | Hindi and Hinglish news, script heavy, huge sitemaps |
| 3 | djangoproject.com | fastapi.tiangolo.com | Small enough to crawl completely |

Full run command, the same for every pair:

    ./seo-intel python.org --competitor ruby-lang.org

Headline numbers of a finished run:

    .venv/bin/python benchmarks/summarise_run.py runs/python.org__ruby-lang.org

## Hard limits

| Limit | Target | Measured | Where |
|---|---|---|---|
| Scale | 50,000 URLs per site | Frontier tracks up to 50,000 per site. Fetched in the crawl time: 9,968 and 9,964 (pair 1), 10,376 and 10,352 (pair 2), 1,898 and 2,029 (pair 3, sites exhausted). Analysis alone handles 50,000 pages in 84 s and 1,042 MB. | pairs 1 to 3, `benchmarks/scale.py 25000` |
| Time | 90 min | Crawl stops at 60 min. Rendering, analysis, agent and live recheck then took 7.2 min on pair 1. About 67 min in total. | pair 1, laptop |
| Memory | 2 GB peak | Full run inside a 2 GB hard cap: finished, 0 out of memory events. Tool process peak 588 MB; whole container with the browser 1,168 MB. | pair 1, container |
| Memory, heaviest pair | 2 GB peak | 1,044 MB for analysis of 20,728 link heavy Hindi pages | pair 2, laptop |
| LLM cost | $0.50 per run | $0.0008 to $0.0042 per run, 3 to 12 calls, largest prompt 5,086 tokens against the 8,000 cap | all pairs, `logs/llm_usage.json` |
| Politeness | 3 requests per second per host | Requests to one host start at least 0.34 s apart, at most 2.94 per second. Pair 1 averaged 2.78 pages per second per host. | `tests/test_crawl.py`, pair 1 |
| Robots | Google rules | All 21 tests from Google's parser pass | `.venv/bin/pytest tests/test_robots_google.py` |
| Repeatability | Byte identical | Two runs, 12 output files, identical SHA-256 hashes | pair 1, container and laptop |
| Rerun | 10% of first run | Same day rerun: 27.5 s in the container, 23 s on the laptop, under 1% of the first run | pair 1 |
| Invented facts | 0 | Every claim is recomputed from the crawl store and cited pages are refetched; prose is built by code from checked reasons | `tests/test_pipeline.py`, `tests/test_live.py` |

Notes on honesty:

- The LLM cost uses assumed prices of $0.10 and $0.40 per million input and
  output tokens for `gemini-3.5-flash-lite`. The runs were on the free tier,
  so the real charge was zero. Check the price before relying on the figure.
- Wall clock time of the container run is not reported. The laptop went to
  sleep during it, so its clock is meaningless. Its CPU time was 344 s on
  top of the 60 minute crawl.
- The next day rerun (conditional requests and a change report) is tested on
  a local site only (`tests/test_part_a.py`). It gets 7% of the crawl time,
  which is 4.2 minutes, plus under a minute of analysis.
- "Scale" is the brief's hardest line. 50,000 fetches per site cannot fit in
  90 minutes at 3 requests per second (it needs 4.6 hours per host), so the
  crawl is capped by time. See DECISIONS.md.

## Results per pair

| | Pair 1 | Pair 2 | Pair 3 |
|---|---|---|---|
| Pages fetched, target | 9,968 | 10,376 | 1,898 |
| Pages fetched, competitor | 9,964 | 10,352 | 2,029 |
| Indexable, target | 8,921 | 7,392 | 1,566 |
| Trap URLs refused, target | 2 | 7,315 | 3 |
| Share of pages rendered, target | 2.2% | 0.2% | 1.8% |
| Flagged as needing JavaScript but not rendered | 0 | 782 | 0 |
| Soft 404s reported | 0 | 0 | 0 |
| Near duplicate pairs | 184 | 255 | 109 |
| Cannibalization groups | 14 | 333 | 82 |
| Competitor gaps | 8 | 22 | 9 |
| New links chosen (budget 40) | 40 | 18 | 40 |
| Priority PageRank, before to after | 0.00151 to 0.00598 | 0.00196 to 0.00229 | 0.00203 to 0.00793 |
| Actions in the plan | 25 | 25 | 25 |
| Verified claims in the plan | 193 | 190 | 220 |
| Plan written by | agent | agent | agent |

Pairs 1 and 2 were crawled with an earlier build and re-analysed with the
final one, so trap counts for them include repeat sightings (fixed since).
Pair 2 shows the rendering budget of 8 minutes is small for a slow, script
heavy site: 782 pages were identified as needing JavaScript but only 0.2%
of pages could be rendered in the time.

## Part targets

| Part | Target in the brief | Measured | Command | Caveat |
|---|---|---|---|---|
| A1 robots | Pass Google's tests | 21 of 21 | `.venv/bin/pytest tests/test_robots_google.py` | |
| A2 traps | Under 5% of budget wasted, patterns reported | Calendar, filter, growing path and session traps all stopped and named; each trap costs at most its cap before refusal | `.venv/bin/pytest tests/test_part_a.py` | Local trap site |
| A3 rendering | Render at most 15%, catch 95% | Rendered 10.8%, caught 22 of 22, 0 false alarms | `PYTHONPATH=tests .venv/bin/python benchmarks/rendering.py` | Local site, also run in the container |
| A4 redirects | All kinds found | 3xx chains and loops, meta refresh, script redirects, canonical chains, canonical to a 404, header noindex | `.venv/bin/pytest tests/test_part_a.py` | Local trap site |
| A5 soft 404 | Precision 90% | 3 of 3 found, 0 false alarms; 0 reported on the three real pairs after fixes | `.venv/bin/pytest tests/test_part_a.py` | No labelled real set |
| A6 resume | Kill safe, change report | Killed with SIGKILL and resumed: nothing lost, at most 4 requests repeated; new, removed, title changed and newly redirected all reported | `.venv/bin/pytest tests/test_crawl.py tests/test_part_a.py` | |
| B extraction | Token F1 0.90 | 0.9999 (0.8820 with no template removal) | `.venv/bin/python benchmarks/extraction.py` | Generated site, not hand marked pages |
| B duplicates | Recall on 200 planted pairs, no all pairs | 200 of 200 among 50,000 pages, 10.5 s, 545 MB, 0 false pairs | `.venv/bin/python benchmarks/duplicates.py` | |
| B languages | English, Hindi, Hinglish | Tokeniser, sentence and shingle tests pass; pair 2 ran end to end | `.venv/bin/pytest tests/test_text.py` | |
| C cannibalization | Precision at 20 of 0.80 | 1.00, recall 1.00 | `.venv/bin/python benchmarks/cannibalization.py` | Generated site with planted groups, not SEO judged |
| C gaps | Precision at 20 of 0.75 | Not measured | | Needs SEO reviewers |
| D optimiser | Compare greedy with a better method | Greedy plus swaps matched brute force on 40 of 40 graphs; ranking once reached 87.6% of the best gain | `.venv/bin/python benchmarks/link_methods.py` | Small graphs, 30 pages |
| E claims | No false claim | No claim failed verification in the final runs. In pair 2 the agent asked for 5 reasons its claims did not prove; code removed them and logged it. | `logs/rejections.jsonl` in each run | |
| E judge | Cohen's kappa on 40 labels | LLM judge marks 34 of 50 real recommendations sound. Kappa not reported yet. | `.venv/bin/seo-intel-judge runs/python.org__ruby-lang.org runs/www.djangoproject.com__fastapi.tiangolo.com --labels benchmarks/labels.csv` | Needs the 40 human labels in `benchmarks/labels_to_fill.csv` |

The ablation table for Part C is in DECISIONS.md.

## Install and tests on a clean machine

    bash install.sh

| Measure | Result |
|---|---|
| Install time in the clean container | 1 min 42 s, including the browser |
| Tests in the container | all pass |
| Tests on the laptop | 69 pass in about 13 s |

Raw results are in `benchmarks/results/`.
