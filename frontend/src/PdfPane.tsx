import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import type { PDFDocumentProxy, PageViewport, RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import type { Affine, BBox, PDFPage, Region, SourceRef } from './types';
import type { Dictionary } from './i18n';

GlobalWorkerOptions.workerSrc = workerUrl;

interface Props {
  projectId: string;
  page: number;
  pageInfo: PDFPage | undefined;
  zoom: number;
  region: Region | null;
  highlights: SourceRef[];
  guides: number[];
  guideMode: boolean;
  onRegion: (region: Region) => void;
  onGuide: (x: number) => void;
  t: Dictionary;
}

function corners(bbox: BBox) {
  return [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]];
}

function displayBox(viewport: PageViewport, bbox: BBox) {
  const points = corners(bbox).map(([x, y]) => viewport.convertToViewportPoint(x, y));
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  return { left: Math.min(...xs), top: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
}

function apply(matrix: Affine, x: number, y: number): [number, number] {
  return [matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]];
}

function invert(matrix: Affine, x: number, y: number): [number, number] {
  const [a, b, c, d, e, f] = matrix, det = a * d - b * c;
  return [(d * (x - e) - c * (y - f)) / det, (-b * (x - e) + a * (y - f)) / det];
}

export default function PdfPane({ projectId, page, pageInfo, zoom, region, highlights, guides, guideMode, onRegion, onGuide, t }: Props) {
  const host = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<PageViewport | null>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [width, setWidth] = useState(640), [viewport, setViewport] = useState<PageViewport | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const [drag, setDrag] = useState<{ x: number; y: number; endX: number; endY: number } | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(160, entry.contentRect.width - 48)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError(''); setDoc(null); setViewport(null);
    const task = getDocument({
      url: `/api/projects/${projectId}/source`,
      cMapUrl: '/pdf-assets/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/pdf-assets/standard_fonts/', wasmUrl: '/pdf-assets/wasm/',
    });
    task.promise.then(pdf => { if (alive) setDoc(pdf); }).catch(cause => {
      if (alive) { setError(cause instanceof Error ? cause.message : String(cause)); setLoading(false); }
    });
    return () => { alive = false; void task.destroy(); };
  }, [projectId, retry]);

  useEffect(() => {
    if (!doc) return;
    let alive = true, rendering: RenderTask | undefined;
    setLoading(true); setError(''); start.current = null; setDrag(null);
    void doc.getPage(page).then(pdfPage => {
      if (!alive || !canvas.current) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const next = pdfPage.getViewport({ scale: width / base.width * zoom });
      viewportRef.current = next; setViewport(next);
      const dpr = window.devicePixelRatio || 1;
      const target = canvas.current;
      target.width = Math.ceil(next.width * dpr); target.height = Math.ceil(next.height * dpr);
      const context = target.getContext('2d');
      if (!context) throw new Error('Canvas is unavailable.');
      rendering = pdfPage.render({ canvas: target, canvasContext: context, viewport: next, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] });
      return rendering.promise;
    }).then(() => { if (alive) setLoading(false); }).catch(cause => {
      if (alive && cause?.name !== 'RenderingCancelledException') { setError(cause instanceof Error ? cause.message : String(cause)); setLoading(false); }
    });
    return () => { alive = false; rendering?.cancel(); };
  }, [doc, page, zoom, width]);

  function localPoint(event: React.PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const view = viewportRef.current!;
    return { x: Math.max(0, Math.min(view.width, event.clientX - bounds.left)), y: Math.max(0, Math.min(view.height, event.clientY - bounds.top)) };
  }

  function pointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !viewportRef.current || loading) return;
    const point = localPoint(event);
    if (guideMode && region?.page === page && pageInfo?.transform) {
      const pdfPoint = viewportRef.current.convertToPdfPoint(point.x, point.y);
      const transformed = apply(pageInfo.transform, pdfPoint[0], pdfPoint[1]);
      const regionPoints = corners(region.bbox).map(([x, y]) => apply(pageInfo.transform!, x, y));
      const minX = Math.min(...regionPoints.map(p => p[0])), maxX = Math.max(...regionPoints.map(p => p[0]));
      const minY = Math.min(...regionPoints.map(p => p[1])), maxY = Math.max(...regionPoints.map(p => p[1]));
      if (transformed[0] > minX && transformed[0] < maxX && transformed[1] >= minY && transformed[1] <= maxY) onGuide(transformed[0]);
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = point; setDrag({ ...point, endX: point.x, endY: point.y });
  }

  function pointerUp(event: React.PointerEvent<HTMLDivElement>) {
    if (!start.current || !viewportRef.current) return;
    const point = localPoint(event), origin = start.current;
    start.current = null; setDrag(null);
    if (Math.abs(point.x - origin.x) < 5 || Math.abs(point.y - origin.y) < 5) return;
    const points = corners([Math.min(point.x, origin.x), Math.min(point.y, origin.y), Math.max(point.x, origin.x), Math.max(point.y, origin.y)])
      .map(([x, y]) => viewportRef.current!.convertToPdfPoint(x, y));
    onRegion({ page, bbox: [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))] });
  }

  const visibleRefs = highlights.filter(ref => ref.page === page);
  const highlightedCharIds = new Set(visibleRefs.flatMap(ref => ref.charIds ?? []));
  const highlightedChars = pageInfo?.chars.filter(char => highlightedCharIds.has(char.id)) ?? [];
  const matrix = pageInfo?.transform;
  const guidePaths = region && matrix && viewport && region.page === page ? guides.map(x => {
    const ys = corners(region.bbox).map(([px, py]) => apply(matrix, px, py)[1]);
    const p1 = invert(matrix, x, Math.min(...ys)), p2 = invert(matrix, x, Math.max(...ys));
    const v1 = viewport.convertToViewportPoint(...p1), v2 = viewport.convertToViewportPoint(...p2);
    return { x, v1, v2 };
  }) : [];

  return <div className="pdf-scroll" ref={host}>
    {error && <div className="pdf-error" role="alert"><strong>{t.sourceError}</strong><p>{error}</p><button onClick={() => setRetry(value => value + 1)}>{t.retry}</button></div>}
    {loading && <div className="pdf-loading"><span className="spinner" />{t.loading}</div>}
    <div className={`pdf-paper ${guideMode ? 'guide-mode' : ''}`} style={{ width: viewport?.width || width, height: viewport?.height || width * 1.3 }}
      data-testid="pdf-page" aria-label={`${t.page} ${page}`} onPointerDown={pointerDown}
      onPointerMove={event => { if (start.current) { const point = localPoint(event); setDrag({ ...start.current, endX: point.x, endY: point.y }); } }}
      onPointerUp={pointerUp} onPointerCancel={() => { start.current = null; setDrag(null); }}>
      <canvas ref={canvas} style={{ width: viewport?.width, height: viewport?.height }} />
      {viewport && visibleRefs.map((ref, index) => <div key={`${index}-${ref.bbox.join()}`} className="pdf-highlight" style={displayBox(viewport, ref.bbox)} />)}
      {viewport && highlightedChars.map(char => <div key={char.id} className="pdf-char-highlight" data-char-id={char.id} style={displayBox(viewport, char.bbox)} />)}
      {viewport && region?.page === page && <div className="pdf-region" style={displayBox(viewport, region.bbox)}><span>{t.selection}</span></div>}
      {drag && <div className="pdf-drag" style={{ left: Math.min(drag.x, drag.endX), top: Math.min(drag.y, drag.endY), width: Math.abs(drag.endX - drag.x), height: Math.abs(drag.endY - drag.y) }} />}
      {viewport && <svg className="guide-layer" width={viewport.width} height={viewport.height}>{guidePaths.map(({ x, v1, v2 }) => <line key={x} x1={v1[0]} y1={v1[1]} x2={v2[0]} y2={v2[1]} />)}</svg>}
    </div>
  </div>;
}
