"""Restore a trusted backup into a NEW private directory, verify every byte.

Never points at or overwrites the live volume. Report contains counts/hashes,
not project titles, input data, document texts or credentials.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile


def sha(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def restore(archive: Path, destination: Path, expected_sha256: str) -> dict:
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must not exist; live data cannot be overwritten")
    with archive.open("rb") as source:
        archive_hash = sha(source)
    if archive_hash != expected_sha256:
        raise ValueError("Backup checksum mismatch")
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe backup entry; only relative regular files/directories allowed")
            if path in seen:
                raise ValueError("Duplicate backup entry")
            seen.add(path)
        destination.mkdir(mode=0o700)
        # Do not preserve ownership or permissive archive modes. No links/devices.
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.extractfile(member) as original, target.open("xb") as output:
                target.chmod(0o600)
                while chunk := original.read(1024 * 1024):
                    output.write(chunk)
        count, total = 0, 0
        manifest = hashlib.sha256()
        for member in sorted(members, key=lambda item: item.name):
            if not member.isfile():
                continue
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            with source.extractfile(member) as original, target.open("rb") as recovered:
                original_hash, recovered_hash = sha(original), sha(recovered)
            if original_hash != recovered_hash or target.stat().st_size != member.size:
                raise ValueError("Restored file differs from backup")
            count += 1
            total += member.size
            manifest.update(f"{member.name}\0{member.size}\0{original_hash}\n".encode())
    suffixes = Counter(file.suffix for file in destination.rglob("*") if file.is_file())
    json_count = 0
    for path in destination.rglob("*.json"):
        json.loads(path.read_text())
        json_count += 1
    databases = 0
    for path in destination.rglob("*.sqlite3"):
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored SQLite integrity check failed")
        finally:
            db.close()
        databases += 1
    projects = [p for p in destination.rglob("*.meta") if re.fullmatch(r"[a-f0-9]{10}", p.stem)]
    # Top-level saved projects must retain their YAML partner.
    if any(not path.with_suffix(".yaml").is_file() for path in projects):
        raise ValueError("Restored project is missing its YAML")
    return {
        "verified": True, "archive_sha256": archive_hash,
        "manifest_sha256": manifest.hexdigest(), "files": count, "bytes": total,
        "projects": len(projects), "studio_drafts": sum(1 for _ in destination.rglob("draft.json")),
        "json_parsed": json_count, "sqlite_checked": databases, "pdf_files": suffixes[".pdf"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.archive, args.destination, args.sha256), indent=2))


if __name__ == "__main__":
    main()
