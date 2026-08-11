# Phase 06 - Finalization and Cleanup

Goal: finalize videos from approved continuous segments and retire storyboard-only assumptions.

## Checklist

- [ ] Update finalization to assemble approved continuous segments in order.
- [ ] Ensure finalization validates:
  - [ ] All required segments exist
  - [ ] All required segments are approved
  - [ ] Video files exist in storage
  - [ ] Durations are valid
  - [ ] Sequence order is complete
- [ ] Update export manifests to reference continuous segments instead of storyboard frames.
- [ ] Update quality checks to inspect segment continuity instead of storyboard coverage.
- [ ] Update cost summaries to report:
  - [ ] Visual Bible image cost
  - [ ] Continuous video generation cost
  - [ ] Regeneration cost
  - [ ] Finalization cost
- [ ] Remove storyboard requirements from production-step gating.
- [ ] Remove storyboard-only copy from the main UI.
- [ ] Mark old storyboard service paths as legacy or remove them after migration confidence is high.
- [ ] Add data cleanup tools for orphan storyboard files.
- [ ] Add data cleanup tools for unused storyboard assets and artifacts.
- [ ] Add migration notes for old projects.
- [ ] Update README or product docs with the new workflow.
- [ ] Run full unit test suite.
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

## Exit Criteria

- [ ] Finalization works without storyboard frames.
- [ ] Main production flow no longer depends on storyboard.
- [ ] Legacy storyboard data has a clear retention or cleanup policy.
