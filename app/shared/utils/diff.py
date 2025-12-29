"""Utility helpers for building text and HTML diffs."""

from __future__ import annotations

import difflib
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "dict_to_text",
    "diff_html_from_texts",
    "diff_html_from_dicts",
]


def _flatten_mapping(
    data: Mapping[Any, Any],
    *,
    parent_key: str = "",
    sep: str = ".",
) -> Dict[str, Any]:
    """Flatten nested mapping keys into ``dot`` notation."""
    items: Dict[str, Any] = {}
    for key, value in data.items():
        key_str = str(key)
        new_key = f"{parent_key}{sep}{key_str}" if parent_key else key_str
        if isinstance(value, Mapping):
            items.update(_flatten_mapping(value, parent_key=new_key, sep=sep))
        else:
            items[new_key] = value
    return items


def _should_ignore(key: str, prefixes: Optional[Iterable[str]]) -> bool:
    return bool(prefixes) and any(key.startswith(prefix) for prefix in prefixes)


def dict_to_text(
    data: Mapping[Any, Any],
    ignore_prefixes: Optional[List[str]] = None,
    rename_fields: Optional[Dict[str, str]] = None,
) -> str:
    """
    Flatten the mapping and render it as sorted text: one line per ``<key>: <value>``.
    """
    flattened = _flatten_mapping(data)

    if rename_fields:
        renamed: Dict[str, Any] = {}
        for key, value in flattened.items():
            renamed[rename_fields.get(key, key)] = value
        flattened = renamed

    lines = []
    for key in sorted(flattened.keys(), key=lambda item: item):
        if _should_ignore(key, ignore_prefixes):
            continue
        lines.append(f"{key}: {flattened[key]}")

    return "\n".join(lines)


