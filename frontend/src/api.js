export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiRequest(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers)

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    const detail = data?.detail

    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join('；')
      : typeof detail === 'string'
        ? detail
        : `请求失败（${response.status}）`

    throw new ApiError(message, response.status)
  }

  return data
}

export function login(username, password) {
  return apiRequest('/api/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      username,
      password,
    }),
  })
}

export function getCurrentUser(token) {
  return apiRequest('/api/auth/me', { token })
}

export function getKnowledgeBases(token) {
  return apiRequest('/api/knowledge-bases?page=1&size=20', {
    token,
  })
}