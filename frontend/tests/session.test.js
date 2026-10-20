import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { readSavedToken, saveToken, clearSavedToken } from '../src/session.js'

const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
afterEach(() => {
  if (descriptor) Object.defineProperty(globalThis, 'sessionStorage', descriptor)
  else delete globalThis.sessionStorage
})

test('only token is saved and can be restored then cleared', () => {
  const values = new Map()
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  })
  assert.equal(readSavedToken(), '')
  assert.equal(saveToken('fake-token'), true)
  assert.equal(values.size, 1)
  assert.equal(readSavedToken(), 'fake-token')
  clearSavedToken()
  assert.equal(readSavedToken(), '')
  assert.equal(values.size, 0)
})

test('blocked storage falls back without throwing or reporting persisted success', () => {
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new Error('storage blocked') },
  })
  assert.equal(readSavedToken(), '')
  assert.equal(saveToken('fake-token'), false)
  assert.doesNotThrow(() => clearSavedToken())
})
