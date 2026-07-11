import { ApiError, type ProblemDetail } from "./errors";

const BASE_URL =
  process.env.NEXT_PUBLIC_CRATE_API_URL ?? "http://localhost:8200";

/**
 * Optional bearer-token source for API requests. The Clerk auth root
 * registers its session-token getter here; in dev auth mode nothing is
 * registered and requests go out bare (the API resolves its dev user).
 */
type AuthTokenProvider = () => Promise<string | null>;

let authTokenProvider: AuthTokenProvider | null = null;

export function setAuthTokenProvider(provider: AuthTokenProvider | null) {
  authTokenProvider = provider;
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  params?: Record<string, string | string[] | number | boolean | undefined>;
  body?: unknown;
  signal?: AbortSignal;
}

interface BaseResponse<T> {
  message?: string;
  data: T;
  _links?: Record<string, { href: string }>;
}

async function parseErrorResponse(
  response: Response,
  method: HttpMethod,
  endpoint: string,
): Promise<ApiError> {
  let problem: ProblemDetail | undefined;
  try {
    const body = await response.json();
    // The API may return an RFC 7807 problem detail directly or a bare detail.
    if (body.title && body.status) {
      problem = body as ProblemDetail;
    } else if (body.detail) {
      problem = {
        title: body.title ?? response.statusText,
        status: response.status,
        detail: body.detail,
        error_code: body.error_code,
      };
    }
  } catch {
    // Response body not JSON — fall through to the status-line fallback.
  }

  // Fallback message cites the method, path, and HTTP status — never a
  // friendly paraphrase. Server-provided `detail` wins when present.
  const fallback = `${method} ${endpoint} — ${response.status} ${response.statusText || "HTTP error"}`;

  return new ApiError(problem?.detail ?? fallback, response.status, {
    problem,
  });
}

export async function request<T>(
  method: HttpMethod,
  endpoint: string,
  options?: RequestOptions,
): Promise<T> {
  const url = buildUrl(`${BASE_URL}${endpoint}`, options?.params);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authTokenProvider) {
    const token = await authTokenProvider();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: options?.body ? JSON.stringify(options.body) : undefined,
      signal: options?.signal,
    });
  } catch (error) {
    const cause = error instanceof Error ? error.message : "unknown";
    throw new ApiError(
      `Network error: ${method} ${endpoint} unreachable at ${BASE_URL} (${cause})`,
      0,
      { isNetworkError: true },
    );
  }

  if (!response.ok) {
    throw await parseErrorResponse(response, method, endpoint);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const json = await response.json();

  // Unwrap the { data: T } envelope if present.
  if (json && typeof json === "object" && "data" in json) {
    return (json as BaseResponse<T>).data;
  }

  return json as T;
}

function buildUrl(
  base: string,
  params?: Record<string, string | string[] | number | boolean | undefined>,
): string {
  if (!params) return base;

  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const v of value) {
        searchParams.append(key, v);
      }
    } else {
      searchParams.set(key, String(value));
    }
  }

  const qs = searchParams.toString();
  return qs ? `${base}?${qs}` : base;
}
