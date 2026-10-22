# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic, nonconfidential header-only microbenchmark; NOT import fidelity."""
import ast
import io
import json
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[2]
tree = ast.parse((ROOT / "source/import_max.py").read_text(encoding="utf-8"))
nodes = [n for n in tree.body if isinstance(n, ast.Assign)
         and any(isinstance(t, ast.Name) and t.id in {"MAGIC", "MIN_FILE_SIZE"} for t in n.targets)]
nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "is_maxfile"]
ns = {"io": io}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "<isolated-legacy-header-probe>", "exec"), ns)
magic = ns["MAGIC"]
fixtures = {
    "synthetic-header-only": magic + bytes(1536 - len(magic)),
    "synthetic-nonmax": b"NOT-MAX!" + bytes(1536 - 8),
    "synthetic-short": b"X" * 8,
}
results = []
for label, payload in fixtures.items():
    observations = []
    for _ in range(100):
        start = time.perf_counter_ns()
        result = ns["is_maxfile"](io.BytesIO(payload))
        observations.append(time.perf_counter_ns() - start)
    results.append({"fixture": label, "size_bytes": len(payload),
                    "header_recognized": result,
                    "median_header_probe_ns": int(statistics.median(observations))})
print(json.dumps({"benchmark": "header-only; NOT full MAX import",
                  "real_scene_import": "not_run_no_legal_fixture", "samples": results}, indent=2))
