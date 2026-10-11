import type { Operation, Project } from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      const detail = body.detail ?? body.error ?? body.message;
      message = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : message;
    } catch { /* A plain HTTP failure still has a useful status. */ }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function operate(project: Project, operation: Operation) {
  return request<Project>(`/api/projects/${project.id}/operations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: project.version, operation }),
  });
}
