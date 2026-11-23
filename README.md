# seo-intel

Give it your website and a competitor's website. It reads both sites, finds
pages of yours that compete with each other, finds topics the competitor
covers and you do not, picks the best new internal links, and writes a
25 step action plan. Every fact in the plan is checked by code against the
pages it actually read.

## Install (one command)

You need Python 3.9 or newer. In the project folder run:

    bash install.sh

## Add a Gemini key (optional)

Open the file `.env` and paste a Gemini API key after `GEMINI_API_KEY=`.
Without a key the tool still runs and writes the plan with standard wording.

The key stays on your computer. `.env` is listed in `.gitignore`, so it is
never uploaded, and the key is only ever sent to Google's Gemini service.

## Run

    ./seo-intel yoursite.com --competitor theirsite.com

A full run takes up to 90 minutes. Results appear in
`runs/yoursite.com__theirsite.com/output/`.

## What you get

| File | What it tells you |
|---|---|
| `action_plan.md` | The 25 actions, in order, with the evidence for each |
| `action_plan.json` | The same plan for programs, with every claim |
| `cannibalization.json` | Groups of your pages that compete, with a severity score |
| `gaps.json` | Topics the competitor covers in depth and you do not |
| `internal_links.json` | New links to add, the sentence to put them in, and the gain |
| `near_duplicates.json` | Pages that are almost copies |
| `crawl_issues.json` | Redirect chains, canonical problems, pages hidden from search |
| `soft_404s.json` | Pages that load fine but are really "not found" |
| `spider_traps.json` | Endless URL patterns the crawler refused to follow |
| `render_report.json` | Pages that only show their content with JavaScript |
| `change_report.json` | What changed since the last run |
| `crawl_summary.json` | How many pages were read |

A real result, python.org against ruby-lang.org, is in
`examples/python.org__ruby-lang.org/`.

## Running it again

- The same day: it reuses what it read and writes identical files.
- The next day or later: it quickly rechecks pages and reports what changed.
- If it is stopped halfway, run the same command; it continues where it stopped.

## Useful options

| Option | Meaning |
|---|---|
| `--priority-urls file.txt` | Pages you most want to rank, one URL per line |
| `--link-budget 40` | How many new links to suggest |
| `--seed 0` | Same seed gives the same result |
| `--no-llm` | Write the plan without the language model |

## Good manners

It never asks a website for more than 3 pages a second and it obeys each
site's robots.txt the way Google does.

## For engineers

`bash install.sh && .venv/bin/python -m pip install pytest && .venv/bin/pytest`
runs the tests. Settings live in `src/seo_intel/config.py`. Measurements are
in `BENCHMARKS.md`, design choices in `DECISIONS.md`.
