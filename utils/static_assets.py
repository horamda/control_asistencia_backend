"""Versioned static URLs (cache of one year, immutable) and cached gzip for text assets."""
import gzip
import hashlib
import mimetypes
from pathlib import Path
from flask import request

# Texto: se sirve comprimido. Binarios (imagenes, fuentes): ya vienen comprimidos.
TEXT_SUFFIXES = {'.css', '.js', '.svg'}
BINARY_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.woff2'}


def init_static_assets(app):
    # No todos los sistemas conocen .woff2: sin esto se serviria como octet-stream.
    mimetypes.add_type('font/woff2', '.woff2')
    assets = {}
    for path in Path(app.static_folder).rglob('*'):
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES | BINARY_SUFFIXES or not path.is_file():
            continue
        content = path.read_bytes()
        name = path.relative_to(app.static_folder).as_posix()
        compressed = gzip.compress(content, mtime=0) if suffix in TEXT_SUFFIXES else None
        assets[name] = (hashlib.sha256(content).hexdigest()[:16], compressed)

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
        if request.args.get('v') == version:
            # Flask agrega no-cache por defecto, que obliga a revalidar en cada
            # carga y anula immutable: la URL versionada nunca cambia de contenido.
            response.cache_control.no_cache = None
            response.cache_control.public = True
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        if compressed is None:
            return response
        response.vary.add('Accept-Encoding')
        if request.accept_encodings['gzip'] > 0 and 'Content-Encoding' not in response.headers:
            response.direct_passthrough = False
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.set_etag(version + '-gzip')
            response.make_conditional(request)
        return response
