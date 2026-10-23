import assert from 'node:assert/strict'
import { chmodSync, mkdtempSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { setTimeout } from 'node:timers/promises'
import { openRooms } from '../cli/excalidraw-board/rooms.mjs'

const first = { name: 'Design', id: 'abcd0' + '0'.repeat(35), key: 'AAAAAAAAAAAAAAAAAAAAAA' }

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'excalidraw-rooms-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  return join(root, 'registry')
}

test('persists rooms privately and restores the caller umask', t => {
  const directory = fixture(t)
  const previous = process.umask(0)
  let rooms
  try {
    rooms = openRooms(directory)
    assert.equal(process.umask(), 0)
    assert.equal(statSync(directory).mode & 0o777, 0o700)
    const row = rooms.add(first)
    assert.deepEqual({ name: row.name, id: row.id, key: row.key }, first)
    assert.ok(Number.isFinite(Date.parse(row.added)))
    assert.ok(Number.isFinite(Date.parse(row.last_used)))
    assert.equal(rooms.link(row), `https://excalidraw.com/#room=${first.id},${first.key}`)
    rooms.close()
    rooms = undefined
    for (const file of readdirSync(directory)) {
      assert.equal(statSync(join(directory, file)).mode & 0o777, 0o600)
    }
    rooms = openRooms(directory)
    assert.equal(rooms.list()[0].id, first.id)
    assert.equal(rooms.list()[0].short_id, 'abcd')
  } finally {
    rooms?.close()
    process.umask(previous)
  }
})

test('validates room fields without normalizing identifiers or exposing keys', t => {
  const rooms = openRooms(fixture(t))
  t.after(() => rooms.close())
  for (const name of ['', '   ', 'bad\nname', 'bad\u0000name', 'bad\u0085name', null]) {
    assert.throws(() => rooms.add({ ...first, name }), /name/i)
  }
  for (const id of ['', 'a'.repeat(129), 'a/b', 'a b', 'abcd\n', null]) {
    assert.throws(() => rooms.add({ ...first, id }), /id/i)
  }
  for (const key of ['', first.key + '=', 'A'.repeat(21), 'A'.repeat(21) + 'B', null]) {
    assert.throws(() => rooms.add({ ...first, key }), error => {
      assert.match(error.message, /key/i)
      assert.ok(!error.message.includes(first.key))
      return true
    })
  }
  const ids = ['a'.repeat(20), 'b'.repeat(30), 'Mixed_ID-9', 'mixed_ID-9', 'x', 'z'.repeat(128)]
  for (const id of ids) rooms.add({ ...first, name: id, id })
  assert.deepEqual(rooms.list().map(row => row.id).sort(), [...ids].sort())
  assert.throws(() => rooms.link({ ...first, id: 'bad/id' }), /id/i)
  assert.throws(() => rooms.link({ ...first, key: 'bad' }), /key/i)
})

test('duplicate ids keep the original row and refuse conflicting keys', t => {
  const rooms = openRooms(fixture(t))
  t.after(() => rooms.close())
  const warnings = []
  t.mock.method(console, 'warn', (...args) => warnings.push(args.join(' ')))
  const original = rooms.add(first)
  assert.deepEqual(rooms.add({ ...first, name: 'Renamed' }), original)
  const wrongKey = 'AQEBAQEBAQEBAQEBAQEBAQ'
  assert.throws(() => rooms.add({ ...first, key: wrongKey }), error => {
    assert.match(error.message, /key/i)
    assert.ok(!error.message.includes(wrongKey))
    assert.ok(!error.message.includes(first.key))
    return true
  })
  assert.equal(rooms.list().length, 1)
  assert.equal(rooms.list()[0].name, first.name)
  assert.equal(rooms.list()[0].key, first.key)
  assert.ok(warnings.some(warning => warning.includes(first.name)))
  assert.ok(warnings.every(warning => !warning.includes(first.key) && !warning.includes('https://')))
})

