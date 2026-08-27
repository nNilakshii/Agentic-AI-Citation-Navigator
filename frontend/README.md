# frontend

React reader UI (PDF view, highlights, side-by-side, chat panel). Vite + React.

## Run

The backend must be running first — the reader gets both its PDFs and its parses from it.

```bash
cd ../backend && .venv/bin/uvicorn app.main:app --reload --port 8000   # terminal 1
npm install && npm run dev                                            # terminal 2
```

Opens on <http://localhost:5173>. Proxies `/api/*` and `/health` to the backend on port 8000.

## Test

```bash
npm test          # vitest, single run
npm run test:watch
```

## What's here (tasks 1.3, 1.4)

| Path | Role |
|---|---|
| `src/App.jsx` | Reader shell — paper picker, reading goal, outline, viewer |
| `src/components/PdfViewer.jsx` | Continuous-scroll pages via `react-pdf`, one overlay per page |
| `src/components/HighlightLayer.jsx` | Draws highlight rectangles for a set of bboxes |
| `src/components/Outline.jsx` | Section list; click a heading to jump to its page |
| `src/components/PaperPicker.jsx` | Open a sample paper or a PDF from disk |
| `src/lib/geometry.js` | PDF points → CSS pixels. The whole coordinate story |
| `src/lib/outline.js` | Section depth, offset lookup, display formatting |
| `src/lib/api.js` | Reader API client |

### Highlights

The backend gives every sentence bounding boxes in PDF points with a top-left origin, which
is already the CSS orientation, so positioning a highlight is one multiply by a scale factor.
That scale is **measured** — `renderedWidth / originalWidth` — not assumed, which is what
keeps overlays aligned through zoom and window resize.

`HighlightLayer` takes bboxes and a variant, so Phase 1.7's reading path and Phase 2.12's
cited span are different *inputs* to it, not new rendering code.

### Note on jsdom

`react-pdf` needs a canvas and a worker, neither of which jsdom provides, so `PdfViewer` is
stubbed in `App.test.jsx` and the geometry is unit-tested directly. Rendering itself was
verified in Chrome — see the browser-harness entry under "Open decisions" in
`docs/architecture.md`.
