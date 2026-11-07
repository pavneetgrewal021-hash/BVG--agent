"""
EXPERIMENT: a tool-calling agent that decides the follow-up action itself.

The model gets the policy in its system prompt and four read-only tools to look up a
candidate's situation, plus decide(). It has no tool that sends or changes anything.
eval/run_followup_eval.py compares its decisions with plan_followup(), the rule version
of the same policy. The app uses the rules; this module exists to measure whether a small
local model can be trusted to make the decision instead.
"""
import json
from types import SimpleNamespace

from services.followup import ACTIONS
from services.llm_client import LLMError, chat_tools

MAX_STEPS = 6
DEFAULT_AGENT_MODEL = "phi4-mini"  # qwen3:4b could not finish a tool call on this hardware (see eval/README.md)


def text_tool_calls(content):
    """
    Some local models write the tool call as text, e.g. '... [{"name": "decide", "arguments": {...}}]',
    instead of in Ollama's tool_calls field. Parse that text into the same shape.
    """
    content = content or ""
    for start, end in (("[", "]"), ("{", "}")):
        i, j = content.find(start), content.rfind(end)
        if i == -1 or j <= i:
            continue
        try:
            data = json.loads(content[i:j + 1])
        except json.JSONDecodeError:
            continue
        calls = data if isinstance(data, list) else [data]
        parsed = [SimpleNamespace(function=SimpleNamespace(name=c["name"],
                                                           arguments=c.get("arguments") or c.get("parameters") or {}))
                  for c in calls if isinstance(c, dict) and "name" in c]
        if parsed:
            return parsed
    return []

SYSTEM_PROMPT = """You decide the next follow-up action for one job candidate's background verification.
Look up the facts with the tools, then call decide exactly once.

Policy (apply the first rule that matches):
1. If the candidate is not finished (documents missing OR open flags) AND follow-ups sent >= {limit}: escalate_to_hr
2. If there are open flags: request_clarification
3. If any required document is missing: request_documents
4. Otherwise: none

A document is missing when it is in the required list but not in the received list."""


def run_agent(state, settings, required_docs):
    """
    state: {"received": [...], "flags": [(type, doc_type)], "followups_sent": int}
    Returns {"action", "reason", "steps", "tool_calls", "error"}; action None if the agent never decided.
    """
    decision = {}
    trace = []

    # Tools read from the given state only. Docstrings and type hints become the tool schema.
    def get_required_documents() -> list:
        """List the document types every candidate must submit."""
        return required_docs

    def get_received_documents() -> list:
        """List the document types received from this candidate."""
        return state["received"]

    def get_open_flags() -> list:
        """List open problems found across the candidate's documents, as 'flag type: document type'."""
        return [f"{t}: {d}" for t, d in state["flags"]]

    def get_followups_sent() -> int:
        """Number of follow-up emails already sent to this candidate."""
        return state["followups_sent"]

    def decide(action: str, reason: str) -> str:
        """Record the final decision. action must be one of: none, request_documents,
        request_clarification, escalate_to_hr. reason: one short sentence."""
        decision.update(action=action, reason=reason)
        return "recorded"

    tools = {f.__name__: f for f in (get_required_documents, get_received_documents,
                                     get_open_flags, get_followups_sent, decide)}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(limit=settings.get("max_followups", 2))},
        {"role": "user", "content": "Decide the follow-up action for this candidate."},
    ]

    agent_settings = {**settings, "llm_model": settings.get("agent_model", DEFAULT_AGENT_MODEL)}
    for step in range(1, MAX_STEPS + 1):
        try:
            reply = chat_tools(messages, list(tools.values()), agent_settings)
        except LLMError as e:
            return {"action": None, "reason": None, "steps": step, "tool_calls": trace, "error": str(e)}
        messages.append(reply)
        calls = reply.tool_calls or text_tool_calls(reply.content)
        if not calls:
            messages.append({"role": "user", "content": "Use the tools, then call decide."})
            continue
        for call in calls:
            name, args = call.function.name, dict(call.function.arguments or {})
            trace.append(name)
            if name not in tools:
                result = f"unknown tool {name}"
            else:
                try:
                    result = tools[name](**args)
                except TypeError as e:
                    result = f"bad arguments: {e}"
            messages.append({"role": "tool", "content": str(result), "tool_name": name})
        if decision:
            action = decision["action"] if decision["action"] in ACTIONS else None
            return {"action": action, "reason": decision.get("reason"), "steps": step,
                    "tool_calls": trace, "error": None if action else f"invalid action {decision['action']!r}"}

    return {"action": None, "reason": None, "steps": MAX_STEPS, "tool_calls": trace,
            "error": "no decision within the step limit",
            "last_reply": " ".join((reply.content or "").split())[:200]}
