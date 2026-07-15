import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

import type { Recommendation } from "@/lib/schemas";

// Streaming can produce dozens of state updates per second. Persisting the
// entire conversation synchronously on every token makes the input and scroll
// feel sticky as history grows, so coalesce writes while keeping a trailing
// save for durability.
let pendingWrite: { name: string; value: string } | null = null;
let writeTimer: ReturnType<typeof setTimeout> | null = null;

function flushConversationWrite() {
  if (pendingWrite) {
    localStorage.setItem(pendingWrite.name, pendingWrite.value);
    pendingWrite = null;
  }
  if (writeTimer) {
    clearTimeout(writeTimer);
    writeTimer = null;
  }
}

const throttledStorage: StateStorage = {
  getItem: (name) => localStorage.getItem(name),
  setItem: (name, value) => {
    pendingWrite = { name, value };
    if (!writeTimer) {
      writeTimer = setTimeout(flushConversationWrite, 250);
    }
  },
  removeItem: (name) => {
    if (pendingWrite?.name === name) {
      pendingWrite = null;
    }
    localStorage.removeItem(name);
  },
};

window.addEventListener("pagehide", flushConversationWrite);

// A conversation is a single ordered timeline: text messages, tool activity,
// patch proposals, and citation cards all interleave the way they streamed,
// mirroring how Claude Code renders a turn in VS Code.
export type TimelineItem =
  | { id: string; kind: "user"; content: string; createdAt: string }
  | { id: string; kind: "assistant"; content: string; createdAt: string; open?: boolean }
  | {
      id: string;
      kind: "tool";
      tool: string;
      args: string;
      status: "running" | "done" | "error" | "stopped";
      summary?: string;
      createdAt: string;
    }
  | {
      id: string;
      kind: "patch";
      toolCallId: string;
      patch: unknown;
      preview: unknown;
      status: "pending" | "accepted";
      createdAt: string;
    }
  | { id: string; kind: "recommendations"; items: Recommendation[]; createdAt: string }
  | { id: string; kind: "error"; message: string; createdAt: string };

export type ChatConversation = {
  id: string;
  projectId: string;
  title: string;
  sessionId: string | null;
  items: TimelineItem[];
  createdAt: string;
  updatedAt: string;
};

type AgentState = {
  conversations: ChatConversation[];
  activeConversationByProject: Record<string, string>;
  ensureConversation: (projectId: string) => string;
  startConversation: (projectId: string) => string;
  setActiveConversation: (projectId: string, conversationId: string) => void;
  deleteConversation: (projectId: string, conversationId: string) => void;
  setConversationSessionId: (projectId: string, sessionId: string | null) => void;
  addUserMessage: (projectId: string, content: string) => void;
  appendAssistantText: (projectId: string, chunk: string) => void;
  closeAssistantMessage: (projectId: string) => void;
  addToolCall: (projectId: string, tool: string, args: string) => void;
  completeToolCall: (
    projectId: string,
    tool: string,
    status: "done" | "error",
    summary?: string,
  ) => void;
  stopRunningTools: (projectId: string) => void;
  addPatch: (projectId: string, toolCallId: string, patch: unknown, preview: unknown) => void;
  markPatchAccepted: (projectId: string, toolCallId: string) => void;
  addRecommendations: (projectId: string, items: Recommendation[]) => void;
  addError: (projectId: string, message: string) => void;
};

function now() {
  return new Date().toISOString();
}

function titleFrom(content: string) {
  const trimmed = content.trim();
  if (!trimmed) {
    return "New conversation";
  }
  return trimmed.length > 42 ? `${trimmed.slice(0, 39)}...` : trimmed;
}