test('duplicate names warn with ids and resolve the newest room, touching only its last_used', async t => {
  const directory = fixture(t)
  const rooms = openRooms(directory)
  t.after(() => rooms.close())
  const warnings = []
  t.mock.method(console, 'warn', (...args) => warnings.push(args.join(' ')))
  const older = rooms.add(first)
  const newer = rooms.add({ ...first, id: 'abcd1' + '0'.repeat(35) })
  assert.ok(warnings.some(warning => warning.includes(first.id)))
  await setTimeout(5)
  const found = rooms.resolve({ name: first.name })
  assert.equal(found.id, newer.id)
  assert.equal(found.added, newer.added)
  assert.ok(found.last_used > newer.last_used)
  assert.ok(warnings.some(warning => warning.includes(older.id) && warning.includes(newer.id)))
  assert.ok(warnings.every(warning => !warning.includes(first.key)))
  const reopened = openRooms(directory)
  try {
    assert.equal(reopened.list().find(row => row.id === older.id).last_used, older.last_used)
    assert.equal(reopened.list().find(row => row.id === newer.id).last_used, found.last_used)
  } finally {
    reopened.close()
  }
  assert.throws(() => rooms.resolve({ name: 'Des' }), /not found/i)
  for (const selector of [{}, { name: first.name, id: first.id }, { name: '' }, { id: '' }]) {
    assert.throws(() => rooms.resolve(selector))
  }
})

test('lists shortest globally unique case-sensitive ids and filters only literal name prefixes', t => {
  const rooms = openRooms(fixture(t))
  t.after(() => rooms.close())
  rooms.add(first)
  rooms.add({ ...first, name: 'Other', id: 'abcd1' + '0'.repeat(35) })
  rooms.add({ ...first, name: 'Design_100%', id: 'ABCD_123' })
  rooms.add({ ...first, name: 'Tiny', id: 'x' })
  const rows = rooms.list()
  assert.equal(rows.find(row => row.id === first.id).short_id, 'abcd0')
  assert.equal(rows.find(row => row.name === 'Other').short_id, 'abcd1')
  assert.equal(rows.find(row => row.name === 'Design_100%').short_id, 'ABCD')
  assert.equal(rows.find(row => row.name === 'Tiny').short_id, 'x')
  assert.deepEqual(rooms.list('Design').map(row => row.name).sort(), ['Design', 'Design_100%'])
  assert.equal(rooms.list('Design')[0].short_id, 'ABCD')
  assert.equal(rooms.list('Design').find(row => row.id === first.id).short_id, 'abcd0')
  assert.equal(rooms.list('Design_100%').length, 1)
  assert.deepEqual(rooms.list('design'), [])
  assert.deepEqual(rooms.list('abcd'), [])
  for (const row of rows) assert.equal(rooms.resolve({ id: row.short_id }).id, row.id)
  assert.equal(rooms.resolve({ id: 'A' }).id, 'ABCD_123')
  assert.throws(() => rooms.resolve({ id: 'abcd' }), /ambiguous/i)
  assert.throws(() => rooms.resolve({ id: 'abCD' }), /not found/i)
  assert.throws(() => rooms.resolve({ id: '%' }), /id/i)
})

test('repairs existing storage permissions and restores umask when opening fails', t => {
  const directory = fixture(t)
  const rooms = openRooms(directory)
  rooms.close()
  chmodSync(directory, 0o755)
  chmodSync(join(directory, 'rooms.db'), 0o644)
  const reopened = openRooms(directory)
  reopened.close()
  assert.equal(statSync(directory).mode & 0o777, 0o700)
  assert.equal(statSync(join(directory, 'rooms.db')).mode & 0o777, 0o600)
  const invalid = join(directory, 'not-a-directory')
  writeFileSync(invalid, '')
  const before = process.umask()
  assert.throws(() => openRooms(invalid))
  assert.equal(process.umask(), before)
})

test('waits for another process holding a write transaction without losing rows', async t => {
  const directory = fixture(t)
  const rooms = openRooms(directory)
  t.after(() => rooms.close())
  rooms.add(first)
  const child = spawn(process.execPath, ['--input-type=module', '-e', `
    import { DatabaseSync } from 'node:sqlite'
    const db = new DatabaseSync(process.argv[1])
    db.exec('BEGIN IMMEDIATE')
    process.stdout.write('locked')
    setTimeout(() => { db.exec('COMMIT'); db.close() }, 150)
  `, join(directory, 'rooms.db')], { stdio: ['ignore', 'pipe', 'pipe'] })
  t.after(() => child.kill())
  const exited = once(child, 'exit')
  let stderr = ''
  child.stderr.on('data', data => { stderr += data })
  const [ready] = await once(child.stdout, 'data')
  assert.equal(String(ready), 'locked')
  const second = { ...first, name: 'Second', id: 'Second-ID' }
  rooms.add(second)
  const [code] = await exited
  assert.equal(code, 0, stderr)
  assert.deepEqual(rooms.list().map(row => row.id).sort(), [first.id, second.id].sort())
})
