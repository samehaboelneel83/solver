"""The python adapter kind's reference (queue R41): `solve` takes the compiled model and the same
keywords every built-in takes, and returns a `Solution`."""

from app.solve import cpsat


def solve(compiled, *, time_limit, workers, should_stop=None, seed=None, gap_rel=0.0, on_progress=None, **_):
    return cpsat.solve(compiled, time_limit=time_limit, workers=workers, should_stop=should_stop, seed=seed,
                       gap_rel=gap_rel, on_progress=on_progress)
