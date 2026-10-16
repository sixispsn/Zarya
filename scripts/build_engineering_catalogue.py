"""Build a portable catalogue index; no network and no calculation changes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.data.engineering_catalogue_store import export_sqlite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('output/data/zarya_engineering_catalogue.sqlite'))
    parser.add_argument('--replace',action='store_true')
    args = parser.parse_args()
    result = export_sqlite(args.output,replace=args.replace)
    print(json.dumps({'path':str(args.output.resolve()),**result},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
