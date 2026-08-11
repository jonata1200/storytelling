# Phase 05 - UI Migration

Goal: remove storyboard from the main user journey and make continuous video the primary production experience.

## Checklist

- [ ] Replace the Storyboard workspace tab with a Continuous Video tab.
- [ ] Remove storyboard-specific primary actions from the main flow.
- [ ] Add a segment timeline view showing:
  - [ ] Segment number
  - [ ] Scene or shot range
  - [ ] Status
  - [ ] Duration
  - [ ] Cost estimate
  - [ ] Source frame
  - [ ] Generated video preview
  - [ ] Final frame preview
- [ ] Add actions for each segment:
  - [ ] Generate
  - [ ] Approve
  - [ ] Reject
  - [ ] Regenerate
  - [ ] Continue to next segment
- [ ] Add clear disabled states explaining why an action is blocked.
- [ ] Add progress UI for long-running segment generation.
- [ ] Make progress resilient to page reloads or navigation.
- [ ] Show recoverable errors on the segment card.
- [ ] Add a global action to continue from the latest approved segment.
- [ ] Keep Visual Bible visible as the consistency anchor.
- [ ] Hide or demote storyboard prompts and frames from the default UI.
- [ ] Add a legacy access path only if existing projects need it.
- [ ] Update assistant/chat routing so requests like "gerar storyboard" map to continuous video guidance or a legacy path.
- [ ] Update workspace readiness rules so Video no longer requires storyboard frames.
- [ ] Add UI tests for:
  - [ ] Empty continuous-video state
  - [ ] Segment ready for review
  - [ ] Approved segment
  - [ ] Rejected segment
  - [ ] Blocked next segment
  - [ ] Retry/regenerate actions

## Exit Criteria

- [ ] A user can complete the production path without seeing storyboard as a required step.
- [ ] Continuous video controls are clear and review-oriented.
- [ ] Existing storyboard UI does not confuse the main flow.
