import hashlib
import io
import tarfile

import pytest

from scripts.verify_backup_restore import restore


def archive(tmp_path, entries):
    path = tmp_path / "backup.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            tar.addfile(member, io.BytesIO(data) if member.size else None)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_restores_every_file_without_clobbering_source(tmp_path):
    path, checksum = archive(tmp_path, [
        ("./aabbccddee.meta", b"Test|date|hash", tarfile.REGTYPE),
        ("./aabbccddee.yaml", b"{}", tarfile.REGTYPE),
        ("./_studio/abc/draft.json", b'{"revision":0}', tarfile.REGTYPE),
        ("./_studio/abc/file.pdf", b"%PDF-test", tarfile.REGTYPE),
    ])
    target = tmp_path / "restore"
    result = restore(path, target, checksum)
    assert result["verified"] and result["files"] == 4 and result["projects"] == 1
    assert result["studio_drafts"] == result["json_parsed"] == result["pdf_files"] == 1
    assert (target / "aabbccddee.yaml").stat().st_mode & 0o777 == 0o600
    assert target.stat().st_mode & 0o777 == 0o700
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    with pytest.raises(ValueError, match="must not exist"):
        restore(path, target, checksum)


@pytest.mark.parametrize("name,kind", [
    ("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
    ("link", tarfile.SYMTYPE), ("hardlink", tarfile.LNKTYPE), ("device", tarfile.CHRTYPE),
])
def test_unsafe_entries_do_not_create_destination(tmp_path, name, kind):
    path, checksum = archive(tmp_path, [(name, b"", kind)])
    with pytest.raises(ValueError, match="Unsafe"):
        restore(path, tmp_path / "restore", checksum)
    assert not (tmp_path / "restore").exists()


def test_checksum_failure_does_not_extract(tmp_path):
    path, _ = archive(tmp_path, [("file", b"data", tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="checksum"):
        restore(path, tmp_path / "restore", "0" * 64)
    assert not (tmp_path / "restore").exists()


def test_duplicate_entry_does_not_extract(tmp_path):
    path, checksum = archive(tmp_path, [("file", b"1", tarfile.REGTYPE), ("./file", b"2", tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="Duplicate"):
        restore(path, tmp_path / "restore", checksum)
