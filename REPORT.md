# Design Report — Computer-Use Automation System

---

## 1. Architecture

The system is a single-process Python application with six modules separated by concern: agent loop, artifact schema, replay engine, safety layer, escalation handler, and observability. There are no queues, no distributed components, and no external infrastructure.

**Why single-process?**  
The assignment asks for a system that demonstrates design judgment, not operational scale. Introducing a task queue (Celery, RQ) or a separate browser-farm service would add moving parts without solving any design problem that exists at this scope. Single-process also makes the control flow explicit and readable — the call stack is the architecture. The right time to add a worker tier is when a single process becomes the bottleneck, not before.

**Module boundaries:**

```
src/
  agent/        ← everything that touches the LLM
  artifact/     ← schema + persistence (no browser, no LLM)
  replay/       ← deterministic execution (no LLM)
  safety/       ← policy enforcement (pure functions)
  escalation/   ← human handoff (pause/resume lifecycle)
  observability/← logging + screenshots (side-effecting, isolated)
```

Each boundary is enforced by dependency direction: `replay/` imports `artifact/` but never `agent/`. The LLM is entirely contained in `agent/planner.py`. If you replaced the Claude API with a local model tomorrow, only that file changes.

**Control flow:**

```
discover command
  └── agent/loop.py
        ├── agent/observer.py   (page state)
        ├── agent/planner.py    (LLM decision)
        ├── agent/executor.py   (Playwright action)
        └── artifact/recorder.py → artifact/store.py

replay command
  └── replay/engine.py
        ├── replay/locator.py   (element resolution)
        ├── replay/checkpoint.py (step verification)
        └── replay/error_handler.py (three-tier taxonomy)
```

---

## 2. Artifact Schema

The artifact is the central design decision. It transforms a one-off LLM observation into a reusable, typed capability that an AI agent can invoke like a function:

```
lookup_member_balance(member_id="12345") → {"savings_balance": "$15,234.56"}
```

**Typed input/output parameters:**  
`input_params` and `output_schema` are typed dictionaries (Pydantic models). This is what makes the artifact callable: a downstream orchestration system can introspect the schema, validate its inputs, and know exactly what to expect back — without running the LLM again.

**Multiple locator strategies per element:**  
Each `ElementLocator` has a `primary` strategy and an ordered list of `fallbacks`. The primary is always the accessibility label (most stable). Fallbacks degrade through text content to CSS selectors (least stable). The `reasoning` field documents why the primary was chosen — so a future human reviewer can assess whether it's still valid after a UI update.

The fallback chain matters in practice: table-layout legacy apps frequently restructure divs and rename CSS classes without touching aria-labels. An automation that relies solely on CSS selectors breaks on every visual redesign; one that leads with accessibility labels survives them.

**Per-step error handlers:**  
Error handlers live on each `ActionStep`, not globally. This is intentional: the failure modes of a login step (session cookie) are different from those of a search step (member not found) which are different from those of a confirmation step (permission denied). A global catch would erase that distinction and prevent callers from knowing what went wrong.

**Sensitivity level:**  
The artifact carries a single `sensitivity_level` for the whole capability (`read_only`, `state_changing`, or `destructive`). The safety layer reads this before execution starts — no need to walk every step to decide whether to require confirmation. Individual steps also carry `is_reversible` for step-level granularity if needed.

---

## 3. Determinism & Error Handling

**How replay avoids the LLM:**  
The replay engine loads the artifact JSON and executes each `ActionStep` in order. It does not call the planner, observer, or any inference endpoint. The artifact is the program. The only runtime variability is parameter substitution (replacing `{{member_id}}` with the actual value) and error detection.

**Locator fallback chain:**  

```
accessibility_label → text_content → role_and_name → css_selector
```

At each step, the engine tries the primary locator within the configured timeout. If the element is not found or not visible, it tries fallbacks in order. If all strategies fail, it raises `LOCATOR_FAILED` — a hard failure. This is the correct behaviour: silently continuing after a locator miss would produce silent data corruption.

**Three-tier error taxonomy:**

