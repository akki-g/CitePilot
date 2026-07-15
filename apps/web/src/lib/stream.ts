import { apiBaseUrl, ApiError } from "./api";

export type AgentEvent = {
  event: string;
  data: Record<string, unknown>;
};

function parseEventBlock(block: string): AgentEvent | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    const data = JSON.parse(dataLines.join("\n"));
    return { event, data: typeof data === "object" && data !== null ? data : { value: data } };
  } catch {
    return { event, data: { message: dataLines.join("\n") } };
  }
}

export async function streamAgentTurn(
  body: {
    project_id: string;
    session_id?: string;
    message: string;
    active_file_path?: string;
    selected_text?: string;
  },
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/agent/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail: unknown = response.statusText;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const parsed = parseEventBlock(block);
      if (parsed) {
        onEvent(parsed);
      }
    }
  }

  const remaining = parseEventBlock(buffer);
  if (remaining) {
    onEvent(remaining);
  }
}
