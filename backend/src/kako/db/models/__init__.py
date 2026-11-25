"""Every table in docs/data-model.md, as SQLAlchemy models, by layer.

Importing this package registers every table on `kako.db.base.Base.metadata`, which Alembic and the
schema test compare with the migrated database.
"""

from kako.db.models.decisions import Decision, DecisionAssumption, DecisionOption
from kako.db.models.dreaming import DreamRun, Proposal, ProposalEvidence
from kako.db.models.engine import CalcInput, CalcRun, Figure
from kako.db.models.facts import Fact, LifeEvent
from kako.db.models.household import Entity, Household, Person
from kako.db.models.meko import ContextGap, MekoLink
from kako.db.models.planning import (
    AgentStep,
    Plan,
    Recommendation,
    RecommendationSource,
    Reconciliation,
    Scenario,
    ScenarioOverride,
)
from kako.db.models.sessions import Session, SessionParticipant, SessionTurn
from kako.db.models.system import LlmCall, MekoCall, NumberCheck

__all__ = [
    "AgentStep",
    "CalcInput",
    "CalcRun",
    "ContextGap",
    "Decision",
    "DecisionAssumption",
    "DecisionOption",
    "DreamRun",
    "Entity",
    "Fact",
    "Figure",
    "Household",
    "LifeEvent",
    "LlmCall",
    "MekoCall",
    "MekoLink",
    "NumberCheck",
    "Person",
    "Plan",
    "Proposal",
    "ProposalEvidence",
    "Recommendation",
    "RecommendationSource",
    "Reconciliation",
    "Scenario",
    "ScenarioOverride",
    "Session",
    "SessionParticipant",
    "SessionTurn",
]
