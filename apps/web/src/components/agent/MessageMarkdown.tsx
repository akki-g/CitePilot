import { Fragment, type ReactNode } from "react";

// Minimal markdown renderer for agent replies: paragraphs, fenced code, inline
// code, bold/italic, links, lists, and headings. Builds React elements only —
// no HTML injection — so model output is safe to render.

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // tokenize: `code`, **bold**, *italic*, [label](url)
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\((?:https?:\/\/)[^)\s]+\))/g;
  const parts = text.split(pattern);

  parts.forEach((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (!part) {
      return;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-ink-700/80 px-1 py-0.5 font-mono text-[0.85em] text-indigo-200"
        >
          {part.slice(1, -1)}
        </code>,
      );
    } else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      nodes.push(
        <strong key={key} className="font-semibold text-snow">
          {part.slice(2, -2)}
        </strong>,
      );
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      nodes.push(<em key={key}>{part.slice(1, -1)}</em>);
    } else if (part.startsWith("[")) {
      const match = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
      if (match) {
        nodes.push(
          <a
            key={key}
            href={match[2]}
            target="_blank"
            rel="noreferrer"
            className="text-indigo-300 underline decoration-indigo-300/40 underline-offset-2 hover:text-indigo-200"
          >
            {match[1]}
          </a>,
        );
      } else {
        nodes.push(<Fragment key={key}>{part}</Fragment>);
      }
    } else {
      nodes.push(<Fragment key={key}>{part}</Fragment>);
    }
  });
  return nodes;
}

type Block =
  | { type: "code"; lang: string; lines: string[] }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "heading"; text: string }
  | { type: "paragraph"; lines: string[] };

function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1; // closing fence
      blocks.push({ type: "code", lang, lines: code });
      continue;
    }

    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      const items: string[] = [];
      while (index < lines.length) {
        const itemMatch = ordered
          ? /^\s*\d+[.)]\s+(.*)$/.exec(lines[index])
          : /^\s*[-*]\s+(.*)$/.exec(lines[index]);
        if (!itemMatch) {
          break;
        }
        items.push(itemMatch[1]);
        index += 1;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", text: heading[1] });
      index += 1;
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !lines[index].startsWith("```") &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !/^#{1,4}\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", lines: paragraph });
  }

  return blocks;
}

export function MessageMarkdown({ text }: { text: string }) {
  const blocks = parseBlocks(text);

  return (
    <div className="space-y-2.5 text-[13px] leading-6 text-mist">
      {blocks.map((block, blockIndex) => {
        const key = `block-${blockIndex}`;
        if (block.type === "code") {
          return (
            <pre
              key={key}
              className="overflow-x-auto rounded-lg border border-edge bg-ink-950/80 p-3 font-mono text-xs leading-5 text-indigo-100"
            >
              <code>{block.lines.join("\n")}</code>
            </pre>
          );
        }
        if (block.type === "list") {
          const ListTag = block.ordered ? "ol" : "ul";
          return (
            <ListTag
              key={key}
              className={[
                "space-y-1 pl-5",
                block.ordered ? "list-decimal" : "list-disc",
                "marker:text-fog",
              ].join(" ")}
            >
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
              ))}
            </ListTag>
          );
        }
        if (block.type === "heading") {
          return (
            <p key={key} className="pt-1 text-sm font-semibold text-snow">
              {renderInline(block.text, key)}
            </p>
          );
        }
        return <p key={key}>{renderInline(block.lines.join(" "), key)}</p>;
      })}
    </div>
  );
}
