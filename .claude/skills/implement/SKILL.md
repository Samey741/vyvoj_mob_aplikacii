---
name: implement
description: Run the implementer → verifier pipeline on an approved design document.
argument-hint: [path-to-design-doc] [step-number]
---
You are the orchestrator of a multi-agent implementation pipeline.
Raw arguments of this run: `$ARGUMENTS`

Parse them as whitespace-separated values:
- first argument (required): path to the approved design document
- second argument (optional): a step number referring to the
  document's implementation-order section
If no design-document path is given, STOP and ask the user for it.

If a step number is given, the SCOPE of this run is that single step:
tell every subagent to implement or verify ONLY that step, to treat
earlier steps as already present in the codebase, and to leave later
steps alone. If no step number is given, the scope is the whole
document.

You do NOT write code or review code yourself. You delegate to two
subagents and route work between them based on their reports.

## Step 0 — Validate the input
Read the design document. It must contain: goal and scope, affected
files/modules, interfaces and data model, ordered implementation steps,
test strategy, risks. If any section is missing or contradicts the
codebase, STOP and ask the user — do not guess.

Record the diff base: run `git rev-parse HEAD` and keep the SHA as
BASE. If the repository has no commits or the working tree is dirty,
STOP and ask the user to commit first — the verifier needs a clean base.

## Step 1 — Implement
Use the `implementer` subagent (model: sonnet). Pass it:
- the full design document
- the scope (step number, or "whole document")
- nothing else from this conversation
Wait for its Implementation Report.

If the report says the build or tests fail, send it back to the same
implementer with the failing output. Maximum 3 rounds; then stop and
report to the user.

## Step 2 — Verify
Use a NEW `verifier` subagent (model: opus) with a fresh context.
Pass it ONLY:
- the design document
- the scope (step number, or "whole document")
- the Implementation Report
- the output of `git diff BASE` (plus `git status --short` for new files)
Never pass the implementer's conversation or your own reasoning.
Wait for its Verification Report.

## Step 3 — Route the verdict
- PASS with no findings, or only findings whose cause = design →
  go to Step 4 (design findings go into the PR description).
- PASS with findings whose cause = implementation (any severity) →
  use a new `implementer` subagent with the design document + the
  scope + ONLY those implementation findings from the Verification
  Report (tell it to leave design findings alone and to add tests
  that would have caught each fix). Then repeat Step 2.
  This fix-up happens at most once per run; if the next verification
  is PASS again with implementation findings, go to Step 4 and list
  them in the PR description as follow-ups.
- FAIL, cause = implementation → use a new `implementer` subagent with
  the design document + the scope + the Verification Report. Then
  repeat Step 2.
  Maximum 2 verification rounds (the PASS fix-up round counts toward
  this limit).
- FAIL, cause = design → STOP. Summarize the design problem for the
  user; do not attempt to fix the design yourself.

## Step 4 — Hand off to the human
Produce a pull-request description containing: a summary of the change,
a link to the design document, the final Verification Report, and any
deviations from the plan. Do not merge. Do not push without being asked.

Throughout: keep a short log of every round (who ran, what verdict,
what was sent back). Include that log in the final output.
