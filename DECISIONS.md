# Decisions

What was tried, what failed, and the numbers that settled it. Every number
here came from a test or benchmark in this repo. The command that reproduces
it is given next to it.

## The 50,000 URL limit

This is the one hard limit the tool does not meet as a fetch count, so the
reasoning comes first.

Three hard limits apply to the same crawl:

| Limit | Value |
|---|---|
| Scale | 50,000 URLs per site |
| Politeness | at most 3 requests per second per host |
| Time | full run, both sites, within 90 minutes |

The arithmetic for one host:

| Question | Answer |
|---|---|
| Most requests 90 minutes allows at 3 per second | 3 x 60 x 90 = 16,200 |
| Time 50,000 requests need at 3 per second | 50,000 / 3 = 16,667 s = 4.6 hours |
| Requests per second needed for 50,000 in 90 minutes | 9.3, three times the politeness limit |

Both sites are crawled at the same time, so the ceiling is per host, not
shared. Even so, 16,200 is the most any polite crawler can fetch from one
host in the whole 90 minutes, with nothing left for analysis. Meeting the
fetch count would mean breaking either the politeness limit or the time
limit, and both of those are also hard limits.

So the tool reads "50,000 URLs per site" as the size of site it must handle,
and does this:

| What | How | Measured |
|---|---|---|
| Tracks up to 50,000 URLs per site | The frontier stores every URL found, up to 50,000, with its state | python.org 15,747 known, ruby-lang.org 20,854, amarujala.com 33,068 |
| Fetches as many as the limits allow | 60 of the 90 minutes go to crawling, at one request per 0.34 s per host | 9,964 to 10,376 pages per site on the two large pairs |
| Fetches the most useful pages first | Pages are taken by click distance from the homepage, sitemap URLs after homepage links | |
| Reports what was left | `crawl_summary.json` gives known, fetched and waiting URLs per site | |
| Analyses 50,000 pages within the limits | Every stage after the crawl avoids all pairs comparisons | 50,000 pages in 84 s and 1,042 MB, `benchmarks/scale.py 25000` |
| Stays within memory at 50,000 URLs | Only URLs are kept for unfetched pages, bodies are compressed on disk | full run peaked at 588 MB inside a 2 GB cap |

What would raise the fetch count, and why it is not the default:

- **More crawl time.** `--crawl-minutes 75` fetches about 13,000 per site.
  It leaves 15 minutes for rendering, analysis and the agent, which took
  about 7 minutes on a fast laptop. Too thin a margin for a 4 core machine.
- **Counting subdomains as one site.** Each host has its own 3 per second,
  so a site spread over several hosts could pass 16,200. Not built: it
  changes what "the site" means and was not tested.
- **Going faster than 3 per second.** Not considered.

## Other limits that pull against each other

| Conflict | Arithmetic | Decision |
|---|---|---|
| Rerun in 10% of the time, with conditional requests | Even a "not modified" reply costs one request, so rechecking every page takes as long as the first crawl | The rerun gets 7% of the crawl time and rechecks pages closest to the homepage first, then fetches newly found URLs. |
| Byte identical output, and a rerun that detects changes | A rerun that refetches pages can legitimately change the output | A rerun within 12 hours reuses the stored crawl and makes no requests. After 12 hours it revalidates and writes a change report. |

Scope is the start host with and without `www`. Other subdomains are treated
as other sites.

## Part A: crawler

**Failed: rate limiter scheduled from planned times.** Each request was
scheduled one gap after the previous planned start. When the event loop was
busy, a late request was followed too closely by the next. In
`tests/test_crawl.py::test_host_limiter_spaces_requests` the smallest gap
measured 0.0238 s against a 0.05 s target. Now the gap is measured from the
real start of the previous request, and the test passes repeatedly.

**Failed: treating every 3xx reply as a redirect.** During revalidation a
`304 Not Modified` reply was handled as a redirect. On the trap test site
this reported 80 pages as "newly redirected" when one was. `304` and failed
requests now leave the stored page untouched
(`tests/test_part_a.py::test_next_day_rerun_reports_changes`).

**Failed: reading all sitemaps before crawling.** On two large news sites a
25 second trial fetched 0 pages: the whole budget went on sitemap files, and
100,000 sitemap URLs filled both frontiers before the homepage was read.
Sitemaps now load alongside the workers, are capped at 20,000 URLs per site
and rank below pages linked from the homepage. The same trial then fetched
155 pages.

