import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PREFIX = "apple-titles-helper-";

/**
 * Compiles `source` with the system Swift toolchain into `directory`, named by the source hash,
 * so an unchanged source never rebuilds and a changed one replaces the old binary.
 * Returns the binary path.
 */
export async function buildHelper({ source, directory, swiftc = ["/usr/bin/xcrun", "swiftc"] }) {
  const hash = createHash("sha256").update(source).digest("hex").slice(0, 16);
  const binary = join(directory, `${PREFIX}${hash}`);
  if (isFile(binary)) return binary;

  mkdirSync(directory, { recursive: true });
  const work = join(directory, `build-${process.pid}-${Date.now()}`);
  mkdirSync(work);
  try {
    const sourcePath = join(work, "title.swift");
    writeFileSync(sourcePath, source);
    const output = join(work, "helper");
    try {
      await execFileAsync(swiftc[0], [...swiftc.slice(1), "-O", "-o", output, sourcePath], {
        timeout: 120_000,
      });
    } catch (error) {
      throw new Error(`Compiling the Swift helper failed: ${error.stderr || error.message}`.trim());
    }
    renameSync(output, binary);
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
  for (const name of readdirSync(directory)) {
    if (name.startsWith(PREFIX) && join(directory, name) !== binary) {
      rmSync(join(directory, name), { force: true });
    }
  }
  return binary;
}

function isFile(path) {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** Runs `binary mode`, writes `input` to its stdin, and returns its last stdout line parsed as JSON. */
export function runHelper(binary, mode, { input = "", signal } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(binary, [mode], { stdio: ["pipe", "pipe", "pipe"], signal });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => {
      const line = stdout.trim().split("\n").pop();
      try {
        resolve(JSON.parse(line));
      } catch {
        reject(new Error(`The Swift helper exited with ${code}: ${stderr.trim() || "no output"}`));
      }
    });
    child.stdin.on("error", () => {});
    child.stdin.end(input);
  });
}

/**
 * Builds the helper at most once at a time. `status` waits up to `statusWaitMs` for a build, so a
 * fresh install usually reports ready on its first check, and never longer, so the picker and
 * Automatic stay responsive.
 */
export function createHelperService({ build, run = runHelper, statusWaitMs = 3000 }) {
  let binary = null;
  let building = null;
  let buildError = null;

  function ensureBuilt() {
    if (binary !== null) return Promise.resolve(binary);
    building ??= build().then(
      (path) => {
        binary = path;
        buildError = null;
        return path;
      },
      (error) => {
        buildError = error;
        throw error;
      },
    ).finally(() => {
      building = null;
    });
    return building;
  }

  return {
    async status() {
      if (binary === null) {
        const pending = ensureBuilt().catch(() => {});
        let timer;
        await Promise.race([pending, new Promise((resolve) => (timer = setTimeout(resolve, statusWaitMs)))]);
        clearTimeout(timer);
      }
      if (binary === null) {
        return { ready: false, message: buildError ? buildError.message : "Building the Swift helper" };
      }
      return run(binary, "status");
    },
    async complete(prompt, signal) {
      const path = await ensureBuilt();
      return run(path, "complete", { input: prompt, signal });
    },
  };
}
