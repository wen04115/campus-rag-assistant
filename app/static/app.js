const messages = document.querySelector('#messages')
const status = document.querySelector('#status')
const fileInput = document.querySelector('#knowledge-file')
const uploadStatus = document.querySelector('#upload-status')

function addMessage(text, className) {
  const message = document.createElement('article')

  message.className = className
  message.textContent = text

  messages.append(message)
  messages.scrollTop = messages.scrollHeight

  return message
}

document.querySelector('#upload').onclick = async () => {
  const file = fileInput.files[0]

  if (!file) {
    uploadStatus.textContent = '请先选择一个 .txt、.md 或文字版 PDF 文件re'
    return
  }

  const formData = new FormData()
  formData.append('file', file)

  uploadStatus.textContent = '正在上传…'

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail)
    }

    uploadStatus.textContent =
      `${data.filename} 上传成功，请点击“建立 / 重建索引”`

    fileInput.value = ''
  } catch (error) {
    uploadStatus.textContent = `上传失败：${error.message}`
  }
}

document.querySelector('#index').onclick = async () => {
  status.textContent = '正在生成向量…'

  try {
    const response = await fetch('/api/index', {
      method: 'POST',
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail)
    }

    status.textContent =
      `完成：${data.documents} 个文档，${data.chunks} 个片段`
  } catch (error) {
    status.textContent = `失败：${error.message}`
  }
}

document.querySelector('#form').onsubmit = async (event) => {
  event.preventDefault()

  const input = document.querySelector('#question')
  const question = input.value.trim()

  if (!question) {
    return
  }

  addMessage(question, 'user')
  input.value = ''

  const pendingMessage = addMessage('正在检索并生成回答…', 'bot')

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
      }),
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail)
    }

    pendingMessage.textContent =
      `${data.answer}\n\n来源：${data.sources.join('、')}`
    } catch (error) {
    pendingMessage.textContent = `请求失败：${error.message}`
  }
}