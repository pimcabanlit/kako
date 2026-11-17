## Summary

<!-- What changed and why, with a link to the issue or conversation that asked for it.
     Name the build-plan task when there is one (for example: Phase 1, task 3). -->

## Testing

<!-- Pasted evidence, not "it works": the commands and their output.
     A change to a prompt, an agent's tools, dreaming or the Meko adapter also needs a run on
     local Meko (and the agent test set, once it exists), with the score (REVIEW.md). -->

- [ ] `uv run pytest` (from `backend/`), with `ruff` and `mypy`
- [ ] `npm run lint && npm run build` (from `web/`)
- [ ] Browser check as a guest and as an admin, with a screenshot, when the UI changes
      (until Kako has sign-in, one check of the household's view)

## Risk

<!-- The tier from REVIEW.md (Low, Medium or High) and the file that sets it.
     The highest tier touched wins; when unsure, go one tier up. -->

**Tier:**

- [ ] High tier only: `/security-review` run, and every finding answered below

## How to revert

<!-- Usually "revert this PR", plus anything extra: a migration downgrade, a data fix, or a key
     to rotate. -->

## Review findings

- [ ] Every review finding (the AI reviewer, `/security-review`, Pim) is fixed, or answered with a reason
