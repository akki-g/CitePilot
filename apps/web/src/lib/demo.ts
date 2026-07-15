import { apiBaseUrl, ApiError, csrfToken } from "./api";

export type DemoSourceFile = { path: string; content: string };
export type DemoPaper = { key: string; title: string; year: number; role: string };
export type DemoLimits = {
  agent_limit: number;
  agent_remaining: number;
  preview_limit: number;
  preview_remaining: number;
};
export type DemoChatMessage = { role: "user" | "assistant"; content: string };

const VISITOR_KEY = "citepilot_demo_visitor";

export function demoVisitorId(): string {
  const existing = sessionStorage.getItem(VISITOR_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  sessionStorage.setItem(VISITOR_KEY, id);
  return id;
}

function headers(): HeadersInit {
  return {
    "content-type": "application/json",
    "x-demo-visitor": demoVisitorId(),
    ...(csrfToken() ? { "x-csrf-token": csrfToken() } : {}),
  };
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown = response.statusText;
  try {
    detail = await response.json();
  } catch {
    detail = await response.text();
  }
  return new ApiError(response.status, detail);
}

export async function getDemoLimits(): Promise<DemoLimits> {
  const response = await fetch(`${apiBaseUrl}/api/demo/limits`, {
    credentials: "include",
    headers: { "x-demo-visitor": demoVisitorId() },
  });
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<DemoLimits>;
}

export async function compileDemo(
  files: DemoSourceFile[],
): Promise<{ pdf: Blob; remaining: number }> {
  const response = await fetch(`${apiBaseUrl}/api/demo/compile`, {
    method: "POST",
    credentials: "include",
    headers: headers(),
    body: JSON.stringify({ files, main_file_path: "main.tex" }),
  });
  if (!response.ok) throw await errorFrom(response);
  return {
    pdf: await response.blob(),
    remaining: Number(response.headers.get("x-demo-remaining") ?? 0),
  };
}

type DemoAgentEvent = { event: string; data: Record<string, unknown> };

function parseEvent(block: string): DemoAgentEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) as Record<string, unknown> };
  } catch {
    return { event, data: { message: data.join("\n") } };
  }
}

export async function streamDemoAgent(
  body: {
    project_name: string;
    files: DemoSourceFile[];
    papers: DemoPaper[];
    message: string;
    active_file_path?: string;
    selected_text?: string;
    conversation: DemoChatMessage[];
  },
  onEvent: (event: DemoAgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/demo/agent`, {
    method: "POST",
    credentials: "include",
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) throw await errorFrom(response);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const parsed = parseEvent(block);
      if (parsed) onEvent(parsed);
    }
  }
  const final = parseEvent(buffer);
  if (final) onEvent(final);
}