**Failed: storing "too many requests" replies as pages.** On a full run
djangoproject.com answered 429 for 92 of 1,898 URLs and those pages were
lost. A refused URL now stays queued, the host's gap doubles (up to 5 s) and
eases back on success, and the URL is retried up to 3 times
(`tests/test_fixes.py::test_rate_limited_pages_are_retried_not_lost`).

**Failed: two trap limits that cut real pages.** A 20 variant limit per path
refused `/weblog/?page=21` on djangoproject.com as a "filter" trap, and a
60 page limit per calendar shape refused monthly news archives on
ruby-lang.org. A single numeric parameter is now treated as pagination
(limit 300), and the calendar limit is 400, enough for every month in the
allowed years. Refused URLs are also counted once each; the first report
counted every repeat sighting and showed 11,401 for ruby-lang.org.

**Failed: assuming the browser can start.** In a clean Linux container the
browser driver failed on a missing system library and the whole run stopped.
Any browser failure now skips rendering and records why in
`render_report.json`; the installer also adds the library when it can.

**Failed: "no text" as proof of a soft 404.** On livehindustan.com 102 game
and widget pages have no text in raw HTML because scripts build them. They
were reported as soft 404s. An empty page with scripts is now a rendering
candidate instead, and loose phrases such as "not found" on their own were
dropped after one matched a short Hindi news story. That run now reports 0.

**Kept: how rendering is decided without rendering everything.** Two cheap
signals pick the pages, then the budget caps them at 15%.

1. Raw HTML hint. A page with under 80 words of text that also carries
   scripts, or one whose `noscript` text asks for JavaScript, is rendered.
2. Template samples. Pages are grouped by URL shape (first folder and
   depth). Two pages of each shape with at least 5 pages are rendered. If
   most samples gain 20% and 50 or more words, or 5 or more links, or a
   changed title, canonical or robots tag, every page of that shape is
   queued, because pages built from one template behave alike.

Pages that qualify but do not fit the 15% or the 8 minute budget are still
listed in `render_report.json` as needing JavaScript. The browser obeys the
same 3 per second limit and robots rules as the crawler and skips images,
fonts, media and stylesheets. On the local test site this rendered 10.8% of
pages and caught 22 of 22 (`benchmarks/rendering.py`). The hint alone would
have caught 12 of 22; the 10 pages that have plenty of text before
JavaScript adds more were caught only by the template samples.

**Kept: traps are refused at enqueue time, not after fetching.** A URL is
checked against calendar, faceted, growing path and session rules before it
enters the frontier, so a trap costs at most its cap in fetches (20 filter
mixes per path, 60 dates per calendar shape). Each refusal is counted with
its pattern in `spider_traps.json`.

**Kept: soft 404 needs evidence, not just thin text.** A page is flagged only
if it has no text, or a short page says "not found" in its title or heading,
or its content matches the site's own answer to a URL that cannot exist. The
homepage is never flagged. On the trap test site this finds 3 of 3 with no
false alarms (`tests/test_part_a.py::test_soft_404s_are_found_without_false_alarms`).

**Known limit: kill and resume.** Stored pages are never duplicated or lost.
Requests that were in flight at the moment of a kill are fetched again on
resume, at most 4 (one per worker).

## Part B: main content and duplicates

**Failed: repeated text alone as the template signal.** Marking a block as
template when its text repeats on 10% of pages misses chrome that changes
per page, such as related links and breadcrumbs.

| Method | Token F1 |
|---|---|
| All page text | 0.8820 |
| Repeated blocks only | 0.9481 |
| Repeated blocks plus link heavy positions | 0.9999 |

Reproduce: `.venv/bin/python benchmarks/extraction.py`. This is a generated
120 page site with known answers, not hand marked real pages.

**Failed: text beside child blocks was dropped.** The first extractor only
read leaf blocks, so `<div>text <p>more</p></div>` lost "text". This was
found by reading the code after a soft 404 test misfired, not by a
benchmark, so there is no number for it. Loose text is now kept as its own
block.

**Failed: one Python string per word.** Holding every token as its own
object used 1.81 GB for 50,000 pages of 300 words, too close to the 2 GB
limit. Sharing word objects and storing shingles as sorted arrays brought
this to 473 MB, and the duplicate search from 47.9 s to 11.4 s.

**Failed: holding every parsed page and every link string.** Two real runs
were far heavier than the generated test data.

