import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import {
  ApiError, apiRequest, createKnowledgeBase, deleteKnowledgeBase,
  getCurrentUser, login, renameKnowledgeBase,
} from '../src/api.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('request forwards token, abort signal and JSON response', async () => {
  const controller = new AbortController()
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/test')
    assert.equal(options.headers.get('Authorization'), 'Bearer fake-token')
    assert.equal(options.signal, controller.signal)
    return Response.json({ ok: true })
  }
  assert.deepEqual(await apiRequest('/test', { token: 'fake-token', signal: controller.signal }), { ok: true })
})

test('401 keeps status for logout handling', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'expired' }, { status: 401 })
  await assert.rejects(getCurrentUser('fake'), (error) => error instanceof ApiError && error.status === 401 && error.message === 'expired')
})

test('validation errors are rendered as text', async () => {
  globalThis.fetch = async () => Response.json({ detail: [{ msg: 'invalid name' }] }, { status: 422 })
  await assert.rejects(apiRequest('/test'), /invalid name/)
})

test('non-JSON error response produces a useful status message', async () => {
  globalThis.fetch = async () => new Response('Bad gateway', { status: 502 })
  await assert.rejects(apiRequest('/test'), (error) => error.status === 502 && error.message.includes('502'))
})

test('network failures are not disguised as authentication errors', async () => {
  globalThis.fetch = async () => { throw new TypeError('offline') }
  await assert.rejects(apiRequest('/test'), (error) => error instanceof TypeError && error.status === undefined)
})

test('FormData is forwarded without forcing JSON content type', async () => {
  const body = new FormData()
  body.append('file', new Blob(['test']), 'test.txt')
  globalThis.fetch = async (_path, options) => {
    assert.equal(options.body, body)
    assert.equal(options.headers.has('Content-Type'), false)
    return Response.json({ id: 1 })
  }
  await apiRequest('/upload', { method: 'POST', body })
})

test('login and knowledge-base mutations use expected methods and bodies', async () => {
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, method: options.method, body: options.body })
    return Response.json({ id: 2 })
  }
  await login('test', 'fake-password')
  await createKnowledgeBase('token', '资料')
  await renameKnowledgeBase('token', 2, '新名称')
  await deleteKnowledgeBase('token', 2)
  assert.deepEqual(calls, [
    { path: '/api/auth/login', method: 'POST', body: JSON.stringify({ username: 'test', password: 'fake-password' }) },
    { path: '/api/knowledge-bases', method: 'POST', body: JSON.stringify({ name: '资料' }) },
    { path: '/api/knowledge-bases/2', method: 'PATCH', body: JSON.stringify({ name: '新名称' }) },
    { path: '/api/knowledge-bases/2', method: 'DELETE', body: undefined },
  ])
})
