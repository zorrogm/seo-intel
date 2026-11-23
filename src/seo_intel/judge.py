"""Evaluation harness: fixed checks, an LLM judge, and kappa."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List

from seo_intel import config
from seo_intel.llm import Gemini, LLMError
from seo_intel.plan import ACTION_TEXT, claim_text, rationale_problem
from seo_intel.report import write_json

_SYSTEM = (
    "You review SEO recommendations. Each has a type, a rationale and verified "
    "facts. Judge whether you would act on it. Answer sound or unsound for "
    "each, with a short reason that only uses the facts given. "
    "Call the judge tool once, with one verdict per recommendation, in order. "
    "Rubric, learned from human labels: "
    "1. Canonicalize is sound when two URLs show the same page: same title "
    "with nearly the same text, or the same address differing only by "
    "protocol or a query parameter. "
    "2. Merge or canonicalize is unsound when the pages are different items "
    "of a kind, such as different releases, years, events, plans or groups, "
    "even if their text overlaps. "
    "3. Create page is sound only when the topic fits the target site's own "
    "subject. A competitor's own product news or archive lists are not a gap. "
    "4. Add internal link is unsound when the target is a numbered list page "
    "or the source is about a different year or item. "
    "5. Fixing a redirect chain of two or more hops is sound."
)
_TOOL = [{"functionDeclarations": [{
    "name": "judge",
    "description": "One verdict per recommendation, in order.",
    "parameters": {"type": "OBJECT", "required": ["verdicts"], "properties": {
        "verdicts": {"type": "ARRAY", "items": {
            "type": "OBJECT", "required": ["label", "reason"], "properties": {
                "label": {"type": "STRING", "enum": list(config.JUDGE_LABELS)},
                "reason": {"type": "STRING"}}}}}},
}]}]


def action_key(action: Dict) -> str:
    """Stable name for a recommendation across runs."""
    return "|".join([action["type"]] + action["urls"][:2])


def fixed_checks(action: Dict) -> List[str]:
    """Problems code can prove without a model."""
    problems = []
    if action["type"] not in ACTION_TEXT:
        problems.append("unknown action type")
    if not action["claims"]:
        problems.append("no claims")
    if any("id" not in claim or "value" not in claim for claim in action["claims"]):
        problems.append("malformed claim")
    lint = rationale_problem(action["rationale"], action)
    if lint:
        problems.append(lint)
    return problems


def _describe(action: Dict) -> str:
    facts = [f"{claim['id']}: {claim_text(claim)}" for claim in action["claims"]]
    return f"type: {action['type']}\nrationale: {action['rationale']}\nfacts:\n" + "\n".join(facts)


def llm_verdicts(actions: List[Dict], llm: Gemini) -> List[Dict]:
    """The model's sound or unsound call per action."""
    verdicts: List[Dict] = []
    for start in range(0, len(actions), config.JUDGE_BATCH):
        batch = actions[start : start + config.JUDGE_BATCH]
        text = "\n\n".join(f"Recommendation {n}\n{_describe(a)}" for n, a in enumerate(batch, 1))
        body = {
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "tools": _TOOL,
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        }
        parts = llm.generate(body)["candidates"][0]["content"]["parts"]
        found = next(p["functionCall"]["args"]["verdicts"] for p in parts if "functionCall" in p)
        if len(found) != len(batch):
            raise LLMError("judge returned the wrong number of verdicts")
        verdicts.extend(found)
    return verdicts


def cohen_kappa(first: List[str], second: List[str]) -> float:
    """Agreement beyond chance between two raters."""
    total = len(first)
    if total == 0:
        return 0.0
    observed = sum(a == b for a, b in zip(first, second)) / total
    labels = set(first) | set(second)
    expected = sum((first.count(l) / total) * (second.count(l) / total) for l in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def read_labels(path: Path) -> Dict[str, str]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["action"]: row["human_label"].strip().lower()
            for row in rows if row["human_label"].strip().lower() in config.JUDGE_LABELS}


def write_sheet(path: Path, actions: List[Dict]) -> None:
    """A sheet for a person to fill in."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["action", "type", "pages", "facts", "rationale", "human_label", "note"])
        for action in actions:
            facts = _describe(action).split("facts:\n", 1)[1]
            writer.writerow([action_key(action), action["type"], "\n".join(action["urls"][:4]),
                             facts, action["rationale"], "", ""])


def evaluate(folders: List[Path], labels_path: Path, seed: int = config.DEFAULT_SEED) -> Dict:
    actions = []
    for folder in folders:
        plan = folder / config.OUTPUT_FOLDER / "action_plan.json"
        actions.extend(json.loads(plan.read_text(encoding="utf-8")))
    checks = {action_key(a): fixed_checks(a) for a in actions}
    llm = Gemini(folders[0] / config.LLM_CACHE_FOLDER, seed)
    verdicts = llm_verdicts(actions, llm)
    # A failed fixed check overrides the model
    judged = {
        action_key(a): "unsound" if checks[action_key(a)] else v["label"]
        for a, v in zip(actions, verdicts)
    }
    reasons = {action_key(a): v["reason"] for a, v in zip(actions, verdicts)}
    report: Dict = {
        "recommendations": len(actions),
        "failed_fixed_checks": {k: v for k, v in sorted(checks.items()) if v},
        "judge_sound": sum(label == "sound" for label in judged.values()),
        "llm": llm.usage(),
    }
    labels = read_labels(labels_path) if labels_path.is_file() else {}
    shared = sorted(set(labels) & set(judged))
    if shared:
        human = [labels[k] for k in shared]
        model = [judged[k] for k in shared]
        report["labelled"] = len(shared)
        report["agreement"] = round(sum(h == m for h, m in zip(human, model)) / len(shared), 4)
        report["cohen_kappa"] = round(cohen_kappa(human, model), 4)
        report["disagreements"] = [
            {"action": k, "human": labels[k], "judge": judged[k], "judge_reason": reasons[k]}
            for k in shared if labels[k] != judged[k]
        ]
    else:
        write_sheet(folders[0] / config.LOG_FOLDER / config.JUDGE_SHEET_NAME, actions)
        report["labelled"] = 0
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="seo-intel-judge")
    parser.add_argument("folders", nargs="+", help="run folders to evaluate")
    parser.add_argument("--labels", default="benchmarks/labels.csv")
    args = parser.parse_args()
    folders = [Path(folder) for folder in args.folders]
    report = evaluate(folders, Path(args.labels))
    target = folders[0] / config.LOG_FOLDER / config.JUDGE_REPORT_NAME
    write_json(target, report)
    print(json.dumps({k: v for k, v in report.items() if k != "disagreements"}, indent=1))
    print(f"Full report: {target}")
    return 0
