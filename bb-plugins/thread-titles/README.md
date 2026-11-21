# thread-titles

A [bb](https://getbb.app) plugin that writes thread titles with the Apple on-device language model. It registers the AI service **Apple on-device model**. Titles are always in English, whatever language the first message is in. The text never leaves the Mac.

## Install

Use an Apple silicon Mac with macOS 26 or newer, Apple Intelligence turned on, the Xcode command line tools (`xcrun swiftc` must work), [Node.js](https://nodejs.org/en/download) 22 or newer, and bb with its CLI. Use a checkout you intend to keep.

```sh
cd bb-plugins/thread-titles
npm ci --ignore-scripts
bb plugin install . --yes
bb settings ai-services set thread-title apple-foundation-models
bb settings ai-services test thread-title
```

The last command prints a title and how long it took. `bb settings ai-services show` lists the service and, when the model is unavailable, the reason Apple reports. Choose **Apple on-device model** for thread titles in Settings, AI services, to do the same in the app.

## How it works

bb writes the prompt and cleans the reply. The plugin appends one fixed English instruction to the prompt and passes it to a small Swift program that calls `SystemLanguageModel` from the FoundationModels framework.

- The plugin compiles the program once with `xcrun swiftc` from the source in `swift-source.js`. It stores the binary in the plugin's host data directory, named by a hash of the source, and removes older builds. It uses only system frameworks, so it adds no dependency. Nothing is downloaded or committed as a binary.
- Each request runs the program as a fresh process and sends the prompt on standard input. A request normally finishes in under a second. bb aborts a text request after 5 seconds, and the abort stops the process.
- A guardrail or generation error from the model is retried once, because the same input usually succeeds on a second attempt. Any other failure, or a second failure, rejects the request so bb treats it as a failure.
- `status` reports not ready with Apple's reason when Apple Intelligence is off, the Mac is not eligible, or the model is still downloading. It reports not ready while the first build runs, and a compile error shows in the same message.
- One function, `complete` in `server.js`, reaches the model. A second backend would replace it.

bb's Automatic mode tries services in plugin id order. The id `thread-titles` sorts after the Codex plugin, so Automatic keeps trying Codex first and uses this service only as a later fallback. The service also appears for commit messages. Its outputs come from a small model, so select it explicitly only for tasks where that quality is enough.

## Development

```sh
npm test
bb plugin build .
```

The test for the Swift source compiles it on the machine that runs the tests and asks the real model for a reply. It accepts a guardrail or an unavailable model as an answer, because those are protocol-correct results.

Tested with bb 0.50.1 on macOS 26.5.1.
