import { useCallback, useState } from 'react'
import DocumentPanel from './DocumentPanel.jsx'
import {
  login,
  getCurrentUser,
  getKnowledgeBases,
  createKnowledgeBase,
  renameKnowledgeBase,
  deleteKnowledgeBase,
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
  const [newLibraryName, setNewLibraryName] = useState('')
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
    setNewLibraryName('')
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

    async function handleCreateLibrary(event) {
    event.preventDefault()
    if (!session || busy) return

    const name = newLibraryName.trim()

    if (!name) {
      setError('请输入知识库名称')
      return
    }

    setBusy(true)
    setError('')

    let creationSucceeded = false

    try {
      const created = await createKnowledgeBase(session.token, name)
      creationSucceeded = true
      setNewLibraryName('')

      if (!created || !Number.isInteger(created.id)) {
        throw new Error('创建接口返回格式异常')
      }

      const data = await getKnowledgeBases(session.token)
      applyLibraries(data)

      if (data.items.some((item) => item.id === created.id)) {
        setSelectedId(String(created.id))
      }
    } catch (requestError) {
      if (requestError.status === 401) {
        handleLogout()
        setError('登录已失效，请重新登录后检查知识库列表')
      } else if (creationSucceeded) {
        setError(
          '知识库已创建，但列表刷新失败。请点击刷新知识库，不要重复创建。',
        )
      } else {
        setError(
          `${requestError.message || '创建请求失败'}。`
          + '如果是网络错误，请先刷新列表确认是否已创建，避免重复提交。',
        )
      }
    } finally {
      setBusy(false)
    }
  }

    async function handleRenameLibrary() {
    if (!session || !selectedLibrary || busy) return

    const entered = window.prompt(
      '请输入新的知识库名称（最多100个字符）',
      selectedLibrary.name,
    )

    if (entered === null) return

    const name = entered.trim()

    if (!name || name.length > 100) {
      setError('知识库名称需要为1～100个字符')
      return
    }

    if (name === selectedLibrary.name) return

    const id = selectedLibrary.id

    setBusy(true)
    setError('')

    try {
      const updated = await renameKnowledgeBase(session.token, id, name)

      if (
        updated?.id !== id
        || typeof updated.name !== 'string'
      ) {
        throw new Error('重命名接口返回格式异常')
      }

      setLibraries((previous) => previous.map((item) => (
        item.id === id ? { ...item, name: updated.name } : item
      )))
    } catch (requestError) {
      if (requestError.status === 401) {
        handleLogout()
        setError('登录已失效，请重新登录')
      } else {
        setError(
          `${requestError.message || '重命名失败'}。`
          + '如果是网络错误，请刷新知识库列表确认最终名称。',
        )
      }
    } finally {
      setBusy(false)
    }
  }

    async function handleDeleteLibrary() {
        if (!session || !selectedLibrary || busy) return

        const { id, name } = selectedLibrary

        const confirmed = window.confirm(
        `确定删除知识库“${name}”（ID：${id}）吗？`
        + '\n只能删除没有文档的知识库，删除后无法在页面恢复。',
        )

        if (!confirmed) return

        setBusy(true)
        setError('')

        let deletionSucceeded = false

        try {
        await deleteKnowledgeBase(session.token, id)
        deletionSucceeded = true

        // 删除成功后立即取消选择，卸载原知识库的文档面板。
        setSelectedId('')
        setLibraries((previous) => (
            previous.filter((item) => item.id !== id)
        ))
        setTotal((previous) => Math.max(0, previous - 1))

        const data = await getKnowledgeBases(session.token)
        applyLibraries(data)
        } catch (requestError) {
        if (requestError.status === 401) {
            handleLogout()
            setError('登录已失效，请重新登录')
        } else if (deletionSucceeded) {
            setError('知识库已删除，但列表刷新失败，请点击刷新知识库。')
        } else {
            setError(
            `${requestError.message || '删除请求失败'}。`
            + '如果是网络错误，请先刷新列表确认结果。',
            )
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

                          <form onSubmit={handleCreateLibrary}>
                <label htmlFor="new-library-name">
                  新知识库名称
                </label>

                <input
                  id="new-library-name"
                  value={newLibraryName}
                  onChange={(event) => {
                    setNewLibraryName(event.target.value)
                  }}
                  placeholder="例如：课程资料、实习文档"
                  maxLength={100}
                  required
                  disabled={busy}
                />

                <button
                  type="submit"
                  disabled={busy || !newLibraryName.trim()}
                >
                  {busy ? '处理中…' : '创建知识库'}
                </button>
              </form>

              <button
                type="button"
                onClick={handleRefresh}
                disabled={busy}
              >
                {busy ? '处理中…' : '刷新知识库'}
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
                    <button
                      type="button"
                      onClick={handleRenameLibrary}
                      disabled={busy}
                    >
                      重命名当前知识库
                    </button>
                  )}

                  {selectedLibrary && (
                    <button
                      type="button"
                      onClick={handleDeleteLibrary}
                      disabled={busy}
                    >
                      删除当前空知识库
                    </button>
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