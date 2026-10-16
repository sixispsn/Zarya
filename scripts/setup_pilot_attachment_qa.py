"""Create disposable local identities; outputs the temporary directory, never keys."""
import os
from pathlib import Path
import tempfile

from app.intake.pilot_access import AccessStore
from reportlab.pdfgen import canvas


def main():
    root = Path(tempfile.mkdtemp(prefix="zarya-attachments-qa.", dir="/tmp"))
    for name, role in (("alice", "tester"), ("bob", "tester"), ("owner", "admin")):
        _, key = AccessStore(root / "access").issue(name, role=role, days=1)
        fd = os.open(root / (name + ".key"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(key)
    pdf = canvas.Canvas(str(root / "test.pdf"))
    pdf.drawString(60, 800, "Synthetic PDF for private pilot upload test")
    pdf.save()
    print(root)


if __name__ == "__main__":
    main()
