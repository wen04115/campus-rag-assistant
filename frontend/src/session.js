const TOKEN_KEY = 'campus-rag.access-token'

export function readSavedToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function saveToken(token) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
    return true
  } catch {
    return false
  }
}

export function clearSavedToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // Storage may be unavailable; callers still clear their in-memory session.
  }
}
