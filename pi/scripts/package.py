"""Build shareable runtime and standalone repository archives without installing."""
import json
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "package.json").read_text())
dist = root / "dist"
dist.mkdir(exist_ok=True)
subprocess.run(
    ["npm", "pack", "--ignore-scripts", "--pack-destination", str(dist)],
    cwd=root, check=True,
)
archive = dist / f"{manifest['name']}-{manifest['version']}-source.tar.gz"
excluded = {"dist", "verification", "node_modules", ".git", "__pycache__", "tests"}
with tarfile.open(archive, "w:gz") as bundle:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts) or path.is_symlink():
            continue
        if path.is_file():
            bundle.add(path, arcname=Path(manifest["name"]) / relative, recursive=False)
print(archive)
