# Commands and element fields

`<board>` is a board name from `wjrj boards`, or a board id. File arguments
are relative to the current directory. Every command exits 0 on success, 1 when
wjrj refuses or cannot answer, and 2 for a usage mistake.

```sh
wjrj boards
wjrj create
wjrj read <board> --outline
wjrj read <board> --ids idea-a,a-to-b
wjrj read <board> --full --ids idea-a
wjrj read <board> --since 16
wjrj read <board> --at 12
wjrj write <board> < batch.json
wjrj history <board>
wjrj image <board> board.png --ids idea-a,idea-b --scale 2
wjrj image <board> area.png --area 0,0,1200,800
wjrj snapshot <board> board.html
wjrj register notes/plan.md
wjrj register https://example.com/
```

## Read output {:#read-output}

A read prints one JSON document with one element per line:

```json
{"board":{"id":"Qm3vT8kLx2NcR5wYp7HdZa","name":"calm-otter","created":1795000000000,"revision":17},
"since":null,
"missing":["gone"],
"elements":[
{"id":"idea-a","type":"rectangle","x":0,"y":0,"width":200,"height":100,"label":"Capture"}
],
"materials":[
{"resource":"Kp4sW9eTq1BvM6yUo2RjXc","kind":"markdown","name":"plan.md","path":"/Users/me/notes/plan.md"}
],
"comments":[],
"deleted":{"elements":[],"comments":[]}}
```

- The default view leaves out `seed`, `index`, and fields at their default
  values, and rounds numbers to two decimal places. `--full` prints elements
  as stored.
- `--outline` prints each element's `box` as `[x, y, width, height]`, its
  label or text cut to 60 characters, a material's `resource`, and an arrow's
  `from` and `to` ids.
- `missing` appears only with `--ids`, and lists ids that are not on the board.
- `materials` lists the material that the printed elements show. A file has a
  `path` and a web page has a `url`.
- With `--since`, the read holds only elements changed after that revision,
  and `deleted` lists what was deleted after it. `--at` shows the whole board
  as it was at that revision.

`write` prints the receipt `{"revision":17,"changed":["idea-a"]}`. `image`
prints `{"file","revision","area","width","height"}`, where `area` is the
board rectangle the image covers. `snapshot` prints `{"file","revision"}`.
`register` prints `{"id","name","kind"}`, and `id` is the `resource` for a
material element. `history` prints one line per revision with the time and the
number of elements it changed.

## Batches {:#batches}

A batch is one JSON object with the arrays `add`, `update`, `delete`, and
`restore`. Each is optional. The server checks the whole batch, and saves all
of it or none of it.

```json
{
	"add": [
		{"id":"idea-a","type":"rectangle","x":0,"y":0,"width":200,"height":100,"label":"Capture"},
		{"id":"idea-b","type":"rectangle","x":400,"y":0,"width":200,"height":100,"label":"Review"},
		{"id":"a-to-b","type":"arrow","x":200,"y":50,"points":[[0,0],[200,0]],
			"start":{"element":"idea-a","fixedPoint":[1,0.5]},"end":{"element":"idea-b","fixedPoint":[0,0.5]}}
	],
	"update": [{"id":"idea-b","strokeColor":"#1971c2"}],
	"delete": ["old-note"]
}
```

- `update` items carry the `id` and the fields to change. To change a field
  only while it still holds the value you read, add `expected` with the old
  values, such as `{"id":"idea-b","x":420,"expected":{"x":400}}`. A field the
  person has changed since then keeps the person's value.
- `delete` items are ids. Deleting a box unbinds the arrows attached to it.
  Comments pinned to it move to the board.
- `restore` items are whole elements with every field, such as one from
  `read --at <rev> --full`. A restore brings back an element the board had
  before, including a deleted one.
- Ids are 1 to 64 letters, digits, `_`, or `-`.

## Element fields {:#element-fields}

Every element has `id`, `type`, and optional `hidden` and `index`. A new
element goes on top of the stack unless the batch gives an `index`.

| Type | Required | Optional |
| --- | --- | --- |
| `rectangle`, `ellipse` | `x`, `y`, `width`, `height` | `label` and the style fields |
| `text` | `x`, `y`, `width`, `height`, `text` | `fontSize` (20) and the style fields |
| `arrow` | `x`, `y`, `points` (two or more) | `start`, `end`, `startArrowhead` (null), `endArrowhead` (`arrow`), and the style fields |
| `freedraw` | `x`, `y`, `points` (one or more) | the style fields |
| `material` | `x`, `y`, `width`, `height`, `resource` | `url`, `scrollX`, `scrollY` |

Style fields and their defaults: `strokeColor` (`#1e1e1e`), `backgroundColor`
(`transparent`), `fillStyle` (`solid`, `hachure`, or `cross-hatch`),
`strokeWidth` (2), `strokeStyle` (`solid`, `dashed`, or `dotted`), `roughness`
(0, 1, or 2, default 1), and `opacity` (0 to 100, default 100). Colors are hex,
such as `#e03131`, or `transparent`. Arrowheads are `arrow`, `triangle`, `bar`,
`dot`, or null. `points` are `[x, y]` offsets from the element's `x` and `y`.

## Material {:#material}

Register a file or a web address first, then place it:

```sh
wjrj register notes/plan.md
printf '%s\n' '{"add":[{"id":"plan","type":"material","resource":"<id>","x":0,"y":200,"width":640,"height":480}]}' |
	wjrj write calm-otter
```

Use material for Markdown files, images (PNG, JPEG, GIF, and WebP), and http or
https pages. A refused registration names the reason. Agents cannot upload pasted bytes or
copy a selection as an image. Those actions belong to the person.
