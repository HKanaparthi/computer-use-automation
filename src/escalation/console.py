"""Minimal operator console for human-in-the-loop escalation.

Presents a CLI prompt when the automation is stuck or hits a hard failure.
The mechanism is real: automation pauses, the operator sees the live browser,
makes a choice, and automation resumes based on that choice.

A full real-time co-browsing console is out of scope for this implementation.
The CLI prompt is the minimum viable handoff mechanism — it satisfies the
pause → expose → record → resume contract without premature infrastructure.
"""

from typing import Any, Literal


class OperatorConsole:
    """CLI-based operator console for escalation handling."""

    def prompt_operator(
        self, context: dict[str, Any]
    ) -> Literal["continue", "skip", "abort"]:
        """Print escalation context and wait for operator input."""
        print("\n" + "=" * 60)
        print("[ESCALATION] Automation paused — operator action required")
        print("=" * 60)
        print(f"  Capability : {context.get('capability', 'unknown')}")
        print(f"  Stuck at   : Step {context.get('stuck_at_step', '?')}")
        print(f"  Reason     : {context.get('reason', '')}")
        print(f"  Browser URL: {context.get('page_url', '')}")
        print(f"  Evidence   : {context.get('evidence_path', '')}")
        print("-" * 60)
        print("The browser window is open. You may interact with it manually.")
        print()
        print("Options:")
        print("  1. Continue  — I fixed the issue, resume automation")
        print("  2. Skip      — Skip this step and continue from the next")
        print("  3. Abort     — Stop this run entirely")
        print("-" * 60)

        mapping = {"1": "continue", "2": "skip", "3": "abort"}

        while True:
            try:
                choice = input("Enter choice [1/2/3]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nNo input received — aborting run.")
                return "abort"

            if choice in mapping:
                decision = mapping[choice]
                print(f"[ESCALATION] Operator chose: {decision.upper()}")
                print("=" * 60 + "\n")
                return decision

            print("  Invalid choice. Enter 1, 2, or 3.")
