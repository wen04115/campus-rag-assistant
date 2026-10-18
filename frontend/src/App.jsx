import { useEffect, useState } from 'react'

function App() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('请选择 .txt 或 .md 文件')
  const [indexStatus, setIndexStatus] = useState('请先上传文件并建立索引')
  const [uploading, setUploading] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [files, setFiles] = useState([])
  const [filesStatus, setFilesStatus] = useState('正在读取已上传文件...')
  const [filesLoading, setFilesLoading] = useState(false)
  const [deletingFile, setDeletingFile] = useState('')

  const [question, setQuestion] = useState('')
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

      setIndexStatus(data.message)
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
    setHistoryStatus(`共 ${data.length} 条历史记录`)
  } catch (error) {
    setHistoryStatus(`读取失败：${error.message}`)
  } finally {
    setHistoryLoading(false)
  }
 }

  async function handleAsk(event) {
    event.preventDefault()

    const text = question.trim()

    if (!text) {
      setChatError('请输入问题后再发送')
      return
    }

setChatError('')

    setMessages((oldMessages) => [
      ...oldMessages,
      { role: 'user', content: text },
    ])

    setQuestion('')
    setAsking(true)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: text,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '提问失败')
      }

      setMessages((oldMessages) => [
        ...oldMessages,
        {
          role: 'assistant',
          answer: data.answer,
          sources: data.sources || [],
          citations: data.citations || [],
        },
      ])
      await loadHistory()

    } catch (error) {
      setMessages((oldMessages) => [
        ...oldMessages,
        {
          role: 'assistant',
          answer: `请求失败：${error.message}`,
          sources: [],
          citations: [],
        },
      ])
    } finally {
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
          <p className="hint">仅支持 UTF-8 编码的 .txt 或 .md 文件</p>

          <input
            type="file"
            accept=".txt,.md"
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
                        <p>引用片段：</p>

                        {message.citations.map((citation, citationIndex) => (
                          <div
                            className="citation"
                            key={`${citation.source}-${citation.chunk_index}-${citationIndex}`}
                          >
                            <strong>
                              {citation.source} · 第 {citation.chunk_index} 段
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
            来源：{item.sources.join('、')}
          </p>
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
