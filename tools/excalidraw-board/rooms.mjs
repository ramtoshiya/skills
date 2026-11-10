import { chmodSync, closeSync, lstatSync, mkdirSync, openSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

function validateName(name) {
  if (typeof name !== 'string' || !name.trim() || /\p{Cc}/u.test(name)) {
    throw new Error('Room name must be nonempty and contain no control characters')
  }
}

function validateId(id) {
  // App and older CLI IDs differ in length. Bound input for storage safety.
  if (typeof id !== 'string' || !id.length || id.length > 128 || /[^A-Za-z0-9_-]/u.test(id)) {
    throw new Error('Room id must contain 1 to 128 letters, digits, underscores, or hyphens')
  }
}

function validateKey(key) {
  if (typeof key !== 'string' || key.length !== 22 ||
      Buffer.from(key, 'base64url').length !== 16 ||
      Buffer.from(key, 'base64url').toString('base64url') !== key) {
    throw new Error('Room key must be a canonical base64url encoding of 16 bytes')
  }
}

export function openRooms(directory = join(homedir(), '.local/state/excalidraw-board')) {
  const previousMask = process.umask(0o077)
  let db
  try {
    mkdirSync(directory, { recursive: true, mode: 0o700 })
    if (!lstatSync(directory).isDirectory()) throw new Error('Room directory must be a directory')
    chmodSync(directory, 0o700)
    const path = join(directory, 'rooms.db')
    closeSync(openSync(path, 'a', 0o600))
    if (!lstatSync(path).isFile()) throw new Error('Room database must be a regular file')
    chmodSync(path, 0o600)
    db = new DatabaseSync(path)
    db.exec('PRAGMA busy_timeout = 5000')
    db.exec(`CREATE TABLE IF NOT EXISTS rooms (
      name TEXT NOT NULL,
      id TEXT PRIMARY KEY,
      key TEXT NOT NULL,
      added TEXT NOT NULL,
      last_used TEXT NOT NULL
    )`)
  } catch (error) {
    db?.close()
    throw error
  } finally {
    process.umask(previousMask)
  }

  return {
    add({ name, id, key }) {
      validateName(name)
      validateId(id)
      validateKey(key)
      const now = new Date().toISOString()
      const result = db.prepare('INSERT INTO rooms VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING')
        .run(name, id, key, now, now)
      if (result.changes === 0) {
        const existing = { ...db.prepare('SELECT * FROM rooms WHERE id = ?').get(id) }
        if (existing.key !== key) throw new Error('Room id is already stored with a different key')
        console.warn(`Room id ${id} is already stored as ${JSON.stringify(existing.name)}. Keeping it.`)
        return existing
      }
      const sameName = db.prepare('SELECT id FROM rooms WHERE name = ? ORDER BY added DESC, rowid DESC').all(name)
      if (sameName.length > 1) {
        console.warn(`Room name ${JSON.stringify(name)} is shared by ids: ${sameName.map(row => row.id).join(', ')}`)
      }
      return { name, id, key, added: now, last_used: now }
    },
    list(prefix = '') {
      if (typeof prefix !== 'string') throw new Error('Room name prefix must be a string')
      const rows = db.prepare('SELECT * FROM rooms ORDER BY added DESC, rowid DESC').all()
      return rows.filter(row => row.name.startsWith(prefix)).map(row => {
        let length = Math.min(4, row.id.length)
        while (length < row.id.length && rows.some(other =>
          other.id !== row.id && other.id.startsWith(row.id.slice(0, length)))) length++
        return { ...row, short_id: row.id.slice(0, length) }
      })
    },
    resolve({ name, id } = {}) {
      if ((name === undefined) === (id === undefined)) {
        throw new Error('Specify exactly one room name or id')
      }
      if (name === undefined) validateId(id)
      else validateName(name)
      const rows = name === undefined
        ? db.prepare('SELECT * FROM rooms').all().filter(row => row.id.startsWith(id))
        : db.prepare('SELECT * FROM rooms WHERE name = ? ORDER BY added DESC, rowid DESC').all(name)
      if (!rows.length) throw new Error('Room not found')
      if (rows.length > 1) {
        const ids = rows.map(row => row.id).join(', ')
        if (name === undefined) throw new Error(`Ambiguous room id prefix. Matching ids: ${ids}`)
        console.warn(`Room name ${JSON.stringify(name)} matches ids: ${ids}. Using newest id ${rows[0].id}.`)
      }
      const row = rows[0]
      const now = new Date().toISOString()
      db.prepare('UPDATE rooms SET last_used = ? WHERE id = ?').run(now, row.id)
      return { ...row, last_used: now }
    },
    link(row) {
      validateId(row.id)
      validateKey(row.key)
      return `https://excalidraw.com/#room=${row.id},${row.key}`
    },
    close() {
      db.close()
    },
  }
}
