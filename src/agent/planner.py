"""LLM prompting and action parsing for the discovery agent.

The planner is the only module that touches the Anthropic API.  It takes the
current page state and action history, sends a structured prompt to the model,
and parses the JSON response into a typed action dict.

We keep the prompt tight and demand JSON output to make parsing reliable.
The model is instructed to classify its own actions and assess reversibility —
this feeds directly into the artifact's safety metadata.
"""

import json
import re
from typing import Any, Optional

import anthropic


SYSTEM_PROMPT = """You are an AI agent operating a web browser to accomplish a goal on behalf of a user.
You observe the current page state (accessibility tree) and decide the next action.

Rules:
- Prefer accessibility labels for locating elements — they are more stable than CSS selectors.
- Never take destructive actions without explicit instruction.
- If you have accomplished the goal, respond with action "done" and include the extracted data.
- If you are stuck (same state for multiple steps), respond with action "stuck".
- Be concise in reasoning — one or two sentences is enough.
- You must respond with valid JSON only. No markdown fences, no extra text.

Response schema:
{
  "reasoning": "Brief explanation of why you chose this action",
  "action": "click" | "type" | "navigate" | "read" | "wait" | "done" | "stuck",
  "navigate_url": "full URL to go to (only when action is navigate)",
  "locator": {
    "strategy": "accessibility_label" | "text_content" | "role_and_name" | "css_selector",
    "value": "the identifier string",
    "description": "human-readable description of this element",
    "fallbacks": [
      {"strategy": "text_content", "value": "fallback text", "description": "text fallback"},
      {"strategy": "css_selector", "value": "input[name='member_id']", "description": "CSS fallback"}
    ],
    "text_hint": "visible text near or on the element",
    "reasoning": "why this locator will remain stable"
  },
  "input_value": "text to type (only when action is type)",
  "extracted_data": {"key": "value"},
  "checkpoint": "What you expect to see on the page after this action succeeds"
}

IMPORTANT: For "navigate" actions, set "navigate_url" to the full URL (e.g., "http://example.com/page"). Do NOT use the locator for navigation — it's only for element targeting on the current page.
For "click", "type", and "read" actions, always provide a locator.
For "done", set extracted_data with all values you found.
For "stuck", explain in reasoning why you cannot proceed.

For "done", set extracted_data to the values you found. For "stuck", set reasoning to why.
"""


class AgentPlanner:
    """Calls the Claude API to decide the next agent action."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.Anthropic()
        self._model = model

    def decide(
        self,
        goal: str,
        page_state: dict[str, str],
        action_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Ask the LLM what to do next and return a parsed action dict.

        Raises:
            ValueError: if the model returns unparseable output after retries.
        """
        user_message = self._build_user_message(goal, page_state, action_history)

        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = message.content[0].text.strip()
        return self._parse_response(raw)

    def _build_user_message(
        self,
        goal: str,
        page_state: dict[str, str],
        action_history: list[dict[str, Any]],
    ) -> str:
        history_text = (
            json.dumps(action_history[-5:], indent=2)
            if action_history
            else "(none)"
        )
        page_text = page_state.get("page_text", "")
        return (
            f"Goal: {goal}\n\n"
            f"Current URL: {page_state.get('url', '')}\n"
            f"Page title: {page_state.get('title', '')}\n\n"
            f"Accessibility tree:\n{page_state.get('accessibility_tree', '')}\n\n"
            f"Visible page text:\n{page_text}\n\n"
            f"Last {min(5, len(action_history))} actions taken:\n{history_text}\n\n"
            f"Decide the next action."
        )

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Extract the first JSON object from the model's response.

        The model occasionally appends reasoning text after the JSON block.
        We extract the first well-formed JSON object using brace counting rather
        than relying on the response ending cleanly after the closing brace.
        """
        # Strip accidental markdown fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()

        # Fast path: the whole response is valid JSON
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Slow path: brace-count to extract the first complete JSON object
        start = cleaned.find("{")
        if start == -1:
            raise ValueError(f"No JSON object found in response: {raw[:300]}")

        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(cleaned[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start: i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Extracted invalid JSON: {candidate[:300]}") from exc

        raise ValueError(f"Unterminated JSON object in response: {raw[:300]}")
