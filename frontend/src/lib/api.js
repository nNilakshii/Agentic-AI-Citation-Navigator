/**
 * Client for the reader API (backend Phase 1.2).
 *
 * Requests go to a relative /api path, which Vite proxies to the backend in
 * development — so there is no host to configure and no CORS in the loop.
 */

const BASE = "/api/reader";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export { ApiError };

/**
 * Issue a request and surface the backend's `detail` message on failure.
 *
 * FastAPI reports problems as `{"detail": "..."}`, which is far more useful to
 * show a user than "500", so it is unwrapped here rather than at each call site.
 */
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (cause) {
    throw new ApiError("Cannot reach the backend. Is uvicorn running?", 0);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Not JSON — keep the status-based message.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

/** Names of the PDFs in data/samples. */
export function listSamples() {
  return request(`${BASE}/samples`);
}

/** Summaries of every paper already parsed and cached. */
export function listPapers() {
  return request(`${BASE}/papers`);
}

/** Parse one of the local sample papers. Cached server-side after the first call. */
export function parseSample(name) {
  return request(`${BASE}/papers/samples/${encodeURIComponent(name)}`, {
    method: "POST",
  });
}

/** Upload and parse a PDF chosen from the user's disk. */
export function uploadPaper(file) {
  const body = new FormData();
  body.append("file", file);
  return request(`${BASE}/papers`, { method: "POST", body });
}

/** Fetch a previously parsed paper by id. */
export function getPaper(paperId) {
  return request(`${BASE}/papers/${paperId}`);
}

/** The URL the PDF renderer should load. Stable and immutable per paper. */
export function pdfUrl(paperId) {
  return `${BASE}/papers/${paperId}/pdf`;
}

/**
 * Build (or fetch the cached) goal-conditioned reading path for a paper.
 *
 * POST because a cache miss ranks the paper, which costs LLM quota and takes
 * seconds; the backend serves a cached path without calling the model.
 *
 * @param {string} paperId
 * @param {string} goalId - "skim" | "in-depth" | "critique"
 * @param {{force?: boolean}} [options]
 */
export function fetchReadingPath(paperId, goalId, { force = false } = {}) {
  const query = new URLSearchParams({ goal: goalId });
  if (force) query.set("force", "true");
  return request(`${BASE}/papers/${paperId}/reading-path?${query}`, {
    method: "POST",
  });
}
