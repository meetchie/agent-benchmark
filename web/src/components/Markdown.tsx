import { Fragment, type ReactNode } from "react";

/**
 * A small markdown renderer for text a model wrote, such as the agent's final
 * report: paragraphs, line breaks, bullet and numbered lists, **bold**, *italics*
 * and `inline code`. A heading line ("## Result") shows as a bold line. Anything
 * else, links and HTML included, shows exactly as typed.
 *
 * It builds React elements and every piece of the input reaches the page as a
 * text node, so HTML in the text (a <script>, an <img onerror>) is shown, never run.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <>
      {parseBlocks(text).map((block, i) => {
        if (block.kind === "p") {
          return <p key={i}>{withLineBreaks(block.lines)}</p>;
        }
        const items = block.items.map((item, j) => <li key={j}>{withLineBreaks(item)}</li>);
        return block.kind === "ul" ? (
          <ul key={i} className="list-disc pl-5 space-y-0.5">{items}</ul>
        ) : (
          <ol key={i} start={block.start === 1 ? undefined : block.start} className="list-decimal pl-5 space-y-0.5">
            {items}
          </ol>
        );
      })}
    </>
  );
}

type Block =
  | { kind: "p"; lines: ReactNode[][] }
  | { kind: "ul"; items: ReactNode[][][] }
  | { kind: "ol"; start: number; items: ReactNode[][][] };

const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const NUMBERED = /^\s{0,3}(\d{1,9})[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null;
  let blankBefore = false;

  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line.trim()) {
      blankBefore = true;
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    const heading = bullet || numbered ? null : HEADING.exec(line);

    if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      const content = parseInline((bullet ? bullet[1] : numbered![2]).trim());
      // A list goes on across blank lines while its items keep coming.
      if (current && current.kind === kind) {
        current.items.push([content]);
      } else {
        current =
          kind === "ul"
            ? { kind: "ul", items: [[content]] }
            : { kind: "ol", start: Number(numbered![1]), items: [[content]] };
        blocks.push(current);
      }
    } else if (heading) {
      blocks.push({ kind: "p", lines: [[<strong key="h">{parseInline(heading[1])}</strong>]] });
      current = null;
    } else if (current && current.kind !== "p" && !blankBefore && /^\s/.test(line)) {
      // An indented line right under a list item belongs to that item.
      current.items[current.items.length - 1].push(parseInline(line.trim()));
    } else if (current && current.kind === "p" && !blankBefore) {
      current.lines.push(parseInline(line.trim()));
    } else {
      current = { kind: "p", lines: [parseInline(line.trim())] };
      blocks.push(current);
    }
    blankBefore = false;
  }
  return blocks;
}

function withLineBreaks(lines: ReactNode[][]): ReactNode[] {
  return lines.map((nodes, i) => (
    <Fragment key={i}>
      {i > 0 && <br />}
      {nodes}
    </Fragment>
  ));
}

const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch);
const isWordChar = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);

/**
 * Where the emphasis that opens at `from` with `marker` ("**", "__", "*" or "_")
 * closes, or -1 when it does not. Like markdown, the text inside must not start
 * or end with a space, and an underscore counts only at a word's edge, so
 * snake_case names stay as they are.
 */
function closingMarker(text: string, from: number, marker: string): number {
  const ch = marker[0];
  const open = from + marker.length;
  if (isSpace(text[open])) return -1;
  if (ch === "_" && isWordChar(text[from - 1])) return -1;
  for (let j = open + 1; j <= text.length - marker.length; j++) {
    if (text[j] === "`") {
      // Code inside the emphasis is skipped whole, markers in it do not count.
      const end = text.indexOf("`", j + 1);
      if (end !== -1) {
        j = end;
        continue;
      }
    }
    if (!text.startsWith(marker, j)) continue;
    if (marker.length === 1 && text[j + 1] === ch) {
      // A double marker inside a single one: step over the pair.
      j++;
      continue;
    }
    if (isSpace(text[j - 1])) continue;
    if (ch === "_" && isWordChar(text[j + marker.length])) continue;
    return j;
  }
  return -1;
}

function parseInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let plain = "";
  let i = 0;
  const flush = () => {
    if (plain) out.push(plain);
    plain = "";
  };

  while (i < text.length) {
    const ch = text[i];
    if (ch === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > i + 1) {
        flush();
        out.push(
          <code key={out.length} className="font-mono text-[0.9em] bg-slate-100 px-1">
            {text.slice(i + 1, end)}
          </code>
        );
        i = end + 1;
        continue;
      }
    } else if (ch === "*" || ch === "_") {
      const marker = text[i + 1] === ch ? ch + ch : ch;
      const end = closingMarker(text, i, marker);
      if (end !== -1) {
        flush();
        const inner = parseInline(text.slice(i + marker.length, end));
        out.push(
          marker.length === 2 ? <strong key={out.length}>{inner}</strong> : <em key={out.length}>{inner}</em>
        );
        i = end + marker.length;
        continue;
      }
      // An unmatched double marker is two plain characters.
      plain += marker;
      i += marker.length;
      continue;
    }
    plain += ch;
    i++;
  }
  flush();
  return out;
}
