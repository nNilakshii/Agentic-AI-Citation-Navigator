/**
 * Client for the reader API (backend Phase 1.2).
 *
 * In development, requests go to a relative /api path that Vite proxies to the
 * backend — no host to configure and no CORS in the loop. In a deployed build
 * the two halves live on different origins (the page on GitHub Pages, the API
 * on its own host), so VITE_API_BASE supplies the absolute origin at build
 * time and the backend allows it by CORS.
 */

/** Origin of the backend. Empty in dev, where the proxy handles it. */
const ORIGIN = (import.meta.env?.VITE_API_BASE ?? "").replace(/\/$/, "");

const BASE = `${ORIGIN}/api/reader`;

/** What to tell someone whose backend is not answering. */
export const UNREACHABLE =
  "Cannot reach the backend. Start it with: uvicorn app.main:app --reload --port 8000";

/**
 * Statuses a dead upstream can arrive as. The dev server proxies /api, so when
 * uvicorn is down it is *Vite* that answers — with its own plain-text 5xx, not
 * a thrown fetch. Without this the reader reports "Request failed (500)", which
 * reads like a backend bug rather than a backend that is not running.
 */
const GATEWAY_STATUSES = new Set([500, 502, 503, 504]);

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
    // No proxy in the way (a production build), so the failure surfaces here.
    throw new ApiError(UNREACHABLE, 0);
  }

  if (!response.ok) {
    let detail = null;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // Not JSON. FastAPI always answers errors as {"detail": ...}, so a
      // non-JSON 5xx did not come from the backend at all.
    }
    if (detail === null && GATEWAY_STATUSES.has(response.status)) {
      throw new ApiError(UNREACHABLE, 0);
    }
    throw new ApiError(
      detail ?? `Request failed (${response.status})`,
      response.status,
    );
  }
  return response.json();
}

/**
 * Is the backend answering?
 *
 * Used on mount so the reader can say what is wrong before the first click,
 * rather than after it.
 *
 * @returns {Promise<boolean>}
 */
export async function isBackendUp() {
  return (await fetchStatus()) !== null;
}

/**
 * The backend's health, including how many live rankings remain today.
 *
 * Returns `null` when the backend cannot be reached, so a caller can tell
 * "down" from "up but out of budget" — the two look identical to a reader
 * otherwise, and only one of them is worth waiting out.
 *
 * @returns {Promise<{status: string, rankings_left_today: number}|null>}
 */
export async function fetchStatus() {
  try {
    const response = await fetch(`${ORIGIN}/health`);
    if (!response.ok) return null;
    const body = await response.json();
    return body?.status === "ok" ? body : null;
  } catch {
    return null;
  }
}

/** Names of the PDFs in data/samples. */
export function listSamples() {
  return request(`${BASE}/samples`);
}

/**
 * Which papers already have a reading path, per goal.
 *
 * Lets the picker say which papers open instantly, before anything is
 * clicked. Shape: `[{filename, paper_id, ready: ["skim", ...]}]`.
 */
export function fetchCoverage() {
  return request(`${BASE}/coverage`);
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
