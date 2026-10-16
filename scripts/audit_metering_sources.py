"""Re-fetch manufacturer evidence without silently updating the catalogue.

Changed bytes require a human dimensional review; HTTP 200 alone is not one.
Run explicitly, never during a user's offline calculation.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def fetch_source(item, output):
    ident, source = item
    url = urllib.parse.quote(source["url"], safe=":/?=&%")
    result = dict(id=ident, url=source["url"], previous_sha256=source.get("sha256"))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Zarya-source-review/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read(35_000_001)
        if len(data) > 35_000_000:
            raise ValueError("Source exceeds review limit")
        digest = hashlib.sha256(data).hexdigest()
        pdf = data.startswith(b"%PDF")
        result.update(sha256=digest, bytes=len(data), is_pdf=pdf,
                      status="unchanged" if digest == source.get("sha256") else "review_required")
        (output / (ident + (".pdf" if pdf else ".html"))).write_bytes(data)
    except Exception as exc:
        result.update(status="unavailable", error=str(exc))
    return result


if __name__ == "__main__":
    output = ROOT / "tmp" / "metering-source-review-20261012"
    output.mkdir(parents=True, exist_ok=True)
    sources = json.loads((ROOT / "app/data/metering_products.json").read_text())["sources"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda item: fetch_source(item, output), sources.items()))
    (output / "review.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    for row in rows:
        print(row["id"], row["status"], row.get("bytes", ""))
