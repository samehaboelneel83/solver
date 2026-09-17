const TOKEN_KEY = "solver_token";

export function setToken(token: string | null) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage unavailable (private mode, etc.) — token just won't persist
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Encodes a pathname + search as a `next` redirect param value. */
export function currentLocationParam(pathname: string, search: string): string {
  return encodeURIComponent(pathname + search);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, { ...options, headers });

  if (response.status === 401) {
    setToken(null);
    const { pathname, search } = window.location;
    if (pathname !== "/login") {
      const next = currentLocationParam(pathname, search);
      window.location.href = `/login?reason=expired&next=${next}`;
    }
    throw new ApiError(401, "unauthorized");
  }

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body || response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password });
  const response = await fetch("/api/auth/login", { method: "POST", body });
  if (!response.ok) {
    throw new ApiError(response.status, "invalid credentials");
  }
  const data = await response.json();
  setToken(data.access_token);
  return data.access_token as string;
}
