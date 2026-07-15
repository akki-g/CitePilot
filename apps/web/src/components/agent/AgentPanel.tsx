import { useEffect, useMemo, useRef, useState } from "react";
import {
  FileText,
  History,
  Plus,
  Send,
  Sparkles,
  Square,
  TextSelect,
  Trash2,
  X,
} from "lucide-react";

import { recommendationSchema, type Recommendation } from "@/lib/schemas";
import { streamAgentTurn } from "@/lib/stream";
import { useAgentStore, type ChatConversation, type TimelineItem } from "@/stores/agentStore";
import { CitationSuggestionCard } from "./CitationSuggestionCard";
import { MessageMarkdown } from "./MessageMarkdown";
import { PatchReviewCard } from "./PatchReviewCard";
import { ToolCallChip } from "./ToolCallChip";

type AgentPanelProps = {
  projectId: string;
  activeFilePath: string | null;
  selectedText: string;
  onInsertCitation: (bibtexKey: string) => void;
  onRefresh: () => Promise<void> | void;
};

const QUICK_PROMPTS = [
  "Suggest related work citations for this paragraph.",
  "Explain the citation graph around this project.",
  "Tighten the selected text without changing meaning.",
];

function parseRecommendations(value: unknown[]): Recommendation[] {
  return value
    .map((item) => recommendationSchema.safeParse(item))
    .filter((result) => result.success)
    .map((result) => result.data);
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function formatThreadTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-1">
      {[0, 1, 2].map((dot) => (
        <span key={dot} className="thinking-dot h-1.5 w-1.5 rounded-full bg-indigo-300" />
      ))}
    </div>
  );
}

