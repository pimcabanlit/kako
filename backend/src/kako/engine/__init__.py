"""The engine: every figure in docs/data-model.md, "Calculations", from a snapshot.

Pure: integer centavos and `Decimal` rates, no database, Meko, model, clock or randomness (a test
enforces it). The engine calculates; the agents only read its figures. `compute` is the entry point.
"""

from kako.engine.engine import ENGINE_VERSION, EngineInputError, compute
from kako.engine.figures import Figure, FigureRef, Run
from kako.engine.inputs import Override

__all__ = [
    "ENGINE_VERSION",
    "EngineInputError",
    "Figure",
    "FigureRef",
    "Override",
    "Run",
    "compute",
]
