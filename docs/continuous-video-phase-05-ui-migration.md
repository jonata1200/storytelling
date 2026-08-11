# Phase 05 - UI Migration

Goal: remove storyboard from the main user journey and make continuous video the primary production experience.

## Checklist

- [x] Replace the Storyboard workspace tab with a Continuous Video tab.
- [x] Remove storyboard-specific primary actions from the main flow.
- [x] Add a segment timeline view showing:
  - [x] Segment number
  - [x] Scene or shot range
  - [x] Status
  - [x] Duration
  - [x] Cost estimate
  - [x] Source frame
  - [x] Generated video preview
  - [x] Final frame preview
- [x] Add actions for each segment:
  - [x] Generate
  - [x] Approve
  - [x] Reject
  - [x] Regenerate
  - [x] Continue to next segment
- [x] Add clear disabled states explaining why an action is blocked.
- [x] Add progress UI for long-running segment generation.
- [x] Make progress resilient to page reloads or navigation.
- [x] Show recoverable errors on the segment card.
- [x] Add a global action to continue from the latest approved segment.
- [x] Keep Visual Bible visible as the consistency anchor.
- [x] Hide or demote storyboard prompts and frames from the default UI.
- [x] Add a legacy access path only if existing projects need it.
- [x] Update assistant/chat routing so requests like "gerar storyboard" map to continuous video guidance or a legacy path.
- [x] Update workspace readiness rules so Video no longer requires storyboard frames.
- [x] Add UI tests for:
  - [x] Empty continuous-video state
  - [x] Segment ready for review
  - [x] Approved segment
  - [x] Rejected segment
  - [x] Blocked next segment
  - [x] Retry/regenerate actions

## Implementation Notes

- The default workspace tabs no longer show Storyboard; legacy storyboard routes remain available.
- The Video tab is now the continuous-video control surface in continuous mode.
- Segment cards show source frame, generated video, final frame, recoverable errors, and review actions.
- Assistant routing redirects storyboard requests to continuous-video behavior when the project workflow is `continuous_fast`.

## Exit Criteria

- [x] A user can complete the production path without seeing storyboard as a required step.
- [x] Continuous video controls are clear and review-oriented.
- [x] Existing storyboard UI does not confuse the main flow.
