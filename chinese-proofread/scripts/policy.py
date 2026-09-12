"""Deployment defaults, not language-quality guarantees (Python 3.8+)."""
CHAT_CHARS = 500
REVIEW_INPUT_CHARS = 12000
CONSISTENCY_INPUT_CHARS = 16000


def consistency_required(manifest):
    # Older workspaces retain their original contract.
    return manifest.get('consistency_required', manifest.get('long_document', False))
