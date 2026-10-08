import pymupdf
import re
from pathlib import Path

WD = Path("/home/leonardo/Downloads/OneDrive_2026-04-25/02. Nacional/")


def extract_key(file: Path):
    keys = []
    doc = pymupdf.open(file)
    for page in doc:
        page_text = page.get_text()
        matches = re.findall(r"\d(?:[ .-]*\d){43}", page_text)
        keys.extend(re.sub(r"[ .-]+", "", m) for m in matches)
    return keys


def save_keys(filename, keys):
    with open(filename, "a") as f:
        f.writelines(key + "\n" for key in keys)


def main():
    for file in WD.rglob("*"):
        if file.is_file() and file.suffix.lower() == ".pdf":
            keys = extract_key(file)
            save_keys("chaves_nfe.csv", keys)


if __name__ == "__main__":
    main()
