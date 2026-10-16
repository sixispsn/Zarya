"""Read-only verification: only manifest files may differ from live runtime."""
import json
from pathlib import Path
import subprocess
import sys

CODE = '''
from pathlib import Path
from hashlib import sha256
import json
result={}
for root in ('app','demo','legacy'):
 for p in Path('/app',root).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
   result[str(p.relative_to('/app'))]=sha256(p.read_bytes()).hexdigest()
print(json.dumps(result))
'''


def main():
    manifest=json.loads(Path(sys.argv[1]).read_text())
    def inventory(container):
        return json.loads(subprocess.check_output(['docker','exec',container,'python','-c',CODE]))
    before=inventory('zarya-app-1');after=inventory('zarya-samara-vk-smoke')
    changes={k for k in set(before)|set(after) if before.get(k)!=after.get(k)}
    assert changes==set(manifest), (changes-set(manifest),set(manifest)-changes)
    for k,v in manifest.items():
        assert before.get(k)==v['baseline_sha256'],k
        assert after[k]==v['sha256'],k
    assert after['legacy/sp30_calculator.html']=='00a14a5b5ec9a195894db4da92e2439b6453f4e71e34e89a48c5b622e68068e4'
    print(json.dumps(dict(verified=True,changed_files=len(changes),legacy_unchanged=True)))


if __name__=='__main__':main()