| Tier | Example | Action |
|------|---------|--------|
| `business_outcome` | "No member found with ID 99999" | Return structured result to caller; not a failure |
| `recoverable` | Session timeout → login page appears | Re-authenticate and retry from last checkpoint |
| `hard_failure` | "Access Denied — restricted account" | Stop, log everything, escalate |

The `business_outcome` tier is the most important distinction. When a downstream AI agent asks "what is member 99999's balance?" and the member does not exist, the correct answer is `{"status": "business_outcome", "code": "MEMBER_NOT_FOUND"}` — not an exception. The caller asked a valid question and got a valid answer. Throwing an error here would force every caller to add exception handling for normal operational conditions.

**Checkpoint verification:**  
After every step, the engine evaluates a `Checkpoint` — a declarative assertion about the expected page state. Supported types: `element_visible`, `element_contains`, `url_matches`, `text_present`. A failed checkpoint before a known error is matched means the UI changed unexpectedly (hard failure). A failed checkpoint that matches a known error pattern routes to the correct handler.

---

## 4. Heterogeneity & Multi-tenancy

**Surface abstraction:**  
The locator strategy hierarchy is designed to extend beyond web browsers. Accessibility APIs exist on every major platform:

- Web: WAI-ARIA attributes (`aria-label`, `role`, `name`) — what we use
- macOS desktop: NSAccessibility (accessible names, roles, values) — same concepts
- Windows desktop: UI Automation (AutomationId, Name, ControlType) — same structure
- Legacy Windows: MSAA (accessible name + role) — same model

The `LocatorStrategy.strategy` enum could be extended with `accessibility_id` or `automation_element` strategies for desktop. The `ElementLocatorEngine` in `replay/locator.py` would map these to the appropriate platform-specific calls. The artifact schema and replay engine remain unchanged — only the executor backend differs.

**Parameterised artifacts:**  
The `input_params` dictionary on every artifact is what enables multi-tenant reuse. During discovery, the agent types `12345` into the member ID field. The recorder detects that this value matches a known parameter and substitutes `{{member_id}}` in the stored template. At replay time, any caller can supply `member_id="12346"` and get the correct result for a different member.

For a true multi-tenant deployment, tenant-specific overrides would live in a thin config layer above the artifact: `{"entry_url": "https://tenant-b.portal.example.com/login", "credentials_secret": "vault://tenant-b/login"}`. The artifact steps themselves remain unchanged because they navigate by aria-labels, not by hardcoded URLs.

**Version drift detection:**  
The artifact stores a `target_app_fingerprint` field — a hash of the aria-labels of key elements on the entry page. Before each replay, the engine can re-compute this fingerprint and compare it to the stored value. A mismatch means the UI changed since discovery: the safe response is to refuse the replay and flag re-discovery rather than attempt a run that will likely produce wrong outputs silently.

---

## 5. Escalation & Handoff

**Stuck detection:**  
The `StuckDetector` tracks the URL of each step. If the same URL appears `threshold` times consecutively, the engine concludes it is not making progress and escalates. This is a proxy metric — URL sameness doesn't prove nothing happened, but it's cheap to compute and catches the common cases (form validation loop, repeated permission denials, redirect cycles).

The discovery agent uses an additional signal: accessibility tree sameness. If the tree hasn't changed across three consecutive LLM decisions, the agent exits with "stuck" rather than spinning on the same state.

**Pause → expose → record → resume:**  
When escalation is triggered:

1. The Playwright session is **paused** — the browser stays open, frozen on the current page.
2. The `OperatorConsole` prints the full context to the terminal: which capability, which step, why it stopped, the live URL, and the path to screenshots.
3. The operator sees the **live browser window** and can manually interact with it.
4. The operator enters a choice: continue (automation resumes from the next step), skip (advance past the failing step), or abort.
5. The decision is logged and the `ReplayEngine` acts on it.

The "record what the human did" requirement is partially satisfied: the human's choice (continue/skip/abort) is logged with a timestamp and step context. Recording fine-grained mouse/keyboard actions during the manual window would require injecting a CDP listener — that is scoped out (see section 7).

