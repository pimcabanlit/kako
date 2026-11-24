"""Dreaming's checks in code, and the classification (docs/architecture.md, "How dreaming works",
step 3). Pure: no database, Meko, model or clock.

Each claim the extraction step found is checked before anything is proposed:

- its turn is one of the session's, and its quote is in that turn, word for word;
- the entity and the attribute exist, and the value is the attribute's type;
- every number a proposal would write is in the quote (V-09, `facts.evidence`): dreaming copies
  what the household said, it never works a number out.

Then each fact is compared with what Kako holds on the day it takes effect:

- **same**: Kako holds that value already (dropped);
- **new**: Kako holds nothing for it (`new_fact`);
- **replace**: a later value for the same thing (`replace_fact` of the fact in force then);
- **retract**: the household says the value Kako holds was wrong (`retract_fact`, then the right
  value from the same day as a `new_fact` when they gave one);
- **conflict**: two values for the same day, or a value older than one Kako has: nothing is
  proposed, and the finding says why, to be asked.

A claim that fails a check is **refused**, with the reason. Two claims in one session about the same
thing: the same value said again is **same**; two values for the same day are a **conflict**; a
second change while the first waits for a yes is **deferred** (a replacement names an open fact).
A life event Kako has already is **same**, and the facts of a new one name it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from html import unescape
from typing import Any, Final, Literal

from kako.agents.present import day, fact_value, money
from kako.dreaming.claims import Claim, ClaimedFact, SaidTurn
from kako.facts.attributes import CATALOG, attribute
from kako.facts.evidence import unquoted
from kako.facts.model import EntityRow, FactRow, FactValue
from kako.facts.proposals import (
    LIFE_EVENT_KINDS,
    PayloadError,
    fact_payload,
    fact_target,
    life_event_payload,
    retract_payload,
)
from kako.facts.snapshot import known, take_snapshot
from kako.facts.values import FactValueError, parse_stated

Outcome = Literal["new", "replace", "retract", "same", "conflict", "refused", "deferred"]
PROPOSING: Final = frozenset({"new", "replace", "retract"})
# Chosen by accepting a plan's option, never stated as a change.
NOT_STATED: Final = frozenset({"plan.allocation"})
SPACE: Final = re.compile(r"\s+")
MAX_REASON: Final = 1_000


def words(text: str) -> str:
    """Text with its whitespace collapsed: a quote is found in its turn this way."""
    return SPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class Known:
    """What Kako holds, as dreaming compares a claim with it."""

    household_id: uuid.UUID
    facts: tuple[FactRow, ...]  # every fact of the household's, as loaded
    entities: Mapping[str, EntityRow]  # by ref (`debt:credit-card`)
    # Life events Kako has, and those waiting for a yes (id, kind, occurs_on): a fact names its own.
    life_events: tuple[tuple[uuid.UUID, str, date], ...] = ()
    known_at: datetime | None = None  # as Kako knew it then (None: now)


@dataclass(frozen=True)
class Proposal:
    """One proposal dreaming would make: its kind, payload, the idempotency key's target, and the
    proposal in plain words."""

    kind: str
    payload: dict[str, Any]
    target: str
    shown: str


@dataclass(frozen=True)
class FactEvidence:
    """Evidence beyond the quote: the fact a correction replaces from its own start date."""

    fact_id: uuid.UUID
    quote: str


@dataclass(frozen=True)
class Finding:
    """One thing a claim said, what dreaming makes of it, and the proposals it would make."""

    claim: int  # the claim's position (from 1) in what the model handed back
    turn: SaidTurn | None  # None: the claim named no turn of the session
    quote: str
    outcome: Outcome
    shown: str  # what it is, in plain words
    reason: str = ""  # why, for same, conflict, refused and deferred
    proposals: tuple[Proposal, ...] = ()
    evidence: tuple[FactEvidence, ...] = ()
    # Ties a fact to its life event: approved together, the event first.
    life_event_id: uuid.UUID | None = None
    subject: tuple[uuid.UUID | None, str] | None = field(default=None, compare=False)
    # For `same`: what Kako holds that it says the same as (fact or life_event, its id).
    held: tuple[str, uuid.UUID] | None = None


class _Refused(Exception):
    pass


def _shown(attribute_key: str, value: FactValue) -> str:
    attr = attribute(attribute_key)
    if attr.value_type == "money" and isinstance(value, int):
        return money(value)
    if isinstance(value, Decimal):
        return f"{(value * 100).normalize():f}%"
    if isinstance(value, date):
        return day(value)
    return str(value)


def _date(raw: str, name: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _Refused(f'{name} {raw!r} isn\'t a date written as "2026-12-01"') from None


def _entity(known_: Known, claimed: ClaimedFact) -> tuple[uuid.UUID | None, str]:
    """The entity a fact is about and its name; refused if it isn't the attribute's kind."""
    if claimed.attribute not in CATALOG or claimed.attribute in NOT_STATED:
        raise _Refused(f"{claimed.attribute!r} isn't an attribute dreaming can propose")
    attr = attribute(claimed.attribute)
    if attr.household_wide:
        if claimed.entity:
            raise _Refused(f"{claimed.attribute} is household-wide, not about {claimed.entity}")
        return None, "The household"
    entity = known_.entities.get(claimed.entity)
    if entity is None:
        raise _Refused(f"no entity {claimed.entity!r}")
    if entity.kind not in attr.entity_kinds:
        raise _Refused(f"{claimed.entity} is a {entity.kind}; {claimed.attribute} isn't about one")
    return entity.id, entity.name


def _alive(known_: Known, entity_id: uuid.UUID | None, key: str) -> list[FactRow]:
    return [
        f
        for f in known_.facts
        if f.household_id == known_.household_id
        and (f.entity_id, f.attribute) == (entity_id, key)
        and known(f, known_.known_at)
    ]


def _quoted(proposal: Proposal, quotes: Sequence[str], today: date) -> None:
    missing = unquoted(proposal.kind, proposal.payload, quotes, today=today)
    if missing:
        raise _Refused("not in the quote: " + "; ".join(missing))


def _fact(
    known_: Known,
    turn: SaidTurn,
    claim: Claim,
    claimed: ClaimedFact,
    event_id: uuid.UUID | None,
) -> Finding:
    entity_id, name = _entity(known_, claimed)
    key = claimed.attribute
    on = _date(claimed.valid_from, "valid_from") if claimed.valid_from else turn.said_on
    at = take_snapshot(known_.household_id, known_.facts, on, known_.known_at).get(entity_id, key)
    what = f"{name}: {key}"
    base = Finding(0, turn, claim.quote, "refused", what, subject=(entity_id, key))
    retract_only = claim.correction and not claimed.value
    if not claimed.value and not claim.correction:
        raise _Refused("no value: a fact states one (an empty value only retracts)")
    if retract_only:
        if at is None:
            return _with(base, "conflict", f"{what}: Kako holds nothing on {day(on)} to retract")
        proposal = Proposal(
            "retract_fact",
            retract_payload(at.id, _reason(claim.quote)),
            f"fact/{at.id}",
            f"Retract {what} = {fact_value(at)} (since {day(at.valid_from)})",
        )
        _quoted(proposal, [claim.quote], turn.said_on)
        return _with(base, "retract", proposal.shown, proposals=(proposal,))
    try:
        value = parse_stated(key, claimed.value)
    except (ValueError, FactValueError) as exc:
        raise _Refused(f"{key}: {exc}") from None
    stated = f"{what} = {_shown(key, value)}"
    if at is not None and at.value == value:
        same = _with(base, "same", stated, f"Kako holds it already (since {day(at.valid_from)})")
        return replace(same, held=("fact", at.id))
    if claim.correction and at is not None:
        if at.replaced_by is not None and any(
            f.id == at.replaced_by and known(f, known_.known_at) for f in known_.facts
        ):
            return _with(base, "conflict", stated, f"a later value replaced {fact_value(at)}")
        retraction = Proposal(
            "retract_fact",
            retract_payload(at.id, _reason(claim.quote)),
            f"fact/{at.id}",
            f"Retract {what} = {fact_value(at)} (since {day(at.valid_from)}): said to be wrong",
        )
        corrected = Proposal(
            "new_fact",
            fact_payload(
                entity_id=entity_id,
                attribute_key=key,
                value=value,
                valid_from=at.valid_from,
                life_event_id=event_id,
            ),
            fact_target(entity_id, key, at.valid_from),
            f"{stated} from {day(at.valid_from)}, in its place",
        )
        evidence = FactEvidence(at.id, f"Kako recorded {what} from {at.valid_from.isoformat()}")
        _quoted(retraction, [claim.quote], turn.said_on)
        _quoted(corrected, [claim.quote, evidence.quote], turn.said_on)
        return _with(
            base,
            "retract",
            f"{stated} from {day(at.valid_from)}, not {fact_value(at)}",
            proposals=(retraction, corrected),
            evidence=(evidence,),
        )
    if at is not None and at.valid_from == on:
        return _with(
            base, "conflict", stated, f"Kako holds {fact_value(at)} for the same day, {day(on)}"
        )
    later = sorted(f.valid_from for f in _alive(known_, entity_id, key) if f.valid_from > on)
    if later:
        return _with(base, "conflict", stated, f"Kako has a later value, from {day(later[0])}")
    proposal = Proposal(
        "replace_fact" if at is not None else "new_fact",
        fact_payload(
            entity_id=entity_id,
            attribute_key=key,
            value=value,
            valid_from=on,
            replaces=at.id if at is not None else None,
            life_event_id=event_id,
        ),
        fact_target(entity_id, key, on),
        f"{stated} from {day(on)}"
        + (f", replacing {fact_value(at)} (since {day(at.valid_from)})" if at else ""),
    )
    _quoted(proposal, [claim.quote], turn.said_on)
    return _with(
        base, "replace" if at is not None else "new", proposal.shown, proposals=(proposal,)
    )


def _reason(quote: str) -> str:
    reason = f"Said in the session: “{words(quote)}”"
    return reason if len(reason) <= MAX_REASON else reason[: MAX_REASON - 2] + "”"


def _with(
    base: Finding,
    outcome: Outcome,
    shown: str,
    reason: str = "",
    *,
    proposals: tuple[Proposal, ...] = (),
    evidence: tuple[FactEvidence, ...] = (),
) -> Finding:
    return replace(
        base, outcome=outcome, shown=shown, reason=reason, proposals=proposals, evidence=evidence
    )


def _event(
    known_: Known,
    turn: SaidTurn,
    claim: Claim,
    held: list[tuple[str, date, uuid.UUID]],
    new_id: Callable[[], uuid.UUID],
) -> tuple[Finding, uuid.UUID | None]:
    """The claim's life event: same (Kako has it, or the session already said it) or new."""
    event = claim.life_event
    if event is None:
        raise _Refused("no life event")
    if event.kind not in LIFE_EVENT_KINDS:
        raise _Refused(f"{event.kind!r} isn't a kind of life event")
    if not event.description:
        raise _Refused("a life event is described in the household's words")
    occurs_on = _date(event.occurs_on, "occurs_on")
    what = f"Life event ({event.kind}) on {day(occurs_on)}"
    base = Finding(0, turn, claim.quote, "same", what)
    for event_id, kind, on in (*known_.life_events, *((i, k, o) for k, o, i in held)):
        if (kind, on) == (event.kind, occurs_on):
            same = _with(base, "same", what, "Kako has it already")
            return replace(same, held=("life_event", event_id)), event_id
    event_id = new_id()
    proposal = Proposal(
        "life_event",
        life_event_payload(
            event_id=event_id,
            kind=event.kind,
            description=event.description,
            occurs_on=occurs_on,
            source_ref=turn.seed,
        ),
        f"{event.kind}/{occurs_on.isoformat()}",
        f"{what}: {event.description}",
    )
    _quoted(proposal, [claim.quote], turn.said_on)
    held.append((event.kind, occurs_on, event_id))
    return _with(base, "new", proposal.shown, proposals=(proposal,)), event_id


