"""Artificial external command; copied as an executable .toy input by the harness.

It intentionally does not write an index. Its only responsibilities are process
behavior and an independent receipt proving which selected input actually ran.
"""

from pathlib import Path
import json
import os
import sys


source = Path(__file__).resolve()
settings = json.loads((source.parent / "scenario.json").read_text(encoding="utf-8"))
mode = settings[source.name]
exit_code = 7 if mode == "exit7" else 0
if mode == "exit7":
    print("TOY_EXTERNAL_NONZERO", flush=True)
elif mode == "stderr-zero":
    print("TOY_EXTERNAL_STDERR_WARNING", file=sys.stderr, flush=True)
elif mode != "silent-zero":
    raise ValueError(f"Unknown fixture mode: {mode}")

source.with_suffix(".receipt.json").write_text(json.dumps({
    "mode": mode, "exit_code": exit_code, "source": str(source),
    "cwd": str(Path.cwd()), "pid": os.getpid(), "arguments": sys.argv[1:],
}, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(exit_code)
