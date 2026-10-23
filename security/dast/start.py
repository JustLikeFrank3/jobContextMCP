"""Start the real HTTP app using only disposable, synthetic CI state."""
import json
import os
from pathlib import Path

root = Path('/sandbox')
for name in ('data', 'resumes', 'leetcode'):
    (root / name).mkdir(parents=True, exist_ok=True)
config = root / 'config.json'
config.write_text(json.dumps({
    'data_folder': str(root / 'data'),
    'resume_folder': str(root / 'resumes'),
    'leetcode_folder': str(root / 'leetcode'),
    'side_project_folders': [],
}), encoding='utf-8')
os.environ.update({
    'JOBCONTEXT_CONFIG': str(config),
    'HOST': '0.0.0.0', 'PORT': '8000', 'ENABLE_REMOTE': 'true',
    # Public-surface scan; a known test-only value keeps auth enforcement on.
    'API_KEY': 'dast-synthetic-not-a-secret',
})
from transport.http.main import main  # noqa: E402

main()
