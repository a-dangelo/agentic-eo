"""Check the notebook's setup cell without making API calls or printing secrets."""

import contextlib
import io
import json
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
notebook = json.loads(Path("START_HERE.ipynb").read_text())
setup = next(cell for cell in notebook["cells"] if cell["cell_type"] == "code")
namespace = {"__name__": "__main__"}
with contextlib.redirect_stdout(io.StringIO()):
    exec("".join(setup["source"]), namespace)
assert {"Agent", "settings", "ask", "eve_llm", "local_server_client"} <= namespace.keys()
print("PASS: notebook setup and helper imports (no API calls).")
