"""CLI entry point for the Computer-Use Automation System.

Usage:
  python -m src.main discover --goal "..." --target "http://..." --output path/to/artifact.json
  python -m src.main replay  --artifact path/to/artifact.json --params '{"member_id":"12346"}' --output evidence/replay_run_1/
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        print("Copy .env.example to .env and add your key.", file=sys.stderr)
        sys.exit(1)


def cmd_discover(args: argparse.Namespace) -> None:
    """Run the LLM-driven discovery agent."""
    _require_api_key()

    from src.agent.loop import run_discovery

    run_id = str(uuid.uuid4())[:8]
    output = args.output or f"evidence/discovery_run_{run_id}/artifact.json"
    args.output = output
    run_dir = str(Path(output).parent)

    print(f"[Discovery] Goal     : {args.goal}")
    print(f"[Discovery] Target   : {args.target}")
    print(f"[Discovery] Artifact : {args.output}")
    print(f"[Discovery] Run dir  : {run_dir}")
    print()

    artifact = run_discovery(
        goal=args.goal,
        target_url=args.target,
        artifact_output_path=args.output,
        run_dir=run_dir,
        credentials=getattr(args, "credentials", None),
    )

    if artifact:
        print(f"[Discovery] Success — artifact saved to {args.output}")
        print(f"[Discovery] Steps recorded: {len(artifact.steps)}")
    else:
        print("[Discovery] Failed — see run_log.json for details.", file=sys.stderr)
        sys.exit(1)


def cmd_replay(args: argparse.Namespace) -> None:
    """Replay a saved capability artifact with given parameters."""
    from src.artifact.store import ArtifactStore
    from src.replay.engine import ReplayEngine

    params: dict[str, str] = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"Error: --params must be valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

    run_id = str(uuid.uuid4())[:8]
    output_dir = (args.output or f"evidence/replay_run_{run_id}").rstrip("/")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    store = ArtifactStore()
    try:
        artifact = store.load(args.artifact)
    except FileNotFoundError:
        print(f"Error: Artifact not found: {args.artifact}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error loading artifact: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[Replay] Artifact  : {args.artifact} ({artifact.name})")
    print(f"[Replay] Parameters: {params}")
    print(f"[Replay] Output dir: {output_dir}")
    print()

    engine = ReplayEngine(run_dir=output_dir, run_id=run_id)
    result = engine.run(artifact=artifact, params=params)

    print(f"[Replay] Status          : {result.status.upper()}")
    print(f"[Replay] Steps completed : {result.steps_completed}/{result.steps_total}")
    print(f"[Replay] Duration        : {result.duration_ms}ms")

    if result.status == "success" and result.outputs:
        print(f"[Replay] Outputs:")
        for k, v in result.outputs.items():
            print(f"           {k}: {v}")
    elif result.status == "business_outcome" and result.business_outcome:
        print(f"[Replay] Business outcome: {result.business_outcome}")
    elif result.error:
        print(f"[Replay] Error: {result.error}")

    print(f"[Replay] Evidence saved to: {result.evidence_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="computer-use-automation",
        description="AI-driven computer-use automation with deterministic replay",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # discover sub-command
    discover_parser = sub.add_parser("discover", help="Run LLM-guided discovery")
    discover_parser.add_argument("--goal", required=True, help="Natural language goal")
    discover_parser.add_argument("--target", required=True, help="Starting URL")
    discover_parser.add_argument("--output", default=None, help="Path to save the artifact JSON (auto-generated if omitted)")
    discover_parser.add_argument("--credentials", default=None, help="Login credentials as user:pass (never logged)")

    # replay sub-command
    replay_parser = sub.add_parser("replay", help="Replay a saved capability artifact")
    replay_parser.add_argument("--artifact", required=True, help="Path to artifact JSON")
    replay_parser.add_argument("--params", default="{}", help="JSON string of runtime parameters")
    replay_parser.add_argument("--output", default=None, help="Directory to save evidence (auto-generated if omitted)")

    args = parser.parse_args()

    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "replay":
        cmd_replay(args)


if __name__ == "__main__":
    main()
