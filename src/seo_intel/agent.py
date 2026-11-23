"""LLM agent that ranks actions through tools."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from seo_intel import config
from seo_intel.facts import PAGE_FIELDS, Facts
from seo_intel.llm import Gemini, LLMError
from seo_intel.plan import REASONS, claim_text, supported_reasons

_SYSTEM = (
    "You are an SEO lead building an action plan for a website. "
    "You can only learn about the site through the tools. "
    "Candidate actions were found by code and each has verified claims. "
    "Steps: call list_actions, inspect the promising ones with get_action, "
    "optionally check pages, then call submit_plan once. "
    f"Make at most {config.AGENT_MAX_LOOKUPS_PER_STEP} tool calls per step. "
    f"Pick up to {config.PLAN_ACTIONS} actions, ordered by expected impact, "
    "and prefer a mix of action types over many of one type. "
    "You do not write prose. For each action choose the reason codes that "
    "best justify it, strongest first, only from the codes get_action lists "
    "for that action. Code turns them into checked sentences. "
    "The only reason codes that exist are: " + ", ".join(REASONS) + "."
)


def _string(description: str) -> Dict:
    return {"type": "STRING", "description": description}


_TOOLS = [{
    "functionDeclarations": [
        {
            "name": "list_actions",
            "description": "List candidate actions, best score first.",
            "parameters": {"type": "OBJECT", "properties": {
                "offset": {"type": "INTEGER", "description": "Rows to skip."}}},
        },
        {
            "name": "get_action",
            "description": "Full detail and claims of one candidate action.",
            "parameters": {"type": "OBJECT", "properties": {"id": _string("Action id.")},
                           "required": ["id"]},
        },
        {
            "name": "get_page",
            "description": "Crawled fields of one page.",
            "parameters": {"type": "OBJECT", "properties": {"url": _string("Page URL.")},
                           "required": ["url"]},
        },
        {
            "name": "get_graph_stats",
            "description": "Internal link numbers for one page.",
            "parameters": {"type": "OBJECT", "properties": {"url": _string("Page URL.")},
                           "required": ["url"]},
        },
        {
            "name": "submit_plan",
            "description": "Submit the final ranked plan and finish.",
            "parameters": {"type": "OBJECT", "required": ["actions"], "properties": {
                "actions": {"type": "ARRAY", "items": {
                    "type": "OBJECT", "required": ["id", "reasons"],
                    "properties": {"id": _string("Action id."),
                                   "reasons": {"type": "ARRAY", "items": _string("Reason code.")}},
                }}}},
        },
    ]
}]


def _short(value, limit: int = 100):
    return value[:limit] if isinstance(value, str) else value


class Toolbox:
    """The only window the model has on the data."""

    def __init__(self, candidates: List[Dict], facts: Facts):
        self.candidates = candidates
        self.by_id = {c["id"]: c for c in candidates}
        self.facts = facts

    def list_actions(self, offset: int = 0) -> Dict:
        offset = max(0, int(offset))
        rows = self.candidates[offset : offset + config.AGENT_LIST_PAGE_SIZE]
        return {
            "total": len(self.candidates),
            "rows": [
                f"{c['id']} {c['type']} score={c['score']} reasons={','.join(supported_reasons(c))}"
                for c in rows
            ],
        }

    def get_action(self, id: str = "") -> Dict:
        action = self.by_id.get(id)
        if action is None:
            return {"error": "unknown action id"}
        claims = [f"{c['id']} {claim_text(c, 100)}" for c in action["claims"]]
        reasons = {code: REASONS[code].replace(" {refs}", "") for code in supported_reasons(action)}
        return {"id": id, "type": action["type"], "score": action["score"],
                "claims": claims, "reasons_you_may_use": reasons}

    def get_page(self, url: str = "") -> Dict:
        if not self.facts.knows(url):
            return {"error": "page not in crawl"}
        return {name: _short(self.facts.field(url, name)) for name in PAGE_FIELDS}

    def get_graph_stats(self, url: str = "") -> Dict:
        if not self.facts.knows(url):
            return {"error": "page not in crawl"}
        return {name: self.facts.field(url, name) for name in ("inlinks", "click_depth")}

    def call(self, name: str, args: Dict) -> Dict:
        tool = getattr(self, name, None) if name in (
            "list_actions", "get_action", "get_page", "get_graph_stats") else None
        if tool is None:
            return {"error": "unknown tool"}
        try:
            return tool(**args)
        except (TypeError, ValueError):
            return {"error": "bad arguments"}


def _too_big(body: Dict) -> bool:
    size = len(json.dumps(body, ensure_ascii=False))
    return size / config.LLM_CHARS_PER_TOKEN > config.LLM_PROMPT_TOKEN_BUDGET


def _blank(parts: List[Dict], note: Dict) -> bool:
    for part in parts:
        response = part.get("functionResponse")
        if response and response["response"] != note:
            response["response"] = note
            return True
    return False


def _trim(contents: List[Dict]) -> bool:
    """Blank one tool result, oldest messages first."""
    for message in contents[1:-1]:
        if _blank(message.get("parts", []), {"trimmed": True}):
            return True
    # Last resort: shorten the newest answers, keep the first
    newest = contents[-1].get("parts", [])
    return _blank(list(reversed(newest[1:])), {"error": "too much at once, ask again"})


def run_agent(candidates: List[Dict], facts: Facts, llm: Gemini) -> Optional[List[Dict]]:
    """Ranked picks with rationales, or None on failure."""
    if not candidates:
        return None
    toolbox = Toolbox(candidates, facts)
    contents = [{"role": "user", "parts": [{"text": "Build the action plan now."}]}]
    try:
        for step in range(config.LLM_MAX_STEPS):
            calling = {"mode": "ANY"}
            if step == config.LLM_MAX_STEPS - 1:
                # Last step: the plan must be submitted
                calling["allowedFunctionNames"] = ["submit_plan"]
            body = {
                "systemInstruction": {"parts": [{"text": _SYSTEM}]},
                "contents": contents,
                "tools": _TOOLS,
                "toolConfig": {"functionCallingConfig": calling},
            }
            while _too_big(body) and _trim(contents):
                pass
            if _too_big(body):
                raise LLMError("prompt too big after trimming")
            result = llm.generate(body)
            reply = result["candidates"][0]["content"]
            calls = [p["functionCall"] for p in reply.get("parts", []) if "functionCall" in p]
            if not calls:
                raise LLMError("model made no tool call")
            contents.append(reply)
            answers = []
            for call in calls:
                args = call.get("args") or {}
                if call["name"] == "submit_plan":
                    picks = args.get("actions")
                    if not isinstance(picks, list):
                        raise LLMError("plan was not a list")
                    return picks
                answers.append({"functionResponse": {
                    "name": call["name"], "response": toolbox.call(call["name"], args)}})
            contents.append({"role": "user", "parts": answers})
        raise LLMError("ran out of steps")
    except (LLMError, KeyError, IndexError, TypeError) as exc:
        # The run continues with template text
        llm.last_error = f"{type(exc).__name__}: {exc}"
        return None
