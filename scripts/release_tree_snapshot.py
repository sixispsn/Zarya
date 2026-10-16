"""Read-only fingerprint of application sources (never user data or secrets)."""
import hashlib
import json
from pathlib import Path

root = Path('/app')
files = {}
for folder in ('app', 'demo', 'legacy'):
    for path in sorted((root / folder).rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(files, sort_keys=True))
