# Workflow workers in bb {:#workflow-workers}

The user explicitly asks you to start the worker threads that your
instructions call for. This standing request is the explicit request that the
bb introduction requires before you spawn a thread, so do not ask again before
each spawn.

- It covers the separate roles that a skill, mode, or workflow you were told to
  follow assigns to workers, such as arena candidates, cross-model judges,
  reviewers, Comment Sicko, and research workers. Start only those roles, with
  the counts and model families the workflow sets.
- Start each one with `bb nest spawn`, as the `nest` skill shows, so it reports
  to your thread at any depth. Do not use `bb thread spawn --parent-self`,
  which bb rejects below four thread levels. Do not move a role to a hidden
  subagent instead. Archive each worker with `bb thread archive <id>` after you
  have read its result.
- While `bb nest spawn` works, do not replace separate workers with your own
  sequential passes. Use a workflow's sequential fallback only when spawning
  fails, and report the failure.
- It covers spawning and talking to your own workers only. Messages to any other
  thread still follow the bb introduction.

## Messages between threads {:#thread-messages}

Decide whether each message to another thread is worth a turn. `bb thread
tell` and `bb mail send <thread> --wake` start the recipient's turn. Use them
for a final result, a failure, a question you need answered, or a request
that needs action now. For progress, a fact the recipient may use later, or
"main moved", use `bb mail send <thread>` without `--wake`. It waits in the
recipient's inbox and arrives with its next turn. To reach several threads,
use `bb mail send --where <selector>`. The `mail` skill has the selectors.

## BB references and customizations {:#bb-references-customizations}

Separate a thread or message reference from adjacent text with spaces, including
before Korean particles. For example: @thread:thr_abc123 에서 확인하세요.
Keep the reference syntax described in the bb introduction.

For BB customizations, use supported BB settings or plugins. For work on BB
itself, never propose, draft, or use a BB application fork, a personal core
patch, or an installed bundle patch unless the user explicitly requests that
route. Approval of the desired behavior alone does not authorize it. You may
investigate the core and SDK boundary read-only. If supported settings or
plugins cannot deliver the behavior, state the limit and surface the upstream
request or bug report route without creating a fork-backed draft.

## Impeccable decision rounds {:#impeccable-decisions}

In bb threads the shell sets `IMPECCABLE_QUESTION_DISABLED=1`. The person often
answers from another device, and Impeccable's decision page listens only on
this Mac's loopback address. With the variable set, `serve-question --start`
exits 2, which is Impeccable's documented route to the text channel. Take that
route in the thread:

- Write the round as one HTML file in thread storage. Give each option a card
  with its id, label, comp image or HTML sketch, thesis, palette, and risk, in
  the order the payload would use. Copy each image next to the file, link it by
  relative path, and show the file with the `inline-vis` directive.
- Under the page, ask in chat for an option id. Also offer re-roll (plain,
  safer, or bolder), the canon exit, a steer, and the build path when the
  payload would offer them. Do not open a browser page or a question dialog.
- Treat the reply as the ANSWER, including a partial or mixed one such as "v2's
  left column with v1's pool". Ask again only when the reply matches no option
  and no steer.

## Impeccable plan and asset review {:#impeccable-plan-review}

`component-review serve` reads the same variable and exits 2, and Impeccable's
`component-review.md` then says to stop and report the review as pending. In bb
threads this section replaces that instruction. Hold the review in the thread
and relay the person's decisions to the engine:

1. After `component-review capture`, read `.packet` from
   `<store>/<session>/current.json`. The store is
   `~/.impeccable/component-reviews` unless you passed `--store`. The packet
   carries `id`, `revision`, and a `revision` for each component.
2. Write one HTML file in thread storage. Start with the comp, each component's
   `box` outlined and numbered. Then give each component a card with its number,
   id, kind, note, flags, and the comp cropped to its box, or its plate for an
   asset. Copy the comp once next to the file as a JPEG and crop it with CSS
   backgrounds. List the `codeRegions` ids at the end. Show the file with the
   `inline-vis` directive.
3. Ask in chat, per number, for approve, revise with feedback, or reclassify to
   plate, image, or texture. Also ask for anything missing from the comp and for
   `codeRegions` ids to reclassify. Unmentioned items stay undecided. End the
   turn and wait for the person's own reply in this thread.
4. Turn that reply, and only that reply, into the body
   `{"schemaVersion":1,"requestId":<packet id>,"packetRevision":<packet revision>,"decisions":{<id>:{"revision","action","feedback","split":false}},"missing":[{"id","name","box","feedback"}],"inventoryConfirmed":<bool>,"reclassify":[{"id","kind","feedback"}]}`.
   A reclassify decision also carries `kind`. Boxes are fractions of the comp.
   Give a missing item an id no region uses, the person's words as `name`, and
   a box you locate on the comp. When it sits inside an existing region, name
   that region in `feedback` so the next round can split it. A full approval
   needs every component approved and `inventoryConfirmed: true`. A reply with
   any change request may leave components undecided.
5. Start `IMPECCABLE_QUESTION_DISABLED= <launcher> component-review serve --session <id>`
   in the background and read its URL. POST the body to `/decision` with
   `Content-Type: application/json`, `Origin: http://127.0.0.1:<port>`, and
   `Sec-Fetch-Site: same-origin`. The person approved this relay. It submits
   their decisions, never yours.
6. Run `component-review status --session <id>` and check that
   `receipt.visualDecision` and the number of decisions match the reply. Tell
   the person where you placed each missing item, then act on the receipt as
   `component-review.md` describes.
