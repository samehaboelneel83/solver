import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";

/**
 * The assistant's markdown, as React elements -- never as HTML, so nothing a
 * model writes can run in the page. Headings, paragraphs, lists, tables, code
 * blocks, **bold**, *italic*, `code` and [links](...). A link to a page of the
 * app (`/domains/3/problems/7`) opens in the app; any other http(s) link opens
 * in a new tab; anything else is plain text.
 */
export default function Markdown({ text }: { text: string }) {
  return <div className="space-y-2 text-sm leading-relaxed text-slate-800">{blocks(text)}</div>;
}

function blocks(source: string): ReactNode[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${i}`;
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const fold = line.trim().match(/^<details>\s*<summary>(.*)<\/summary>$/);
    if (fold) {
      // The platform's own fold (a stop's "Technical detail"): shown closed, not as its tags (the Delta Pharma
      // trace in the browser, 10 October 2026).
      const inner: string[] = [];
      i += 1;
      while (i < lines.length && lines[i].trim() !== "</details>") inner.push(lines[i++]);
      i += 1;
      out.push(
        <details key={key} className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600">
          <summary className="cursor-pointer select-none">{fold[1]}</summary>
          <div className="mt-1 space-y-2">{blocks(inner.join("\n"))}</div>
        </details>,
      );
      continue;
    }
    if (line.trimStart().startsWith("```")) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) body.push(lines[i++]);
      i += 1;
      out.push(
        <pre key={key} className="overflow-x-auto rounded-md bg-slate-100 p-2 font-mono text-xs text-slate-800">
          {body.join("\n")}
        </pre>,
      );
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      out.push(
        <p key={key} className={heading[1].length <= 2 ? "pt-1 text-[15px] font-semibold text-slate-900" : "pt-1 font-semibold text-slate-900"}>
          {inline(heading[2])}
        </p>,
      );
      i += 1;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      out.push(table(rows, key));
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        let item = lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "");
        i += 1;
        // continuation lines, indented
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
          item += " " + lines[i].trim();
          i += 1;
        }
        items.push(item);
      }
      const List = ordered ? "ol" : "ul";
      out.push(
        <List key={key} className={`${ordered ? "list-decimal" : "list-disc"} space-y-1 ps-5`}>
          {items.map((item, n) => <li key={n}>{inline(item)}</li>)}
        </List>,
      );
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i]) && !lines[i].trimStart().startsWith("```") &&
      !/^\s*\|.*\|\s*$/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])
    ) para.push(lines[i++]);
    out.push(
      <p key={key}>
        {para.map((p, n) => <Fragment key={n}>{n > 0 && <br />}{inline(p)}</Fragment>)}
      </p>,
    );
  }
  return out;
}

function cells(row: string): string[] {
  return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function table(rows: string[], key: string): ReactNode {
  const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
  const [head, ...rest] = body;
  return (
    <div key={key} className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>{cells(head ?? "").map((c, n) => <th key={n} className="border border-slate-200 bg-slate-50 px-2 py-1 text-start font-semibold">{inline(c)}</th>)}</tr>
        </thead>
        <tbody>
          {rest.map((r, n) => (
            <tr key={n}>{cells(r).map((c, m) => <td key={m} className="border border-slate-200 px-2 py-1 align-top">{inline(c)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/g;

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const key = `i${match.index}`;
    if (match[1]) {
      out.push(<code key={key} className="rounded bg-slate-100 px-1 font-mono text-[0.85em]">{token.slice(1, -1)}</code>);
    } else if (match[2]) {
      out.push(<strong key={key} className="font-semibold">{token.slice(2, -2)}</strong>);
    } else if (match[3]) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      const [, label, href] = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/) ?? [];
      out.push(link(label ?? token, href ?? "", key));
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function link(label: string, href: string, key: string): ReactNode {
  const cls = "font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900";
  if (href.startsWith("/") && !href.startsWith("//")) {
    return <Link key={key} to={href} className={cls}>{label}</Link>;
  }
  if (/^https?:\/\//i.test(href)) {
    return <a key={key} href={href} target="_blank" rel="noreferrer noopener" className={cls}>{label}</a>;
  }
  return <Fragment key={key}>{label}</Fragment>;
}
