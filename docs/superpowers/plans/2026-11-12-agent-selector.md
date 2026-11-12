# Herdr Pane Agent Selector Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Ship and install a portable numbered local/remote agent selector and native SSH setup guide.

**Architecture:** One Python standard-library executable reads the inherited local Herdr session and enabled native machine profiles. Query subprocesses have deadlines and run in parallel; immutable rows preserve profile and terminal identity until revalidation. SSH attach uses an explicitly selected session and safely quoted arguments.

**Tech Stack:** Python 3.9+, Herdr CLI, OpenSSH; unittest for automated verification.

**Spec:** `docs/workflows.md`, `docs/connection-guide.md`, `docs/acceptance.md`.

## Global Constraints

- Keep native authentication and confirmation prompts; never auto-install, stop servers, take over, or reconnect.
- List agents only, isolate failed sources, clear terminal control characters in displayed metadata.
- No private profiles, addresses, identities, transcripts or paths in source or fixtures.
- Feature branch only; do not recreate the retired command name.
- Local discovery and attach inherit the same socket context. Remote discovery and attach use the same saved profile/session.

## Review Focus

- Duplicate names/pane IDs on different machines must not cross-connect.
- Edited/deleted/disabled profiles and replaced terminal IDs must fail revalidation.
- Hanging subprocesses and Ctrl+C must terminate query children, not servers.
- SSH targets and display strings must not become options, commands or terminal escapes.
- Caller identity can be stale: do not infer the caller from UI focus.

### Task 1: Inventory and identity

Files: create `herdr_pane.py`, `tests/test_herdr_pane.py`.
Interfaces: immutable `Source`, `AgentRow`; `parse_sources`, `parse_agents`, `inventory`, `revalidate`.
- [x] Write tests for local+remote inventory, disabled/offline sources, duplicate names, malformed JSON, changed profile/terminal, and display control characters.
- [x] Run `python3 -m unittest discover -s tests -v`; confirm missing implementation fails.
- [x] Implement profile parsing, bounded subprocesses, source isolation and identity checks.
- [x] Run the whole suite; expected all inventory tests pass.

### Task 2: Interactive connect and setup

Files: extend `herdr_pane.py`, tests.
Interfaces: `attach_command`, `add_remote`, `main`; CLI `--list`, `--add-remote [SSH_TARGET]`, `--remote-session`, `--timeout`.
- [x] Write failing tests for safe argv/SSH quoting, immutable selection, empty/cancel/invalid input, native setup delegation and no takeover/retry.
- [x] Implement numbered menu, target revalidation, TTY attach and native setup with explicit session prompt defaulting to default.
- [x] Run the suite; expected all tests pass.
- [x] Run live list and an isolated terminal attach/detach; do not attach a user's working agent.

### Task 3: Delivery

Files: update README, connection guide, acceptance and review records; add installation instructions.
- [x] Update implemented state, install command, dependencies and verification limits.
- [x] Get independent review from the existing right-hand agent via Herdr; resolve material findings with regression tests.
- [ ] Run tests, diff checks and repeated working-tree/history secret scans.
- [ ] Commit on `feat/agent-selector`, publish only reviewed files through the authenticated peer, verify the remote tree.
- [ ] Back up the local launcher and atomically install the reviewed executable. Verify local and remote agents appear and retired entry stays absent.
