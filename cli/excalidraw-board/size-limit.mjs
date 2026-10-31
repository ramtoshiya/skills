// Byte-size limits for data this command chooses to bound itself. Past the soft
// limit the work continues and stderr names the limit, the actual size, and the
// soft limit. Only the hard limit stops the command. excalidraw-web-export ships
// the same file, worktreeinclude inlines checkSize, and test/size-limit.test.mjs
// keeps the copies equal.
export const hardLimit = 1024 ** 3;

export function checkSize(name, bytes, softLimit, warn = message => process.stderr.write(`${message}\n`)) {
  if (bytes > hardLimit) throw new Error(`${name} is ${bytes} bytes, over the hard limit of ${hardLimit} bytes`);
  if (bytes > softLimit) warn(`warning: ${name} is ${bytes} bytes, over the soft limit of ${softLimit} bytes`);
  return bytes;
}
