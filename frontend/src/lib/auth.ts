/**
 * JWT session token storage for the FrigoLoco frontend.
 *
 * The backend issues a bearer token from POST /api/v1/auth/login. We persist it
 * in localStorage so the session survives reloads, and the api client attaches
 * it as `Authorization: Bearer <token>` on every request. A 401 from any
 * endpoint clears it and bounces the user to /login.
 */

/** localStorage key under which the bearer token is persisted. */
export const TOKEN_STORAGE_KEY = 'frigoloco_token'

/** Return the stored bearer token, or null when the user is not signed in. */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    // localStorage can throw in private-mode / sandboxed contexts.
    return null
  }
}

/** Persist the bearer token returned by a successful login. */
export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    // Ignore storage failures; the in-memory request will still carry the header.
  }
}

/** Remove the stored bearer token (logout, or after an expired-session 401). */
export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Nothing to do if storage is unavailable.
  }
}

/** True when a token is present. Cheap guard check; does not validate the token. */
export function hasToken(): boolean {
  return getToken() !== null
}
