# Phase 04 - Review Workflow

Goal: let the user approve or reject each generated segment before continuing.

## Checklist

- [ ] Design the segment review state machine.
- [ ] Add service functions to:
  - [ ] Approve a segment
  - [ ] Reject a segment
  - [ ] Retry a failed segment
  - [ ] Regenerate a rejected segment
  - [ ] Continue to the next segment
- [ ] Ensure approval records the segment as the continuity source for the next segment.
- [ ] Ensure rejection prevents the segment from feeding downstream generation.
- [ ] Add metadata for user review decisions:
  - [ ] Decision
  - [ ] Timestamp
  - [ ] Optional note
  - [ ] Previous status
- [ ] Add guardrails:
  - [ ] Do not generate segment `N + 1` without segment `N` approved.
  - [ ] Do not finalize while any required segment is missing or unapproved.
  - [ ] Do not silently skip failed segments.
- [ ] Add a compact continuity summary after each approved segment.
- [ ] Add tests for approval and rejection behavior.
- [ ] Add tests for blocked continuation.
- [ ] Add tests for retry after failure.

## Exit Criteria

- [ ] The user can review one generated segment at a time.
- [ ] The app clearly blocks unsafe continuation.
- [ ] Approved segments become the only continuity source.
