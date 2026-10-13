"""Versioned CSS/JS URLs and cached gzip responses for shared panel assets."""
import gzip
import hashlib
from pathlib import Path
from flask import request


def init_static_assets(app):
    assets = {}
    for path in Path(app.static_folder).rglob('*'):
        if path.suffix not in {'.css', '.js'} or not path.is_file():
            continue
        content = path.read_bytes()
        name = path.relative_to(app.static_folder).as_posix()
        assets[name] = (hashlib.sha256(content).hexdigest()[:16], gzip.compress(content, mtime=0))

    @app.url_defaults
    def version_static(endpoint, values):
        if endpoint == 'static' and values.get('filename') in assets:
            values.setdefault('v', assets[values['filename']][0])

    @app.after_request
    def serve_compressed_static(response):
        if request.endpoint != 'static' or response.status_code != 200 or 'Range' in request.headers:
            return response
        asset = assets.get((request.view_args or {}).get('filename'))
        if not asset:
            return response
        version, compressed = asset
        response.vary.add('Accept-Encoding')
        if request.args.get('v') == version:
            response.cache_control.public = True
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        if request.accept_encodings['gzip'] > 0 and 'Content-Encoding' not in response.headers:
            response.direct_passthrough = False
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.set_etag(version + '-gzip')
            response.make_conditional(request)
        return response
