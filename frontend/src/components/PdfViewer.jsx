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

import CitationLayer from "./CitationLayer.jsx";
import HighlightLayer from "./HighlightLayer.jsx";
import { targetsOnPage } from "../lib/citations.js";
import { bboxesOnPage, scaleFor } from "../lib/geometry.js";

// Bundled with the app rather than fetched from a CDN, so the reader works
// offline and cannot be broken by a third-party host.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/** Horizontal padding to leave around the page, in pixels. */
const GUTTER = 32;

/** Room left above a scrolled-to passage, in pixels, so it is not flush. */
const SCROLL_MARGIN = 72;

export default function PdfViewer({
  fileUrl,
  highlightSentences,
  scrollToPage,
  onPageChange,
  citationGroups,
  activeCitationKey,
  onCitationClick,
  highlightVariant = "path",
}) {
  const containerRef = useRef(null);
  const pageRefs = useRef(new Map());
  const [pageCount, setPageCount] = useState(0);
  const [width, setWidth] = useState(0);
  const [originalWidth, setOriginalWidth] = useState(0);
  const [originalHeight, setOriginalHeight] = useState(0);
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
    const viewport = firstPage.getViewport({ scale: 1 });
    setOriginalWidth(viewport.width);
    // Page 1's height too: every page placeholder is sized before it renders,
    // so the layout does not shift as pages arrive and a scroll to a passage
    // deep in the paper lands where it was aimed (2.12).
    setOriginalHeight(viewport.height);
  }, []);

  // Scroll the requested page into view when the outline is clicked. Keyed on
  // the request object, not the page number, so clicking the same section twice
  // scrolls back to it rather than doing nothing. A request with `y` (PDF
  // points from the page top) scrolls to that spot on the page — a passage
  // rather than its page (2.12).
  //
  // Each request is applied once. One made before the PDF is sized waits for
  // it; after that, a resize (the cited pane opening beside this viewer) must
  // not drag the reader back to a place they have since scrolled away from.
  const appliedScroll = useRef(null);
  useEffect(() => {
    if (!scrollToPage || appliedScroll.current === scrollToPage) return;
    const node = pageRefs.current.get(scrollToPage.page);
    const container = containerRef.current;
    if (scrollToPage.y === undefined || !container?.scrollTo) {
      if (!node) return;
      node.scrollIntoView({ behavior: "smooth", block: "start" });
      appliedScroll.current = scrollToPage;
      return;
    }
    if (!node || !width || !originalWidth) return; // not sized yet: wait
    const pageTop =
      container.scrollTop +
      node.getBoundingClientRect().top -
      container.getBoundingClientRect().top;
    container.scrollTo({
      top: Math.max(
        0,
        pageTop + scrollToPage.y * scaleFor(width, originalWidth) - SCROLL_MARGIN,
      ),
      behavior: "smooth",
    });
    appliedScroll.current = scrollToPage;
  }, [scrollToPage, pageCount, width, originalWidth]);

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
            style={
              originalHeight && scale
                ? { minHeight: `${Math.round(originalHeight * scale)}px` }
                : undefined
            }
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
              variant={highlightVariant}
            />
            <CitationLayer
              targets={targetsOnPage(citationGroups, index)}
              scale={scale}
              activeKey={activeCitationKey}
              onSelect={onCitationClick}
            />
            <span className="viewer__page-number">{index + 1}</span>
          </div>
        ))}
      </Document>
    </div>
  );
}
