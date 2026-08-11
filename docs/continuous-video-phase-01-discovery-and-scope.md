# Phase 01 - Discovery and Scope

Goal: define the exact replacement for the storyboard stage before changing runtime behavior.

## Checklist

- [x] Map every current dependency on `StoryboardFrame`, `Animatic`, and storyboard assets.
- [x] Identify all UI entry points that expose storyboard generation, prompt approval, frame regeneration, animatic generation, and video generation from frames.
- [x] Document the current production flow:
  - [x] Briefing
  - [x] Ideas
  - [x] Script
  - [x] Scenes and shots
  - [x] Visual Bible
  - [x] Storyboard
  - [x] Video
  - [x] Finalization
- [x] Define the target production flow:
  - [x] Briefing
  - [x] Ideas
  - [x] Script
  - [x] Scenes and shots
  - [x] Visual Bible
  - [x] Continuous video segments
  - [x] Segment review
  - [x] Finalization
- [x] Decide the segment granularity for the first release:
  - [x] One segment per shot
  - [ ] One segment per scene
  - [ ] One segment per group of shots
- [x] Define how the first segment starts:
  - [x] Text prompt only
  - [x] Visual Bible references
  - [x] Optional user-uploaded start frame
- [x] Define how subsequent segments start:
  - [x] Last approved frame from the previous segment
  - [x] Visual Bible references
  - [x] Continuity notes from the approved segment
- [x] Decide whether storyboard data remains readable as legacy data.
- [x] Decide whether existing projects with storyboard data keep their old workspace view or migrate to continuous mode.
- [x] Write acceptance criteria for the new continuous-video workflow.
- [x] Confirm cost expectations with a small estimate comparing storyboard-first and continuous-video-first production.

## Implementation Notes

- The first release keeps one generated segment per shot because the existing continuous-video planner already maps script/scenes/shots into ordered segments.
- Storyboard and animatic data remain readable as legacy project data; the continuous-video path no longer depends on generated storyboard frames.
- New projects can move through Visual Bible directly into continuous video segments, then review each segment before the next segment is eligible.
- Cost reduction comes from removing storyboard image generation and animatic preparation as mandatory runtime steps.

## Exit Criteria

- [x] The desired workflow is documented and agreed.
- [x] The minimum viable continuous-video behavior is clear.
- [x] Current storyboard dependencies are known.
- [x] Phase 01 itself introduced no runtime behavior changes.
