import { z } from "zod";

import {
  citationNeighborhoodSchema,
  compilationSchema,
  compileLatexOutputSchema,
  healthSchema,
  importPaperOutputSchema,
  jobSchema,
  paperDetailSchema,
  paperSearchOutputSchema,
  projectFileSchema,
  projectPaperSchema,
  projectSchema,
  type CitationNeighborhood,
  type Compilation,
  type Health,
  type Job,
  type PaperDetail,
  type PaperSearchResult,
  type Project,
  type ProjectFile,
  type ProjectPaper,
} from "./schemas";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiFetch<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  init?: RequestInit,
): Promise<z.output<S>> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init?.headers,
    },
  });
  const payload = await parseJson(response);

  if (!response.ok) {
    throw new ApiError(response.status, payload);
  }

  return schema.parse(payload);
}

export function getHealth(): Promise<Health> {
  return apiFetch("/api/health", healthSchema);
}

export function listProjects(): Promise<Project[]> {
  return apiFetch("/api/projects", z.array(projectSchema));
}

export function createProject(body: { name: string; description?: string }): Promise<Project> {
  return apiFetch("/api/projects", projectSchema, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listFiles(projectId: string): Promise<ProjectFile[]> {
  return apiFetch(`/api/projects/${projectId}/files`, z.array(projectFileSchema));
}

export function importProjectFiles(
  projectId: string,
  files: Array<{ path: string; content: string }>,
  overwrite = false,
): Promise<{ imported: ProjectFile[]; skipped: string[] }> {
  return apiFetch(
    `/api/projects/${projectId}/files/import`,
    z.object({ imported: z.array(projectFileSchema), skipped: z.array(z.string()) }),
    {
      method: "POST",
      body: JSON.stringify({ files, overwrite }),
    },
  );
}

export function updateFile(
  projectId: string,
  fileId: string,
  body: { content: string; base_version: number; explicit: boolean },
): Promise<Pick<ProjectFile, "id" | "path" | "version">> {
  return apiFetch(
    `/api/projects/${projectId}/files/${fileId}`,
    projectFileSchema.pick({ id: true, path: true, version: true }),
    {
      method: "PUT",
      body: JSON.stringify(body),
    },
  );
}

export function listProjectPapers(projectId: string): Promise<ProjectPaper[]> {
  return apiFetch(`/api/projects/${projectId}/papers`, z.array(projectPaperSchema));
}

export async function searchPapers(body: {
  query: string;
  source: "local" | "openalex";
  project_id?: string;
  year_min?: number;
  year_max?: number;
  limit: number;
}): Promise<{ papers: PaperSearchResult[]; summary: string }> {
  return apiFetch("/api/papers/search", paperSearchOutputSchema, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function importPaper(body: {
  source: "openalex";
  source_id: string;
  project_id: string;
}): Promise<{ job_id: string; status: "queued"; summary: string }> {
  return apiFetch("/api/papers/import", importPaperOutputSchema, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getPaperDetail(paperId: string, projectId?: string): Promise<PaperDetail> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiFetch(`/api/papers/${encodeURIComponent(paperId)}${query}`, paperDetailSchema);
}

export function getJob(jobId: string): Promise<Job> {
  return apiFetch(`/api/jobs/${jobId}`, jobSchema);
}

export function getNeighborhood(
  paperId: string,
  perHop = 15,
): Promise<CitationNeighborhood> {
  return apiFetch(
    `/api/graph/neighborhood?paper_id=${encodeURIComponent(paperId)}&per_hop=${perHop}`,
    citationNeighborhoodSchema,
  );
}

export function getProjectGraph(projectId: string): Promise<CitationNeighborhood> {
  return apiFetch(
    `/api/graph/project/${encodeURIComponent(projectId)}`,
    citationNeighborhoodSchema,
  );
}

export function expandGraph(
  projectId: string,
  topN: number,
): Promise<{ job_id: string; status: string }> {
  return apiFetch("/api/graph/expand", z.object({ job_id: z.string(), status: z.string() }), {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, top_n: topN }),
  });
}

export function compileLatex(projectId: string): Promise<{ compilation_id: string }> {
  return apiFetch("/api/latex/compile", compileLatexOutputSchema, {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, main_file_path: "main.tex" }),
  });
}

export function getCompilation(compilationId: string): Promise<Compilation> {
  return apiFetch(`/api/latex/compilations/${compilationId}`, compilationSchema);
}

export function getPdfUrl(compilationId: string): string {
  return `${apiBaseUrl}/api/latex/compilations/${compilationId}/pdf`;
}

export function acceptPatch(toolCallId: string): Promise<Record<string, unknown>> {
  return apiFetch(`/api/agent/patches/${toolCallId}/accept`, z.record(z.unknown()), {
    method: "POST",
  });
}
