from __future__ import annotations

import json
import py_compile
from pathlib import Path

FILES = [
    "src/prediction_engine/catalysts/sec_catalyst_scanner.py",
    "src/prediction_engine/catalysts/enrich_signal_dashboard_with_sec.py",
    "scripts/run_sec_catalyst_scanner.py",
]

for file in FILES:
    py_compile.compile(file, doraise=True)

print(json.dumps({"status": "PASS", "validated_files": FILES}, indent=2))