def classify(
    claims: Sequence[Claim],
    turns: Sequence[SaidTurn],
    known_: Known,
    *,
    new_id: Callable[[], uuid.UUID],
) -> list[Finding]:
    """Every claim checked and compared with what Kako holds, in the order the model gave them.
    `new_id` names a new life event (the caller's: this module draws no randomness)."""
    by_seed = {t.seed: t for t in turns}
    findings: list[Finding] = []
    events: list[tuple[str, date, uuid.UUID]] = []
    for n, claim in enumerate(claims, start=1):
        turn = by_seed.get(claim.turn)
        if turn is None:
            findings.append(
                Finding(n, None, claim.quote, "refused", claim.quote, f"no turn {claim.turn!r}")
            )
            continue
        claim = replace(claim, quote=unescape(claim.quote))  # as the brief showed the words
        if words(claim.quote) not in words(turn.text):
            findings.append(
                Finding(
                    n,
                    turn,
                    claim.quote,
                    "refused",
                    claim.quote,
                    "the quote isn't the household's words in that turn",
                )
            )
            continue
        event_id: uuid.UUID | None = None
        if claim.life_event is not None:
            try:
                finding, event_id = _event(known_, turn, claim, events, new_id)
            except (_Refused, PayloadError) as exc:
                finding = Finding(n, turn, claim.quote, "refused", "Life event", str(exc))
            findings.append(replace(finding, claim=n))
        for claimed in claim.facts:
            try:
                finding = _fact(known_, turn, claim, claimed, event_id)
            except (_Refused, PayloadError, FactValueError) as exc:
                finding = Finding(
                    n,
                    turn,
                    claim.quote,
                    "refused",
                    f"{claimed.entity or 'household'}: {claimed.attribute}",
                    str(exc),
                )
            if finding.proposals and event_id is not None:
                finding = replace(finding, life_event_id=event_id)
            findings.append(replace(finding, claim=n))
    return _within_session(findings)


