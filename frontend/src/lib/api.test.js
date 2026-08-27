import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "./api.js";

function mockFetch(response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  globalThis.fetch = fetchMock;
  return fetchMock;
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("read endpoints", () => {
  it("lists samples", async () => {
    const fetchMock = mockFetch(ok(["bert.pdf"]));
    await expect(api.listSamples()).resolves.toEqual(["bert.pdf"]);
    expect(fetchMock).toHaveBeenCalledWith("/api/reader/samples", {});
  });

  it("gets a paper by id", async () => {
    const fetchMock = mockFetch(ok({ paper_id: "abc" }));
    await api.getPaper("abc");
    expect(fetchMock).toHaveBeenCalledWith("/api/reader/papers/abc", {});
  });

  it("builds a stable pdf url", () => {
    expect(api.pdfUrl("abc")).toBe("/api/reader/papers/abc/pdf");
  });
});

describe("parse endpoints", () => {
  it("POSTs to parse a sample", async () => {
    const fetchMock = mockFetch(ok({ paper_id: "abc" }));
    await api.parseSample("bert.pdf");
    expect(fetchMock).toHaveBeenCalledWith("/api/reader/papers/samples/bert.pdf", {
      method: "POST",
    });
  });

  it("escapes a sample name so it cannot alter the path", async () => {
    const fetchMock = mockFetch(ok({}));
    await api.parseSample("../secrets.pdf");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/reader/papers/samples/..%2Fsecrets.pdf",
    );
  });

  it("uploads a file as multipart form data", async () => {
    const fetchMock = mockFetch(ok({ paper_id: "abc" }));
    const file = new File([new Uint8Array([1, 2])], "paper.pdf", {
      type: "application/pdf",
    });
    await api.uploadPaper(file);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/reader/papers");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect(options.body.get("file")).toBe(file);
  });
});

describe("error handling", () => {
  it("surfaces the backend's detail message", async () => {
    mockFetch({
      ok: false,
      status: 422,
      json: async () => ({ detail: "notes.txt is not a PDF" }),
    });
    await expect(api.listSamples()).rejects.toThrow("notes.txt is not a PDF");
  });

  it("keeps a status-based message when the body is not JSON", async () => {
    mockFetch({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    });
    await expect(api.listSamples()).rejects.toThrow("Request failed (500)");
  });

  it("explains an unreachable backend", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.listSamples()).rejects.toThrow(/Is uvicorn running\?/);
  });

  it("carries the HTTP status on the error", async () => {
    mockFetch({ ok: false, status: 404, json: async () => ({ detail: "gone" }) });
    await expect(api.getPaper("x")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