function makeConversation(projectId: string): ChatConversation {
  const timestamp = now();
  return {
    id: crypto.randomUUID(),
    projectId,
    title: "New conversation",
    sessionId: null,
    items: [],
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}

export const useAgentStore = create<AgentState>()(
  persist(
    (set, get) => {
      // every mutation funnels through this: update the active conversation
      // for the project and bump its updatedAt
      function updateActive(
        projectId: string,
        update: (conversation: ChatConversation) => ChatConversation,
      ) {
        set((state) => {
          const activeId = state.activeConversationByProject[projectId];
          return {
            conversations: state.conversations.map((conversation) =>
              conversation.id === activeId && conversation.projectId === projectId
                ? { ...update(conversation), updatedAt: now() }
                : conversation,
            ),
          };
        });
      }

      function pushItem(projectId: string, item: TimelineItem) {
        updateActive(projectId, (conversation) => ({
          ...conversation,
          items: [...conversation.items, item],
        }));
      }

      return {
        conversations: [],
        activeConversationByProject: {},
        ensureConversation: (projectId) => {
          const state = get();
          const activeId = state.activeConversationByProject[projectId] ?? null;
          const existing = state.conversations.find(
            (conversation) => conversation.id === activeId && conversation.projectId === projectId,
          );
          if (existing) {
            return existing.id;
          }
          const next = makeConversation(projectId);
          set((current) => ({
            conversations: [next, ...current.conversations],
            activeConversationByProject: {
              ...current.activeConversationByProject,
              [projectId]: next.id,
            },
          }));
          return next.id;
        },
        startConversation: (projectId) => {
          const next = makeConversation(projectId);
          set((state) => ({
            conversations: [next, ...state.conversations],
            activeConversationByProject: {
              ...state.activeConversationByProject,
              [projectId]: next.id,
            },
          }));
          return next.id;
        },
        setActiveConversation: (projectId, conversationId) =>
          set((state) => ({
            activeConversationByProject: {
              ...state.activeConversationByProject,
              [projectId]: conversationId,
            },
          })),
        deleteConversation: (projectId, conversationId) =>
          set((state) => {
            const conversations = state.conversations.filter(
              (conversation) => conversation.id !== conversationId,
            );
            const active = { ...state.activeConversationByProject };
            if (active[projectId] === conversationId) {
              const fallback = conversations.find(
                (conversation) => conversation.projectId === projectId,
              );
              if (fallback) {
                active[projectId] = fallback.id;
              } else {
                delete active[projectId];
              }
            }
            return { conversations, activeConversationByProject: active };
          }),
        setConversationSessionId: (projectId, sessionId) =>
          updateActive(projectId, (conversation) => ({ ...conversation, sessionId })),
        addUserMessage: (projectId, content) =>
          updateActive(projectId, (conversation) => ({
            ...conversation,
            title:
              conversation.title === "New conversation" && conversation.items.length === 0
                ? titleFrom(content)
                : conversation.title,
            items: [
              ...conversation.items,
              { id: crypto.randomUUID(), kind: "user", content, createdAt: now() },
            ],
          })),
        appendAssistantText: (projectId, chunk) =>
          updateActive(projectId, (conversation) => {
            const items = [...conversation.items];
            const last = items[items.length - 1];
            if (last && last.kind === "assistant" && last.open) {
              items[items.length - 1] = { ...last, content: last.content + chunk };
            } else {
              items.push({
                id: crypto.randomUUID(),
                kind: "assistant",
                content: chunk,
                createdAt: now(),
                open: true,
              });
            }
            return { ...conversation, items };
          }),
        closeAssistantMessage: (projectId) =>
          updateActive(projectId, (conversation) => ({
            ...conversation,
            items: conversation.items.map((item) =>
              item.kind === "assistant" && item.open ? { ...item, open: false } : item,
            ),
          })),
        addToolCall: (projectId, tool, args) =>
          pushItem(projectId, {
            id: crypto.randomUUID(),
            kind: "tool",
            tool,
            args,
            status: "running",
            createdAt: now(),
          }),
        completeToolCall: (projectId, tool, status, summary) =>
          updateActive(projectId, (conversation) => {
            const items = [...conversation.items];
            // match the most recent still-running call of this tool
            for (let index = items.length - 1; index >= 0; index -= 1) {
              const item = items[index];
              if (item.kind === "tool" && item.tool === tool && item.status === "running") {
                items[index] = { ...item, status, summary };
                break;
              }
            }
            return { ...conversation, items };
          }),
        stopRunningTools: (projectId) =>
          updateActive(projectId, (conversation) => ({
            ...conversation,
            items: conversation.items.map((item) =>
              item.kind === "tool" && item.status === "running"
                ? { ...item, status: "stopped", summary: "Stopped by user" }
                : item,
            ),
          })),
        addPatch: (projectId, toolCallId, patch, preview) =>
          pushItem(projectId, {
            id: crypto.randomUUID(),
            kind: "patch",
            toolCallId,
            patch,
            preview,
            status: "pending",
            createdAt: now(),
          }),
        markPatchAccepted: (projectId, toolCallId) =>
          updateActive(projectId, (conversation) => ({
            ...conversation,
            items: conversation.items.map((item) =>
              item.kind === "patch" && item.toolCallId === toolCallId
                ? { ...item, status: "accepted" }
                : item,
            ),
          })),
        addRecommendations: (projectId, items) =>
          pushItem(projectId, {
            id: crypto.randomUUID(),
            kind: "recommendations",
            items,
            createdAt: now(),
          }),
        addError: (projectId, message) =>
          pushItem(projectId, {
            id: crypto.randomUUID(),
            kind: "error",
            message,
            createdAt: now(),
          }),
      };
    },
    {
      name: "citepilot-agent-conversations",
      storage: createJSONStorage(() => throttledStorage),
      version: 2,
      partialize: (state) => ({
        conversations: state.conversations,
        activeConversationByProject: state.activeConversationByProject,
      }),
      migrate: (persisted: unknown, version) => {
        // v1 stored conversations as { messages: [{role, content}] }; map those
        // into the timeline shape so existing chats survive the upgrade
        if (version >= 2 || !persisted || typeof persisted !== "object") {
          return persisted as AgentState;
        }
        const old = persisted as {
          conversations?: Array<
            Omit<ChatConversation, "items"> & {
              messages?: Array<{ id: string; role: string; content: string; createdAt: string }>;
            }
          >;
          activeConversationByProject?: Record<string, string>;
        };
        return {
          activeConversationByProject: old.activeConversationByProject ?? {},
          conversations: (old.conversations ?? []).map((conversation) => ({
            id: conversation.id,
            projectId: conversation.projectId,
            title: conversation.title,
            sessionId: conversation.sessionId,
            createdAt: conversation.createdAt,
            updatedAt: conversation.updatedAt,
            items: (conversation.messages ?? [])
              .filter((message) => message.content)
              .map((message) => ({
                id: message.id,
                kind: message.role === "user" ? ("user" as const) : ("assistant" as const),
                content: message.content,
                createdAt: message.createdAt,
              })),
          })),
        } as AgentState;
      },
    },
  ),
);
