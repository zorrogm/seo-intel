"""Share rendered and share caught on a local JavaScript site."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fake_site import FakeSite  # noqa: E402
from js_site import APP, HYBRID, JsSite  # noqa: E402
from seo_intel import config, pipeline  # noqa: E402


def main():
    site, other = JsSite(), FakeSite()
    try:
        with tempfile.TemporaryDirectory() as folder:
            pipeline.run(site.base, other.base, Path(folder), crawl_minutes=2.0, max_urls=5000,
                         gap_seconds=0.001, use_llm=False, live_check=False)
            report_path = Path(folder) / config.OUTPUT_FOLDER / "render_report.json"
            report = json.loads(report_path.read_text())
    finally:
        site.close()
        other.close()
    mine = report["sites"][site.base.split("//")[1]]
    needs = {f"{site.base}/app/{i}" for i in range(APP)} | {f"{site.base}/hybrid/{i}" for i in range(HYBRID)}
    caught = {p["url"] for p in mine["pages"] if p["needs_javascript"]}
    json.dump({
        "state": report["state"],
        "html_pages": mine["html_pages"],
        "pages_that_need_javascript": len(needs),
        "rendered": mine["rendered"],
        "rendered_share": mine["rendered_share"],
        "caught": len(needs & caught),
        "recall": round(len(needs & caught) / len(needs), 4),
        "false_alarms": len(caught - needs),
        "why": mine["why"],
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
