import CodeMirror from "@uiw/react-codemirror";

type LatexEditorProps = {
  value: string;
  path: string;
  onChange: (value: string) => void;
  onSelectionChange: (value: string) => void;
};

export function LatexEditor({ value, path, onChange, onSelectionChange }: LatexEditorProps) {
  return (
    <div className="h-full overflow-hidden bg-ink-950 [&_.cm-editor]:h-full [&_.cm-editor]:text-[13px] [&_.cm-scroller]:font-mono">
      {path ? (
        <CodeMirror
          value={value}
          height="100%"
          style={{ height: "100%" }}
          basicSetup={{
            foldGutter: true,
            lineNumbers: true,
            highlightActiveLine: true,
            bracketMatching: true,
          }}
          theme="dark"
          onChange={onChange}
          onUpdate={(update) => {
            const selection = update.state.sliceDoc(
              update.state.selection.main.from,
              update.state.selection.main.to,
            );
            onSelectionChange(selection);
          }}
        />
      ) : (
        <div className="grid h-full place-items-center text-sm text-fog">
          Select a project file to begin editing.
        </div>
      )}
    </div>
  );
}