def _within_session(findings: list[Finding]) -> list[Finding]:
    """Two proposals about the same thing in one session: the same value again is same; two
    values for one day are a conflict; a later change waits for the first (deferred)."""
    out = list(findings)
    first: dict[tuple[uuid.UUID | None, str], int] = {}
    for i, f in enumerate(out):
        if f.outcome not in PROPOSING or f.subject is None:
            continue
        j = first.get(f.subject)
        if j is None:
            first[f.subject] = i
            continue
        earlier = out[j]
        mine = {p.target: p.payload for p in f.proposals if p.kind != "retract_fact"}
        theirs = {p.target: p.payload for p in earlier.proposals if p.kind != "retract_fact"}
        same_target = mine.keys() & theirs.keys()
        if same_target and all(mine[t]["value"] == theirs[t]["value"] for t in same_target):
            out[i] = _with(f, "same", f.shown, f"said again (claim {earlier.claim})")
        elif same_target:
            out[i] = _with(f, "conflict", f.shown, f"claim {earlier.claim} says otherwise")
            if earlier.outcome in PROPOSING:
                why = f"claim {f.claim} says otherwise"
                out[j] = _with(earlier, "conflict", earlier.shown, why)
        else:
            out[i] = _with(
                f, "deferred", f.shown, f"waits for claim {earlier.claim} to be approved first"
            )
    return out
