# Phase 03 - Continuous Generation Service

Goal: generate video segments without requiring storyboard frames.

## Checklist

- [x] Create or refactor a service entry point for generating one continuous segment.
- [x] Create or refactor a service entry point for generating the next eligible segment.
- [x] Build the first-segment prompt from:
  - [x] Script context
  - [x] Scene and shot plan
  - [x] Visual Bible references
  - [x] Production settings
  - [x] User prompt overrides
- [x] Build subsequent segment prompts from:
  - [x] Previous approved segment metadata
  - [x] Previous final frame asset
  - [x] Current scene and shot plan
  - [x] Visual Bible references
  - [x] Continuity ledger
- [x] Add final-frame extraction after a video is generated.
- [x] Store extracted final frames as assets.
- [x] Attach final-frame assets to the segment that produced them.
- [x] Ensure the next segment uses only approved previous output.
- [x] Support regeneration of the current segment.
- [x] Support regeneration from segment `N` with downstream invalidation.
- [x] Persist provider requests, prompt executions, cost entries, and errors.
- [x] Preserve partial progress if a later segment fails.
- [x] Ensure provider failures are surfaced as user-friendly errors.
- [x] Add tests for:
  - [x] First-segment generation
  - [x] Next-segment generation from prior final frame
  - [x] Regeneration
  - [x] Downstream invalidation
  - [x] Provider error handling
  - [x] Cost tracking

## Implementation Notes

- Added `generate_continuous_video_segment` for explicit one-segment generation.
- Added `generate_next_continuous_video_segment` so the workflow advances only to the next eligible segment.
- Segment `N + 1` is blocked until segment `N` is approved.
- Successful generation stores the generated video asset, extracts the final frame with FFmpeg when available, stores that frame as an image asset, and moves the segment to `ready_for_review`.
- The next segment prefers image-to-video from the approved final frame when the provider supports it, then falls back to provider video extension, then prompt-only continuity.
- Regeneration can reset the current segment and invalidate downstream generated-but-unapproved segments while preserving approved progress.

## Exit Criteria

- [x] One segment can be generated without any storyboard frame.
- [x] Segment chaining works from approved final frames.
- [x] Failures leave recoverable state.
