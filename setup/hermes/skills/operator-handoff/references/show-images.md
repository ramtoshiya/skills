# Show images {:#show-images}

bb shows an HTML page inside your reply. You write no files, so:

- For your own diagram or chart, write the page in the reply as a fenced
  block whose language is `inline-vis`. It holds self-contained HTML and
  cannot load local files.
- For a worker's images, the brief asks the worker to write a page with the
  images and captions, as its `inline-vis` skill describes, into
  `~/.bb/thread-storage/<your thread id>/reports/<topic>/index.html`. Use
  `$BB_THREAD_ID` for your thread id. Show it with
  `::inline-vis{source="thread-storage" file="reports/<topic>/index.html"}`
  on its own line.
