"""Dreaming: after a session, find what the household said that Kako doesn't hold yet, and
propose it (docs/architecture.md, "How dreaming works").

- `claims.py` (pure): the household's turns as dreaming reads them, and the claims the extraction
  step hands back, parsed and bounded.
- `classify.py` (pure): each claim checked in code and compared with what Kako holds: same, new,
  replace, retract or conflict, with the proposals it would make.
- `extract.py`: the one model step (structured output only).
- `job.py`: the job: one `dream_run` per ended session, the turns read from Meko, the proposals
  stored pending with their evidence.
"""
