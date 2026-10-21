import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest, ApiError } from './api.js'
import HistoryPanel from './HistoryPanel.jsx'

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
  const [historyVersion, setHistoryVersion] = useState(0)
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

      let reader
      let answer = ''
      let metadataSeen = false
      let completed = false

      function processLine(line) {
        if (signal.aborted || !line.trim()) return

        if (completed) {
          throw new Error('完成事件之后收到额外数据')
        }

        const event = JSON.parse(line)

        if (event.type === 'error') {
          throw new Error(event.message || '回答未完成')
        }

        if (event.type === 'metadata') {
          if (
            metadataSeen
            || event.knowledge_base_id !== knowledgeBaseId
            || !Array.isArray(event.sources)
            || !Array.isArray(event.citations)
          ) {
            throw new Error('流式来源信息异常')
          }

          metadataSeen = true

          setReply({
            knowledge_base_id: knowledgeBaseId,
            question: text,
            answer: '',
            sources: event.sources,
            citations: event.citations,
            complete: false,
          })
          return
        }

        if (!metadataSeen) {
          throw new Error('没有收到知识库来源信息')
        }

        if (event.type === 'token') {
          if (typeof event.content !== 'string') {
            throw new Error('回答片段格式异常')
          }

          answer += event.content
          const currentAnswer = answer

          setReply((previous) => (
            previous
              ? { ...previous, answer: currentAnswer }
              : previous
          ))
          return
        }

        if (event.type === 'done') {
          if (
            event.knowledge_base_id !== knowledgeBaseId
            || typeof event.answer !== 'string'
            || event.answer !== answer
            || !Array.isArray(event.sources)
            || !Array.isArray(event.citations)
          ) {
            throw new Error('完整回答校验失败')
          }

          completed = true

          setReply({
            knowledge_base_id: knowledgeBaseId,
            question: text,
            answer: event.answer,
            sources: event.sources,
            citations: event.citations,
            complete: true,
          })
          return
        }

        throw new Error('收到未知的流式事件')
      }

      try {
        const response = await fetch(
          `/api/knowledge-bases/${knowledgeBaseId}/chat/stream`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ question: text }),
            signal,
          },
        )

        if (!response.ok) {
          const data = await response.json().catch(() => null)

          throw new ApiError(
            typeof data?.detail === 'string'
              ? data.detail
              : `请求失败（${response.status}）`,
            response.status,
          )
        }

        if (
          !response.headers.get('content-type')
            ?.includes('application/x-ndjson')
        ) {
          throw new Error('服务器没有返回预期的数据流')
        }

        if (!response.body) {
          throw new Error('浏览器没有收到可读取的数据流')
        }

        reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8', { fatal: true })
        let buffer = ''

        while (true) {
          const { value, done } = await reader.read()

          if (signal.aborted) return
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          let newline
          while ((newline = buffer.indexOf('\n')) !== -1) {
            const line = buffer.slice(0, newline)
            buffer = buffer.slice(newline + 1)
            processLine(line)
          }
        }

        buffer += decoder.decode()

        if (buffer.trim()) {
          processLine(buffer)
        }

        if (!completed) {
          throw new Error('连接已结束，但未收到完成事件，回答不完整')
        }
        setHistoryVersion((previous) => previous + 1)
      } catch (requestError) {
        if (!signal.aborted) {
          setReply((previous) => (
            previous
              ? { ...previous, complete: false }
              : previous
          ))
        }

        throw requestError
      } finally {
        if (reader) {
          await reader.cancel().catch(() => undefined)
          reader.releaseLock()
        }
      }
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

      <details className="document-disclosure" key={knowledgeBaseId}>
        <summary>已上传文档（共 {total} 个，点击展开 / 收起）</summary>

        <p className="hint">
          当前列出最近 {documents.length} 个文档，最多显示 20 个。
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
      </details>

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

                        <p
              className={reply.complete ? 'status' : 'account-error'}
              role="status"
            >
              {reply.complete
                ? '回答已完成'
                : busy === 'ask'
                  ? '回答生成中，当前文字尚不是完整结论…'
                  : '回答未完成，请勿将部分文字当作完整结论。'}
            </p>

            <p className="knowledge-answer">
              <strong>回答：</strong>
              {reply.answer || (
                busy === 'ask'
                  ? '等待模型返回首段文字…'
                  : '未收到回答文字'
              )}
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

      <HistoryPanel
        key={`${knowledgeBaseId}:${historyVersion}`}
        token={token}
        knowledgeBaseId={knowledgeBaseId}
        onUnauthorized={onUnauthorized}
      />

      {message && <p className="status" role="status">{message}</p>}

      {error && (
        <p className="account-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
