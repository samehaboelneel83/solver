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
  window.dispatchEvent(new Event("solver-auth-changed"));
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

/** Browser could not complete the request (API down, DNS, CORS, offline network). */
export class NetworkError extends Error {
  constructor(message = "The platform API could not be reached.") {
    super(message);
    this.name = "NetworkError";
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  // A form body (a file upload) sets its own multipart boundary.
  if (!(options.body instanceof URLSearchParams) && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new NetworkError();
  }

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

/** Plain-text API response (Prometheus metrics, CSV exports). */
export async function apiText(path: string): Promise<string> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new NetworkError();
  }
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
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  return response.text();
}

/** A file from the API, with the signed-in token: a template to download (queue R21). */
export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new NetworkError();
  }
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  return { blob: await response.blob(), filename };
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password });
  let response: Response;
  try {
    response = await fetch("/api/auth/login", { method: "POST", body });
  } catch {
    throw new NetworkError();
  }
  if (!response.ok) {
    // Only a refusal of the credentials is the person's to fix by retyping them.
    throw new ApiError(response.status, response.status === 401 || response.status === 400
      ? "Wrong username or password."
      : response.status === 429 ? "Too many sign-in attempts; wait a minute and try again."
        : "Signing in failed on the server; try again, and tell your administrator if it persists.");
  }
  const data = await response.json();
  setToken(data.access_token);
  return data.access_token as string;
}
