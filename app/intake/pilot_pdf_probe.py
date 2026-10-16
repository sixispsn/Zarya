"""Bounded PDF structure probe; no rendering, text extraction or external calls."""
import json
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    # Linux production enforces address-space limits; macOS rejects RLIMIT_AS.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    from pypdf import PdfReader
    try:
        reader = PdfReader(sys.argv[1], strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted")
        count = len(reader.pages)
        if not 1 <= count <= 2000:
            raise ValueError("pages")
        print(json.dumps({"pages": count}))
    except Exception:
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
