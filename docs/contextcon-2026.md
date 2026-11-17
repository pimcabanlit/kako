# ContextCon 2026: requirements and submission checklist

Source: the ContextCon overview, Challenge 05 brief and FAQ at
https://www.hackerearth.com/lp/challenges/contextcon (checked Nov 17, 2026).
The official page is the authority; this is a working summary. Full terms and
conditions are not published yet.

## Key dates

| Milestone | Pacific Time | Manila |
| --- | --- | --- |
| Registration opens, build begins | Nov 7, 2026 | Nov 7, 2026 |
| **Submissions due** | **Sun Jan 17, 2027, 11:59 PM** | **Mon Jan 18, 2027, 3:59 PM** |
| Judging by Yugabyte experts | Jan 18–24, 2027 | |
| Final Demo Day (finalists, live online) | To be announced | |
| Winners announced | February 2027 | |

Our working dates (Manila): feature freeze Jan 10, submit Jan 16. Codegeist
(Qorren) comes first until Dec 21.

## Eligibility and basics

- Developers anywhere, aged 18 or older. Solo or teams of up to 4. Kako is solo.
- Free to enter. Fully online.
- Every project must use Meko as its context layer, with any model and any MCP
  client.
- Entrants keep ownership of what they build.

## Challenge 05: The Planner That Remembers

"Good advice depends on knowing your whole story, and remembering it."

**Objectives**

| Objective | What the brief asks |
| --- | --- |
| Remember the person | Goals, preferences, constraints and life events as long-term memory |
| Plan across areas | Specialist agents (budget, debt, savings, goals) share one financial context |
| Adapt over time | Show the plan updating when a life event happens (a new job, a baby, a move) |
| Explain the advice | Every recommendation is traceable to the memories and data behind it |

**Meko at the core**

| Meko feature | How the brief uses it |
| --- | --- |
| Memory | Goals, risk profile and past decisions, kept across sessions |
| Knowledge base | Statements, budgets and planning rules (synthetic) |
| Artifacts | Generated plans and reports stored in the datapack |
| Conversations | Planning sessions over time |
| Traces | Why each recommendation was made |

**Expected outcomes**

- A synthetic household or small-business financial profile.
- A planning agent system connected to Meko.
- 3 or more sessions showing memory carrying over and the plan adapting to a life event.
- Trace-backed explanations for the key recommendations.
- Encouraged: a what-if scenario planner.

## Judging

| Criterion | Weight | What it rewards |
| --- | --- | --- |
| Use of Meko | 30% | All parts of the context (conversations, memory, learning, knowledge, artifacts, decision tracing); blending data infrastructure, Postgres inside the context; sharing context and collaborating to improve it |
| Impact and usefulness | 25% | A real problem, solved for real users |
| Technical execution | 20% | Working demo, code quality and architecture |
| Innovation | 15% | A fresh take on multi-agent memory and shared context |
| Presentation | 10% | Clear demo video and documentation |

Nothing says judges will run the app, so the video, the README and a measured
metrics page are what they experience.

## Prizes

Open to every theme; solo builders and teams compete for the same prizes.

| Prize | Amount | For |
| --- | --- | --- |
| Grand prize | $4,000 | Best overall build: collective memory in action, agents that learn, share and improve over time |
| Runner-up | $2,500 | |
| Second runner-up | $1,500 | |
| Best use of shared memory | $1,000 | Agents that build on each other's learning, with a clear decision-trace story |
| People's choice | $1,000 | Community vote |

## Submission checklist

- [ ] Demo video under 5 minutes, linked
- [ ] Public (or open-source) GitHub repository with setup instructions
- [ ] Documentation (optional): architecture, how Kako uses Meko, and measured token or relevance metrics
- [ ] Repository licence checked against the full terms once published
- [ ] Demo datapack and its artifacts still available through judging (Free-tier artifacts expire after 30 days unused)

## Meko Free tier

Our account is on Free. Limits that shape the build (from Meko's pricing page
and account screen, November 2026):

- Limits are account totals across all datapacks (up to 10).
- **1,000 conversations.** Every session, test run and evaluation uses one, so
  development and tests run against local Meko and Meko Cloud holds the demo only.
- No shared datapacks or roles (Pro only), so per-person privacy is a stretch goal.
- Artifacts expire after 30 days unused.
- AMP (Postgres in the datapack) only accepts connections from listed IP
  addresses, so the demo backend needs a fixed outgoing IP. Its compute limit on
  Free is not yet known.

## Open questions

- **Pro access for entrants.** The Meko team reportedly said entrants can have
  Pro; the official page does not mention it. Confirm on the Meko Discord.
- **Full terms and conditions.** Not published yet. Check them for licence or
  open-source requirements before submitting (Kako is "all rights reserved"
  for now).
- **AMP limits on Free**, and whether a fixed-IP host works (Phase 1 test).
- **Final Demo Day date**, likely on US hours.
