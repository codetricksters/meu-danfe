from pathlib import Path

src_dir = Path("/home/leonardo/Documents/XML")
# Filenames follow the pattern NFE-{key}.xml; strip the prefix to get bare keys.
existing = {p.stem.split("-", 1)[-1] for p in src_dir.iterdir() if p.is_file()}

todo = Path("todo.csv")
out = Path("out.csv")

with todo.open() as f_in, out.open("w") as f_out:
    for line in f_in:
        # Keep the line only if none of its comma-separated fields matches a known key.
        fields = {field.strip() for field in line.split(",")}
        if fields.isdisjoint(existing):
            f_out.write(line)
