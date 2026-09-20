"""Load administrative alerts independently of page rendering."""
import time
from flask import Blueprint, jsonify, render_template, session
from web.auth.decorators import _cached_web_user
from services.panel_notifications_service import build_panel_notifications

panel_notifications_bp = Blueprint('panel_notifications', __name__)

@panel_notifications_bp.get('/panel/notificaciones')
def notifications():
    user = _cached_web_user(session.get('user_id'))
    if not user or not user.get('activo'):
        return jsonify(error='Sesion no valida'), 401
    role = str(user.get('rol') or '').lower()
    if role not in {'admin', 'rrhh'}:
        return jsonify(error='Sin permiso'), 403
    key = f"panel_alerts:{user['id']}:{user.get('empresa_id')}:{role}"
    cached = session.get(key)
    now = time.time()
    if cached and 0 <= now - cached.get('ts', 0) < 30:
        data = cached['data']
    else:
        data = build_panel_notifications(role)
        session[key] = {'ts': now, 'data': data}
    response = jsonify(total=data['total'], html=render_template('_panel_notifications.html', panel_notifications=data))
    response.headers['Cache-Control'] = 'no-store'
    return response
