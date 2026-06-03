# holster-scan

**See what an AI agent would inherit — and catch hallucinated/typosquatted packages — before the agent runs or the repo gets shared. Local. Free. No signup.**

Coding agents (Claude Code, Cursor, Codex) and MCP servers now reach your files, shell, tokens, and tools. `holster-scan` reads your repo + agent config locally and tells you two things plainly: **is this safe to run, and is this safe to share** — plus the AI-specific risk nobody else checks: **hallucinated / slopsquatted package imports.**

Not another secret scanner. A pre-run / pre-share boundary check for AI-agent work.

```bash
pipx install git+https://github.com/nauta-ai/holster-scan   # PyPI + Homebrew coming
holster-scan .                                              # scan the current repo + any agent/MCP config
```

Runs entirely on your machine. Your code, configs, and secrets never leave it. No account, no telemetry.

---

## What it catches

- **Hallucinated / slopsquatted packages** — AI-invented imports (`reqeusts`, `langchain-utils`, `panda`) and published typosquats that real scanners miss. (95% recall, 0.36% false-positive rate on 10 major real repos.)
- **What the agent inherits** — shell env, file scope, tokens, MCP tools, cloud creds.
- **Safe-to-share gaps** — live-credential pointers, secrets in git history, MCP tools with no allow-list.
- **Blast radius** — what a misused agent or shared config could actually reach.
- **A fix-first order** — five steps, not two hundred warnings.

## What it looks like

```text
$ holster-scan .

  Agent Boundary Report  ·  client-portal-agent

  Safe to run?     ⚠  yes, with restrictions   (2 to fix)
  Safe to share?   ✗  no                        (3 blockers)
  Risk             HIGH

  PACKAGES
    ✗ reqeusts            hallucinated — typo of "requests" (not on PyPI)
    ✗ langchain-utils     hallucinated "-utils" helper of langchain

  BOUNDARY
    ⚠ run wrapper inherits full shell env (AWS_*, STRIPE_* visible to agent)
    ⚠ MCP fs-server scope = $HOME, not project
    ✗ docker-compose.override.yml → live key path /Users/.../stripe/live.key
    ✗ .env present in git history (recoverable)
    ✗ MCP tool "shell.exec" has no allow-list

  FIX FIRST
    1 rotate the referenced live key   2 isolate the wrapper env
    3 restrict MCP fs + shell.exec     4 scrub .env from history
    5 re-run  →  target: safe to run + safe to share

  Nothing left your machine.
```

## In CI (GitHub Action)

```yaml
- uses: nauta-ai/holster-scan@v0
  with:
    fail-on: high          # fail the build on high-severity findings
    format: sarif          # results show in GitHub code scanning
```

## Why it's different

- **AI-specific.** It's not fighting Snyk/Semgrep on generic SAST — it catches the risks unique to AI-generated code and agent setups.
- **Local-first by design.** Analysis runs on your machine. `--offline` works; unknown packages are flagged, never silently passed.
- **Boundary, not just secrets.** A clean local run doesn't prove a clean shareable artifact. It checks both.
- **Allow-list your private packages** — `.holster.yml` suppresses internal/vendor-index packages so the noise stays near zero.

## Config

```yaml
# .holster.yml
allow: [ "torch_mlu", "internal-*" ]   # private/vendor packages, not flagged
fail_on: high
registry: on                           # PyPI existence + maintenance checks
```

Open-core. Free to run locally and in CI, forever.

---

<sub>**Need a human to review a real client repo or agent setup in depth?** We do a written **Agent Boundary Review** — safe-to-run / safe-to-share verdict, inheritance map, prioritized fixes — for one repo/config. Founder price $500. Optional live walkthrough. → nautaai.com/holster · Holster by **Nauta AI**.</sub>
