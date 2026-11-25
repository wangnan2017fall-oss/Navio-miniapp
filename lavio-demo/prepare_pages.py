"""Prepare the verified, browser-local LAVIO demo for GitHub Pages.

First bootstrap verifies every public asset against the supplied SHA-256 manifest.
The generated site is then committed so subsequent Pages builds use GitHub alone.
"""
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import re
import shutil
import urllib.request
import urllib.parse

def build(manifest_path, output, local_source=None):
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    spec = json.loads(manifest_bytes)
    base = spec['base_path']
    assert base == '/Navio-miniapp/'
    assert spec['source_origin'] == 'https://lavio-health-demo.wangnan2017fall.chatgpt.site'
    output = Path(output)
    marker = hashlib.sha256(manifest_bytes).hexdigest()
    if (output / '.manifest-sha256').exists() and (output / '.manifest-sha256').read_text() == marker:
        print('Using the complete demo already committed in GitHub.')
        return
    output.mkdir(parents=True, exist_ok=True)

    def materialize(entry):
        path = PurePosixPath(entry['path'])
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('Unsafe asset path')
        if 'inline_text' in entry:
            data = entry['inline_text'].encode('utf-8')
        elif local_source:
            data = (Path(local_source) / path).read_bytes()
        else:
            url = spec['source_origin'] + '/' + urllib.parse.quote(path.as_posix())
            request = urllib.request.Request(url, headers={'User-Agent': 'LAVIO-GitHub-Pages-bootstrap/1.0'})
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.url.startswith(spec['source_origin'] + '/'):
                    raise ValueError('Unexpected external redirect')
                data = response.read()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Asset verification failed: ' + path.as_posix())
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(materialize, spec['files']))

    for file in output.rglob('*'):
        if not file.is_file() or file.suffix not in {'.html', '.js', '.css', '.json'}:
            continue
        text = file.read_text()
        # Rebase assets, without rewriting the application's /pages/... hash routes.
        for quote in ['"', "'", '`']:
            text = text.replace(quote+'/static/', quote+base+'static/')
            text = text.replace(quote+'/assets/', quote+base+'assets/')
        if file.suffix == '.js':
            text = text.replace('function(e){return"/"+e}(n)', 'function(e){return"'+base+'"+e}(n)')
            text = text.replace('router:{mode:"hash",base:"/",assets:', 'router:{mode:"hash",base:"'+base+'",assets:')
        if file.suffix == '.css':
            text = re.sub(r'url\(([^\S\r\n]*[\"\']?)/(?!/)', lambda m: 'url('+m.group(1)+base, text)
        file.write_text(text)

    # Keep the complete desktop phone preview as the first page.
    # app.html is the unchanged application entry apart from the static asset base.
    app = (output/'index.html').read_text()
    (output/'app.html').write_text(app)
    preview = (output/'preview.html').read_text()
    preview = preview.replace('src="/#/', 'src="'+base+'app.html#/')
    preview = preview.replace('href="/#/', 'href="'+base+'app.html#/')
    preview = preview.replace("return '/?ui='", "return '"+base+"app.html?ui='")
    preview = preview.replace("href='/'+h", "href='"+base+"app.html'+h")
    preview = preview.replace(spec['source_origin']+'/demo-article.html', base+'demo-article.html')
    preview = preview.replace('http://127.0.0.1:48100/demo-article.html', base+'demo-article.html')
    (output/'preview.html').write_text(preview)
    (output/'index.html').write_text(preview)
    (output/'.nojekyll').write_text('')
    (output/'.manifest-sha256').write_text(marker)
    assert '127.0.0.1' not in preview
    assert len(json.loads(re.search(r'const routes=(\[.*?\]);const groupOrder=', preview).group(1))) == 58
    assert 'iframe' in preview and base+'app.html' in preview
    print('Prepared 58 page entries at '+base+'; all assets verified.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--local-source')
    args = parser.parse_args()
    build(args.manifest, args.output, args.local_source)