**Control transfer model:**  
At any moment, exactly one of two parties is in control:

- **Automation** — driving Playwright via the replay engine
- **Human operator** — in control when `OperatorConsole.prompt_operator()` is blocking on `input()`

There is no ambiguity: the automation cannot advance while waiting for `input()`, and the operator cannot accidentally trigger automation logic while typing in the browser.

---

## 6. Safety

**Allowlist enforcement:**  
Before any run begins, the target URL is checked against `SAFETY_CONFIG["allowed_domains"]`. Currently `localhost:5000` and `127.0.0.1:5000`. Any other domain causes an immediate abort with a `safety_block` log entry. Specific URL patterns (e.g., `/admin/*`) are additionally blocked by regex before navigation.

This is a coarse first gate, not a complete firewall. The intent is to prevent the automation from accidentally navigating to external sites if a redirect or crafted link is encountered during a run.

**Action classification:**  
Every action is classified before execution via `safety/classifier.py`:

- `read_only` — navigate, read, wait, type (typing without submitting is non-destructive)
- `state_changing` — click on "Confirm", "Submit", or "Open Sub-Account" buttons
- `destructive` — click on "Delete", "Remove", "Close Account" (irreversible)

The artifact records the `sensitivity_level` of the whole capability and the `is_reversible` flag per step. A downstream orchestrator can gate `state_changing` capabilities behind a confirmation prompt before even starting the replay.

**PII redaction:**  
The `safety/redactor.py` module is called at the point of logging — before any log entry touches disk. It matches:

- Social Security numbers (`XXX-XX-XXXX`) → `[SSN-REDACTED]`
- Full payment card numbers → `[CARD-REDACTED]`
- Long account numbers → `[ACCT-XXXX<last4>]`
- Passwords (by key name) → `[REDACTED]`

Passwords are never passed through the logger at all — the re-login recovery path calls `fill("admin123")` directly without logging the value.

The redactor is conservative: it will not miss a pattern if it appears inside a longer string, but it may over-redact numbers that happen to be long. This is the correct trade-off for a banking context.

---

## 7. Cuts — What Was Left Out and Why

**What was cut:**

*Fine-grained manual action recording during escalation*  
The current implementation logs the operator's *choice* (continue/skip/abort) but not the specific clicks and keystrokes they performed in the browser window during the manual window. Recording those would require attaching a Chrome DevTools Protocol (CDP) session listener to the Playwright page — feasible, but a significant scope addition. The pause/expose/resume contract is fully implemented; the recording granularity is the cut.

*Artifact versioning and upgrade path*  
The schema has a `version` field and a `target_app_fingerprint`, but there is no migration logic. If the UI changes and the fingerprint no longer matches, the safe response is to re-discover. An upgrade path (attempt the run, detect the drift point, re-discover just the affected steps) would make the system more resilient to incremental UI changes — that is meaningful engineering that is out of scope here.

*Desktop surface support (macOS/Windows automation)*  
The architecture is explicitly designed to extend to desktop apps (accessibility APIs map cleanly), but the executor currently speaks only to Playwright. A desktop adapter would implement the same `execute(action, locator)` interface against `pyautogui` + `pywinauto` or macOS's `ApplicationServices` framework.

*Multi-tenant configuration layer*  
The artifact schema supports parameterised inputs and tenant-scoped overrides are architecturally straightforward, but the config resolution layer (reading tenant credentials from a vault, overriding the entry URL per environment) is not built.

*Real-time operator console*  
A web-based co-browsing console with live screenshot streaming would make the escalation experience far smoother for operators. The CLI prompt is the minimum viable mechanism that satisfies the pause/expose/resume contract.

**What would be built next with more time:**

1. CDP-based action recording during manual intervention windows
2. UI drift detection with selective re-discovery of changed steps
3. Desktop executor adapter (macOS Accessibility API + Windows UI Automation)
4. Artifact library with versioning, tagging, and search
5. Tenant config resolution (vault integration for credentials)
6. Web operator console with live screenshot streaming during escalation
