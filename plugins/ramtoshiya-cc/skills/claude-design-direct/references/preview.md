# Previewing an artboard outside the canvas

Opened straight from disk, a `.dc.html` shows literal `{{ }}` bindings, every `sc-if` branch at
once, and the page repeated. **That is a missing runtime file, not a broken artboard.** `support.js`
owns `hideRawTemplate()`, and a browser treats unknown `sc-for` / `sc-if` elements as ordinary
inline wrappers whose children always render. Diagnose the absence before doubting the artboard, or
you will "fix" a file that was already correct.

`support.js` is that runtime. It is in no repo, so pull it with `get_file` from the project that
owns the artboard. That read follows the same two modes as any other, so if it comes back inline,
write it to disk before you copy it anywhere. Then put both files in one directory and serve that
directory over HTTP:

```sh
D=$(mktemp -d)
cp path/to/Artboard.dc.html path/to/support.js "$D/"
uv run python -m http.server 8899 --directory "$D" &   # background it; it never returns
preview_pid=$!
# now at http://localhost:8899/Artboard.dc.html — stop it with: kill "$preview_pid"
```

That is the whole harness. Any static server does.

Do not supply React: `support.js` loads its own, and its loader returns early if `window.React`
and `window.ReactDOM` are already set, so a React you inject renders the page under your version
while it still looks correct.

Do not try to open the canvas's own preview URL. `<projectId>.claudeusercontent.com/_bootstrap` is
an auth handshake, not a page: it waits for a `postMessage` from claude.ai, sets
`__Host-omelette-preview` with `Partitioned`, then redirects to the real file. Every other path 404s
until that cookie exists, and `Partitioned` keys the cookie to claude.ai as the top-level site, so
holding a token would not help.

When the artboard has to be looked at, hand over the local render rather than the canvas. It is a
normal top-level page, so devtools, `getComputedStyle` and element pickers all reach it, and none
of those cross into the canvas iframe. Serving it is your job and opening it is not.
