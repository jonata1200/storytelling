# Phase 04 - Review Workflow

Goal: let the user approve or reject each generated segment before continuing.

## Checklist

- [x] Design the segment review state machine.
- [x] Add service functions to:
  - [x] Approve a segment
  - [x] Reject a segment
  - [x] Retry a failed segment
  - [x] Regenerate a rejected segment
  - [x] Continue to the next segment
- [x] Ensure approval records the segment as the continuity source for the next segment.
- [x] Ensure rejection prevents the segment from feeding downstream generation.
- [x] Add metadata for user review decisions:
  - [x] Decision
  - [x] Timestamp
  - [x] Optional note
  - [x] Previous status
- [x] Add guardrails:
  - [x] Do not generate segment `N + 1` without segment `N` approved.
  - [x] Do not finalize while any required segment is missing or unapproved.
  - [x] Do not silently skip failed segments.
- [x] Add a compact continuity summary after each approved segment.
- [x] Add tests for approval and rejection behavior.
- [x] Add tests for blocked continuation.
- [x] Add tests for retry after failure.

## Implementation Notes

- Segment review now uses `pending`, `generating`, `ready_for_review`, `approved`, `rejected`, and `failed` as the user-facing state machine.
- Approval writes review metadata, creates a compact continuity summary, and links the next segment to the approved segment/video/final frame.
- Rejection preserves the rejected result for review but invalidates downstream unapproved continuity.
- Retry and regeneration use dedicated service entry points so failed and rejected states are recoverable.

## Exit Criteria

- [x] The user can review one generated segment at a time.
- [x] The app clearly blocks unsafe continuation.
- [x] Approved segments become the only continuity source.
