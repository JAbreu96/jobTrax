/**
 * Thin fetch wrapper for the /api/* routes in src/jobs_gui.py.
 *
 * Mirrors JobFields.postJSON's error semantics in src/static/job_fields.js:
 * every route returns `{error: "..."}` alongside a non-2xx status on
 * failure. That helper hands both the status and the parsed body back to its
 * caller to decide what to do (e.g. treat 409 as "blocked" rather than a
 * hard failure); these two just throw, since Phase 0's callers are TanStack
 * Query hooks that want a rejected promise to drive `isError`/`error`.
 */

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function parseBody(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

function errorMessage(body: unknown, res: Response): string {
  if (body && typeof body === "object" && "error" in body) {
    const err = (body as { error?: unknown }).error;
    if (typeof err === "string" && err) return err;
  }
  return `Request failed with status ${res.status} ${res.statusText}`;
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(errorMessage(body, res), res.status, body);
  }
  return body as T;
}

export async function postJSON<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(errorMessage(body, res), res.status, body);
  }
  return body as T;
}
