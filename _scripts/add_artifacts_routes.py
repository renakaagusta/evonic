#!/usr/bin/env python3
"""Inject artifacts API routes and SYSTEM.md injection logic into routes/agents.py"""

INSERT_MARKER = "# ==================== Agent Avatar API ===================="

CODE_TO_INSERT = r'''
# ==================== Agent Artifacts API ====================

ARTIFACTS_DIR = os.path.join(BASE_DIR, 'shared', 'agents')

def _artifacts_dir(agent_id: str) -> str:
    d = os.path.join(ARTIFACTS_DIR, agent_id, 'artifacts')
    os.makedirs(d, exist_ok=True)
    return d


_ARTIFACT_PROMPT_BLOCK = '''
You have an **Artifacts** feature that allows you to save files you produce during your work. Files are stored in your dedicated artifacts directory and are accessible via the web UI.

Available tool: `save_artifact(filename, content, mime_type?)`

Use this tool after:
- Completing analysis or generating reports
- Creating images, PDFs, or markdown documents
- Producing any output file that should be persisted

Your artifact files are stored under `shared/agents/<agent-id>/artifacts/` and can be viewed/downloaded from the Artifacts tab on your agent detail page.
'''


def _ensure_artifacts_prompt(agent_id: str, enabled: bool):
    """Inject or remove the artifacts instructions block in SYSTEM.md."""
    sp_path = _system_prompt_path(agent_id)
    block_marker = "<!-- artifacts-block -->"
    block_start = f"{block_marker}\n"
    block_end = f"\n{block_marker}"

    if not os.path.isfile(sp_path):
        return

    with open(sp_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if enabled:
        # Check if block already exists
        if block_marker in content:
            return  # Already injected, nothing to do
        # Append the block at the end
        new_content = content.rstrip() + "\n\n" + block_start + _ARTIFACT_PROMPT_BLOCK.strip() + "\n" + block_end + "\n"
        with open(sp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    else:
        # Remove the block if it exists
        if block_marker not in content:
            return  # Not injected, nothing to do
        # Remove everything between block markers (inclusive)
        import re
        new_content = re.sub(
            r'\n*' + re.escape(block_start) + r'.*?' + re.escape(block_end) + r'\n*',
            '\n',
            content,
            flags=re.DOTALL
        ).strip()
        if new_content:
            new_content += '\n'
        with open(sp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)


def _guess_artifact_type(filename: str) -> str:
    """Categorize a file by its extension."""
    ext = os.path.splitext(filename)[1].lower()
    doc_exts = {'.md', '.pdf'}
    text_exts = {'.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.log'}
    img_exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.ico'}
    snd_exts = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma'}
    if ext in doc_exts:
        return 'document'
    if ext in text_exts:
        return 'text'
    if ext in img_exts:
        return 'image'
    if ext in snd_exts:
        return 'sound'
    return 'data'


def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


@agents_bp.route('/api/agents/<agent_id>/artifacts', methods=['GET'])
def api_list_artifacts(agent_id):
    if not db.get_agent(agent_id):
        return jsonify({'error': 'Agent not found'}), 404
    arts_dir = os.path.join(ARTIFACTS_DIR, agent_id, 'artifacts')
    if not os.path.isdir(arts_dir):
        return jsonify({'files': []})

    # Parse query parameters
    sort_by = request.args.get('sort', 'newest')
    search_q = request.args.get('q', '').strip().lower()
    type_filter = request.args.get('type', '').strip().lower()

    files = []
    for fname in os.listdir(arts_dir):
        fpath = os.path.join(arts_dir, fname)
        if not os.path.isfile(fpath):
            continue
        stat = os.stat(fpath)
        art_type = _guess_artifact_type(fname)

        # Apply type filter
        if type_filter and type_filter != 'all':
            if art_type != type_filter:
                continue

        # Apply search filter
        if search_q and search_q not in fname.lower():
            continue

        files.append({
            'filename': fname,
            'size': stat.st_size,
            'size_formatted': _format_file_size(stat.st_size),
            'modified': stat.st_mtime,
            'type': art_type,
        })

    # Sort
    if sort_by == 'updated':
        files.sort(key=lambda f: f['modified'], reverse=True)
    elif sort_by == 'alpha':
        files.sort(key=lambda f: f['filename'].lower())
    elif sort_by == 'alpha_desc':
        files.sort(key=lambda f: f['filename'].lower(), reverse=True)
    else:  # newest
        files.sort(key=lambda f: f['modified'], reverse=True)

    return jsonify({'files': files})


@agents_bp.route('/api/agents/<agent_id>/artifacts/<path:filename>', methods=['GET'])
def api_get_artifact(agent_id, filename):
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    fpath = os.path.join(ARTIFACTS_DIR, agent_id, 'artifacts', filename)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'File not found'}), 404
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    if mime is None:
        mime = 'application/octet-stream'
    from flask import send_file
    return send_file(fpath, mimetype=mime, as_attachment=False)


@agents_bp.route('/api/agents/<agent_id>/artifacts/<path:filename>', methods=['DELETE'])
def api_delete_artifact(agent_id, filename):
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    fpath = os.path.join(ARTIFACTS_DIR, agent_id, 'artifacts', filename)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'File not found'}), 404
    os.remove(fpath)
    return jsonify({'success': True})


@agents_bp.route('/api/agents/<agent_id>/artifacts', methods=['POST'])
def api_save_artifact(agent_id):
    """Save an artifact file (for internal/agent use)."""
    if not db.get_agent(agent_id):
        return jsonify({'error': 'Agent not found'}), 404
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    filename = data.get('filename', '').strip()
    content = data.get('content', '')
    if not filename:
        return jsonify({'error': 'filename is required'}), 400
    if '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    arts_dir = _artifacts_dir(agent_id)
    fpath = os.path.join(arts_dir, filename)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/api/agents/<agent_id>/artifacts/toggle', methods=['POST'])
def api_toggle_artifacts(agent_id):
    """Toggle artifacts_enabled and update SYSTEM.md accordingly."""
    if not db.get_agent(agent_id):
        return jsonify({'error': 'Agent not found'}), 404
    data = request.get_json()
    enabled = data.get('enabled', True)
    db.update_agent(agent_id, {'artifacts_enabled': 1 if enabled else 0})
    _ensure_artifacts_prompt(agent_id, enabled)
    return jsonify({'success': True, 'artifacts_enabled': enabled})

'''


def main():
    with open('/workspace/routes/agents.py', 'r') as f:
        content = f.read()

    if INSERT_MARKER in content:
        # Insert before the marker
        content = content.replace(INSERT_MARKER, CODE_TO_INSERT + '\n' + INSERT_MARKER, 1)
        with open('/workspace/routes/agents.py', 'w') as f:
            f.write(content)
        print('OK - artifacts routes injected')
    else:
        print('ERROR: Marker not found')
        # Find what marker exists
        for line in content.split('\n'):
            if 'Agent Avatar' in line:
                print(f'Found: {line}')


if __name__ == '__main__':
    main()
