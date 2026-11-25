# Dreaming

After a session ends, Kako rereads it and proposes what the household said that Kako doesn't hold yet, and the patterns in their decisions. It only proposes: nothing is learned until a person says yes.

## When it runs

A session ends when someone ends it (the **End session** button, the API or `kako dream end`); there is no timer. Ending it refuses more turns and queues one dreaming run, once. `kako dream run` works through the queue, oldest first, and retries a run that failed. Demo mode runs it for you.

## What it does

1. **Read.** The session's turns from Meko, the household's facts and life events, and the memories Meko extracted from those turns on its own (Meko's learnings), which Kako treats as candidates.
2. **Extract.** One model call, one tool (`submit_claims`): each thing the household said, its exact quote, the day it takes effect. The model copies; it never calculates, and reads only the household's words.
3. **Check, in code.** The quote must be in the session word for word; every number in a claim must be in its quote. A claim that fails is refused, with why.
4. **Compare** with what Kako holds on that day: the same (dropped), new, a replacement, a correction, or a conflict (nothing proposed; Kako asks).
5. **Patterns.** Code counts the household's decisions by what the chosen option leans to. Three the same way, across at least two sessions, with none the other way, make a preference to propose.
6. **Promotion.** An approved preference, or a decision still in force two sessions later, is offered for sharing with every agent, once, asked twice because it can't be undone.
7. **Propose.** Everything goes to the approvals inbox with its evidence: the quote, the turn, who said it.
8. **Settle Meko's candidates.** Each ends linked to a fact a person approved, or deleted.

> **In the story · Oct 20.** Session 1 (keep a bigger buffer), Session 2 (the split) and Session 3 (keep the bonus for the trip) each chose the option that keeps cash on hand. Dreaming proposes the preference for flexibility; **Mara approves** it; **Jun confirms** sharing it, and Session 1's decision record. In Session 4, the debt specialist cites it though nobody mentions it.

> **In the story · Nov 20.** Mara's new job is proposed during Session 4 itself. When dreaming reads that session, it finds the same words and reports them as already proposed: never twice.

## How it's tested

A labelled set of scripted sessions with the proposals a person would expect, scored in code for what dreaming found, missed and wrongly proposed. It passes at 90% found, with no number that isn't in its quote.

## Not yet

Nothing runs the queue in the background, and a session nobody ends stays open. *Planned: a small worker, and a gentle "end this session?" after a quiet spell.*
