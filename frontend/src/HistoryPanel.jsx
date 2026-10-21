import { useEffect, useState } from 'react'
import { apiRequest } from './api.js'

const PAGE_SIZE = 10

export default function HistoryPanel({ token, knowledgeBaseId, onUnauthorized }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    apiRequest(
      `/api/knowledge-bases/${knowledgeBaseId}/history?page=${page}&size=${PAGE_SIZE}`,
      { token, signal },
    )
      .then((data) => {
        if (signal.aborted) return
        if (!Array.isArray(data?.items) || !Number.isInteger(data.total)) {
          throw new Error('历史列表返回格式异常')
        }
        setItems(data.items)
        setTotal(data.total)
      })
      .catch((requestError) => {
        if (signal.aborted) return
        if (requestError.status === 401) {
          onUnauthorized()
        } else {
          setError(requestError.message || '读取历史失败，请稍后刷新重试')
        }
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [token, knowledgeBaseId, page, refresh, onUnauthorized])

  function changePage(next) {
    setError('')
    setLoading(true)
    setItems([])
    setPage(next)
  }

  return (
    <details className="panel history-disclosure" aria-label="当前知识库问答历史">
      <summary>
        问答历史（{loading ? '正在读取…' : error ? '读取失败' : `共 ${total} 条`}，点击展开 / 收起）
      </summary>
      <p className="hint">
        仅显示当前知识库已保存的完整回答。引用是回答时的快照，原文档可能已修改或删除。
        历史不会自动作为下一次提问的上下文。
      </p>
      <button
        type="button"
        disabled={loading}
        onClick={() => {
          setError('')
          setLoading(true)
          setItems([])
          setRefresh((previous) => previous + 1)
        }}
      >
        {loading ? '正在读取历史…' : '刷新问答历史'}
      </button>
      {error && <p className="account-error" role="alert">{error}</p>}
      {!loading && !error && items.length === 0 && <p>这一页暂无问答历史。</p>}
      <div className="history-records" role="region" aria-label="本页问答历史记录" tabIndex={0}>
      {items.map((record) => (
        <details className="panel" key={record.id}>
          <summary>{record.question}</summary>
          <p className="hint">
            记录 #{record.id} · {new Date(record.created_at).toLocaleString()}
          </p>
          <p className="knowledge-answer">{record.answer}</p>
          {record.citations.map((citation, index) => (
            <blockquote key={`${citation.document_id}-${index}`}>
              <strong>{citation.source}</strong>
              {citation.page != null && ` · 第 ${citation.page} 页`}
              <p className="knowledge-answer">{citation.excerpt}</p>
            </blockquote>
          ))}
        </details>
      ))}
      </div>
      <p className="hint">共 {total} 条 · 第 {page} 页</p>
      <div className="account-toolbar">
        <button type="button" disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>
          上一页
        </button>
        <button type="button" disabled={loading || page * PAGE_SIZE >= total} onClick={() => changePage(page + 1)}>
          下一页
        </button>
      </div>
    </details>
  )
}
