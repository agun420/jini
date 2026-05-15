from __future__ import annotations

import ast
import json
from pathlib import Path

REQUIRED_FILES = [
    'src/prediction_engine/learning/signal_journal.py',
    'scripts/run_signal_journal.py',
    '.github/workflows/signal-journal.yml',
]


def validate_python(path: Path) -> None:
    ast.parse(path.read_text(encoding='utf-8'))


def main() -> None:
    for item in REQUIRED_FILES:
        path = Path(item)
        if not path.exists():
            raise SystemExit(f'Missing required file: {item}')
        if path.suffix == '.py':
            validate_python(path)

    print(json.dumps({
        'status': 'PASS',
        'message': 'Package 4 files are present and Python syntax is valid.',
    }, indent=2))


if __name__ == '__main__':
    main()
