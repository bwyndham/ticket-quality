"""Atlassian Document Format (Jira Cloud's rich text) to Markdown.

Covers what ticket descriptions use: paragraphs, headings, lists, task lists,
code blocks, quotes, rules, tables, panels and expand blocks. An expand block
becomes `<details><summary>title</summary> ... </details>`, so a Jira expand
titled "Agent context" is recognised as collapsed agent context.
Unknown nodes keep their text content.
"""

from __future__ import annotations

from typing import Any


def adf_to_markdown(doc: Any) -> str:
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    return _blocks(doc.get("content") or []).strip() + "\n"


def _blocks(nodes: list[dict[str, Any]], indent: str = "") -> str:
    return "".join(_block(n, indent) for n in nodes)


def _inline(nodes: list[dict[str, Any]] | None) -> str:
    out = []
    for n in nodes or []:
        t = n.get("type")
        if t == "text":
            text = n.get("text", "")
            for mark in n.get("marks") or []:
                m = mark.get("type")
                if m == "code":
                    text = f"`{text}`"
                elif m == "strong":
                    text = f"**{text}**"
                elif m == "em":
                    text = f"*{text}*"
                elif m == "strike":
                    text = f"~~{text}~~"
                elif m == "link":
                    text = f"[{text}]({(mark.get('attrs') or {}).get('href', '')})"
            out.append(text)
        elif t == "hardBreak":
            out.append("\n")
        elif t == "mention":
            out.append((n.get("attrs") or {}).get("text", "@someone"))
        elif t == "emoji":
            attrs = n.get("attrs") or {}
            out.append(attrs.get("text") or attrs.get("shortName", ""))
        elif t in ("inlineCard", "blockCard", "embedCard"):
            out.append((n.get("attrs") or {}).get("url", ""))
        elif t == "status":
            out.append(f"[{(n.get('attrs') or {}).get('text', '')}]")
        elif t == "date":
            out.append(str((n.get("attrs") or {}).get("timestamp", "")))
        else:
            out.append(_inline(n.get("content")))
    return "".join(out)


def _list(node: dict[str, Any], indent: str, ordered: bool) -> str:
    lines = []
    for i, item in enumerate(node.get("content") or [], 1):
        marker = f"{i}." if ordered else "-"
        if item.get("type") == "taskItem":
            done = (item.get("attrs") or {}).get("state") == "DONE"
            marker = f"- [{'x' if done else ' '}]"
            lines.append(f"{indent}{marker} {_inline(item.get('content')).strip()}\n")
            continue
        parts = item.get("content") or []
        first, rest = (parts[0], parts[1:]) if parts else ({}, [])
        head = _inline(first.get("content")) if first.get("type") == "paragraph" else _block(first, indent + "  ").strip()
        lines.append(f"{indent}{marker} {head.strip()}\n")
        for sub in rest:
            lines.append(_block(sub, indent + "  "))
    return "".join(lines)


def _block(n: dict[str, Any], indent: str = "") -> str:
    t = n.get("type")
    content = n.get("content") or []
    attrs = n.get("attrs") or {}
    if t == "paragraph":
        text = _inline(content)
        return f"{indent}{text}\n\n" if text.strip() else ""
    if t == "heading":
        return f"{'#' * int(attrs.get('level', 2))} {_inline(content).strip()}\n\n"
    if t == "bulletList":
        return _list(n, indent, ordered=False) + ("\n" if not indent else "")
    if t == "orderedList":
        return _list(n, indent, ordered=True) + ("\n" if not indent else "")
    if t == "taskList":
        return _list(n, indent, ordered=False) + ("\n" if not indent else "")
    if t == "codeBlock":
        return f"```{attrs.get('language') or ''}\n{_inline(content)}\n```\n\n"
    if t == "blockquote":
        inner = _blocks(content).strip()
        return "\n".join("> " + line for line in inner.split("\n")) + "\n\n"
    if t == "rule":
        return "---\n\n"
    if t in ("expand", "nestedExpand"):
        title = attrs.get("title") or "Details"
        return f"<details>\n<summary>{title}</summary>\n\n{_blocks(content).strip()}\n\n</details>\n\n"
    if t == "panel":
        return _blocks(content)
    if t == "table":
        rows = []
        for r_i, row in enumerate(content):
            cells = [_blocks(c.get("content") or []).strip().replace("\n", " ") for c in row.get("content") or []]
            rows.append("| " + " | ".join(cells) + " |")
            if r_i == 0:
                rows.append("|" + "---|" * len(cells))
        return "\n".join(rows) + "\n\n"
    if t in ("mediaSingle", "mediaGroup", "media"):
        return "[attachment]\n\n"
    if content:
        return _blocks(content, indent)
    return _inline([n])


__all__ = ["adf_to_markdown"]
