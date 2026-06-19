#!/usr/bin/env python3
"""Generate the protocols catalog page (``protocols.html``) with version history.

Paths are resolved relative to a data-repo *root* holding ``experiments.db`` and
the output ``catalog/`` directory.
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from eln.generators.nav import render_nav

DEFAULT_DB_NAME = "experiments.db"


def markdown_to_html(text):
    """Simple markdown to HTML converter."""
    if not text:
        return ""

    # Escape HTML
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Headers
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Lists
    text = re.sub(r'^\- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # Wrap consecutive <li> in <ul>
    text = re.sub(r'(<li>.*?</li>\n)+', lambda m: '<ul>' + m.group(0) + '</ul>\n', text, flags=re.DOTALL)

    # Blockquotes
    text = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    # Tables (simple)
    lines = text.split('\n')
    in_table = False
    result = []
    for line in lines:
        if '|' in line and not line.strip().startswith('<'):
            if not in_table:
                result.append('<table border="1" style="border-collapse: collapse; margin: 1rem 0;">')
                in_table = True
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if all(c.replace('-', '').strip() == '' for c in cells):
                continue  # Skip separator line
            result.append('<tr>')
            for cell in cells:
                result.append(f'<td style="padding: 0.5rem;">{cell}</td>')
            result.append('</tr>')
        else:
            if in_table:
                result.append('</table>')
                in_table = False
            result.append(line)

    if in_table:
        result.append('</table>')

    text = '\n'.join(result)

    # Paragraphs
    text = re.sub(r'\n\n+', '</p><p>', text)
    text = '<p>' + text + '</p>'

    # Clean up empty paragraphs around block elements
    text = re.sub(r'<p>(</?(?:h[1-6]|ul|blockquote|table)>)', r'\1', text)
    text = re.sub(r'(</?(?:h[1-6]|ul|blockquote|table)>)</p>', r'\1', text)
    text = re.sub(r'<p>\s*</p>', '', text)

    return text


PROTOCOLS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Protocols - Electronic Lab Notebook</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #27313a;
            background: #eef1f4;
        }}
        .header {{
            background: #263646;
            color: white;
            padding: 1.25rem 1.5rem;
        }}
        .header h1 {{
            font-size: 1.55rem;
            margin-bottom: 0.25rem;
        }}
        .header p {{
            color: #d7e0e7;
        }}
        .nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            background: white;
            padding: 0.8rem 1.5rem;
            border-bottom: 1px solid #d7dde2;
        }}
        .nav a {{
            color: #286b9f;
            text-decoration: none;
            font-weight: 650;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 1.5rem;
        }}
        .protocol-list {{
            background: white;
            border: 1px solid #d7dde2;
            border-radius: 8px;
            padding: 1.5rem;
        }}
        .protocol-group {{
            margin-bottom: 1.5rem;
            padding: 1.5rem;
            border: 1px solid #d7dde2;
            background: #f9fbfc;
            border-radius: 8px;
        }}
        .protocol-group:last-child {{
            border-bottom: none;
        }}
        .protocol-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            padding: 0.5rem;
            border-radius: 4px;
            transition: background-color 0.2s;
        }}
        .protocol-header:hover {{
            background-color: #f3f6f8;
        }}
        .protocol-name {{
            font-size: 1.15rem;
            font-weight: 650;
            color: #24313d;
            display: flex;
            align-items: center;
        }}
        .expand-icon {{
            display: inline-block;
            margin-right: 0.75rem;
            font-size: 1rem;
            transition: transform 0.2s;
            color: #286b9f;
        }}
        .protocol-details {{
            display: none;
            margin-top: 1rem;
            padding-top: 1rem;
            border-top: 1px solid #e0e5e9;
        }}
        .latest-badge {{
            background: #e5efe9;
            color: #27735f;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
        }}
        .protocol-description {{
            color: #6a7884;
            margin-bottom: 1rem;
            font-size: 1rem;
        }}
        .version-selector {{
            margin: 1rem 0;
        }}
        .version-selector label {{
            font-weight: 600;
            margin-right: 0.5rem;
        }}
        .version-selector select {{
            padding: 0.5rem 0.65rem;
            border: 1px solid #b8c3cc;
            border-radius: 6px;
            font-size: 0.95rem;
        }}
        .protocol-content {{
            background: #f9fbfc;
            padding: 1.5rem;
            border-radius: 4px;
            border-left: 4px solid #2d6f9f;
            margin-top: 1rem;
            line-height: 1.8;
        }}
        .protocol-content h1 {{
            font-size: 1.8rem;
            margin-top: 1.5rem;
            margin-bottom: 1rem;
            color: #24313d;
        }}
        .protocol-content h2 {{
            font-size: 1.5rem;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            color: #53616d;
        }}
        .protocol-content h3 {{
            font-size: 1.2rem;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            color: #53616d;
        }}
        .protocol-content ul {{
            margin: 0.5rem 0 0.5rem 2rem;
        }}
        .protocol-content li {{
            margin-bottom: 0.25rem;
        }}
        .protocol-content blockquote {{
            border-left: 3px solid #2d6f9f;
            padding-left: 1rem;
            margin: 1rem 0;
            color: #53616d;
            background: white;
            padding: 0.5rem 1rem;
            border-radius: 4px;
        }}
        .protocol-content table {{
            width: 100%;
            margin: 1rem 0;
        }}
        .protocol-meta {{
            display: flex;
            gap: 2rem;
            margin-top: 1rem;
            font-size: 0.9rem;
            color: #6a7884;
        }}
        .protocol-meta .label {{
            font-weight: 600;
        }}
        .no-protocols {{
            text-align: center;
            padding: 3rem;
            color: #6a7884;
        }}
        .footer {{
            text-align: center;
            padding: 1.5rem;
            color: #6a7884;
            font-size: 0.85rem;
            margin-top: 2rem;
        }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <h1>Protocol Documentation</h1>
        <p>Versioned protocols for spheroid experiments</p>
    </div>

    {nav}

    <div class="container">
        <div class="protocol-list">
            {protocols_html}
        </div>
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>

    <script>
        const protocolVersions = {protocols_json};

        function toggleProtocol(protocolId) {{
            const detailsDiv = document.getElementById(`details-${{protocolId}}`);
            const icon = document.getElementById(`icon-${{protocolId}}`);

            if (detailsDiv.style.display === 'none' || detailsDiv.style.display === '') {{
                detailsDiv.style.display = 'block';
                icon.textContent = '▼';
            }} else {{
                detailsDiv.style.display = 'none';
                icon.textContent = '▶';
            }}
        }}

        function changeVersion(protocolName, selectElement) {{
            const versionId = selectElement.value;
            const protocol = protocolVersions[protocolName].find(p => p.id == versionId);

            if (protocol) {{
                const contentDiv = document.getElementById(`content-${{protocolName}}`);
                const metaDiv = document.getElementById(`meta-${{protocolName}}`);

                contentDiv.innerHTML = protocol.content ?
                    `<pre>${{protocol.content}}</pre>` :
                    '<p style="color: #999;">No content available</p>';

                let metaHtml = `<div><span class="label">Version:</span> ${{protocol.version}}</div>`;
                metaHtml += `<div><span class="label">Created:</span> ${{protocol.created_at}}</div>`;
                if (protocol.file_path) {{
                    metaHtml += `<div><span class="label">File:</span> ${{protocol.file_path}}</div>`;
                }}
                metaDiv.innerHTML = metaHtml;
            }}
        }}

        // Auto-expand protocol from URL hash on page load
        window.addEventListener('DOMContentLoaded', function() {{
            const hash = window.location.hash;
            if (hash) {{
                // Extract protocol ID from hash (e.g., #5 -> 5)
                const protocolId = hash.substring(1);
                const protocolGroup = document.getElementById(protocolId);

                if (protocolGroup) {{
                    // Expand the protocol
                    toggleProtocol(protocolId);

                    // Scroll to the protocol with a small delay to ensure rendering
                    setTimeout(function() {{
                        protocolGroup.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    }}, 100);
                }}
            }}
        }});
    </script>
</body>
</html>
"""


