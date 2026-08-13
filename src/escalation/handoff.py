"""Human-in-the-loop escalation handoff.

When the automation cannot proceed, it pauses the Playwright session and
presents a CLI prompt to an operator.  The operator can choose to:
  1. Intervene manually in the open browser, then signal completion
  2. Skip the current step and continue
  3. Abort the run entirely

Control transfer model:
  Automation holds the Playwright session.
  When escalating, it signals the console module to prompt the operator.
  The browser window remains visible and interactive throughout.
  Control returns to automation only when the operator signals readiness.
"""

import time
from typing import Literal, Optional

from playwright.sync_api import Page

from src.escalation.console import OperatorConsole
from src.observability.logger import StructuredLogger


class EscalationHandoff:
    """Manages the pause → expose → record → resume lifecycle."""

    def __init__(self) -> None:
        self._console = OperatorConsole()

    def request_intervention(
        self,
        capability: str,
        stuck_at_step: int,
        reason: str,
        page_url: str,
        evidence_path: str,
        page: Optional[Page] = None,
    ) -> Literal["continue", "skip", "abort"]:
        """Pause automation and present the situation to an operator.

        The browser window stays open — the operator can manually interact
        with it before choosing how to proceed.

        Returns:
            "continue" — operator fixed the situation, resume automation
            "skip"     — skip the failing step and continue from next
            "abort"    — stop the run entirely
        """
        context = {
            "capability": capability,
            "stuck_at_step": stuck_at_step,
            "reason": reason,
            "page_url": page_url,
            "evidence_path": evidence_path,
        }

        decision = self._console.prompt_operator(context)
        return decision
