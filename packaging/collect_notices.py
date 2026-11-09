
"""Collect the license material installed by the Python distributions in this build."""
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys


root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for distribution in metadata.distributions():
    name = distribution.metadata["Name"]
    if not name:
        continue
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{distribution.version}")
    for entry in distribution.files or ():
        if not re.match(r"^(license|licence|copying|notice|authors)([-_.]|$)", entry.name, re.I):
            continue
        source = distribution.locate_file(entry)
        if source.is_file():
            target = root / label / Path(*entry.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
