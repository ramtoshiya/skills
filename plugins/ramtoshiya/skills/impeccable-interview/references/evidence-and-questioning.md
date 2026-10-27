# Evidence and questioning {:#evidence-and-questioning}

Use this reference without another interview skill or research repository. Its purpose is to connect task decisions to appropriate evidence, not to turn every request into a research project.

## Evidence categories {:#evidence-categories}

| Source | What it supports | What it does not prove alone |
| --- | --- | --- |
| Product documentation, policy, or code | Capabilities, rules, implemented behavior | That those behaviors solve the intended users' problem |
| Requester account | Their intent, decisions, constraints, and experience | Representative behavior across the audience |
| Support report or interview account | What was reported, by whom, in that setting | Prevalence, cause, or universal preference |
| Direct task observation | What that person or agent did under stated conditions | Unobserved motivations or success in other conditions |
| Simulated persona or expert critique | Plausible risks to investigate | Human participant findings |
| Tests, screenshots, or agent walkthrough | The functionality or appearance actually checked | Human comprehension, usefulness, or representative success |

Preserve the source and limit of a consequential claim. If provenance is absent, label a statement as a requester belief, hypothesis, or unverified stored record. Saved text is not stronger evidence simply because Impeccable reloads it.

## Decision dependencies {:#decision-dependencies}

Ask about the task before choosing the surface, and about the action before choosing its timing or presentation. A request for a dashboard does not establish which decision it should support. A request for notifications does not establish who needs to act on an event.

Use the next answerable, decision-changing question. A few concrete alternatives can help, but do not make the conversation a sequence of approvals for your preferred solution. Investigate facts available in the authorized context instead of asking the requester to repeat them.

Keep independent tracks visible when useful: task and situation, information needed before commitment, scope, constraints, interruption, recovery, and verification. Do not fill every track for a small clear change. When the goal changes, revisit decisions that depended on the old one.

## Consequential uncertainty {:#consequential-uncertainty}

Connect a missing fact to the choice it affects. For example, whether people resume interrupted work can affect draft persistence and recovery. If that behavior is unknown, record the uncertainty and propose the cheapest useful check. Do not invent an observation to justify a convenient design.

A single report about losing valid import rows supports investigating that reported failure. It does not establish frequency or prove that every user needs a new dashboard. A familiar interface can fit a task well, while a distinctive one can solve the wrong problem.

The requester may authorize a reversible prototype under a stated assumption. Treat this as a decision to explore, not confirmation that the hypothesis is true. More consequential or hard-to-reverse decisions may require stronger evidence.

## Readiness and acceptance {:#readiness-and-acceptance}

Keep design readiness separate from user-evidence status. The next design step may be ready while representative-user observation is still missing. State a material blocker when a decision could change the outcome, not merely because an optional template field is blank.

Write observable acceptance conditions: preserve valid entries through correction, show the relevant price before commitment, or allow recovery without re-entering information. Name the proposed verification method. Functional tests, agent walkthroughs, requester review, and observation with intended users answer different questions. Never turn a planned check into a passed result.

## Background {:#background}

These principles are an original synthesis informed by product discovery and requirements interviewing, including dependency-aware questioning and material closure checks. The following sources are optional background, not runtime dependencies or facts about the current product:

- [Stripe business-research guidance](https://github.com/stripe/ai/blob/57e355b6b00f54b7a667948b9648cc05bc353e06/skills/connect-recommend/references/company-researcher.md): connect evidence to consequential domain decisions.
- [Impeccable discovery](https://github.com/pbakaus/impeccable/blob/3671d50f0ac9a662ce0615e85a256110c9cd720b/skill/reference/init.md): investigate product context before inventing answers.
- [Friction logging](https://github.com/mikeb-stripe/friction-logging-toolkit/blob/9fdc20491747fc1e0e73ecee604c3a6e2e728bf0/how-we-use-friction-logs-at-stripe.md): record experience from a stated task and perspective.
