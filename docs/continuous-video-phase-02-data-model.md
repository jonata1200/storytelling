# Phase 02 - Data Model and State

Goal: make continuous video segments first-class production entities.

## Checklist

- [x] Review existing continuous video models and services.
- [x] Decide whether to extend current continuous-video tables or introduce new tables.
- [x] Ensure each segment stores:
  - [x] Project id
  - [x] Script id
  - [x] Scene range or shot range
  - [x] Segment number
  - [x] Prompt
  - [x] Status
  - [x] Source frame asset id
  - [x] Generated video asset id
  - [x] Extracted final frame asset id
  - [x] Provider
  - [x] Model
  - [x] Duration
  - [x] Cost metadata
  - [x] Error metadata
  - [x] Continuity metadata
- [x] Define allowed segment statuses:
  - [x] `pending`
  - [x] `generating`
  - [x] `ready_for_review`
  - [x] `approved`
  - [x] `rejected`
  - [x] `failed`
- [x] Add database migrations for any missing fields or tables.
- [x] Add indexes for project, script, segment number, status, and selected/approved segment lookup.
- [x] Define invariants:
  - [x] Only one approved result per segment sequence position.
  - [x] Segment `N + 1` cannot generate until segment `N` is approved.
  - [x] Rejected segments do not feed continuity.
  - [x] Regenerating segment `N` invalidates downstream generated-but-unapproved segments.
- [x] Update schemas for API/UI reads.
- [x] Add tests for state transitions and invariants.
- [x] Add test fixtures for projects with no storyboard data.
- [x] Add test fixtures for legacy projects with storyboard data.

## Implementation Notes

- The existing `continuous_video_segments` table was extended instead of introducing a parallel chain table.
- `status` remains the technical generation status, while `review_status` tracks the user-facing review gate.
- Added persistent links for script, source frame, generated video, and extracted final frame assets.
- The migration backfills review state from previous generation status and mirrors the existing generated video asset into `generated_video_asset_id`.

## Exit Criteria

- [x] Continuous segments can represent the full video chain.
- [x] State transitions are validated by tests.
- [x] Legacy storyboard data is not broken.
