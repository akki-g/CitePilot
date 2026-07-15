import { useRef, useState } from "react";
import { FileCode2, FileText, Loader2, Upload } from "lucide-react";

import { importProjectFiles } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import type { ProjectFile } from "@/lib/schemas";

type FileTreeProps = {
  projectId: string;
  files: ProjectFile[];
  activeFileId: string | null;
  isLoading: boolean;
  onSelect: (file: ProjectFile) => void;
  onImported: (files: ProjectFile[]) => void;
};

function iconFor(path: string) {
  return path.endsWith(".tex") || path.endsWith(".bib") ? FileCode2 : FileText;
}

export function FileTree({
  projectId,
  files,
  activeFileId,
  isLoading,
  onSelect,
  onImported,
}: FileTreeProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  async function uploadFiles(selected: File[]) {
    if (selected.length === 0 || uploading) {
      return;
    }
    const existingPaths = new Set(files.map((file) => file.path));
    const conflicts = selected.filter((file) => existingPaths.has(file.name));
    const overwrite =
      conflicts.length > 0 &&
      window.confirm(
        `${conflicts.length} selected file${conflicts.length === 1 ? "" : "s"} already exist. Replace them with new versions?`,
      );
    if (conflicts.length > 0 && !overwrite) {
      setUploadMessage("Import cancelled; existing files were left unchanged.");
      return;
    }

    setUploading(true);
    setUploadMessage(null);
    try {
      const payload = await Promise.all(
        selected.map(async (file) => ({ path: file.name, content: await file.text() })),
      );
      const result = await importProjectFiles(projectId, payload, overwrite);
      await queryClient.invalidateQueries({ queryKey: ["project-files", projectId] });
      onImported(result.imported);
      setUploadMessage(
        result.imported.length > 0
          ? `Imported ${result.imported.length} file${result.imported.length === 1 ? "" : "s"}.`
          : "No new files were imported.",
      );
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : "File import failed");
    } finally {
      setUploading(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  }

  return (
    <section
      className="shrink-0"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        void uploadFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <div className="flex h-9 items-center justify-between px-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fog">Files</h2>
        <div className="flex items-center gap-1">
          {isLoading || uploading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-fog" aria-hidden="true" />
          ) : null}
          <input
            ref={inputRef}
            className="hidden"
            type="file"
            accept=".tex,.bib,.sty,.cls,.txt,text/plain"
            multiple
            onChange={(event) => void uploadFiles(Array.from(event.target.files ?? []))}
          />
          <button
            type="button"
            className="grid h-6 w-6 place-items-center rounded text-fog hover:bg-ink-750 hover:text-indigo-200 disabled:opacity-40"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            title="Import LaTeX, BibTeX, style, or text files"
            aria-label="Import project files"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="space-y-0.5 px-2 pb-2">
        {files.map((file) => {
          const Icon = iconFor(file.path);
          const active = file.id === activeFileId;
          return (
            <button
              key={file.id}
              type="button"
              className={[
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left font-mono text-xs transition",
                active
                  ? "bg-indigo-500/15 text-indigo-200"
                  : "text-mist hover:bg-ink-750 hover:text-snow",
              ].join(" ")}
              onClick={() => onSelect(file)}
            >
              <Icon
                className={["h-3.5 w-3.5 shrink-0", active ? "text-indigo-300" : "text-fog"].join(" ")}
                aria-hidden="true"
              />
              <span className="truncate">{file.path}</span>
              <span className="ml-auto text-[10px] text-fog">v{file.version}</span>
            </button>
          );
        })}
        {!isLoading && files.length === 0 ? (
          <p className="rounded-md border border-dashed border-edge-2 p-3 text-xs text-fog">
            No project files are available yet.
          </p>
        ) : null}
        {uploadMessage ? (
          <p className="px-2 py-1.5 text-[10px] leading-4 text-fog">{uploadMessage}</p>
        ) : null}
      </div>
    </section>
  );
}
