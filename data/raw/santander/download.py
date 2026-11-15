"""Stream one SEC file to disk: download.py <url> <dest_filename_in_this_folder>."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # run with `python -I`, which drops the script folder
import sec_get  # noqa: E402

url, name = sys.argv[1], sys.argv[2]
dest = Path(__file__).resolve().parent / name
part = dest.with_suffix(dest.suffix + ".part")
with sec_get.get(url, stream=True) as r:
    r.raise_for_status()
    n = 0
    with open(part, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
            n += len(chunk)
part.rename(dest)
print("saved", dest, n, "bytes")
