"""How much one build, file or candidate set may hold, in one place (plan of 8 October 2026, phase 1B).

Each limit protects a stage of the data path (records and links into the database, the run's snapshot, the
compile); the scale benchmark of 7 October 2026 measured them, after the record and link checks were made
set-based (migration 0117): 1.95 million links built in about three minutes, frozen in 24 s and compiled in 21 s.
An operator may set any of them lower (or higher, on a larger machine) in the environment.
"""
from __future__ import annotations

import os


def _limit(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


#: Records one plan may create (a layout's or a generator's candidates and cells).
SPEC_RECORDS = _limit("SOLVER_MAX_SPEC_RECORDS", 1_500_000)
#: Parameter cells one plan may set.
SPEC_CELLS = _limit("SOLVER_MAX_SPEC_CELLS", 2_000_000)
#: Rows of a table the Assistant generated and loads from its working folder.
GENERATED_ROWS = _limit("SOLVER_MAX_GENERATED_ROWS", 2_000_000)
#: Candidate records and links the candidate API makes in one call.
CANDIDATE_RECORDS = _limit("SOLVER_MAX_CANDIDATE_RECORDS", 1_500_000)
CANDIDATE_LINKS = _limit("SOLVER_MAX_CANDIDATE_LINKS", 2_000_000)
#: A layout's candidate positions and their occupancy links. These bound what a solver can take as a list of
#: candidates (the camp layout at 0.5 m: 54,468 positions, 2.7 million links, solved in two minutes); a finer grid
#: needs a form without a list (plan phase 1C).
LAYOUT_CANDIDATES = _limit("SOLVER_MAX_LAYOUT_CANDIDATES", 150_000)
LAYOUT_LINKS = _limit("SOLVER_MAX_LAYOUT_LINKS", 4_000_000)
