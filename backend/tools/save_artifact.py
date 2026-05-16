"""
Tool: save_artifact -- allows agents to save files to their artifacts directory.

Artifacts are files produced by agents during their work -- reports, analysis,
generated images, PDFs, markdown output, etc. They are stored under
shared/agents/<agent-id>/artifacts/ and are accessible via the web UI.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _artifacts_dir(agent_id: str) -> str:
    d = os.path.join(BASE_DIR, 'shared', 'agents', agent_id, 'artifacts')
    os.makedirs(d, exist_ok=True)
    return d


def execute(agent: dict, args: dict) -> dict:
    agent_id = agent.get('id', agent.get('agent_id', ''))
    if not agent_id:
        return {'error': 'Agent ID not found in context'}

    filename = args.get('filename', '').strip()
    content = args.get('content', '')
    mime_type = args.get('mime_type', '')

    if not filename:
        return {'error': 'filename is required'}

    # Security: prevent path traversal
    if '/' in filename or '\\' in filename or '..' in filename:
        return {'error': 'Invalid filename'}

    artifacts_dir = _artifacts_dir(agent_id)
    filepath = os.path.join(artifacts_dir, filename)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        stat = os.stat(filepath)
        return {
            'result': 'Artifact saved successfully',
            'filepath': filepath,
            'filename': filename,
            'size': stat.st_size,
        }
    except Exception as e:
        return {'error': f'Failed to save artifact: {str(e)}'}