| Run | Pages | Peak before | Peak after |
|---|---|---|---|
| djangoproject.com and fastapi.tiangolo.com | 3,927 | 922 MB | 632 MB |
| livehindustan.com and amarujala.com | 20,728 | 1,852 MB | 1,044 MB |

The fixes: parse results are read one page at a time, link targets and
anchors are shared objects (one site had 1.85 million links to 83,160
distinct URLs), menu link text is dropped, and word counts are freed once
the vectors are built.

**Kept: MinHash with banding, then an exact check.** 64 hash functions in
16 bands find candidates; every candidate is confirmed with exact shingle
overlap, so no false pair is reported. On 50,000 pages it found 200 of 200
planted pairs out of 1.25 billion possible pairs.
Reproduce: `.venv/bin/python benchmarks/duplicates.py`.

## Part C: cannibalization and gaps

**Failed: compact vectors alone, grouped by single links.** Pages were
hashed into 512 dimensions and any two above the threshold were merged into
a group. Unrelated pages collided in the small vector space, and one weak
link pulled them into real groups.

| Version | Test site | Precision at 20 | Recall of planted groups |
|---|---|---|---|
| Hashed vectors, single link groups | first | 0.65 | 0.70 |
| Plus exact term check and tight groups | first | 1.00 | 1.00 |
| Same version | harder | 1.00 | 0.50 |
| Plus title, heading and anchor channel | harder | 1.00 | 1.00 |

**Failed: body text as the only evidence.** After the fix above, a harder
test site (half the competing pages say little about their topic in the
body) showed recall of 0.50. Pages like thin category pages compete through
titles and anchors, not body text. A second channel now pairs pages that
share rare title, heading and anchor terms, found through an index.

**Failed: treating a numbered series as competitors.** On python.org the
first full run reported 216 groups, mostly release pages such as Python
3.8.19 and 3.9.19, election pages for different years, and dated press
releases. An LLM judge marked 36 of 50 recommendations from two runs as
unsound, most for this reason. Pages whose titles or paths differ only in
numbers or month names are now a healthy "numbered series", unless their
text is a near copy under an identical title. python.org dropped to 14
groups with 3,210 pairs set aside, and the judge then marked 34 of 50 sound.

**Failed: trusting body similarity to mean rivalry.** In the 40 labelled
recommendations every one of the 11 merge suggestions was unsound: two
sponsorship plans, two interest groups, a job post and a job list. They
shared vocabulary but were different items. A pair now needs title, heading
or anchor agreement of at least 0.40 as well, unless the text is a near
copy. A merge is only suggested when half the text is shared and severity
is at least 0.60; weaker pairs get the milder advice to tell the pages
apart, at a lower rank.

**Failed: counting a competitor's dated news as a gap.** All 4 gap
suggestions for python.org were Ruby release announcements and yearly news
archives. Competitor pages with a year in the path are now left out of gap
topics, and python.org went from 8 gaps to 1. Link suggestions between two
numbers of one series (a 2019 nominee page linking to the 2022 list) are
skipped the same way, and numbered list pages are never priority pages.

**Ablation: what each signal adds.**
Reproduce: `.venv/bin/python benchmarks/cannibalization.py`.

| Setup | Groups reported | Precision, all groups | Precision at 20 | Recall |
|---|---|---|---|---|
| All signals | 30 | 1.00 | 1.00 | 1.00 |
| No title or heading | 30 | 1.00 | 1.00 | 1.00 |
| No anchor text | 30 | 1.00 | 1.00 | 1.00 |
| No title, heading or anchors | 0 | 0.00 | 0.00 | 0.00 |
| No topic vectors | 30 | 1.00 | 1.00 | 1.00 |
| No template removal | 30 | 1.00 | 1.00 | 1.00 |
| No intent check | 40 | 0.75 | 1.00 | 1.00 |
| No healthy pair rules | 50 | 0.60 | 0.50 | 1.00 |

Reading it: titles and anchors back each other up, but with neither nothing
is reported, because a pair now needs some title agreement to count. The intent check and the healthy pair rules are what keep precision
up. Topic vectors and template removal made no difference on this site,
because the title channel and the exact term check found the same groups
without them. The tool uses hashed TF-IDF vectors it builds itself, not a
neural embedding model, so there is no separate embedding row. These are
results on a generated site with planted groups; they are not the judged
precision the brief asks for, which needs human reviewers.

**Kept: severity is a weighted sum of five signals.** Content overlap 0.30,
topic similarity 0.30, internal link split 0.20, anchor conflict 0.10, depth
closeness 0.10. Overlap and similarity say the pages are substitutes; an
even link split says the site itself has not chosen a winner.

