import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from './api.js'

export default function DocumentPanel({
  token,
  knowledgeBaseId,
  onUnauthorized,
}) {
  const [documents, setDocuments] = useState([])
  const [total, setTotal] = useState(0)
  const [selectedFile, setSelectedFile] = useState(null)
  const [busy, setBusy] = useState('loading')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [question, setQuestion] = useState('')
  const [reply, setReply] = useState(null)
  const controllerRef = useRef(null)
  const fileInputRef = useRef(null)

  const basePath = `/api/knowledge-bases/${knowledgeBaseId}/documents`

  const loadDocuments = useCallback(async (signal) => {
    const data = await apiRequest(`${basePath}?page=1&size=20`, {
      token,
      signal,
    })

    if (signal.aborted) return

    if (!data || !Array.isArray(data.items)) {
      throw new Error('文档列表返回格式异常')
    }

    setDocuments(data.items)
    setTotal(data.total)
  }, [basePath, token])

  const reportError = useCallback((requestError, signal) => {
    if (signal.aborted) return

    if (requestError.status === 401) {
      onUnauthorized()
      return
    }

    setError(requestError.message || '请求失败，请稍后重试')
  }, [onUnauthorized])

    useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    controllerRef.current = controller

    apiRequest(`${basePath}?page=1&size=20`, {
      token,
      signal,
    })
      .then((data) => {
        if (signal.aborted) return

        if (!data || !Array.isArray(data.items)) {
          throw new Error('文档列表返回格式异常')
        }

        setDocuments(data.items)
        setTotal(data.total)
      })
      .catch((requestError) => {
        reportError(requestError, signal)
      })
      .finally(() => {
        if (!signal.aborted) {
          setBusy('')
        }
      })

    return () => {
      controller.abort()
    }
  }, [basePath, token, reportError])


  async function runTask(name, action) {
    if (busy || !controllerRef.current) return

    const signal = controllerRef.current.signal
    if (signal.aborted) return

    setBusy(name)
    setError('')

    try {
      await action(signal)
    } catch (requestError) {
      reportError(requestError, signal)
    } finally {
      if (!signal.aborted) {
        setBusy('')
      }
    }
  }

  async function handleUpload(event) {
    event.preventDefault()

    if (!selectedFile) {
      setError('请先选择文件')
      return
    }

    if (selectedFile.size > 10 * 1024 * 1024) {
      setError('文件不能超过 10 MiB')
      return
    }

    const file = selectedFile

    await runTask('upload', async (signal) => {
      setReply(null)
      const body = new FormData()
      body.append('file', file)

      const result = await apiRequest(basePath, {
        token,
        method: 'POST',
        body,
        signal,
      })

      if (signal.aborted) return

      setMessage(`${result.original_name} 上传成功，请重新建立索引。`)
      setSelectedFile(null)

      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }

      await loadDocuments(signal)
    })
  }

  async function handleDelete(document) {
    if (busy) return

    const confirmed = window.confirm(
      `确定删除“${document.original_name}”（ID：${document.id}）吗？`
      + '删除后需要重新建立索引，且无法通过页面撤销。',
    )

    if (!confirmed) return

    await runTask(`delete-${document.id}`, async (signal) => {
      setReply(null)
      const result = await apiRequest(`${basePath}/${document.id}`, {
        token,
        method: 'DELETE',
        signal,
      })

      if (signal.aborted) return

      setMessage(
        result.cleanup_pending
          ? '文档记录已删除，但磁盘清理未完成，请检查后端日志。'
          : '文档已删除，请重新建立索引。',
      )

      await loadDocuments(signal)
    })
  }

  async function handleIndex() {
    if (busy) return

    await runTask('index', async (signal) => {
      setReply(null)
      setMessage('')

      const result = await apiRequest(
        `/api/knowledge-bases/${knowledgeBaseId}/index`,
        {
          token,
          method: 'POST',
          signal,
        },
      )

      if (signal.aborted) return

      if (
        !result
        || !Number.isInteger(result.documents)
        || !Number.isInteger(result.chunks)
      ) {
        throw new Error('索引接口返回格式异常，请刷新后确认')
      }

      setMessage(
        `索引建立成功：${result.documents} 个文档，`
        + `${result.chunks} 个片段，现在可以进行知识库问答。`,
      )
    })
  }

    async function handleAsk(event) {
    event.preventDefault()
    if (busy) return

    const text = question.trim()

    if (!text) {
      setError('请输入问题')
      return
    }

    await runTask('ask', async (signal) => {
      setReply(null)

      const result = await apiRequest(
        `/api/knowledge-bases/${knowledgeBaseId}/chat`,
        {
          token,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ question: text }),
          signal,
        },
      )

      if (signal.aborted) return

      if (
        !result
        || result.knowledge_base_id !== knowledgeBaseId
        || typeof result.answer !== 'string'
        || !Array.isArray(result.citations)
      ) {
        throw new Error('问答接口返回格式异常')
      }

      setReply({
        ...result,
        question: text,
      })
    })
  }

  return (
    <section className="panel">
      <h2>知识库文档</h2>

      <form onSubmit={handleUpload}>
        <label htmlFor={`document-file-${knowledgeBaseId}`}>
          上传文件
        </label>

        <input
          ref={fileInputRef}
          id={`document-file-${knowledgeBaseId}`}
          type="file"
          accept=".txt,.md,.pdf"
          disabled={Boolean(busy)}
          onChange={(event) => {
            setSelectedFile(event.target.files?.[0] || null)
            setError('')
          }}
        />

        <button
          type="submit"
          disabled={Boolean(busy) || !selectedFile}
        >
          {busy === 'upload' ? '正在上传…' : '上传到当前知识库'}
        </button>
      </form>

      <p className="hint">
        支持 UTF-8 TXT、Markdown 和文字版 PDF，单个文件最多 10 MiB。
      </p>

      <button
        type="button"
        disabled={Boolean(busy)}
        onClick={() => runTask('refresh', loadDocuments)}
      >
        {busy === 'loading' || busy === 'refresh'
          ? '正在读取…'
          : '刷新文档列表'}
      </button>

            <div style={{ marginTop: 12 }}>
        <button
          type="button"
          onClick={handleIndex}
          disabled={Boolean(busy) || total === 0}
        >
          {busy === 'index' ? '正在建立索引，请稍候…' : '建立 / 重建索引'}
        </button>
      </div>

      <p className="hint">
        上传或删除文档后需要重新建立索引。
        建立期间请不要切换知识库或重复点击。
      </p>

      <p className="hint">
        共 {total} 个文档，当前显示最近 {documents.length} 个，最多 20 个。
      </p>

      {documents.length === 0 && !busy && !error && (
        <p>当前知识库还没有文档。</p>
      )}

      <ul className="document-list">
        {documents.map((document) => (
          <li key={document.id} className="document-row">
            <div className="document-info">
              <strong>{document.original_name}</strong>
              <div className="hint">
                ID：{document.id} ·
                大小：{(document.size / 1024).toFixed(1)} KB
              </div>
            </div>

            <button
              type="button"
              disabled={Boolean(busy)}
              onClick={() => handleDelete(document)}
            >
              {busy === `delete-${document.id}` ? '正在删除…' : '删除'}
            </button>
          </li>
        ))}
      </ul>

            <section className="panel">
        <h2>当前知识库问答</h2>

        <form onSubmit={handleAsk}>
          <label htmlFor={`knowledge-question-${knowledgeBaseId}`}>
            你的问题
          </label>

          <textarea
            id={`knowledge-question-${knowledgeBaseId}`}
            className="knowledge-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="例如：OCR是什么？请根据文件解释。"
            rows={3}
            maxLength={500}
            required
            disabled={Boolean(busy)}
          />

          <button
            type="submit"
            disabled={Boolean(busy) || !question.trim() || total === 0}
          >
            {busy === 'ask' ? '正在检索并生成回答…' : '发送问题'}
          </button>
        </form>

        <p className="hint">
          仅检索当前所选知识库。文档变化后，请先重新建立索引。
        </p>

        {reply && (
          <div aria-live="polite">
            <p>
              <strong>问题：</strong>
              {reply.question}
            </p>

            <p className="knowledge-answer">
              <strong>回答：</strong>
              {reply.answer}
            </p>

            {reply.citations.length > 0 && (
              <details>
                <summary>检索片段（请核对是否支持回答）</summary>

                {reply.citations.map((citation, index) => (
                  <div
                    className="panel"
                    key={`${citation.document_id}-${citation.chunk_index}-${index}`}
                  >
                    <strong>
                      {citation.source}
                      {citation.page != null && ` · 第 ${citation.page} 页`}
                      {citation.chunk_index != null
                        && ` · 第 ${citation.chunk_index} 段`}
                    </strong>

                    <p className="hint">
                      文档 ID：{citation.document_id}
                    </p>

                    <p className="knowledge-answer">
                      {citation.excerpt}
                    </p>
                  </div>
                ))}
              </details>
            )}
          </div>
        )}
      </section>

      {message && <p className="status" role="status">{message}</p>}

      {error && (
        <p className="account-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}