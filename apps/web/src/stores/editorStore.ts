import { create } from "zustand";

type EditorState = {
  activeProjectId: string | null;
  activeFileId: string | null;
  activeFilePath: string | null;
  selectedText: string;
  setActiveProject: (projectId: string | null) => void;
  setActiveFile: (fileId: string | null, path: string | null) => void;
  setSelectedText: (selectedText: string) => void;
};

export const useEditorStore = create<EditorState>((set) => ({
  activeProjectId: null,
  activeFileId: null,
  activeFilePath: null,
  selectedText: "",
  setActiveProject: (projectId) => set({ activeProjectId: projectId }),
  setActiveFile: (fileId, path) => set({ activeFileId: fileId, activeFilePath: path }),
  setSelectedText: (selectedText) => set({ selectedText }),
}));
