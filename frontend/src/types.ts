export type BBox = [number, number, number, number];
export type Language = 'en' | 'zh';
export type SelectionMode = 'table' | 'caption' | 'note' | 'unit';
export interface SourceRef { fileHash: string; page: number; bbox: BBox; charIds?: string[] }
export interface PDFChar { id: string; text: string; bbox: BBox }
export type Affine = [number, number, number, number, number, number];
export interface PDFPage { number: number; width: number; height: number; rotation: number; mediaBox: BBox; cropBox: BBox; displayMediaBox?: BBox; transform?: Affine; chars: PDFChar[]; mappingReliable: boolean }
export interface Cell { id: string; row: number; col: number; rowSpan: number; colSpan: number; originalText: string; value: string; sourceRefs: SourceRef[]; reviewed: boolean }
export interface Context { id: string; kind: 'caption' | 'note' | 'unit'; text: string; sourceRefs: SourceRef[] }
export interface Table { id: string; page: number; bbox: BBox; rowCount: number; colCount: number; rowBoundaries?: number[]; colBoundaries?: number[]; cells: Cell[]; contexts: Context[]; omittedText?: { text: string; sourceRefs: SourceRef[] }; warnings?: string[]; supersedes?: string | null }
export interface Project { id: string; name: string; fileHash: string; version: number; pages: PDFPage[]; tables: Table[]; history: unknown[]; undoStack: unknown[]; redoStack: unknown[] }
export interface ProjectSummary { id: string; name: string; version: number; updatedAt: string }
export interface Job { status: 'pending' | 'running' | 'complete' | 'cancelled' | 'failed'; progress: number; error?: string; projectId?: string }
export interface Region { page: number; bbox: BBox }
export type Operation = Record<string, unknown> & { type: 'edit' | 'review' | 'merge' | 'split' | 'context' | 'rename' | 'undo' | 'redo' };