**Kept: "in depth" has numbers.** A gap is a topic where the competitor has
at least 3 pages and 1,500 words, and the target has at most 20% of those
words. Competitor pages in languages the target does not publish in are
left out.

**Kept: LLM on at most 2% of pages.** Intent comes from word and price rules.
Only pages where the rules tie or see one weak hint go to the LLM, capped at
2% of pages and 100 pages.

## Part D: internal links

**Failed: greedy on an estimate.** The first optimiser added, at each step,
the link with the highest estimated flow (source rank divided by its
outlinks) without checking the real effect.

| Method | Mean share of best possible gain | Worst case | Optimal in 40 graphs | Seconds |
|---|---|---|---|---|
| Rank once, take top K | 0.8763 | 0.5397 | 5 | 0.00 |
| Greedy on estimates | 0.9201 | 0.6826 | 7 | 0.07 |
| Greedy on exact gain | 0.9993 | 0.9845 | 37 | 0.34 |
| Greedy on exact gain, then swaps | 1.0000 | 1.0000 | 40 | 0.63 |

Reproduce: `.venv/bin/python benchmarks/link_methods.py`. "Best possible" is
brute force over every combination, on 40 random graphs of 30 pages with 14
candidate links and a budget of 4.

The tool uses the last row: the 8 best estimates are each scored with a full
PageRank recompute, then every chosen link is tested for a better swap. The
problem is known to be NP-hard, so brute force is only for the small graphs.

**Kept: links must already fit the page.** A source page qualifies only if it
is topically related, does not link to the target yet, and has a sentence
that already contains words from the target's title or heading. Those words
become the anchor.

## Part E: agent and verified claims

**Failed: strict claim reference format.** On the first real run the model
wrote `c77` where the rules wanted `[c77]`, and 16 of 25 rationales were
rejected and replaced with standard text. References without brackets are
now accepted and normalised; the same run then had 0 rejections.

**Failed: checking claims only against the stored crawl.** A stored fact can
be stale by the time the plan is read. Cited pages are now fetched again
just before writing; a changed title, canonical, status, redirect or quoted
sentence drops the action and the next best one takes its place.

**Failed: first model choice.** `gemini-2.5-flash-lite` returned 404 "no
longer available to new users". The run fell back to standard wording
without failing. The model is now `gemini-3.5-flash-lite` and the failure
reason is written to `logs/llm_usage.json`.

**Failed: letting the model write the rationale.** Even with the rule "no
numbers, only claim references", the model wrote descriptions that were
wrong: it called Python release pages "user group event pages" and said
"transactional intent" where the claim said informational. That is an
invented fact in the output. The model now chooses reason codes only. Code
checks each code against the action's verified claims and writes the
sentence, so prose cannot say anything a claim does not prove. Unsupported
codes are logged and removed.

**Failed: an agent loop with no hard stop.** One run used all 12 steps on
lookups and never submitted; another overflowed the prompt budget even
after trimming old tool results. The last step now only allows `submit_plan`,
lookups per step are limited to 6, and oversized tool results are blanked,
newest last. The largest prompt across all runs was 5,086 tokens.

**Known limit: Gemini can refuse a prompt.** Intent batches made of page
titles were refused once with `RECITATION`. The run keeps the rule based
intent for those pages and records the error.

**Failed: an LLM judge with no rubric.** Asked only whether each
recommendation "follows from the facts", the judge agreed with the labels
on 57.5% of 40 items, a Cohen's kappa of 0.12. It approved gaps built from
the competitor's own release news and merges of different sponsorship
plans. A five rule rubric written from those disagreements raised agreement
to 80% and kappa to 0.61 on the same items. It still invents details: see
the sponsor banner case in BENCHMARKS.md.

**Kept: the model never writes facts.** Code finds candidate actions and
builds their claims. The model reads them through five tools, picks and
orders actions, and chooses reason codes. Code turns codes into sentences
that point at claim IDs.

**Kept: the run cannot fail because of the LLM.** No key, an error, a prompt
over budget or a bad answer all lead to the same place: actions ranked by
score with standard wording.

## What is not done

- Precision at 20 judged by SEOs, and token F1 on hand marked real pages,
  need people. The repo measures both only on generated sites.
- The calibrated kappa is in sample: the rubric was written from the same
  40 labels it is scored on. A second labeller would make it stronger.
- Rendering recall is measured on a local test site, not on the open web.