def generate_protocol_catalog(root, catalog_out=None, plugins=None):
    """Generate ``protocols.html`` from the notebook DB under *root*.

    Output is written to *catalog_out* (default ``root/catalog``).
    *plugins* (default: discovered) supply extra nav links.
    """
    root = Path(root)
    database_path = root / DEFAULT_DB_NAME
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all protocols grouped by name
    cursor.execute("""
        SELECT * FROM protocols
        ORDER BY name, created_at DESC
    """)
    all_protocols = []
    for row in cursor.fetchall():
        protocol = dict(row)
        # Decode bytes content if necessary
        if isinstance(protocol.get('content'), bytes):
            protocol['content'] = protocol['content'].decode('utf-8')
        all_protocols.append(protocol)
    conn.close()

    if not all_protocols:
        protocols_html = '<div class="no-protocols">No protocols available yet.</div>'
        protocols_json = '{}'
    else:
        # Group protocols by name
        protocol_groups = {}
        for protocol in all_protocols:
            name = protocol['name']
            if name not in protocol_groups:
                protocol_groups[name] = []
            protocol_groups[name].append(protocol)

        # Generate HTML for each protocol group
        protocols_html_list = []
        for name, versions in protocol_groups.items():
            # Get latest version
            latest = next((p for p in versions if p['is_latest']), versions[0])

            # Generate version options
            version_options = []
            for v in versions:
                selected = 'selected' if v['id'] == latest['id'] else ''
                version_options.append(f'<option value="{v["id"]}" {selected}>v{v["version"]} ({v["created_at"]})</option>')

            version_select = f"""
                <div class="version-selector">
                    <label>Version:</label>
                    <select onchange="changeVersion('{name}', this)">
                        {''.join(version_options)}
                    </select>
                </div>
            """

            content_html = markdown_to_html(latest['content']) if latest.get('content') else '<p style="color: #999;">No content available</p>'

            protocols_html_list.append(f"""
                <div class="protocol-group" id="{latest['id']}">
                    <div class="protocol-header" onclick="toggleProtocol('{latest['id']}')">
                        <div class="protocol-name">
                            <span class="expand-icon" id="icon-{latest['id']}">▶</span>
                            {name}
                        </div>
                        <div class="latest-badge">LATEST: v{latest['version']}</div>
                    </div>
                    <div class="protocol-details" id="details-{latest['id']}">
                        {f'<div class="protocol-description">{latest["description"]}</div>' if latest.get('description') else ''}
                        {version_select}
                        <div class="protocol-content" id="content-{name}">
                            {content_html}
                        </div>
                        <div class="protocol-meta" id="meta-{name}">
                            <div><span class="label">Version:</span> {latest['version']}</div>
                            <div><span class="label">Created:</span> {latest['created_at']}</div>
                            {f'<div><span class="label">File:</span> {latest["file_path"]}</div>' if latest.get('file_path') else ''}
                        </div>
                    </div>
                </div>
            """)

        protocols_html = '\n'.join(protocols_html_list)
        protocols_json = json.dumps(protocol_groups)

    # Generate final HTML
    html = PROTOCOLS_HTML_TEMPLATE.format(
        nav=render_nav(plugins),
        protocols_html=protocols_html,
        protocols_json=protocols_json,
    )

    # Write to file
    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "protocols.html"
    output_file.write_text(html)

    print(f"Protocol catalog generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds experiments.db)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_protocol_catalog(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
