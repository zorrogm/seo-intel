"""Main content F1 on a generated site with known answers."""
import json
import sys

import numpy as np

from seo_intel.extract import Template, learn_template, main_blocks, parse_page
from seo_intel.text import tokenize

PAGES = 120
WORDS = (
    "garden soil water plant seed root leaf flower fruit tree prune compost mulch "
    "spring summer autumn winter sun shade frost harvest tool spade rake hose pot "
    "बगीचा मिट्टी पानी पौधा बीज फूल फल पेड़ खाद धूप mausam paani khad beej"
).split()


def sentence(rng, low=8, high=18):
    return " ".join(rng.choice(WORDS, size=rng.randint(low, high))).capitalize() + "."


def build_page(rng, number, titles):
    paragraphs = [" ".join(sentence(rng) for _ in range(rng.randint(2, 5)))
                  for _ in range(rng.randint(3, 8))]
    heading = titles[number]
    related = rng.choice(len(titles), size=5, replace=False)
    links = "".join(f'<li><a href="/post/{i}">{titles[i]}</a></li>' for i in related)
    crumbs = f'<a href="/">Home</a> <a href="/topic/{number % 6}">Topic {number % 6}</a>'
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    html = f"""<html><head><title>{heading} | Green Thumb</title></head><body>
<div class="top"><a href="/">Green Thumb</a> <a href="/about">About us</a> <a href="/contact">Contact</a></div>
<div class="crumbs">{crumbs}</div>
<div class="wrap"><div class="content"><h1>{heading}</h1>{body}</div>
<div class="side"><h3>Related reading</h3><ul>{links}</ul>
<div class="promo"><p>Sign up for our weekly newsletter and never miss a tip.</p></div></div></div>
<div class="bottom"><p>Copyright Green Thumb. All rights reserved.</p><a href="/privacy">Privacy</a></div>
</body></html>"""
    truth = tokenize(heading + " " + " ".join(paragraphs))
    return html, truth


def f1(found, truth):
    remaining = list(truth)
    hits = 0
    for token in found:
        if token in remaining:
            remaining.remove(token)
            hits += 1
    if not found or not truth or not hits:
        return 0.0
    precision, recall = hits / len(found), hits / len(truth)
    return 2 * precision * recall / (precision + recall)


def main():
    rng = np.random.RandomState(0)
    titles = [sentence(rng, 3, 6).rstrip(".") for _ in range(PAGES)]
    built = [build_page(rng, i, titles) for i in range(PAGES)]
    parsed = [parse_page(html.encode("utf-8"), f"http://site.test/post/{i}")
              for i, (html, _truth) in enumerate(built)]
    template = learn_template(parsed)
    with_template = [f1(tokenize(" ".join(main_blocks(page, template))), truth)
                     for page, (_html, truth) in zip(parsed, built)]
    repeats_only = Template(template.repeated, set())
    without_paths = [f1(tokenize(" ".join(main_blocks(page, repeats_only))), truth)
                     for page, (_html, truth) in zip(parsed, built)]
    all_text = [f1(tokenize(" ".join(b[2] for b in page["blocks"])), truth)
                for page, (_html, truth) in zip(parsed, built)]
    json.dump({
        "pages": PAGES,
        "f1_all_page_text": round(float(np.mean(all_text)), 4),
        "f1_repeated_blocks_only": round(float(np.mean(without_paths)), 4),
        "f1_after_template_removal": round(float(np.mean(with_template)), 4),
        "worst_page_f1": round(float(np.min(with_template)), 4),
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
