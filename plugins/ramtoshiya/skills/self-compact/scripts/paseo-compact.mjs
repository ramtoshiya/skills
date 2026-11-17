import { access, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

export async function compactAndResume(client, agentId, note, { resume = true } = {}) {
  await access(note);
  const commands = await client.listCommands({ agentId });
  if (!commands.commands.some(command => command.name === 'compact')) {
    throw new Error('This provider does not advertise /compact. Keep the handoff note.');
  }
  const idle = await client.waitForFinish(agentId, 300_000);
  if (idle.status !== 'idle' || idle.error) {
    throw new Error('The current turn did not finish successfully. No compaction was sent.');
  }
  const before = await client.fetchAgentTimeline(agentId);
  if (before.error || !Number.isInteger(before.window?.maxSeq) ||
      before.agent?.status !== 'idle' || before.agent.pendingPermissions?.length) {
    throw new Error('Cannot establish an idle timeline boundary. No compaction was sent.');
  }
  const messageId = randomUUID();
  await client.sendAgentMessage(agentId,
    `/compact Keep the goal, user constraints, and handoff note path ${JSON.stringify(note)}.`,
    { messageId });
  const compacted = await client.waitForFinish(agentId, 300_000);
  if (compacted.status !== 'idle' || compacted.error) {
    throw new Error('Compaction did not finish successfully. Resume was not sent.');
  }
  const after = await client.fetchAgentTimeline(agentId);
  const recent = after.entries?.filter(entry => entry.seqStart > before.window.maxSeq) ?? [];
  const command = recent.find(entry => entry.item.type === 'user_message' &&
    (entry.item.clientMessageId === messageId || entry.item.messageId === messageId));
  const proof = command?.turnId && recent.find(entry => {
    if (entry.turnId !== command.turnId) return false;
    const item = entry.item;
    return item.status === 'completed' &&
      (item.type === 'compaction' ||
       (item.type === 'tool_call' && item.metadata?.title === 'Compact conversation'));
  });
  if (after.error || after.epoch !== before.epoch || !proof ||
      recent.some(entry => entry.turnId !== command.turnId) ||
      after.agent?.status !== 'idle' || after.agent.pendingPermissions?.length) {
    throw new Error('No isolated completed compaction for this command. Resume was not sent. Keep the handoff note.');
  }
  if (resume) {
    await client.sendAgentMessage(agentId,
      `Resume after self-compaction: read ${JSON.stringify(note)} before anything else and continue from its next step. Delete the note when its task is finished.`);
  }
  return { compacted: true, resumeSent: resume, evidence: proof.item };
}

async function main() {
  const [resources, noteArgument, option] = process.argv.slice(2);
  const agentId = process.env.PASEO_AGENT_ID;
  if (!resources || !noteArgument || !agentId || (option && option !== '--no-resume')) {
    throw new Error('Usage: paseo-compact.sh <handoff-note> [--no-resume], inside a Paseo agent.');
  }
  const note = resolve(noteArgument);
  await readFile(note, 'utf8');
  const cli = resolve(resources, 'bin/paseo');
  const status = JSON.parse(execFileSync(cli, ['daemon', 'status', '--json'], { encoding: 'utf8' }));
  if (!status.desktopManaged || status.connectedDaemon !== 'reachable') {
    throw new Error('A reachable local Desktop-managed Paseo daemon is required.');
  }
  const sdk = pathToFileURL(resolve(resources, 'app.asar/node_modules/@getpaseo/client/dist/node/index.js'));
  const { createHostClient } = await import(sdk.href);
  const client = createHostClient(status.listen, { clientId: `self-compact-${agentId}`, clientType: 'cli' });
  try {
    await client.connect();
    const result = await compactAndResume(client, agentId, note, { resume: option !== '--no-resume' });
    console.log(JSON.stringify(result));
  } finally {
    await client.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
