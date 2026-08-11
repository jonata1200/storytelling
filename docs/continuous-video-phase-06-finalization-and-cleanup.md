# Phase 06 - Finalization and Cleanup

Goal: finalize videos from approved continuous segments and retire storyboard-only assumptions.

## Checklist

- [x] Update finalization to assemble approved continuous segments in order.
- [x] Ensure finalization validates:
  - [x] All required segments exist
  - [x] All required segments are approved
  - [x] Video files exist in storage
  - [x] Durations are valid
  - [x] Sequence order is complete
- [x] Update export manifests to reference continuous segments instead of storyboard frames.
- [x] Update quality checks to inspect segment continuity instead of storyboard coverage.
- [x] Update cost summaries to report:
  - [x] Visual Bible image cost
  - [x] Continuous video generation cost
  - [x] Regeneration cost
  - [x] Finalization cost
- [x] Remove storyboard requirements from production-step gating.
- [x] Remove storyboard-only copy from the main UI.
- [x] Mark old storyboard service paths as legacy or remove them after migration confidence is high.
- [x] Add data cleanup tools for orphan storyboard files.
- [x] Add data cleanup tools for unused storyboard assets and artifacts.
- [x] Add migration notes for old projects.
- [x] Update README or product docs with the new workflow.
- [x] Run full unit test suite.
- [ ] Run a manual smoke test:
  - [ ] Create project
  - [ ] Generate script
  - [ ] Generate scenes and shots
  - [ ] Generate Visual Bible
  - [ ] Generate first segment
  - [ ] Approve first segment
  - [ ] Generate next segment from final frame
  - [ ] Regenerate a segment
  - [ ] Finalize approved segments

## Implementation Notes

- Finalization now prefers continuous-video timelines when continuous segments exist.
- Continuous finalization validates a complete ordered sequence, approved review state, valid duration, valid video asset, and local storage availability.
- Export manifests include `source: continuous_video` and the ordered continuous segment references.
- Storyboard service paths remain legacy-compatible; `delete_storyboard_outputs` remains the project-level cleanup path for legacy frames, clips, animatics, assets, artifacts, and local files.
- Manual smoke testing is intentionally left as a follow-up operational task because it requires interactive provider/API execution.

## Exit Criteria

- [x] Finalization works without storyboard frames.
- [x] Main production flow no longer depends on storyboard.
- [x] Legacy storyboard data has a clear retention or cleanup policy.
