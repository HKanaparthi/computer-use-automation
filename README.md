# Computer-Use Automation System

An AI-driven browser automation framework that lets language models discover how to navigate legacy UIs and then replay those flows deterministically without the model.

## What it does

1. **Discovery** — an LLM-driven agent navigates a real web UI, observing the accessibility tree at each step and deciding what to do next. Every action is recorded.
2. **Artifact** — after a successful run, the trace is compiled into a typed, serialisable `CapabilityArtifact` that describes the flow as a reusable, parameterised function.
3. **Replay** — the artifact is replayed in production without the LLM. The replay engine follows each recorded step, verifies checkpoints, and handles errors via a three-tier taxonomy (business outcome / recoverable / hard failure).

## Prerequisites

- Python 3.11+
- An Anthropic API key (`claude-sonnet-4-6`)

## Setup

```bash
git clone (https://github.com/HKanaparthi/computer-use-automation)
cd computer-use-automation

# Create virtual environment
python3 -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Configure API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Running the demo

**Terminal 1 — start the target banking portal:**

```bash
source venv/bin/activate
python -m flask --app target_app.app run --port=5001 --host=127.0.0.1
# Flask is now running at http://127.0.0.1:5001
# Note: Port 5001 avoids conflict with macOS AirPlay on port 5000
```

**Terminal 2 — run the demo commands:**

```bash
source venv/bin/activate

# 1. Discovery: LLM figures out how to look up a member balance
python -m src.main discover \
  --goal "Look up member 12345 and read their savings balance" \
  --target "http://127.0.0.1:5001/login" \
  --credentials "admin:admin123" \
  --output evidence/discovery_run_1/artifact.json

# 2. Replay with a different member ID (no LLM needed)
python -m src.main replay \
  --artifact evidence/discovery_run_1/artifact.json \
  --params '{"member_id": "12346"}' \
  --output evidence/replay_run_1/

# 3. Replay with member not found (business outcome)
python -m src.main replay \
  --artifact evidence/discovery_run_1/artifact.json \
  --params '{"member_id": "99999"}' \
  --output evidence/replay_error_1/

# 4. Replay with permission denied (hard failure → escalation)
python -m src.main replay \
  --artifact evidence/discovery_run_1/artifact.json \
  --params '{"member_id": "88888"}' \
  --output evidence/replay_escalation_1/
```

## Running tests

```bash
pytest tests/ -v
```

All 43 tests cover: artifact schema validation, replay error taxonomy, action classification, PII redaction, and the safety allowlist.

## Project structure

```
computer-use-automation/
├── src/
│   ├── main.py                   CLI entry point
│   ├── agent/
│   │   ├── loop.py               Observe → decide → act loop (discovery mode)
│   │   ├── observer.py           Accessibility tree + screenshot extraction
│   │   ├── planner.py            Claude API prompting and JSON response parsing
│   │   └── executor.py           Playwright action execution
│   ├── artifact/
│   │   ├── schema.py             Pydantic capability data model
│   │   ├── recorder.py           Converts agent trace to typed artifact
│   │   └── store.py              JSON persistence
│   ├── replay/
│   │   ├── engine.py             Deterministic replay (no LLM)
│   │   ├── locator.py            Element location with fallback chain
│   │   ├── checkpoint.py         Step verification
│   │   └── error_handler.py      Three-tier error taxonomy
│   ├── safety/
│   │   ├── allowlist.py          Domain/route/action allowlisting
│   │   ├── classifier.py         Action risk classification
│   │   └── redactor.py           PII redaction from logs
│   ├── escalation/
│   │   ├── detector.py           Stuck-state detection
│   │   ├── handoff.py            Pause → expose → record → resume
│   │   └── console.py            CLI operator console
│   └── observability/
│       ├── logger.py             Structured JSON logging
│       ├── screenshot.py         Screenshot capture
│       └── evidence.py           Evidence directory management
├── target_app/                   Mock Flask banking portal
├── evidence/                     Run outputs (artifacts, logs, screenshots)
├── tests/                        pytest test suite
└── REPORT.md                     Design write-up (7 sections)
```

## Mock banking portal

The Flask app at `target_app/` simulates a legacy credit union member servicing tool with intentionally messy HTML (table-based layouts, deep nesting, no test IDs) and aria-labels as the stable locator anchor.

**Test credentials:** `admin` / `admin123`

**Special member IDs for testing error paths:**
| ID    | Behaviour                                    |
|-------|----------------------------------------------|
| 12345 | Active member — Alice Johnson                |
| 12346 | Active member — Bob Smith                    |
| 12347 | Active member — Carol Davis                  |
| 99999 | Member not found (business outcome)          |
| 88888 | Restricted account (hard failure / escalate) |
| 77777 | Simulates 10-second delay (slow response)    |

## Environment variables

| Variable          | Required | Description              |
|-------------------|----------|--------------------------|
| ANTHROPIC_API_KEY | Yes      | Anthropic API key        |

## Architecture overview

The system is a single-process Python application with clean module boundaries. There is no queue, no cluster, and no external infrastructure — the right choice at this scope. The LLM is only in the loop during discovery; replay is pure deterministic Python that follows the artifact like a program.

See `REPORT.md` for the full design rationale and trade-off discussion.
