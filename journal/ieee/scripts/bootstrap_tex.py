"""Install an isolated pdfLaTeX toolchain beneath this paper's tools directory."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

JOURNAL=Path(__file__).resolve().parents[1]
URL='https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-linux-x86_64-v2026.10.tar.xz'
EXPECTED='4d519d6236ee6798e3ec0d8e2093d1fda01aeb267aa22c2a5586d76bcfce6566'


def main():
    with urllib.request.urlopen(urllib.request.Request(URL,headers={'User-Agent':'Journal local pdfLaTeX toolchain'}),timeout=60) as response:
        archive=response.read()
    actual=hashlib.sha256(archive).hexdigest()
    if actual!=EXPECTED:raise ValueError('Toolchain archive checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:xz') as handle:
        roots=sorted({m.name.split('/')[0] for m in handle.getmembers()})
        handle.extractall(JOURNAL/'tools',filter='data')
    (JOURNAL/'evidence/tex_toolchain.json').write_text(json.dumps({'distribution':'TinyTeX-1 / TeX Live','release':'v2026.10',
        'url':URL,'archive_sha256':actual,'archive_roots':roots,'reason':'Unmodified ieeeaccess spotcolor requires pdfLaTeX PDF primitives; Tectonic is incompatible.'},indent=2)+'\n')
    print('Isolated pdfLaTeX distribution extracted inside journal/ieee/tools:',roots)


if __name__=='__main__':main()
