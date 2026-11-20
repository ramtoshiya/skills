# newest-model-guard

A [bb](https://getbb.app) plugin that checks the model on an agent-started thread's first message. It rejects an older version when the provider catalog lists both that model and a newer model in the same family.

## Install

From this repository:

```sh
cd bb-plugins/newest-model-guard
npm install
bb plugin install . --yes
```

## Behavior

The guard compares versioned Claude and GPT model IDs numerically within their families. It ignores a trailing date in a Claude version and a bracketed variant on the requested model. It compares against catalog IDs without bracketed variants.

An agent receives a message such as `claude-opus-5 is older than claude-opus-5-5. Start a new thread with claude-opus-5-5, or use the newest-model script from the worker-routing skill.` Start a new thread with the named model.

Messages typed in the app, follow-ups, retries, steers, aliases, and IDs absent from the catalog pass. For CLI and SDK starts, bb can report a parent thread without a sender. The guard treats that parent as the agent attribution, so a person who starts a child from the CLI is also subject to the guard. An unparented CLI start with no sender passes. If the catalog cannot be read within three seconds, the guard logs a warning and lets the message through. A provider can still reject a model itself.

## Development

```sh
npm run typecheck
npm test
bb plugin build .
```

Tested with bb 0.50.1 and plugin SDK 0.6.132.
