import { z } from "zod";

const stringArray = z.array(z.string()).nullish().transform((value) => value ?? []);
const zeroNumber = z.number().nullish().transform((value) => value ?? 0);
const falseBoolean = z.boolean().nullish().transform((value) => value ?? false);
const emptyString = z.string().nullish().transform((value) => value ?? "");

export const healthSchema = z.object({
  status: z.string(),
  postgres: z.string().optional(),
  neo4j: z.string().optional(),
  redis: z.string().optional(),
  note: z.string().optional(),
});

export const authUserSchema = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string().nullish(),
  avatar_url: z.string().nullish(),
  email_verified: z.boolean(),
});

export const authProvidersSchema = z.object({
  google: z.boolean(),
});

export const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

export const projectFileSchema = z.object({
  id: z.string(),
  path: z.string(),
  content: z.string(),
  version: z.number(),
});

export const projectPaperSchema = z.object({
  paper_id: z.string(),
  bibtex_key: z.string(),
  title: z.string().nullish(),
  year: z.number().nullish(),
  cited_by_count: zeroNumber,
  is_stub: falseBoolean,
});

export const paperSearchResultSchema = z.object({
  paper_id: z.string().nullish(),
  external_id: z.string().nullish(),
  title: z.string().nullish(),
  year: z.number().nullish(),
  authors: stringArray,
  abstract: z.string().nullish(),
  cited_by_count: zeroNumber,
  imported: falseBoolean,
});

export const paperSearchOutputSchema = z.object({
  papers: z.array(paperSearchResultSchema),
  summary: emptyString,
});

export const jobSchema = z.object({
  id: z.string(),
  job_type: z.string(),
  status: z.string(),
  result: z.record(z.unknown()).nullish(),
  error: z.string().nullish(),
});

export const graphNodeSchema = z.object({
  id: z.string(),
  title: z.string().nullish(),
  year: z.number().nullish(),
  cited_by_count: zeroNumber,
  is_stub: falseBoolean,
  is_seed: falseBoolean,
  in_project: falseBoolean,
  role: z.string().nullish().transform((value) => value ?? "related"),
  connection_count: zeroNumber,
  bibtex_key: z.string().nullish(),
});

export const graphEdgeSchema = z.object({
  source: z.string(),
  target: z.string(),
  type: z.string().nullish().transform((value) => value ?? "CITES"),
});

export const citationNeighborhoodSchema = z.object({
  nodes: z.array(graphNodeSchema),
  edges: z.array(graphEdgeSchema),
  ranked_neighbors: z.array(z.record(z.unknown())).nullish().transform((value) => value ?? []),
  summary: z.string().optional(),
  stats: z
    .object({
      project_papers: zeroNumber,
      related_papers: zeroNumber,
      citation_links: zeroNumber,
      total_neighbors: zeroNumber,
      visible_neighbors: zeroNumber,
      hidden_stubs: zeroNumber,
    })
    .nullish()
    .transform(
      (value) =>
        value ?? {
          project_papers: 0,
          related_papers: 0,
          citation_links: 0,
          total_neighbors: 0,
          visible_neighbors: 0,
          hidden_stubs: 0,
        },
    ),
});

export const compileLatexOutputSchema = z.object({
  compilation_id: z.string(),
  status: z.literal("queued"),
  summary: z.string().nullish().transform((value) => value ?? "latex compilation queued"),
});

export const compilationSchema = z.object({
  id: z.string(),
  status: z.string(),
  logs: z.string().nullish(),
  error: z.string().nullish(),
  has_pdf: z.boolean(),
  created_at: z.string().nullish(),
  completed_at: z.string().nullish(),
});

export const latestCompilationSchema = z.object({
  compilation: compilationSchema.nullable(),
  latest_attempt: compilationSchema.nullable(),
  is_stale: z.boolean(),
  source_updated_at: z.string().nullish(),
});

export const importPaperOutputSchema = z.object({
  job_id: z.string(),
  status: z.literal("queued"),
  summary: z.string().nullish().transform((value) => value ?? "paper import queued"),
});

export const paperDetailSchema = z.object({
  paper_id: z.string(),
  openalex_id: z.string().nullish(),
  doi: z.string().nullish(),
  title: z.string().nullish(),
  abstract: z.string().nullish(),
  year: z.number().nullish(),
  venue: z.string().nullish(),
  cited_by_count: zeroNumber,
  is_stub: falseBoolean,
  authors: stringArray,
  concepts: stringArray,
  in_project: falseBoolean,
  bibtex_key: z.string().nullish(),
  bibtex: z.string().nullish(),
  url: z.string().nullish(),
  pdf_url: z.string().nullish(),
});

export const recommendationSchema = z.object({
  paper_id: z.string(),
  bibtex_key: z.string().nullish(),
  title: z.string().nullish(),
  reason: z.string(),
  evidence_snippets: stringArray,
  score: z.number(),
  is_stub: falseBoolean,
});

export type Health = z.infer<typeof healthSchema>;
export type AuthUser = z.infer<typeof authUserSchema>;
export type AuthProviders = z.infer<typeof authProvidersSchema>;
export type Project = z.infer<typeof projectSchema>;
export type ProjectFile = z.infer<typeof projectFileSchema>;
export type ProjectPaper = z.infer<typeof projectPaperSchema>;
export type PaperSearchResult = z.infer<typeof paperSearchResultSchema>;
export type Job = z.infer<typeof jobSchema>;
export type GraphNode = z.infer<typeof graphNodeSchema>;
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export type CitationNeighborhood = z.infer<typeof citationNeighborhoodSchema>;
export type Compilation = z.infer<typeof compilationSchema>;
export type LatestCompilation = z.infer<typeof latestCompilationSchema>;
export type PaperDetail = z.infer<typeof paperDetailSchema>;
export type Recommendation = z.infer<typeof recommendationSchema>;
