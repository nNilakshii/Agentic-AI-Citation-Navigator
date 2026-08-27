/**
 * Continuous-scroll PDF viewer (task 1.3) with a highlight overlay per page.
 *
 * Pages render at a measured scale rather than an assumed one: pdf.js reports
 * each page's natural size in points, the container reports its width in pixels,
 * and the ratio is what every highlight is positioned by. That keeps overlays
 * aligned across zoom and window resize, which is the part the renderer decision
 * in docs/architecture.md was really about.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

import HighlightLayer from "./HighlightLayer.jsx";
import { bboxesOnPage, scaleFor } from "../lib/geometry.js";

// Bundled with the app rather than fetched from a CDN, so the reader works
// offline and cannot be broken by a third-party host.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/** Horizontal padding to leave around the page, in pixels. */
const GUTTER = 32;

export default function PdfViewer({
  fileUrl,
  highlightSentences,
  scrollToPage,
  onPageChange,
}) {
  const containerRef = useRef(null);
  const pageRefs = useRef(new Map());
  const [pageCount, setPageCount] = useState(0);
  const [width, setWidth] = useState(0);
  const [originalWidth, setOriginalWidth] = useState(0);
  const [error, setError] = useState(null);

  // Track the container width so pages re-render at the right size on resize.
  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return undefined;

    const measure = () => setWidth(Math.max(0, element.clientWidth - GUTTER));
    measure();

    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [fileUrl]);

  const handleLoad = useCallback(async (pdf) => {
    setError(null);
    setPageCount(pdf.numPages);
    // Page 1's natural width defines the scale for the whole document; papers
    // are uniform, and a mixed-size document would only mis-scale the outliers.
    const firstPage = await pdf.getPage(1);
    setOriginalWidth(firstPage.getViewport({ scale: 1 }).width);
  }, []);

  // Scroll the requested page into view when the outline is clicked. Keyed on
  // the request object, not the page number, so clicking the same section twice
  // scrolls back to it rather than doing nothing.
  useEffect(() => {
    if (!scrollToPage) return;
    const node = pageRefs.current.get(scrollToPage.page);
    node?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [scrollToPage]);

  // Report which page is in view, so the outline can show where the reader is.
  useEffect(() => {
    const element = containerRef.current;
    if (!element || !pageCount || typeof IntersectionObserver === "undefined") {
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) {
          onPageChange?.(Number(visible.target.dataset.pageIndex));
        }
      },
      { root: element, threshold: [0.1, 0.5] },
    );
    pageRefs.current.forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, [pageCount, onPageChange]);

  if (!fileUrl) {
    return (
      <div className="viewer viewer--empty" ref={containerRef}>
        <p>Choose a paper to start reading.</p>
      </div>
    );
  }

  const scale = scaleFor(width, originalWidth);

  return (
    <div className="viewer" ref={containerRef} data-testid="pdf-viewer">
      <Document
        file={fileUrl}
        onLoadSuccess={handleLoad}
        onLoadError={(cause) => setError(cause?.message ?? "Could not load the PDF.")}
        loading={<p className="viewer__status">Loading the PDF…</p>}
        error={<p className="viewer__status viewer__status--error">{error}</p>}
      >
        {Array.from({ length: pageCount }, (_, index) => (
          <div
            className="viewer__page"
            key={index}
            data-page-index={index}
            data-testid={`page-${index}`}
            ref={(node) => {
              if (node) pageRefs.current.set(index, node);
              else pageRefs.current.delete(index);
            }}
          >
            <Page
              pageNumber={index + 1}
              width={width || undefined}
              renderAnnotationLayer={false}
            />
            <HighlightLayer
              bboxes={bboxesOnPage(highlightSentences, index)}
              scale={scale}
            />
            <span className="viewer__page-number">{index + 1}</span>
          </div>
        ))}
      </Document>
    </div>
  );
}
