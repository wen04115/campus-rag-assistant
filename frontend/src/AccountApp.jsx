import { useCallback, useState } from 'react'
import DocumentPanel from './DocumentPanel.jsx'
import {
  login,
  getCurrentUser,
  getKnowledgeBases,
} from './api.js'

export default function AccountApp() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [session, setSession] = useState(null)
  const [libraries, setLibraries] = useState([])
  const [total, setTotal] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selectedLibrary = libraries.find(
    (item) => String(item.id) === selectedId,
  )

  function applyLibraries(data) {
    if (!data || !Array.isArray(data.items)) {
      throw new Error('知识库列表返回格式异常')
    }

    setLibraries(data.items)
    setTotal(data.total)
    setSelectedId((previous) => (
      data.items.some((item) => String(item.id) === previous)
        ? previous
        : data.items.length > 0
          ? String(data.items[0].id)
          : ''
    ))
  }

    const handleLogout = useCallback(() => {
    setSession(null)
    setLibraries([])
    setTotal(0)
    setSelectedId('')
    setUsername('')
    setPassword('')
    setError('')
  }, [])

  async function handleLogin(event) {
    event.preventDefault()
    if (busy) return

    setBusy(true)
    setError('')

    try {
      const result = await login(username.trim(), password)

      if (!result?.access_token) {
        throw new Error('登录接口没有返回有效凭证')
      }

      const token = result.access_token
      const [user, data] = await Promise.all([
        getCurrentUser(token),
        getKnowledgeBases(token),
      ])

      if (!user || typeof user.username !== 'string') {
        throw new Error('用户信息返回格式异常')
      }

      applyLibraries(data)
      setSession({ token, user })
      setPassword('')
    } catch (requestError) {
      setError(requestError.message || '登录失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function handleRefresh() {
    if (!session || busy) return

    setBusy(true)
    setError('')

    try {
      const data = await getKnowledgeBases(session.token)
      applyLibraries(data)
    } catch (requestError) {
      if (requestError.status === 401) {
        handleLogout()
        setError('登录已失效，请重新登录')
      } else {
        setError(requestError.message || '读取知识库失败')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <div className="card">
        <p className="eyebrow">CAMPUS RAG</p>
        <h1>个人知识库助手</h1>

        {!session ? (
          <section className="panel">
            <h2>账号登录</h2>

            <form onSubmit={handleLogin}>
              <label htmlFor="account-username">用户名</label>
              <input
                id="account-username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                maxLength={50}
                required
                disabled={busy}
              />

              <label htmlFor="account-password">密码</label>
              <input
                id="account-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                maxLength={128}
                required
                disabled={busy}
              />

              <button type="submit" disabled={busy}>
                {busy ? '正在登录…' : '登录'}
              </button>
            </form>

            <p className="hint">
              登录凭证仅保存在当前页面内存中，刷新后需要重新登录。
            </p>
          </section>
        ) : (
          <>
            <section className="panel">
              <div className="account-toolbar">
                <span>当前用户：{session.user.username}</span>
                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={busy}
                >
                  退出登录
                </button>
              </div>
            </section>

            <section className="panel">
              <h2>我的知识库</h2>

              <button
                type="button"
                onClick={handleRefresh}
                disabled={busy}
              >
                {busy ? '正在刷新…' : '刷新知识库'}
              </button>

              <p className="hint">
                共 {total} 个知识库，当前显示最近 {libraries.length} 个，
                最多 20 个。
              </p>

              {libraries.length === 0 ? (
                <p>当前账号还没有知识库。</p>
              ) : (
                <>
                  <label htmlFor="account-library">选择知识库</label>
                  <select
                    id="account-library"
                    className="account-select"
                    value={selectedId}
                    onChange={(event) => setSelectedId(event.target.value)}
                    disabled={busy}
                  >
                    {libraries.map((item) => (
                      <option key={item.id} value={String(item.id)}>
                        {item.name}
                      </option>
                    ))}
                  </select>

                  {selectedLibrary && (
                    <p className="status">
                      已选择：{selectedLibrary.name}
                      （ID：{selectedLibrary.id}）
                    </p>
                  )}

                {selectedLibrary && (
                    <DocumentPanel
                      key={`${session.user.id}:${selectedLibrary.id}`}
                      token={session.token}
                      knowledgeBaseId={selectedLibrary.id}
                      onUnauthorized={handleLogout}
                    />
                  )}
                </>
              )}
            </section>
          </>
        )}

        {error && (
          <p className="account-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </main>
  )
}