"""Read-only transport checks; not PDF validation or release authorization."""
import os
from pathlib import Path
import stat


def package_member_name(name):
    return (isinstance(name, str) and bool(name) and name not in {".", ".."}
            and Path(name).name == name and "\\" not in name and "\x00" not in name)


def read_package_member(path):
    """Read one stable nonempty regular file before any HTTP response is sent."""
    if path is None:
        raise OSError("Package member unavailable")
    path = Path(path)
    if not path.is_file():
        raise OSError("Package member is not a regular file")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise OSError("Package member is empty or not a regular file")
        content = stream.read()
        after = os.fstat(stream.fileno())
    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    if len(content) != before.st_size or identity(before) != identity(after):
        raise OSError("Package member changed during reading")
    return content
