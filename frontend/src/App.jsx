import { useEffect, useState } from 'react'

function App() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('请选择 .txt、.md 或文字版 PDF 文件')
  const [indexStatus, setIndexStatus] = useState('请先上传文件并建立索引')
  const [uploading, setUploading] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [files, setFiles] = useState([])
  const [filesStatus, setFilesStatus] = useState('正在读取已上传文件...')
  const [filesLoading, setFilesLoading] = useState(false)
  const [deletingFile, setDeletingFile] = useState('')

  const [question, setQuestion] = useState('')
  const [searchSource, setSearchSource] = useState('')
  const [messages, setMessages] = useState([])
  const [asking, setAsking] = useState(false)
  const [chatError, setChatError] = useState('')
  const [history, setHistory] = useState([])
  const [historyStatus, setHistoryStatus] = useState('正在读取历史记录...')
  const [historyLoading, setHistoryLoading] = useState(false)

  useEffect(() => {
    loadHistory()
    loadFiles()
  }, [])

  function formatFileSize(size) {
    if (size < 1024) return `${size} B`
    return `${(size / 1024).toFixed(1)} KB`
  }

  async function loadFiles() {
    setFilesLoading(true)

    try {
      const response = await fetch('/api/files')
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '读取文件失败')
      }

      setFiles(data)
      setFilesStatus(data.length === 0 ? '还没有上传知识库文件' : `共 ${data.length} 个文件`)
    } catch (error) {
      setFilesStatus(`读取失败：${error.message}`)
    } finally {
      setFilesLoading(false)
    }
  }

  async function handleUpload() {
    if (!selectedFile) {
      setUploadStatus('请先选择一个 .txt 或 .md 文件')
      return
    }

    const formData = new FormData()
    formData.append('file', selectedFile)

    setUploading(true)
    setUploadStatus('正在上传...')

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '上传失败')
      }

      setUploadStatus(`${data.filename} 上传成功，请点击“建立 / 重建索引”`)
      setSelectedFile(null)
      await loadFiles()
    } catch (error) {
      setUploadStatus(`上传失败：${error.message}`)
    } finally {
      setUploading(false)
    }
  }

  async function handleIndex() {
    setIndexing(true)
    setIndexStatus('正在建立索引...')

    try {
      const response = await fetch('/api/index', {
        method: 'POST',
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '建立索引失败')
      }

      setIndexStatus(`完成：${data.documents} 个文档，${data.chunks} 个片段`)
    } catch (error) {
      setIndexStatus(`建立索引失败：${error.message}`)
    } finally {
      setIndexing(false)
    }
  }

  async function handleDeleteFile(filename) {
    const confirmed = window.confirm(`确定删除“${filename}”吗？删除后会同步更新向量索引。`)
    if (!confirmed) return

    setDeletingFile(filename)

    try {
      const response = await fetch(`/api/files/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '删除文件失败')
      }

      if (searchSource === filename) {
        setSearchSource('')
      }
      if (selectedFile?.name === filename) {
        setSelectedFile(null)
      }
      await loadFiles()
    } catch (error) {
      setFilesStatus(`删除失败：${error.message}`)
    } finally {
      setDeletingFile('')
    }
  }

  async function loadHistory() {
  setHistoryLoading(true)

  try {
    const response = await fetch('/api/history')
    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || '读取历史记录失败')
    }

    setHistory(data)
    setHistoryStatus(
      data.length === 0
        ? '暂无历史记录'
        : `显示最近 ${data.length} 条历史记录（最多 20 条）`
    )
  } catch (error) {
    setHistoryStatus(`读取失败：${error.message}`)
  } finally {
    setHistoryLoading(false)
  }
 }

    async function handleAsk(event) {
    event.preventDefault()
    if (asking) return

    const text = question.trim()

    if (!text) {
      setChatError('请输入问题后再发送')
      return
    }

    const assistantIndex = messages.length + 1

    // 后续收到的数据，都更新这一条回答。
    function updateAnswer(fields) {
      setMessages((previous) =>
        previous.map((message, index) =>
          index === assistantIndex
            ? { ...message, ...fields }
            : message
        )
      )
    }

    setChatError('')
    setQuestion('')
    setAsking(true)

    setMessages((previous) => [
      ...previous,
      { role: 'user', content: text },
      {
        role: 'assistant',
        answer: '',
        sources: [],
        citations: [],
      },
    ])

    let reader
    let answer = ''
    let completed = false

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: text,
          source: searchSource || null,
        }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || '提问失败')
      }

      if (!response.body) {
        throw new Error('浏览器未能读取响应数据流')
      }

      reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      function handleLine(line) {
        if (!line.trim()) return

        const data = JSON.parse(line)

        if (data.type === 'metadata') {
          updateAnswer({
            sources: data.sources || [],
            citations: data.citations || [],
          })
        } else if (data.type === 'token') {
          answer += data.content
          updateAnswer({ answer })
        } else if (data.type === 'done') {
          answer = data.answer
          completed = true
          updateAnswer({
            answer,
            sources: data.sources || [],
            citations: data.citations || [],
          })
        } else if (data.type === 'error') {
          throw new Error(data.message || '回答生成失败')
        }
      }

      while (true) {
        const { value, done } = await reader.read()

        if (done) {
          buffer += decoder.decode()
          break
        }

        // 中文字符和 JSON 行可能被拆到不同网络数据包中。
        buffer += decoder.decode(value, { stream: true })

        let newlineIndex = buffer.indexOf('\n')

        while (newlineIndex !== -1) {
          handleLine(buffer.slice(0, newlineIndex))
          buffer = buffer.slice(newlineIndex + 1)
          newlineIndex = buffer.indexOf('\n')
        }
      }

      if (buffer.trim()) {
        handleLine(buffer)
      }

      if (!completed) {
        throw new Error('连接提前结束，回答可能不完整')
      }

      await loadHistory()
    } catch (error) {
      updateAnswer({
        answer: answer
          ? `${answer}\n\n【回答未正常完成：${error.message}】`
          : `请求失败：${error.message}`,
      })
    } finally {
      if (reader) {
        await reader.cancel().catch(() => undefined)
        reader.releaseLock()
      }

      setAsking(false)
    }
  }

  return (
    <main className="page">
      <section className="card">
        <p className="eyebrow">AI · PYTHON · RAG</p>
        <h1>校园知识库助手</h1>
        <p className="subtitle">React + FastAPI + LangChain + Chroma</p>

        <section className="panel">
          <h2>上传知识库文件</h2>
          <p className="hint">
  支持 UTF-8 编码的 .txt、.md，以及文字版 PDF；暂不支持加密 PDF 和纯扫描件
</p>

          <input
            type="file"
            accept=".txt,.md,.pdf"
            onChange={(event) => setSelectedFile(event.target.files[0] || null)}
          />

          <button onClick={handleUpload} disabled={uploading}>
            {uploading ? '上传中...' : '上传文件'}
          </button>

          <p className="status">{uploadStatus}</p>
        </section>

        <section className="panel">
          <details>
            <summary>知识库文件</summary>
         
            <div className="history-title">
            
              <button onClick={loadFiles} disabled={filesLoading || Boolean(deletingFile)}>
              {filesLoading ? '刷新中...' : '刷新列表'}
              </button>
            </div>
          

          <p className="status">{filesStatus}</p>

          {files.length > 0 && (
            <div className="file-list">
              {files.map((file) => (
                <article className="file-item" key={file.name}>
                  <div>
                    <strong>{file.name}</strong>
                    <p>{formatFileSize(file.size)} · {file.updated_at}</p>
                  </div>
                  <button
                    className="danger-button"
                    onClick={() => handleDeleteFile(file.name)}
                    disabled={Boolean(deletingFile)}
                  >
                    {deletingFile === file.name ? '删除中...' : '删除'}
                  </button>
                </article>
              ))}
            </div>
           
          )}
         </details>  
        </section>

        <section className="panel">
          <h2>建立向量索引</h2>

          <button onClick={handleIndex} disabled={indexing}>
            {indexing ? '建立中...' : '建立 / 重建索引'}
          </button>

          <p className="status">{indexStatus}</p>
        </section>

        <section className="panel">
          <h2>知识库问答</h2>
          <label>
            检索范围：
            <select
              value={searchSource}
              onChange={(event) => setSearchSource(event.target.value)}
              disabled={asking || filesLoading}
            >
              <option value="">全部文件</option>
              {files.map((file) => (
                <option key={file.name} value={file.name}>
                  {file.name}
                </option>
              ))}
            </select>
          </label>

          <div className="chat-list">
            {messages.length === 0 && (
              <p className="empty-message">
                输入问题后，我会依据知识库内容回答。
              </p>
            )}

            {messages.map((message, index) => (
              <article
                className={`message ${message.role}`}
                key={`${message.role}-${index}`}
              >
                {message.role === 'user' ? (
                  <p>{message.content}</p>
                ) : (
                  <>
                    <p className="answer">{message.answer}</p>

                                        {message.sources.length > 0 && (
                      <p className="sources">
                        来源：{message.sources.join('、')}
                      </p>
                    )}


                    {message.citations.length > 0 && (
                      <div className="citations">
                        <p>检索片段（请核对是否支持回答）：</p>

                        {message.citations.map((citation, citationIndex) => (
                          <div
                            className="citation"
                            key={`${citation.source}-${citation.chunk_index}-${citationIndex}`}
                          >
                            <strong>
                              {citation.source}
                              {citation.page != null && ` · 第 ${citation.page} 页`}
                              {` · 第 ${citation.chunk_index} 段`}
                            </strong>
                            <p>{citation.excerpt}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </article>
            ))}

            {asking && (
              <p className="loading-message">正在查询知识库...</p>
            )}
          </div>

          <form className="chat-form" onSubmit={handleAsk}>
            <input
              type="text"
              value={question}
              placeholder="输入一个关于知识库的问题..."
              onChange={(event) => setQuestion(event.target.value)}
              disabled={asking}
            />

            <button type="submit" disabled={asking}>
              {asking ? '查询中...' : '发送'}
            </button>
          </form>
          {chatError && (
                 <p className="error-message">{chatError}</p>
          )}
        </section>
        <section className="panel">
    
     <details>

    
       <summary>历史记录</summary>

       <button onClick={loadHistory} disabled={historyLoading}>
         {historyLoading ? '刷新中...' : '刷新记录'}
       </button>
       
  
   
  <p className="status">{historyStatus}</p>

  {history.length === 0 ? (
    <p className="empty-message">还没有历史记录。</p>
  ) : (
    <div className="history-list">
      {history.map((item) => (
        <article className="history-item" key={item.id}>
          <p className="history-time">{item.created_at}</p>

          <p>
            <strong>问：</strong>
            {item.question}
          </p>

          <p>
            <strong>答：</strong>
            {item.answer}
          </p>

                    <p className="history-sources">
            检索范围：
            {item.search_source == null
              ? '未记录（旧记录）'
              : item.search_source === ''
                ? '全部文件'
                : item.search_source}
          </p>

          <p className="history-sources">
            检索来源：{item.sources.join('、')}
          </p>

          {(item.citations || []).length > 0 && (
            <details>
              <summary>检索片段（请核对是否支持回答）</summary>

              {item.citations.map((citation, index) => (
                <div className="citation" key={`${item.id}-${index}`}>
                  <strong>
                    {citation.source}
                    {citation.page != null && ` · 第 ${citation.page} 页`}
                    {` · 第 ${citation.chunk_index} 段`}
                  </strong>
                  <p>{citation.excerpt}</p>
                </div>
              ))}
            </details>
          )}
        </article>
      ))}
    </div>
  )}
  </details> 
 </section>
</section>      
    </main>
  )
} 

export default App
