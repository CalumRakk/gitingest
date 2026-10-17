"""Utilities for extracting tagged content ranges from files."""

from __future__ import annotations

import re

# Regular expression resilient to indentation, comment types, and unclosed open tags
TAG_PATTERN = re.compile(
    r"^[ \t]*(?P<comment>#|//|--|/\*|<!--|;)?[ \t]*<project_context>[ \t]*(?:\*/|-->)?[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"(?:^[ \t]*(?:#|//|--|/\*|<!--|;)?[ \t]*</project_context>[ \t]*(?:\*/|-->)?[ \t]*\r?$|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)


def _get_omitted_placeholder(comment_symbol: str | None) -> str:
    """Generate an omission placeholder that matches the file's language."""
    # TODO: add support for other languages
    if not comment_symbol:
        return "... [código omitido fuera de <project_context>] ..."

    comment = comment_symbol.strip()
    if comment == "/*":
        return "/* ... [código omitido fuera de <project_context>] ... */"
    if comment == "<!--":
        return "<!-- ... [código omitido fuera de <project_context>] ... -->"

    return f"{comment} ... [código omitido fuera de <project_context>] ..."


def extract_project_context_tags(content: str) -> tuple[str, bool]:
    """Extract only the code enclosed within <project_context>...</project_context>.

    Parameter
    ----------
    content : str
    The full content of the file read from disk.

    Return:
    ------
    tuple[str, bool]
    (processed_content, was_trimmed)
    If the file does not contain the tag, returns (content, False).

    """
    if "<project_context>" not in content.lower():
        return content, False

    matches = list(TAG_PATTERN.finditer(content))
    if not matches:
        return content, False

    comment_symbol = matches[0].group("comment")
    placeholder = _get_omitted_placeholder(comment_symbol)

    output_chunks: list[str] = []

    has_code_before = bool(content[: matches[0].start()].strip())
    if has_code_before:
        output_chunks.append(placeholder)

    for i, match in enumerate(matches):
        body = match.group("body").rstrip()
        output_chunks.append(body)

        # Is there any relevant code between this block and the next?
        if i + 1 < len(matches):
            has_code_between = bool(content[match.end() : matches[i + 1].start()].strip())
            if has_code_between:
                output_chunks.append(placeholder)

    # Is there relevant code after the last block?
    has_code_after = bool(content[matches[-1].end() :].strip())
    if has_code_after:
        output_chunks.append(placeholder)

    processed = "\n\n".join(output_chunks).strip() + "\n"
    return processed, True
