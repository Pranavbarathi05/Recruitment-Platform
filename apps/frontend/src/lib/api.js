/**
 * API Client
 *
 * All communication with the backend goes through this module.
 * The frontend NEVER communicates directly with Supabase.
 *
 * The API base URL defaults to same-origin (empty string), which works
 * when the Vite dev server proxies /auth/* and /admin/* to the FastAPI backend,
 * or when both are served from the same origin in production.
 *
 * For local development with separate ports, set VITE_API_URL (e.g. http://localhost:8000).
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

// ---------------------------------------------------------------------------
// Storage helpers for auth tokens
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'dsc_access_token';
const REFRESH_KEY = 'dsc_refresh_token';

export function getStoredAccessToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredRefreshToken() {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function storeTokens(accessToken, refreshToken) {
  try {
    localStorage.setItem(TOKEN_KEY, accessToken);
    if (refreshToken) {
      localStorage.setItem(REFRESH_KEY, refreshToken);
    }
  } catch {
    // localStorage unavailable — degrade gracefully
  }
}

export function clearTokens() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Generic fetch wrapper
// ---------------------------------------------------------------------------

/**
 * Make an API request.
 *
 * @param {string} path - API path (e.g. "/auth/login")
 * @param {object} options - fetch() options (method, body, headers, etc.)
 * @param {object} extraHeaders - Additional headers to merge
 * @returns {Promise<any>} Parsed JSON response
 */
export async function apiRequest(path, options = {}, extraHeaders = {}) {
  const url = `${API_BASE}${path}`;
  const token = getStoredAccessToken();

  const headers = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const resp = await fetch(url, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  });

  // Handle 401 — attempt token refresh
  if (resp.status === 401 && token) {
    const refreshed = await attemptTokenRefresh();
    if (refreshed) {
      // Retry the original request with the new token
      const retryHeaders = {
        ...headers,
        'Authorization': `Bearer ${getStoredAccessToken()}`,
      };
      const retryResp = await fetch(url, {
        ...options,
        headers: {
          ...retryHeaders,
          ...options.headers,
        },
      });
      if (!retryResp.ok) {
        const err = await retryResp.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${retryResp.status}`);
      }
      return retryResp.json();
    } else {
      // Refresh failed — clear tokens and throw
      clearTokens();
      throw new Error('Session expired. Please log in again.');
    }
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  // Some endpoints may return 204 No Content
  if (resp.status === 204) return null;

  return resp.json();
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

let refreshPromise = null;

async function attemptTokenRefresh() {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return false;

  // Deduplicate concurrent refresh attempts
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const url = `${API_BASE}/auth/refresh`;
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!resp.ok) return false;

      const data = await resp.json();
      if (data.session?.access_token) {
        storeTokens(data.session.access_token, data.session.refresh_token);
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// ---------------------------------------------------------------------------
// Auth API calls
// ---------------------------------------------------------------------------

export async function authSignup({ email, password, fullName, usn, semester, branch }) {
  const data = await apiRequest('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
      fullName,
      usn,
      semester: parseInt(semester, 10),
      branch,
    }),
  }, {
    // Signup should NOT send an existing Authorization header
    Authorization: undefined,
  });

  if (data.session?.access_token) {
    storeTokens(data.session.access_token, data.session.refresh_token);
  }

  return data;
}

export async function authLogin({ email, password }) {
  const data = await apiRequest('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }, {
    // Login should NOT send an existing Authorization header
    Authorization: undefined,
  });

  if (data.session?.access_token) {
    storeTokens(data.session.access_token, data.session.refresh_token);
  }

  return data;
}

export async function authLogout() {
  try {
    await apiRequest('/auth/logout', { method: 'POST' });
  } catch {
    // Even if the server call fails, clear local tokens
  }
  clearTokens();
}

export async function authGetMe() {
  return apiRequest('/auth/me', { method: 'GET' });
}