def diff_html_from_texts(
    t1: str,
    t2: str,
    fromdesc: str = "t1",
    todesc: str = "t2",
    full_document: bool = True,
) -> str:
    """
    Build an HTML diff from two multi-line text blocks using ``difflib``.
    """
    lines1 = t1.splitlines()
    lines2 = t2.splitlines()
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    unique_id = str(uuid.uuid4())[:8]

    diff_content = []
    line_num1 = 0
    line_num2 = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                diff_content.append(
                    {
                        "type": "equal",
                        "line1": line_num1 + 1,
                        "line2": line_num2 + 1,
                        "content1": lines1[i],
                        "content2": lines2[j1 + (i - i1)],
                    }
                )
                line_num1 += 1
                line_num2 += 1
        elif tag == "delete":
            for i in range(i1, i2):
                diff_content.append(
                    {
                        "type": "delete",
                        "line1": line_num1 + 1,
                        "line2": None,
                        "content1": lines1[i],
                        "content2": "",
                    }
                )
                line_num1 += 1
        elif tag == "insert":
            for j in range(j1, j2):
                diff_content.append(
                    {
                        "type": "insert",
                        "line1": None,
                        "line2": line_num2 + 1,
                        "content1": "",
                        "content2": lines2[j],
                    }
                )
                line_num2 += 1
        elif tag == "replace":
            max_lines = max(i2 - i1, j2 - j1)
            for offset in range(max_lines):
                content1 = lines1[i1 + offset] if i1 + offset < i2 else ""
                content2 = lines2[j1 + offset] if j1 + offset < j2 else ""
                line1_num = line_num1 + 1 if i1 + offset < i2 else None
                line2_num = line_num2 + 1 if j1 + offset < j2 else None

                diff_content.append(
                    {
                        "type": "replace",
                        "line1": line1_num,
                        "line2": line2_num,
                        "content1": content1,
                        "content2": content2,
                    }
                )
                if i1 + offset < i2:
                    line_num1 += 1
                if j1 + offset < j2:
                    line_num2 += 1

    equal_line_class = f"equal_line_{unique_id}"
    line_number_style = (
        "padding:0;width:36px;text-align:center;font-size:10px;"
        "color:#94a3b8;background-color:#1e293b;vertical-align:middle;"
        "font-family:Monaco,Menlo,Consolas,monospace;line-height:1.4;"
    )
    content_base_style = (
        "padding:4px 8px;font-family:Monaco,Menlo,Consolas,monospace;"
        "font-size:12px;line-height:1.4;white-space:pre-wrap;word-break:break-word;"
        "vertical-align:top;"
    )
    diff_style_map = {
        "equal": "color:#e2e8f0;",
        "delete": "background-color:rgba(239,68,68,0.18);color:#fecaca;",
        "insert": "background-color:rgba(34,197,94,0.18);color:#bbf7d0;",
        "replace": "background-color:rgba(234,179,8,0.18);color:#facc15;",
    }

    rows: List[str] = []
    for item in diff_content:
        line1_num = item["line1"] or ""
        line2_num = item["line2"] or ""
        content1 = item["content1"]
        content2 = item["content2"]
        diff_type = item["type"]
        equal_class = equal_line_class if diff_type == "equal" else ""
        content_style = content_base_style + diff_style_map.get(diff_type, "")

        row_lines = [
            f"                <tr class='{equal_class}' style='border-bottom:1px solid rgba(148,163,184,0.08);'>",
            f"                    <td style='{line_number_style}'>{line1_num}</td>",
            f"                    <td style='{content_style}'>{content1}</td>",
            f"                    <td style='{line_number_style}'>{line2_num}</td>",
            f"                    <td style='{content_style}'>{content2}</td>",
            "                </tr>",
        ]
        rows.append("\n".join(row_lines))

    rows_html = "\n".join(rows)
    left_toggle_button_id = f"toggle-equal-{unique_id}-left"
    right_toggle_button_id = f"toggle-equal-{unique_id}-right"

    header_html = (
        "            <thead>\n"
        "                <tr style='background-color:#0f172a;'>\n"
        f"                    <th scope='col' style='padding:6px 8px;width:48px;text-align:center;font-size:11px;font-weight:600;color:#e2e8f0;'>"
        f"                        <button id='{left_toggle_button_id}' type='button' aria-label='Toggle equal lines' aria-pressed='false' data-diff-toggle"
        " style='display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;background-color:#1f2937;color:#f8fafc;border:1px solid #334155;font-weight:700;font-size:14px;line-height:1;'>-</button>"
        "                    </th>\n"
        f"                    <th scope='col' style='padding:6px 8px;font-size:12px;font-weight:600;color:#f8fafc;text-align:left;text-transform:uppercase;letter-spacing:0.05em;'>{fromdesc}</th>\n"
        f"                    <th scope='col' style='padding:6px 8px;width:48px;text-align:center;font-size:11px;font-weight:600;color:#e2e8f0;'>"
        f"                        <button id='{right_toggle_button_id}' type='button' aria-label='Toggle equal lines' aria-pressed='false' data-diff-toggle"
        " style='display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;background-color:#1f2937;color:#f8fafc;border:1px solid #334155;font-weight:700;font-size:14px;line-height:1;'>-</button>"
        "                    </th>\n"
        f"                    <th scope='col' style='padding:6px 8px;font-size:12px;font-weight:600;color:#f8fafc;text-align:left;text-transform:uppercase;letter-spacing:0.05em;'>{todesc}</th>\n"
        "                </tr>\n"
        "            </thead>\n"
    )

    fragment_script = (
        "    <script>\n"
        "        (function() {\n"
        "            if (window.__cwDiffToggleInit) {\n"
        "                return;\n"
        "            }\n"
        "            window.__cwDiffToggleInit = true;\n"
        "            document.addEventListener('click', function(event) {\n"
        "                const button = event.target.closest('[data-diff-toggle]');\n"
        "                if (!button) {\n"
        "                    return;\n"
        "                }\n"
        "                const root = button.closest('[data-diff-id]');\n"
        "                if (!root) {\n"
        "                    return;\n"
        "                }\n"
        "                const equalClass = root.getAttribute('data-equal-class');\n"
        "                if (!equalClass) {\n"
        "                    return;\n"
        "                }\n"
        "                const currentlyHidden = root.getAttribute('data-equal-hidden') === 'true';\n"
        "                const nextHidden = !currentlyHidden;\n"
        "                root.setAttribute('data-equal-hidden', nextHidden);\n"
        "                root.querySelectorAll('.' + equalClass).forEach(function(row) {\n"
        "                    row.style.display = nextHidden ? 'none' : '';\n"
        "                });\n"
        "                root.querySelectorAll('[data-diff-toggle]').forEach(function(btn) {\n"
        "                    btn.textContent = nextHidden ? '+' : '-';\n"
        "                    btn.setAttribute('aria-pressed', nextHidden ? 'true' : 'false');\n"
        "                });\n"
        "            });\n"
        "        })();\n"
        "    </script>"
    )

    container_id = f"diff-container-{unique_id}"

    table_block = (
        f"    <div id='{container_id}' class='diff-scroll overflow-y-auto' data-diff-id='{unique_id}' data-equal-hidden='false' data-equal-class='{equal_line_class}'"
        " style='background-color:#111827;overflow-y:auto;overflow-x:hidden;max-height:450px;margin:0;'>\n"
        "        <table style='width:100%;border-collapse:collapse;'>\n"
        f"{header_html}"
        "            <tbody>\n"
        f"{rows_html}\n"
        "            </tbody>\n"
        "        </table>\n"
        f"{fragment_script}\n"
        "    </div>\n"
        f"    <style>#{container_id}::-webkit-scrollbar{{width:0;height:0;background:transparent;}}</style>"
    )

    if not full_document:
        return table_block.strip()

    header_block = (
        "            <div class='bg-gradient-to-r from-blue-600 to-purple-600 text-white px-6 py-4'>\n"
        "                <div class='flex items-center justify-between'>\n"
        "                    <div>\n"
        "                        <h1 class='text-2xl font-bold'>Diff Comparison</h1>\n"
        f"                        <p class='text-blue-100 mt-1'>{fromdesc} vs {todesc}</p>\n"
        "                    </div>\n"
        "                </div>\n"
        "            </div>"
    )

    legend_block = (
        "            <div class='bg-gray-700 px-6 py-4 border-t border-gray-600'>\n"
        "                <div class='flex items-center justify-between text-sm text-gray-300'>\n"
        "                    <div class='flex items-center space-x-4'>\n"
        "                        <div class='flex items-center'>\n"
        "                            <div class='w-3 h-3 bg-green-500 rounded mr-2'></div>\n"
        "                            <span>Added</span>\n"
        "                        </div>\n"
        "                        <div class='flex items-center'>\n"
        "                            <div class='w-3 h-3 bg-red-500 rounded mr-2'></div>\n"
        "                            <span>Removed</span>\n"
        "                        </div>\n"
        "                        <div class='flex items-center'>\n"
        "                            <div class='w-3 h-3 bg-yellow-500 rounded mr-2'></div>\n"
        "                            <span>Modified</span>\n"
        "                        </div>\n"
        "                    </div>\n"
        "                    <div class='text-xs'>\n"
        "                        Generated with difflib + Custom Renderer\n"
        "                    </div>\n"
        "                </div>\n"
        "            </div>"
    )

    content_block = (
        "    <div class='container mx-auto px-4 py-8'>\n"
        "        <div class='bg-gray-800 shadow-lg overflow-hidden'>\n"
        f"{header_block}\n"
        "            <div class='p-6'>\n"
        f"{table_block}\n"
        "            </div>\n"
        f"{legend_block}\n"
        "        </div>\n"
        "    </div>"
    )

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diff: {fromdesc} vs {todesc}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .diff-table {{
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 10px;
            line-height: 1.3;
            width: 100%;
            border-collapse: collapse;
            background-color: #1f2937;
        }}
        .diff-table td {{
            padding: 4px 8px;
            vertical-align: top;
            border: none;
        }}
        .diff-table thead th {{
            padding: 6px 8px;
            font-weight: 600;
        }}
        .diff-line {{
            white-space: pre-wrap;
            word-wrap: break-word;
            word-break: break-all;
        }}
        .line-number {{
            width: 40px;
            text-align: center;
            font-size: 8px;
            color: #9ca3af;
            background-color: #374151;
        }}
        .content-left {{
            width: 48%;
            background-color: #1f2937;
        }}
        .content-right {{
            width: 48%;
            background-color: #1f2937;
        }}
        .header-row {{
            background-color: #111827;
        }}
        .header-cell {{
            color: #e5e7eb;
            text-align: left;
        }}
        .header-title {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .toggle-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px;
            height: 20px;
            background-color: #374151;
            color: #f3f4f6;
            border: 1px solid #4b5563;
            cursor: pointer;
            font-weight: 700;
            font-size: 14px;
            line-height: 1;
            transition: background-color 0.2s ease, color 0.2s ease;
        }}
        .toggle-button:hover:not(:disabled) {{
            background-color: #4b5563;
        }}
        .toggle-button:disabled {{
            cursor: not-allowed;
            opacity: 0.5;
        }}
        .equal {{
            background-color: transparent;
            color: #d1d5db;
        }}
        .delete {{
            background-color: #7f1d1d;
            color: #fca5a5;
        }}
        .insert {{
            background-color: #14532d;
            color: #86efac;
        }}
        .replace {{
            background-color: #78350f;
            color: #fbbf24;
        }}
        .diff-table tbody tr:hover {{
            background-color: #374151;
        }}
        .equal-line {{
            transition: opacity 0.3s ease;
        }}
        .equal-line.hidden {{
            display: none;
        }}
        .diff-scroll::-webkit-scrollbar {{
            width: 0px;
            height: 0px;
        }}
        .diff-scroll::-webkit-scrollbar-track {{
            background: transparent;
        }}
        .diff-scroll::-webkit-scrollbar-thumb {{
            background: transparent;
        }}
        .diff-scroll::-webkit-scrollbar-thumb:hover {{
            background: transparent;
        }}
        .diff-scroll {{
            scrollbar-width: none;
            -ms-overflow-style: none;
        }}
    </style>
</head>
<body class="bg-gray-900 min-h-screen">
{content_block}
</body>
</html>
"""

    return html.strip()


def diff_html_from_dicts(
    d1: Mapping[Any, Any],
    d2: Mapping[Any, Any],
    fromdesc: str = "t1",
    todesc: str = "t2",
    ignore_prefixes_d1: Optional[List[str]] = None,
    ignore_prefixes_d2: Optional[List[str]] = None,
    rename_fields_d1: Optional[Dict[str, str]] = None,
    rename_fields_d2: Optional[Dict[str, str]] = None,
    full_document: bool = True,
) -> Tuple[str, str, str]:
    """
    Generate flattened text representations and HTML diff from mappings.
    """
    t1 = dict_to_text(d1, ignore_prefixes_d1, rename_fields_d1)
    t2 = dict_to_text(d2, ignore_prefixes_d2, rename_fields_d2)
    html = diff_html_from_texts(t1, t2, fromdesc, todesc, full_document=full_document)
    return t1, t2, html