export function AgentPanel({
  projectId,
  activeFilePath,
  selectedText,
  onInsertCitation,
  onRefresh,
}: AgentPanelProps) {
  const [message, setMessage] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingTextRef = useRef("");
  const textFrameRef = useRef<number | null>(null);

  const {
    conversations,
    activeConversationByProject,
    ensureConversation,
    startConversation,
    setActiveConversation,
    deleteConversation,
    setConversationSessionId,
    addUserMessage,
    appendAssistantText,
    closeAssistantMessage,
    addToolCall,
    completeToolCall,
    addPatch,
    markPatchAccepted,
    addRecommendations,
    addError,
    stopRunningTools,
  } = useAgentStore();

  const projectConversations = useMemo(
    () =>
      conversations
        .filter((conversation) => conversation.projectId === projectId)
        .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)),
    [conversations, projectId],
  );
  const activeConversationId = activeConversationByProject[projectId] ?? null;
  const activeConversation: ChatConversation | null = useMemo(
    () =>
      projectConversations.find((conversation) => conversation.id === activeConversationId) ??
      projectConversations[0] ??
      null,
    [activeConversationId, projectConversations],
  );
  const items = useMemo(() => activeConversation?.items ?? [], [activeConversation?.items]);

  useEffect(() => {
    ensureConversation(projectId);
  }, [ensureConversation, projectId]);

  // autoscroll only while the user is already at the bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [items]);

  function handleScroll() {
    const el = scrollRef.current;
    if (el) {
      stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    }
  }

  function autoGrow() {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
    }
  }

  const lastItem = items[items.length - 1];
  const showThinking =
    isStreaming &&
    (!lastItem || lastItem.kind === "user" || (lastItem.kind === "tool" && lastItem.status !== "running"));

  function flushAssistantText() {
    if (textFrameRef.current !== null) {
      cancelAnimationFrame(textFrameRef.current);
      textFrameRef.current = null;
    }
    if (pendingTextRef.current) {
      appendAssistantText(projectId, pendingTextRef.current);
      pendingTextRef.current = "";
    }
  }

  function queueAssistantText(chunk: string) {
    pendingTextRef.current += chunk;
    if (textFrameRef.current === null) {
      textFrameRef.current = requestAnimationFrame(() => {
        textFrameRef.current = null;
        if (pendingTextRef.current) {
          appendAssistantText(projectId, pendingTextRef.current);
          pendingTextRef.current = "";
        }
      });
    }
  }

  async function submit(text?: string) {
    const trimmed = (text ?? message).trim();
    if (!trimmed || isStreaming) {
      return;
    }
    ensureConversation(projectId);
    const sessionId = activeConversation?.sessionId ?? undefined;
    addUserMessage(projectId, trimmed);
    setMessage("");
    requestAnimationFrame(autoGrow);
    setIsStreaming(true);
    stickToBottom.current = true;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamAgentTurn(
        {
          project_id: projectId,
          session_id: sessionId,
          message: trimmed,
          active_file_path: activeFilePath ?? undefined,
          selected_text: selectedText || undefined,
        },
        (event) => {
          if (event.event !== "message_delta") {
            // Preserve stream ordering when a tool event follows text in the
            // same network chunk.
            flushAssistantText();
          }
          if (event.event === "session" || event.event === "done") {
            const id = asString(event.data.session_id);
            if (id) {
              setConversationSessionId(projectId, id);
            }
            if (event.event === "done") {
              void onRefresh();
            }
          }
          if (event.event === "message_delta") {
            queueAssistantText(asString(event.data.text) ?? "");
          }
          if (event.event === "tool_call") {
            closeAssistantMessage(projectId);
            addToolCall(
              projectId,
              asString(event.data.tool_name) ?? "tool",
              JSON.stringify(event.data.arguments ?? {}),
            );
          }
          if (event.event === "tool_result") {
            completeToolCall(
              projectId,
              asString(event.data.tool_name) ?? "tool",
              event.data.error ? "error" : "done",
              asString(event.data.summary) ??
                asString(event.data.message) ??
                asString(event.data.error),
            );
          }
          if (event.event === "citation_suggestions") {
            const parsed = parseRecommendations(asArray(event.data.recommendations));
            if (parsed.length > 0) {
              addRecommendations(projectId, parsed);
            }
          }
          if (event.event === "patch_proposal" && asString(event.data.tool_call_id)) {
            addPatch(
              projectId,
              asString(event.data.tool_call_id) ?? "",
              event.data.patch,
              event.data.preview,
            );
          }
          if (event.event === "error") {
            addError(projectId, asString(event.data.message) ?? "Agent stream failed");
          }
        },
        controller.signal,
      );
    } catch (exc) {
      if (exc instanceof DOMException && exc.name === "AbortError") {
        stopRunningTools(projectId);
      } else {
        addError(projectId, exc instanceof Error ? exc.message : "Agent stream failed");
      }
    } finally {
      flushAssistantText();
      closeAssistantMessage(projectId);
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  // Escape stops the current turn, like on other LLM chat UIs
  useEffect(() => {
    if (!isStreaming) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        abortRef.current?.abort();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isStreaming]);

  function renderItem(item: TimelineItem) {
    if (item.kind === "user") {
      return (
        <div key={item.id} className="fade-up rounded-lg border border-edge bg-ink-800 px-3 py-2">
          <p className="whitespace-pre-wrap text-[13px] leading-6 text-snow">{item.content}</p>
        </div>
      );
    }
    if (item.kind === "assistant") {
      return (
        <div key={item.id} className="fade-up px-0.5">
          <MessageMarkdown text={item.content} />
          {item.open && isStreaming ? <span className="stream-caret" /> : null}
        </div>
      );
    }
    if (item.kind === "tool") {
      return <ToolCallChip key={item.id} item={item} />;
    }
    if (item.kind === "patch") {
      return (
        <PatchReviewCard
          key={item.id}
          projectId={projectId}
          patch={item}
          onAccepted={(toolCallId) => markPatchAccepted(projectId, toolCallId)}
        />
      );
    }
    if (item.kind === "recommendations") {
      return (
        <div key={item.id} className="space-y-2">
          {item.items.map((recommendation) => (
            <CitationSuggestionCard
              key={recommendation.paper_id}
              recommendation={recommendation}
              onInsertCitation={onInsertCitation}
            />
          ))}
        </div>
      );
    }
    return (
      <p
        key={item.id}
        className="fade-up rounded-lg border border-red-400/25 bg-red-400/5 px-3 py-2 text-xs leading-5 text-red-300"
      >
        {item.message}
      </p>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-ink-900">
      <div className="relative flex h-10 shrink-0 items-center justify-between border-b border-edge px-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-indigo-300" aria-hidden="true" />
          <h2 className="text-xs font-semibold uppercase tracking-wide text-mist">Agent</h2>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={[
              "grid h-7 w-7 place-items-center rounded-md text-fog hover:bg-ink-750 hover:text-mist",
              historyOpen ? "bg-ink-750 text-mist" : "",
            ].join(" ")}
            onClick={() => setHistoryOpen((open) => !open)}
            aria-label="Conversation history"
            title="History"
          >
            <History className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="grid h-7 w-7 place-items-center rounded-md text-fog hover:bg-ink-750 hover:text-mist"
            onClick={() => {
              startConversation(projectId);
              setHistoryOpen(false);
            }}
            aria-label="New chat"
            title="New chat"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {historyOpen ? (
          <div className="absolute right-2 top-11 z-30 w-72 overflow-hidden rounded-lg border border-edge-2 bg-ink-800 shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-edge px-3 py-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-fog">
                Conversations
              </span>
              <button
                type="button"
                className="grid h-5 w-5 place-items-center rounded text-fog hover:text-mist"
                onClick={() => setHistoryOpen(false)}
                aria-label="Close history"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
            <div className="max-h-64 overflow-auto p-1">
              {projectConversations.map((conversation) => (
                <div
                  key={conversation.id}
                  className={[
                    "group flex items-center gap-2 rounded-md px-2 py-1.5",
                    conversation.id === activeConversation?.id
                      ? "bg-indigo-500/15"
                      : "hover:bg-ink-750",
                  ].join(" ")}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => {
                      setActiveConversation(projectId, conversation.id);
                      setHistoryOpen(false);
                    }}
                  >
                    <span className="block truncate text-xs font-medium text-mist">
                      {conversation.title}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-fog">
                      {formatThreadTime(conversation.updatedAt)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="hidden h-6 w-6 shrink-0 place-items-center rounded text-fog hover:text-red-300 group-hover:grid"
                    onClick={() => deleteConversation(projectId, conversation.id)}
                    aria-label={`Delete ${conversation.title}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
              ))}
              {projectConversations.length === 0 ? (
                <p className="px-2 py-3 text-xs text-fog">No conversations yet.</p>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        {items.length === 0 ? (
          <div className="fade-up rounded-lg border border-edge bg-ink-850 p-4">
            <Sparkles className="h-4 w-4 text-indigo-300" aria-hidden="true" />
            <p className="mt-2 text-[13px] leading-6 text-mist">
              Ask for citations, evidence, LaTeX edits, or an explanation of your citation graph.
              The agent streams its tool calls here as it works.
            </p>
            <div className="mt-3 space-y-1.5">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="block w-full rounded-md border border-edge bg-ink-800 px-2.5 py-1.5 text-left text-xs text-fog transition hover:border-indigo-400/40 hover:text-indigo-200"
                  onClick={() => void submit(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          items.map(renderItem)
        )}
        {showThinking ? <ThinkingIndicator /> : null}
      </div>

      <div className="shrink-0 border-t border-edge bg-ink-900 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex max-w-[220px] items-center gap-1 rounded border border-edge bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-fog">
            <FileText className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{activeFilePath ?? "no file"}</span>
          </span>
          {selectedText.trim() ? (
            <span className="inline-flex items-center gap-1 rounded border border-indigo-400/30 bg-indigo-500/10 px-1.5 py-0.5 font-mono text-[10px] text-indigo-200">
              <TextSelect className="h-3 w-3" aria-hidden="true" />
              {selectedText.trim().split(/\s+/).length} words selected
            </span>
          ) : null}
        </div>
        <form
          className="flex items-end gap-2 rounded-lg border border-edge-2 bg-ink-800 p-2 transition focus-within:border-indigo-400/60"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            className="max-h-[132px] min-h-[24px] flex-1 resize-none bg-transparent px-1 py-0.5 text-[13px] leading-6 text-snow outline-none placeholder:text-fog"
            value={message}
            onChange={(event) => {
              setMessage(event.target.value);
              autoGrow();
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="Ask the agent... (Enter to send)"
          />
          {isStreaming ? (
            <button
              type="button"
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-red-400/40 bg-red-400/10 px-3 text-xs font-semibold text-red-300 transition hover:bg-red-400/20"
              onClick={() => abortRef.current?.abort()}
              aria-label="Stop the agent"
              title="Stop (Esc)"
            >
              <Square className="h-3 w-3 fill-current" aria-hidden="true" />
              Stop
            </button>
          ) : (
            <button
              type="submit"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-accent-deep text-white shadow-lg shadow-indigo-950/40 transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!message.trim()}
              aria-label="Send message"
            >
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </form>
      </div>
    </section>
  );
}
