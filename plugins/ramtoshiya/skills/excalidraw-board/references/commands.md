# Commands and room import

```sh
excalidraw-board room create design-review
excalidraw-board room list design
excalidraw-board read --id <prefix> --outline
excalidraw-board read --id <prefix> --frame <frame-id>
excalidraw-board read --id <prefix> --group <group-id>
excalidraw-board read --id <prefix> --ids a1,b2 --full
excalidraw-board image --id <prefix> --file screenshot.png --element-id capture-home --x 40 --y 80 --width 406
```

Write input is one JSON object, for example:

```json
{
  "add": [
    {"id":"idea-boundary","type":"rectangle","x":0,"y":0,"w":600,"h":400,"backgroundColor":"transparent"},
    {"id":"idea-title","type":"text","x":20,"y":16,"w":240,"h":30,"text":"Login idea"},
    {"id":"a1","type":"rectangle","x":40,"y":80,"w":240,"h":120},
    {"id":"b2","type":"text","x":60,"y":100,"w":200,"h":30,"text":"Login"}
  ],
  "update": [],
  "delete": []
}
```

When the user supplies a link and asks to add the room, use `room import
--name <name> --stdin` with the link on stdin. Import only reads the remote
scene. A missing saved room reports `room is gone`.

