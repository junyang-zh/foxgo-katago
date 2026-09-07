"""Install official Windows OpenCL KataGo and a pinned network into ignored folders.

Run from any working directory: python scripts/setup_katago.py
Downloads remain local and are never committed. No admin rights or CUDA toolkit needed.
"""
import hashlib
import json
from pathlib import Path
import platform
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = 'v1.16.4'
ASSET = f'katago-{RELEASE}-opencl-windows-x64.zip'
NETWORK = 'kata1-b28c512nbt-s13255194368-d5935380940.bin.gz'
MODEL_URL = f'https://media.katagotraining.org/uploaded/networks/models/kata1/{NETWORK}'


def download(url, path):
    if path.exists():
        print('Already downloaded:',path.name,flush=True)
        return
    print('Downloading:',url,flush=True)
    request = urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 FoxGoKataGo/1.0'})
    partial = path.with_suffix(path.suffix+'.part')
    with urllib.request.urlopen(request,timeout=60) as src, partial.open('wb') as dest:
        while block := src.read(1024*1024):
            dest.write(block)
    partial.replace(path)


def main():
    if platform.system() != 'Windows':
        raise SystemExit('This installer targets Windows. On Linux/macOS install KataGo separately and set paths in the UI.')
    engines, models, data = [ROOT / p for p in ('engines','models','data')]
    for p in (engines,models,data):
        p.mkdir(exist_ok=True)
    archive = engines / ASSET
    engine_url = f'https://github.com/lightvector/KataGo/releases/download/{RELEASE}/{ASSET}'
    download(engine_url,archive)
    destination = engines / 'katago'
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            target = (destination/item.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('Unsafe archive member.')
        z.extractall(destination)
    model = models / NETWORK
    download(MODEL_URL,model)
    fingerprints = {str(p.relative_to(ROOT)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
                    for p in (archive,model)} if hasattr(hashlib,'file_digest') else {
                        str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (archive,model)}
    (data/'install.json').write_text(json.dumps(dict(release=RELEASE,engineUrl=engine_url,
        modelUrl=MODEL_URL,sha256=fingerprints),indent=2),encoding='utf-8')
    settings = dict(executable=str(destination/'katago.exe'),model=str(model),
        config=str(ROOT/'config'/'gtp.cfg'),visits=200,seconds=2.0,aiColor='W')
    settings_path = data/'settings.json'
    if settings_path.exists():
        previous=json.loads(settings_path.read_text('utf-8'))
        settings={**settings,**previous}
    settings_path.write_text(json.dumps(settings,indent=2),encoding='utf-8')
    print('Installed. Start the trainer, open Engine settings, then Connect engine.',flush=True)


if __name__ == '__main__':
    main()
