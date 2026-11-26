import type { EngineInterface, Register } from 'claude-code'

type Answer =
  | { kind: 'moved'; tools: string[] }
  | { kind: 'nothing' }
  | { kind: 'refused'; tools: string[] }

const MOVABLE = new Set(['Bash', 'PowerShell'])
const CONTINUE = 'The person moved your running command to the background. It keeps running, and you will be notified when it ends. Continue your work.'

let mainTurn: string | undefined

async function moveRunningCommands($: EngineInterface): Promise<Answer> {
  const turnId = mainTurn
  if (turnId === undefined) return { kind: 'nothing' }
  const latest = (await $.session.messages()).filter((message) => message.role === 'assistant').at(-1)
  const running = (latest?.toolUses ?? []).filter((use) => use.text === undefined).map((use) => use.tool)
  if (running.length === 0) return { kind: 'nothing' }
  const stuck = running.filter((tool) => !MOVABLE.has(tool))
  if (stuck.length > 0) return { kind: 'refused', tools: stuck }
  await $.turn.abort({ turnId })
  void $.prompt.submit({ text: CONTINUE })
  return { kind: 'moved', tools: running }
}

async function serveRequests($: EngineInterface, storage: string) {
  const requests = `${storage}/background-requests`
  await $.fs.write(requests, '')
  let pending = ''
  for await (const { stream, text } of $.process.spawn({ argv: ['tail', '-n', '0', '-f', requests] })) {
    if (stream !== 'stdout') continue
    const lines = (pending + text).split('\n')
    pending = lines.pop() ?? ''
    for (const id of lines.filter(Boolean)) {
      const answer = await moveRunningCommands($)
      await $.fs.write(`${storage}/background-answer-${id}`, JSON.stringify(answer))
    }
  }
}

export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    const storage = await $.env.get('BB_THREAD_STORAGE')
    if (storage !== undefined) {
      void serveRequests($, storage).catch((error) => $.ui.log(`background-tools: ${String(error)}`, { to: 'debug' }))
    }
    return started
  })
  on('turn.start', async ($, e, next) => {
    const started = await next(e)
    if (e.agentId === undefined) mainTurn = started.turnId
    return started
  })
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined && e.turnId === mainTurn) mainTurn = undefined
    return next(e)
  })
}
