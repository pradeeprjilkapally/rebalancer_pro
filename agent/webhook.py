"""
Inbound webhook server.

Routes
------
GET  /callback         Zerodha OAuth redirect
GET  /paytm_callback   Paytm Money OAuth redirect
GET  /dashboard_main   Portfolio dashboard (gated at edge by Cloudflare Access)
GET  /health           Liveness probe

Permanent public URL (never changes):
  https://portfolio-relay.pradeeprjilkapally.workers.dev
"""
import json
import os
import re
import sys

from dotenv import load_dotenv
from flask import Flask, Response, render_template_string, request

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.crypto import encrypt_token, read_encrypted
from agent.gold_price import build_svg_chart, get_price as get_gold_price, load_history as load_gold_history
from agent.manual_holdings import _fetch_navs_amfi, _fetch_nav_mfapi
from agent.auth import (
    _save_tokens as _save_paytm_tokens,
    clear_pending as _clear_paytm_pending,
)
from agent.brokers.zerodha import (
    clear_pending as _clear_zerodha_pending,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Access control — the dashboards are gated at the edge by Cloudflare Access
# (Google + email OTP, scoped to a single email). The app keeps no second
# password layer; the daily sanity check verifies the dashboard is never
# publicly reachable, so an Access misconfiguration is alerted, not silent.
# Machine endpoints (/callback, /paytm_callback, /health) are Access-bypassed
# and protected by token-format validation.
# ---------------------------------------------------------------------------


@app.after_request
def _harden(resp):
    """Security headers on every response; suppress server fingerprinting."""
    resp.headers['X-Content-Type-Options']   = 'nosniff'
    resp.headers['X-Frame-Options']          = 'DENY'
    resp.headers['Referrer-Policy']          = 'no-referrer'
    resp.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    resp.headers['Permissions-Policy']       = 'geolocation=(), camera=(), microphone=()'
    resp.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    resp.headers.pop('X-Powered-By', None)
    # Never let sensitive views be cached by intermediaries
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp


@app.template_global('inr')
def _inr(value, decimals=0):
    """Indian Rupee comma formatting: 6,90,718 / 1,00,000 style."""
    try:
        n = float(value)
        neg = n < 0
        n = abs(n)
        int_n = int(round(n)) if decimals == 0 else int(n)
        s = str(int_n)
        if len(s) <= 3:
            formatted = s
        else:
            result = s[-3:]
            s = s[:-3]
            while s:
                result = s[-2:] + ',' + result
                s = s[:-2]
            formatted = result
        out = ('-' if neg else '') + formatted
        if decimals > 0:
            frac = round((abs(float(value)) - int_n) * (10 ** decimals))
            out += f'.{frac:0{decimals}d}'
        return out
    except (TypeError, ValueError):
        return str(value)


_ENC_TOKEN_FILE = os.path.join(os.path.dirname(__file__), 'brokers', '.zerodha_request_token.enc')
_TOKEN_RE       = re.compile(r'\b([A-Za-z0-9]{32})\b')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_enc_token(raw_token: str):
    encrypted = encrypt_token(raw_token)
    os.makedirs(os.path.dirname(_ENC_TOKEN_FILE), exist_ok=True)
    with open(_ENC_TOKEN_FILE, 'wb') as fh:
        fh.write(encrypted)


# ---------------------------------------------------------------------------
# Shared HTML templates
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Auth</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#f5f5f5}
.box{background:#fff;border-radius:12px;padding:30px;max-width:400px;margin:auto;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.ok{color:{{ color }};font-size:48px}.msg{font-size:18px;margin-top:16px;color:#333}
.sub{font-size:14px;color:#666;margin-top:8px}</style></head>
<body><div class="box"><div class="ok">&#10003;</div>
<div class="msg">{{ title }}</div><div class="sub">{{ subtitle }}</div>
</div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Auth Error</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#f5f5f5}
.box{background:#fff;border-radius:12px;padding:30px;max-width:400px;margin:auto;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.err{color:#c62828;font-size:48px}.msg{font-size:18px;margin-top:16px;color:#333}
.sub{font-size:14px;color:#666;margin-top:8px}</style></head>
<body><div class="box"><div class="err">&#10007;</div>
<div class="msg">{{ error }}</div>
<div class="sub">Please try logging in again from the Slack link.</div>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Route 1: Zerodha OAuth callback
# ---------------------------------------------------------------------------

@app.route('/callback', methods=['GET'])
def zerodha_callback():
    raw_token = request.args.get('request_token', '')
    if request.args.get('status') != 'success' or not raw_token:
        error = request.args.get('message', 'Login failed or was cancelled.')
        return render_template_string(_ERROR_HTML, error=error), 400
    if not _TOKEN_RE.fullmatch(raw_token):
        return render_template_string(_ERROR_HTML, error='Unexpected token format — please retry.'), 400
    try:
        _save_enc_token(raw_token)
        del raw_token
        _clear_zerodha_pending()
        return render_template_string(
            _SUCCESS_HTML, color='#2e7d32',
            title='Zerodha — Authenticated!',
            subtitle="Holdings will appear in tomorrow's 8:00 AM review. You can close this tab.",
        ), 200
    except Exception:
        return render_template_string(_ERROR_HTML, error='Could not save token. Please retry.'), 500


# ---------------------------------------------------------------------------
# Route 2: Paytm Money OAuth callback
# ---------------------------------------------------------------------------

@app.route('/paytm_callback', methods=['GET'])
def paytm_callback():
    # Paytm sends requestToken (camelCase); accept both forms
    raw_token = (request.args.get('requestToken') or request.args.get('request_token', '')).strip()
    if not raw_token:
        return render_template_string(_ERROR_HTML, error=request.args.get('message', 'Login cancelled.')), 400
    try:
        api_key    = os.getenv('PAYTM_API_KEY', '').strip()
        api_secret = os.getenv('PAYTM_API_SECRET', '').strip()
        from pmClient.pmClient import PMClient
        pm   = PMClient(api_secret=api_secret, api_key=api_key)
        resp = pm.generate_session(raw_token)
        del raw_token
        _save_paytm_tokens({
            'access_token':        resp.get('access_token', ''),
            'public_access_token': resp.get('public_access_token', ''),
            'read_access_token':   resp.get('read_access_token', ''),
        })
        _clear_paytm_pending()
        return render_template_string(
            _SUCCESS_HTML, color='#00b9f1',
            title='Paytm Money — Authenticated!',
            subtitle="Holdings will appear in tomorrow's 7:45 AM review. You can close this tab.",
        ), 200
    except Exception as e:
        print(f'  [webhook] Paytm token exchange failed: {e}')
        return render_template_string(_ERROR_HTML, error='Token exchange failed — please retry.'), 500


# ---------------------------------------------------------------------------
# Route 4: Portfolio dashboard
# ---------------------------------------------------------------------------

_MYDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mydata')

# ---------------------------------------------------------------------------
# FIRE ring design preview (served at /fire-preview for design selection)
# ---------------------------------------------------------------------------
_FIRE_PREVIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FIRE Ring — Design Preview</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@400,1&display=swap" rel="stylesheet">
<style>
  body { background:#0B0F1A; color:#E2E8FF; font-family:'Inter',sans-serif; }
  .card { background:#141927; border:1px solid #1e2d4a; border-radius:12px; }
  .tag { font-size:10px; font-weight:700; letter-spacing:.08em; padding:2px 8px; border-radius:4px; }
  .chosen { outline:2px solid #818cf8; outline-offset:3px; }
</style>
</head>
<body class="min-h-screen p-6">
<div class="max-w-5xl mx-auto">
  <h1 class="text-xl font-bold text-white mb-1">FIRE Ring — Design Options</h1>
  <p class="text-[#6B7FA3] text-sm mb-6">Compare all four designs with live data. Tell me which one you want and I'll update the dashboard.</p>

  <!-- Live data strip -->
  <div class="card p-4 mb-6 flex flex-wrap gap-6">
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Corpus</div><div class="font-bold text-white tabular-nums">₹{{ '{:,.0f}'.format(fire.current) }}</div></div>
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Target</div><div class="font-bold text-white tabular-nums">₹{{ '{:.2f}'.format(fire.target / 1e7) }}Cr</div></div>
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Progress</div><div class="font-bold text-[#818cf8] tabular-nums">{{ '{:.1f}'.format(pct) }}%</div></div>
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Years to FIRE</div><div class="font-bold text-[#F59E0B] tabular-nums">{{ '{:.1f}'.format(fire.years_to_fire) }} yrs</div></div>
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Gap</div><div class="font-bold text-[#f87171] tabular-nums">₹{{ '{:.2f}'.format(fire.gap / 1e7) }}Cr</div></div>
    <div><div class="text-[10px] text-[#6B7FA3] uppercase tracking-wider mb-0.5">Monthly SIP</div><div class="font-bold text-white tabular-nums">₹{{ '{:,.0f}'.format(fire.monthly_investment) }}</div></div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

    <!-- ── A: Neon HUD Segments ──────────────────────────────────────────── -->
    <div class="card p-5 flex flex-col gap-4" id="card-a">
      <div class="flex items-center gap-2">
        <span class="tag bg-[#00E5FF]/10 text-[#00E5FF] border border-[#00E5FF]/20">A</span>
        <span class="font-semibold text-white">Neon HUD Segments</span>
        <span class="ml-auto text-[11px] text-[#6B7FA3]">closest to your reference</span>
      </div>
      <div class="flex justify-center"><canvas id="ring-a" width="220" height="220"></canvas></div>
      <div class="text-[11px] text-[#6B7FA3]">60 arc segments with gaps · electric cyan glow · outer tick marks · tip pulse</div>
      <button onclick="pick('A')" id="btn-a" class="w-full py-2 rounded-lg bg-[#00E5FF]/10 text-[#00E5FF] text-sm font-semibold border border-[#00E5FF]/30 hover:bg-[#00E5FF]/20 transition-colors">
        Select A — Neon HUD
      </button>
    </div>

    <!-- ── B: Gradient Glow Arc ──────────────────────────────────────────── -->
    <div class="card p-5 flex flex-col gap-4" id="card-b">
      <div class="flex items-center gap-2">
        <span class="tag bg-[#818cf8]/10 text-[#818cf8] border border-[#818cf8]/20">B</span>
        <span class="font-semibold text-white">Gradient Glow Arc</span>
        <span class="ml-auto text-[11px] text-[#6B7FA3]">premium · sleek</span>
      </div>
      <div class="flex justify-center" id="ring-b"></div>
      <div class="text-[11px] text-[#6B7FA3]">Thick arc with indigo→violet gradient · SVG blur glow · rounded endpoints</div>
      <button onclick="pick('B')" id="btn-b" class="w-full py-2 rounded-lg bg-[#818cf8]/10 text-[#818cf8] text-sm font-semibold border border-[#818cf8]/30 hover:bg-[#818cf8]/20 transition-colors">
        Select B — Gradient Arc
      </button>
    </div>

    <!-- ── C: Concentric Rings ───────────────────────────────────────────── -->
    <div class="card p-5 flex flex-col gap-4" id="card-c">
      <div class="flex items-center gap-2">
        <span class="tag bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/20">C</span>
        <span class="font-semibold text-white">Concentric Rings</span>
        <span class="ml-auto text-[11px] text-[#6B7FA3]">multi-metric</span>
      </div>
      <div class="flex justify-center" id="ring-c"></div>
      <div class="text-[11px] text-[#6B7FA3]">3 rings: corpus % (indigo) · years elapsed (amber) · SIP coverage (green)</div>
      <button onclick="pick('C')" id="btn-c" class="w-full py-2 rounded-lg bg-[#10B981]/10 text-[#10B981] text-sm font-semibold border border-[#10B981]/30 hover:bg-[#10B981]/20 transition-colors">
        Select C — Concentric
      </button>
    </div>

    <!-- ── D: HUD Flat Bars (reference-image style) ──────────────────────── -->
    <div class="card p-5 flex flex-col gap-4" id="card-d">
      <div class="flex items-center gap-2">
        <span class="tag bg-[#F59E0B]/10 text-[#F59E0B] border border-[#F59E0B]/20">D</span>
        <span class="font-semibold text-white">HUD Flat Bars</span>
        <span class="ml-auto text-[11px] text-[#6B7FA3]">your reference · no ring</span>
      </div>
      <div id="ring-d" class="self-stretch"></div>
      <div class="text-[11px] text-[#6B7FA3]">Horizontal segmented neon bars like the sci-fi HUD reference image · 3 metrics</div>
      <button onclick="pick('D')" id="btn-d" class="w-full py-2 rounded-lg bg-[#F59E0B]/10 text-[#F59E0B] text-sm font-semibold border border-[#F59E0B]/30 hover:bg-[#F59E0B]/20 transition-colors">
        Select D — HUD Flat Bars
      </button>
    </div>

  </div>

  <div id="selection-banner" class="hidden mt-6 card p-4 text-center">
    <div class="font-semibold text-white text-lg" id="sel-text"></div>
    <div class="text-[#6B7FA3] text-sm mt-1">Reply in Claude with "apply design X" and I'll update the live dashboard.</div>
  </div>
</div>

<script>
const PCT = {{ pct }};
const CURRENT = {{ fire.current }};
const TARGET  = {{ fire.target }};
const YEARS   = {{ fire.years_to_fire }};
const MONTHLY = {{ fire.monthly_investment }};
const GAP     = {{ fire.gap }};

// ── A: Neon HUD Segments (Canvas) ──────────────────────────────────────────
(function(){
  const canvas = document.getElementById('ring-a');
  const ctx = canvas.getContext('2d');
  const W=220, H=220, cx=110, cy=110;
  const outerR=84, innerR=60, SEGS=60, GAP_R=0.07;
  const filled = Math.round(SEGS * PCT / 100);

  function draw(pulse) {
    ctx.clearRect(0,0,W,H);
    // Segments
    for(let i=0;i<SEGS;i++){
      const a1 = -Math.PI/2 + (2*Math.PI/SEGS)*i + GAP_R/2;
      const a2 = -Math.PI/2 + (2*Math.PI/SEGS)*(i+1) - GAP_R/2;
      ctx.beginPath();
      ctx.arc(cx,cy,outerR,a1,a2);
      ctx.arc(cx,cy,innerR,a2,a1,true);
      ctx.closePath();
      if(i < filled){
        const bright = i===filled-1;
        const intensity = 0.5 + 0.5*(i/filled);
        ctx.shadowBlur = bright ? (pulse?28:20) : 8;
        ctx.shadowColor = '#00E5FF';
        ctx.fillStyle = bright
          ? (pulse ? '#AFFFFF' : '#80FFFF')
          : `hsl(${185+intensity*10},100%,${40+intensity*20}%)`;
      } else {
        ctx.shadowBlur = 0;
        ctx.fillStyle = '#0c1422';
      }
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    // Outer tick marks
    for(let i=0;i<60;i++){
      const a = -Math.PI/2 + (2*Math.PI/60)*i;
      const long = i%5===0;
      const r1=outerR+3, r2=r1+(long?8:3);
      ctx.beginPath();
      ctx.moveTo(cx+r1*Math.cos(a), cy+r1*Math.sin(a));
      ctx.lineTo(cx+r2*Math.cos(a), cy+r2*Math.sin(a));
      ctx.strokeStyle = long ? '#1e3a4a' : '#0f2030';
      ctx.lineWidth = long?1.5:1;
      ctx.stroke();
    }

    // Tip pulse dot
    const tipA = -Math.PI/2 + (2*Math.PI/SEGS)*filled - (Math.PI/SEGS);
    const tipR = (outerR+innerR)/2;
    ctx.beginPath();
    ctx.arc(cx+tipR*Math.cos(tipA), cy+tipR*Math.sin(tipA), pulse?5:3.5, 0, 2*Math.PI);
    ctx.shadowBlur = pulse?24:14;
    ctx.shadowColor='#FFFFFF';
    ctx.fillStyle='#FFFFFF';
    ctx.fill();
    ctx.shadowBlur=0;

    // Center text
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.font='bold 24px "Courier New",monospace';
    ctx.shadowBlur=10; ctx.shadowColor='#00E5FF';
    ctx.fillStyle='#00E5FF';
    ctx.fillText(PCT.toFixed(1)+'%', cx, cy-10);
    ctx.shadowBlur=0;
    ctx.font='10px Inter,sans-serif'; ctx.fillStyle='#2a5a6a';
    ctx.fillText('CORPUS', cx, cy+10);
    ctx.font='9px Inter,sans-serif'; ctx.fillStyle='#1a3a4a';
    ctx.fillText(YEARS.toFixed(1)+' YRS', cx, cy+24);
  }

  let p=false;
  draw(false);
  setInterval(()=>{ p=!p; draw(p); }, 900);
})();

// ── B: Gradient Glow Arc (SVG) ─────────────────────────────────────────────
(function(){
  const R=80, CX=110, CY=110, SW=14;
  const circ=2*Math.PI*R;
  const filled=circ*PCT/100, empty=circ-filled;
  document.getElementById('ring-b').innerHTML=`
<svg width="220" height="220" viewBox="0 0 220 220">
  <defs>
    <linearGradient id="g1" x1="0%" y1="100%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#4338ca"/><stop offset="55%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#c084fc"/>
    </linearGradient>
    <filter id="gB1"><feGaussianBlur stdDeviation="4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="gB2"><feGaussianBlur stdDeviation="9" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#080e1c" stroke-width="${SW+4}"/>
  <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#101828" stroke-width="${SW}"/>
  <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#4338ca"
    stroke-width="${SW+4}" stroke-dasharray="${filled} ${empty}"
    stroke-linecap="round" filter="url(#gB2)" opacity="0.35"
    transform="rotate(-90 ${CX} ${CY})"/>
  <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="url(#g1)"
    stroke-width="${SW}" stroke-dasharray="${filled} ${empty}"
    stroke-linecap="round" filter="url(#gB1)"
    transform="rotate(-90 ${CX} ${CY})"/>
  <text x="${CX}" y="${CY-12}" text-anchor="middle" fill="white"
    font-size="30" font-weight="700" font-family="Inter,sans-serif">${PCT.toFixed(1)}%</text>
  <text x="${CX}" y="${CY+12}" text-anchor="middle" fill="#6B7FA3"
    font-size="11" font-family="Inter,sans-serif">FIRE CORPUS</text>
  <text x="${CX}" y="${CY+28}" text-anchor="middle" fill="#4338ca"
    font-size="9" font-family="Inter,sans-serif">${YEARS.toFixed(1)} YRS REMAINING</text>
</svg>`;
})();

// ── C: Concentric Rings (SVG) ──────────────────────────────────────────────
(function(){
  const CX=110, CY=110;
  const rings=[
    {r:80, sw:9, color:'#6366F1', gcolor:'#6366F1', pct:PCT, label:`${PCT.toFixed(1)}% corpus`},
    {r:63, sw:9, color:'#F59E0B', gcolor:'#F59E0B',
      pct:Math.min(100,(20-YEARS)/20*100),
      label:`${((20-YEARS)/20*100).toFixed(0)}% yrs elapsed`},
    {r:46, sw:9, color:'#10B981', gcolor:'#10B981',
      pct:Math.min(100,MONTHLY/150000*100),
      label:`${(MONTHLY/150000*100).toFixed(0)}% SIP coverage`},
  ];
  let arcs='', filters='', labels='';
  rings.forEach((rg,i)=>{
    const c=2*Math.PI*rg.r;
    const f=c*rg.pct/100;
    filters+=`<filter id="gC${i}"><feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
    arcs+=`<circle cx="${CX}" cy="${CY}" r="${rg.r}" fill="none" stroke="#080e1c" stroke-width="${rg.sw+2}"/>`;
    arcs+=`<circle cx="${CX}" cy="${CY}" r="${rg.r}" fill="none" stroke="${rg.color}"
      stroke-width="${rg.sw}" stroke-dasharray="${f} ${c-f}" stroke-linecap="round"
      filter="url(#gC${i})" transform="rotate(-90 ${CX} ${CY})"/>`;
    labels+=`<text x="208" y="${80+i*44}" text-anchor="end" fill="${rg.color}"
      font-size="9.5" font-family="Inter,sans-serif">● ${rg.label}</text>`;
  });
  document.getElementById('ring-c').innerHTML=`
<svg width="220" height="220" viewBox="0 0 220 220">
  <defs>${filters}</defs>
  ${arcs}
  <text x="${CX}" y="${CY-10}" text-anchor="middle" fill="white"
    font-size="24" font-weight="700" font-family="Inter,sans-serif">${PCT.toFixed(1)}%</text>
  <text x="${CX}" y="${CY+10}" text-anchor="middle" fill="#6B7FA3"
    font-size="10" font-family="Inter,sans-serif">CORPUS</text>
  ${labels}
</svg>`;
})();

// ── D: HUD Flat Bars (reference-image style) ───────────────────────────────
(function(){
  const SEGS=28;
  function bar(pct, color, glow){
    const n=Math.round(SEGS*pct/100);
    let h='<div style="display:flex;gap:2px;">';
    for(let i=0;i<SEGS;i++){
      const on=i<n;
      h+=`<div style="flex:1;height:9px;border-radius:1.5px;background:${on?color:'#091520'};
        ${on?`box-shadow:0 0 5px 1px ${glow}`:''}"></div>`;
    }
    return h+'</div>';
  }
  const corpusPct=PCT;
  const yearsPct=Math.min(100,(20-YEARS)/20*100);
  const sipPct=Math.min(100,MONTHLY/150000*100);
  document.getElementById('ring-d').innerHTML=`
<div style="padding:18px 16px;background:#060d18;border:1px solid #0e2030;border-radius:10px;font-family:'Courier New',monospace;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <span style="color:#00C4D8;font-size:12px;letter-spacing:.18em;text-shadow:0 0 8px #00C4D855;">
      ◈ FIRE MONITOR ◈
    </span>
    <span style="color:#00C4D8;font-size:10px;letter-spacing:.12em;opacity:.7;">LIVE ●</span>
  </div>

  <div style="margin-bottom:12px;">
    <div style="display:flex;justify-content:space-between;color:#1a6070;font-size:10px;margin-bottom:5px;">
      <span>CORPUS</span>
      <span style="color:#00B4C8;">${PCT.toFixed(1)}% &nbsp; ₹${(CURRENT/1e5).toFixed(1)}L / ₹${(TARGET/1e7).toFixed(2)}Cr</span>
    </div>
    ${bar(corpusPct,'#008fa0','#00C4D888')}
  </div>

  <div style="margin-bottom:12px;">
    <div style="display:flex;justify-content:space-between;color:#1a6070;font-size:10px;margin-bottom:5px;">
      <span>TIMELINE</span>
      <span style="color:#c89000;">${yearsPct.toFixed(1)}% &nbsp; ${(20-YEARS).toFixed(1)} / 20 yrs</span>
    </div>
    ${bar(yearsPct,'#a07000','#F59E0B66')}
  </div>

  <div style="margin-bottom:14px;">
    <div style="display:flex;justify-content:space-between;color:#1a6070;font-size:10px;margin-bottom:5px;">
      <span>MONTHLY SIP</span>
      <span style="color:#009a60;">₹${(MONTHLY/1000).toFixed(0)}K / ₹150K &nbsp; ${sipPct.toFixed(0)}%</span>
    </div>
    ${bar(sipPct,'#007040','#10B98166')}
  </div>

  <div style="border-top:1px solid #0e2030;padding-top:10px;display:flex;justify-content:space-between;align-items:center;">
    <span style="color:#0e2a38;font-size:9px;">SYS:OK ● AUTH:OK</span>
    <span style="color:#00C4D8;font-size:11px;font-weight:bold;letter-spacing:.1em;text-shadow:0 0 8px #00C4D8;">
      EST FIRE: +${YEARS.toFixed(1)}Y
    </span>
    <span style="color:#0e2a38;font-size:9px;">GAP ₹${(GAP/1e7).toFixed(2)}Cr</span>
  </div>
</div>`;
})();

function pick(d){
  ['a','b','c','d'].forEach(x=>{
    document.getElementById('card-'+x).classList.remove('chosen');
  });
  document.getElementById('card-'+d.toLowerCase()).classList.add('chosen');
  const names={A:'Neon HUD Segments',B:'Gradient Glow Arc',C:'Concentric Rings',D:'HUD Flat Bars'};
  document.getElementById('sel-text').textContent=`Design ${d} selected — ${names[d]}`;
  document.getElementById('selection-banner').classList.remove('hidden');
  document.getElementById('selection-banner').scrollIntoView({behavior:'smooth',block:'nearest'});
}
</script>
</body>
</html>"""

_DASHBOARD_HTML = """<!DOCTYPE html>
<html class="dark" lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Dashboard</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body { background-color: #0B0F1A; color: #E2E8FF; font-family: 'Inter', sans-serif; -webkit-font-smoothing: antialiased; }
  .card { background-color: #141927; border: 1px solid #1e2d4a; border-radius: 12px; }
  .tabular-nums { font-variant-numeric: tabular-nums; }
  .text-muted { color: #6B7FA3; }
  .text-success { color: #10B981; }
  .text-danger { color: #EF4444; }
  .border-accent-indigo { border-left: 4px solid #6366F1; }
  .border-accent-gold   { border-left: 4px solid #F59E0B; }
  .data-table { width: 100%; border-collapse: collapse; }
  .data-table th { color: #6B7FA3; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; font-weight: 600; padding: 10px 12px; border-bottom: 1px solid #1e2d4a; text-align: left; }
  .data-table th.r { text-align: right; }
  .data-table td { padding: 10px 12px; font-size: 13px; color: #E2E8FF; border-bottom: 1px solid rgba(30,45,74,0.5); }
  .data-table td.r { text-align: right; font-variant-numeric: tabular-nums; }
  .data-table tr:last-child td { border-bottom: none; }
  .data-table tr:hover td { background-color: #1C2235; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #1e2d4a; border-radius: 4px; }
  /* Privacy mask */
  .money { transition: filter 0.18s, opacity 0.18s; }
  body.masked .money { filter: blur(7px); opacity: 0.45; user-select: none; }
  /* Collapsible */
  .card-toggle { cursor: pointer; user-select: none; }
  .chevron { transition: transform 0.2s; display: inline-flex; }
  .card-collapsed .chevron { transform: rotate(-180deg); }
  /* Placeholder shimmer */
  @keyframes shimmer { 0%{opacity:.4}50%{opacity:.7}100%{opacity:.4} }
  .shimmer { animation: shimmer 2s ease-in-out infinite; }
</style>
</head>
<body class="min-h-screen flex flex-col">

<!-- ── Fixed header ───────────────────────────────────────────────────────── -->
<header class="w-full h-[60px] bg-[#0B0F1A] border-b border-[#1e2d4a] flex items-center justify-between px-5 z-50 fixed top-0">
  <div class="flex items-center gap-3">
    <span class="text-[17px] font-semibold text-white">Portfolio</span>
    <div class="flex items-center gap-1.5 bg-[#10B981]/10 px-2 py-0.5 rounded-full border border-[#10B981]/20">
      <div class="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse"></div>
      <span class="text-[10px] font-semibold text-[#10B981] uppercase tracking-wider">Live</span>
    </div>
  </div>
  <div class="flex items-center gap-4">
    <!-- Privacy toggle -->
    <button id="mask-btn" onclick="toggleMask()" title="Hide / show amounts"
      class="flex items-center justify-center w-8 h-8 rounded-lg border border-[#1e2d4a] text-muted hover:text-white hover:border-[#4f46e5] transition-colors">
      <span class="material-symbols-outlined text-[17px]" id="eye-icon" style="font-variation-settings:'FILL' 0;">visibility</span>
    </button>
    <!-- Total -->
    <div class="text-right">
      <div class="text-[9px] text-muted uppercase tracking-widest leading-none mb-0.5">Total Portfolio Value</div>
      <div class="text-[22px] leading-none font-bold tabular-nums text-white money">₹{{ inr(total_portfolio) }}</div>
      <div class="text-[9px] text-muted mt-0.5">Consolidated · {{ generated }}</div>
    </div>
  </div>
</header>

<!-- ── Page body ──────────────────────────────────────────────────────────── -->
<main class="flex-1 mt-[60px] p-4 md:p-6">
<div class="flex flex-col gap-4 max-w-[1440px] mx-auto">

<!-- ── FIRE Progress Banner ───────────────────────────────────────────────── -->
{% if fire %}
<div class="card" id="card-fire">
  <!-- Thin header (always visible) -->
  <div class="card-toggle p-3 px-4 flex items-center gap-3" onclick="toggleCard('fire')">
    <span class="material-symbols-outlined text-[#F59E0B] text-[15px]" style="font-variation-settings:'FILL' 1;">local_fire_department</span>
    <span class="font-semibold text-white text-[13px]">FIRE Progress</span>
    <div class="ml-auto flex items-center gap-3">
      <div class="text-right leading-tight">
        <span class="text-[14px] font-bold text-white tabular-nums money">{{ '{:.1f}'.format(fire.progress_pct) }}%</span>
        <span class="text-muted text-[11px] ml-1.5">of ₹{{ '{:.2f}'.format(fire.target / 1e7) }}Cr · <span class="money">₹{{ inr(fire.current) }}</span> corpus</span>
      </div>
      <span class="chevron material-symbols-outlined text-muted text-[18px] flex-shrink-0">expand_less</span>
    </div>
  </div>
  <!-- Collapsible body: compact horizontal banner (Stitch — Deep Equity Alpha) -->
  <div id="card-body-fire" class="border-t border-[#1e2d4a] p-4">
    <div class="flex items-center gap-5 flex-wrap">
      <!-- Progress ring -->
      <div class="flex-shrink-0 relative w-[88px] h-[88px]">
        <svg class="w-full h-full -rotate-90" viewBox="0 0 88 88">
          <circle cx="44" cy="44" fill="none" r="38" stroke="#1e2d4a" stroke-width="6"></circle>
          <circle cx="44" cy="44" fill="none" r="38" stroke="url(#fireGradient)"
            stroke-dasharray="238.76"
            stroke-dashoffset="{{ 238.76 * (1 - ([fire.progress_pct, 100]|min / 100)) }}"
            stroke-linecap="round" stroke-width="6"></circle>
          <defs>
            <linearGradient id="fireGradient" x1="0%" x2="100%" y1="0%" y2="100%">
              <stop offset="0%" stop-color="#6366F1"></stop>
              <stop offset="100%" stop-color="#C084FC"></stop>
            </linearGradient>
          </defs>
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <span class="text-[20px] font-bold text-white tabular-nums leading-none money">{{ '{:.0f}'.format(fire.progress_pct) }}%</span>
          <span class="text-[9px] font-semibold text-muted tracking-widest mt-0.5">FIRE</span>
        </div>
      </div>
      <!-- Corpus + bar -->
      <div class="flex-grow min-w-[200px] flex flex-col gap-2">
        <div class="flex items-baseline gap-2 flex-wrap">
          <span class="text-[26px] font-bold text-white tabular-nums money">₹{{ inr(fire.current) }}</span>
          <span class="text-[13px] text-muted">of ₹{{ '{:.2f}'.format(fire.target / 1e7) }}Cr target</span>
        </div>
        <div class="w-full max-w-[420px] h-1.5 bg-[#1e2d4a] rounded-full overflow-hidden">
          <div class="h-full bg-[#6366F1] rounded-full" style="width:{{ [fire.progress_pct, 100]|min }}%"></div>
        </div>
      </div>
      <!-- Stat tiles -->
      <div class="flex-shrink-0 flex items-center gap-2.5 flex-wrap">
        <div class="min-w-[118px] bg-[#0c1323] border border-[#1e2d4a] rounded-lg p-3">
          <div class="text-[10px] text-muted uppercase tracking-wider mb-1.5">Years to FIRE</div>
          <div class="text-[18px] font-semibold text-white tabular-nums">{{ '{:.1f}'.format(fire.years_to_fire) }}</div>
        </div>
        <div class="min-w-[118px] bg-[#0c1323] border border-[#1e2d4a] rounded-lg p-3">
          <div class="text-[10px] text-muted uppercase tracking-wider mb-1.5">Monthly SIP</div>
          <div class="text-[18px] font-semibold text-white tabular-nums money">₹{{ inr(fire.monthly_investment) }}</div>
        </div>
        <div class="min-w-[118px] bg-[#0c1323] border border-[#1e2d4a] rounded-lg p-3">
          <div class="text-[10px] text-muted uppercase tracking-wider mb-1.5">Gap to FIRE</div>
          <div class="text-[18px] font-semibold text-[#EF4444] tabular-nums money">₹{{ '{:.2f}'.format(fire.gap / 1e7) }}Cr</div>
        </div>
      </div>
    </div>
  </div>
</div>
{% endif %}

<!-- ── Broker card macro ─────────────────────────────────────────────────────── -->
{% macro broker_card(b, cid) %}
<div class="card overflow-hidden" id="card-{{ cid }}">
  <div class="card-toggle p-4 border-b border-[#1e2d4a] flex justify-between items-center" onclick="toggleCard('{{ cid }}')">
    <div class="flex items-center gap-2.5">
      <div class="w-2.5 h-2.5 rounded-full {{ 'bg-[#F97316]' if b.label == 'Paytm Money' else 'bg-[#8B5CF6]' }}"></div>
      <div>
        <div class="font-semibold text-white text-[14px]">{{ b.label }}</div>
        <div class="text-[11px] text-muted">{{ 'Equity · MF · SIP' if b.label == 'Zerodha' else 'Equity' }}</div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      {% if b.get('placeholder') %}
      <div class="text-[12px] text-muted italic shimmer">Pending purchases this week</div>
      {% else %}
      <div class="text-right">
        <div class="font-bold text-white text-[16px] tabular-nums money">₹{{ inr(b.display_total) }}</div>
        <div class="text-[11px] text-muted tabular-nums">Cash <span class="money">₹{{ inr(b.snapshot.available_cash) }}</span></div>
      </div>
      {% endif %}
      <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
    </div>
  </div>
  <div id="card-body-{{ cid }}">
    {% if b.get('placeholder') %}
    <div class="p-8 flex flex-col items-center gap-3 text-center min-h-[200px] justify-center">
      <span class="material-symbols-outlined text-[44px] shimmer" style="color:#8B5CF6;opacity:.3;">candlestick_chart</span>
      <div class="text-[14px] font-medium text-muted">No holdings yet</div>
      <div class="text-[11px] text-[#6B7FA3]/50 italic">Holdings will appear here after purchases</div>
      <div class="flex gap-8 mt-3 text-center">
        {% for label in ['Equity', 'MF', 'SIP'] %}
        <div><div class="text-[9px] text-muted uppercase tracking-wider mb-1">{{ label }}</div>
          <div class="text-[13px] text-muted shimmer">—</div></div>
        {% endfor %}
      </div>
    </div>
    {% else %}
    {% if b.snapshot.holdings %}
    <div class="overflow-x-auto">
      <table class="data-table">
        <thead><tr>
          <th>Name</th><th class="r">Qty</th><th class="r">LTP</th>
          <th class="r">Value</th><th class="r">Alloc</th><th class="r">P&amp;L</th>
        </tr></thead>
        <tbody>
          {% for h in b.snapshot.holdings if h.get('source','') not in ('manual_gold', 'manual_mf', 'manual_chit') %}
          <tr>
            <td class="font-medium text-white">{{ h.name }}</td>
            <td class="r">{{ '{:.0f}'.format(h.quantity) }}</td>
            <td class="r money">₹{{ inr(h.ltp, 2) }}</td>
            <td class="r money">₹{{ inr(h.current_value) }}</td>
            <td class="r text-muted">{{ '{:.1f}'.format(h.allocation_pct) }}%</td>
            <td class="r {{ 'text-success' if h.unrealised_pnl >= 0 else 'text-danger' }} money">
              {{ '+' if h.unrealised_pnl >= 0 else '' }}₹{{ inr(h.unrealised_pnl) }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
    {% set all_sugg = b.rebalance + b.fire_sugg_formatted %}
    {% if all_sugg %}
    <div class="p-4 border-t border-[#1e2d4a]">
      <div class="text-[10px] text-muted uppercase tracking-wider mb-2">Suggestions ({{ all_sugg|length }})</div>
      {% for s in all_sugg %}
      <div class="flex items-start gap-2 py-2 {% if not loop.first %}border-t border-[#1e2d4a]{% endif %}">
        <span class="mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap
          {{ 'text-[#10B981] bg-[#10B981]/10' if s.action == 'BUY'
             else 'text-[#EF4444] bg-[#EF4444]/10' if s.action == 'SELL'
             else 'text-[#60a5fa] bg-[#60a5fa]/10' }}">{{ s.action }}</span>
        <div>
          <div class="text-[13px] text-white">{{ s.quantity }}× {{ s.name }}
            {% if s.estimated_value %}<span class="text-muted text-[11px] money"> ~₹{{ inr(s.estimated_value) }}</span>{% endif %}
          </div>
          <div class="text-[11px] text-muted mt-0.5">{{ s.reason }}</div>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="p-4 border-t border-[#1e2d4a]">
      <span class="text-[13px] text-muted italic">Portfolio balanced — no actions needed.</span>
    </div>
    {% endif %}
    {% set sips = b.snapshot.get('sips', []) %}
    {% if sips %}
    <div class="p-4 border-t border-[#1e2d4a]">
      <div class="text-[10px] text-muted uppercase tracking-wider mb-2">Active SIPs</div>
      {% for s in sips %}
      <div class="flex justify-between text-[13px] {% if not loop.first %}border-t border-[#1e2d4a] pt-2 mt-2{% endif %}">
        <span class="text-white">{{ s.fund }}</span>
        <span class="text-[#60a5fa] tabular-nums money">₹{{ inr(s.monthly_amount) }}/mo</span>
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% endif %}
  </div>
</div>
{% endmacro %}

<!-- ── Paytm · Zerodha · Manual MF · Diversification ─────────────────────────── -->
<div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-4 items-start">

  <!-- Paytm Money -->
  {% for b in brokers if b.label == 'Paytm Money' %}
  {{ broker_card(b, 'broker-pm') }}
  {% else %}
  <div class="card flex items-center justify-center min-h-[200px] text-muted text-[13px]">
    No Paytm Money data — run the daily review first.
  </div>
  {% endfor %}

  <!-- Zerodha -->
  {% for b in brokers if b.label == 'Zerodha' %}
  {{ broker_card(b, 'broker-zerodha') }}
  {% else %}
  <div class="card flex items-center justify-center min-h-[200px] text-muted text-[13px]">
    Zerodha — no data
  </div>
  {% endfor %}

  <!-- Manual MF corpus -->
  {% if mf_summary %}
  <div class="card overflow-hidden" id="card-mf-summary">
    <div class="card-toggle p-4 border-b border-[#1e2d4a] flex justify-between items-center" onclick="toggleCard('mf-summary')">
      <div class="flex items-center gap-2.5">
        <div class="w-2.5 h-2.5 rounded-full bg-[#6366F1]"></div>
        <div>
          <div class="font-semibold text-white text-[14px]">Manual MF Corpus</div>
          <div class="text-[11px] text-muted">Tracked separately · included in FIRE</div>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <div class="text-right">
          <div class="font-bold text-white text-[16px] tabular-nums money">₹{{ inr(mf_summary.current_value) }}</div>
          <div class="text-[11px] {{ 'text-success' if mf_summary.pnl >= 0 else 'text-danger' }} tabular-nums">
            {{ '+' if mf_summary.pnl >= 0 else '' }}{{ '{:.1f}'.format(mf_summary.pnl_pct) }}%
          </div>
        </div>
        <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
      </div>
    </div>
    <div id="card-body-mf-summary" class="p-4">
      <div class="grid grid-cols-2 gap-3 text-[11px]">
        <div>
          <div class="text-muted uppercase tracking-wider mb-1">Invested</div>
          <div class="font-semibold text-white money">₹{{ inr(mf_summary.invested) }}</div>
        </div>
        <div>
          <div class="text-muted uppercase tracking-wider mb-1">P&amp;L</div>
          <div class="font-semibold {{ 'text-success' if mf_summary.pnl >= 0 else 'text-danger' }} money">
            {{ '+' if mf_summary.pnl >= 0 else '' }}₹{{ inr(mf_summary.pnl) }}
          </div>
        </div>
      </div>
      <div class="text-[11px] text-muted mt-3 leading-relaxed">
        Not forced into target allocation until the fund-level asset split is explicitly tracked.
      </div>
    </div>
  </div>
  {% endif %}

  <!-- Manual Chit funds -->
  {% if chit_summary %}
  <div class="card overflow-hidden" id="card-chit-summary">
    <div class="card-toggle p-4 border-b border-[#1e2d4a] flex justify-between items-center" onclick="toggleCard('chit-summary')">
      <div class="flex items-center gap-2.5">
        <div class="w-2.5 h-2.5 rounded-full bg-[#10B981]"></div>
        <div>
          <div class="font-semibold text-white text-[14px]">Chit Funds</div>
          <div class="text-[11px] text-muted">Tracked separately · included in FIRE</div>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <div class="text-right">
          <div class="font-bold text-white text-[16px] tabular-nums money">₹{{ inr(chit_summary.current_value) }}</div>
          <div class="text-[11px] {{ 'text-success' if chit_summary.pnl >= 0 else 'text-danger' }} tabular-nums">
            {{ '+' if chit_summary.pnl >= 0 else '' }}{{ '{:.1f}'.format(chit_summary.pnl_pct) }}%
          </div>
        </div>
        <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
      </div>
    </div>
    <div id="card-body-chit-summary" class="p-4">
      <div class="grid grid-cols-2 gap-3 text-[11px]">
        <div>
          <div class="text-muted uppercase tracking-wider mb-1">Invested</div>
          <div class="font-semibold text-white money">₹{{ inr(chit_summary.invested) }}</div>
        </div>
        <div>
          <div class="text-muted uppercase tracking-wider mb-1">P&amp;L</div>
          <div class="font-semibold {{ 'text-success' if chit_summary.pnl >= 0 else 'text-danger' }} money">
            {{ '+' if chit_summary.pnl >= 0 else '' }}₹{{ inr(chit_summary.pnl) }}
          </div>
        </div>
      </div>
      <div class="text-[11px] text-muted mt-3 leading-relaxed">
        Contributions in the corpus; not force-bucketed (no fixed asset split).
      </div>
    </div>
  </div>
  {% endif %}

  <!-- Diversification -->
  {% if diversification %}
  <div class="card overflow-hidden" id="card-diversify">
    <div class="card-toggle p-4 border-b border-[#1e2d4a] flex justify-between items-center" onclick="toggleCard('diversify')">
      <div class="flex items-center gap-2.5">
        <span class="material-symbols-outlined text-[#60a5fa] text-[17px]" style="font-variation-settings:'FILL' 1;">donut_small</span>
        <div>
          <div class="font-semibold text-white text-[14px]">Diversification</div>
          <div class="text-[11px] text-muted">Allocatable portfolio · CFO targets</div>
        </div>
      </div>
      <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
    </div>
    <div id="card-body-diversify" class="p-4">
      <!-- Donut -->
      <div class="flex justify-center mb-4">
        <canvas id="diversify-donut" width="160" height="160"></canvas>
      </div>
      <!-- Category breakdown bars -->
      <div class="flex flex-col gap-2.5">
        {% for cat in diversification %}
        <div>
          <div class="flex justify-between items-center text-[11px] mb-1">
            <div class="flex items-center gap-1.5">
              <div class="w-2 h-2 rounded-full flex-shrink-0" style="background:{{ cat.color }}"></div>
              <span class="text-white">{{ cat.name }}</span>
            </div>
            <div class="flex items-center gap-1.5 tabular-nums">
              {% if cat.value > 0 %}<span class="text-muted money text-[10px]">₹{{ inr(cat.value) }}</span>{% endif %}
              <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded
                {{ 'text-[#f87171] bg-[#f87171]/10' if cat.status == 'over'
                   else 'text-[#60a5fa] bg-[#60a5fa]/10' if cat.status == 'under'
                   else 'text-[#10B981] bg-[#10B981]/10' }}">
                {{ '{:.1f}'.format(cat.pct) }}% / {{ '{:.0f}'.format(cat.target_pct) }}%
              </span>
            </div>
          </div>
          <div class="relative h-1.5 bg-[#0a1320] rounded-full overflow-visible">
            {% if cat.value > 0 %}
            <div class="absolute inset-y-0 left-0 rounded-full"
              style="width:{{ [cat.pct / cat.target_pct * 100, 100]|min if cat.target_pct else 0 }}%;
                     background:{{ cat.color }};opacity:.75;"></div>
            {% endif %}
            <div class="absolute inset-y-0 w-px bg-white/20" style="left:100%"></div>
          </div>
        </div>
        {% endfor %}
        <div class="text-[9px] text-muted mt-1 opacity-60">Manual MF is segregated until its asset split is tracked</div>
      </div>
    </div>
  </div>
  {% endif %}

</div>

<!-- ── MF cards ────────────────────────────────────────────────────────────── -->
{% if mf_funds %}
{% for mf in mf_funds %}
{% set cid = 'mf-' + loop.index|string %}
<div class="card border-accent-indigo" id="card-{{ cid }}">
  <div class="card-toggle p-4 flex justify-between items-center" onclick="toggleCard('{{ cid }}')">
    <div class="flex items-center gap-2.5">
      <div class="w-2.5 h-2.5 rounded-full bg-[#6366F1]"></div>
      <div>
        <div class="font-semibold text-white text-[14px] leading-tight">{{ mf.name }}</div>
        <div class="text-[10px] text-muted mt-0.5 uppercase tracking-wider">Direct · Growth · Manual</div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <div class="text-right">
        <div class="font-bold text-white text-[15px] tabular-nums money">₹{{ inr(mf.current_value) }}</div>
        <div class="text-[11px] text-muted">NAV <span class="money">₹{{ inr(mf.nav, 4) }}</span> · {{ mf.nav_date }}</div>
      </div>
      <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
    </div>
  </div>
  <div id="card-body-{{ cid }}" class="border-t border-[#1e2d4a]">
    <div class="grid grid-cols-2 sm:grid-cols-4 divide-x divide-[#1e2d4a]">
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Invested</div>
        <div class="font-semibold text-white tabular-nums money">₹{{ inr(mf.invested) }}</div>
        <div class="text-[11px] text-muted mt-0.5">{{ '{:,.4f}'.format(mf.units) }} units</div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Current</div>
        <div class="font-semibold text-white tabular-nums money">₹{{ inr(mf.current_value) }}</div>
        <div class="text-[11px] text-muted mt-0.5">NAV × units</div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">P&amp;L</div>
        <div class="font-semibold tabular-nums {{ 'text-success' if mf.pnl >= 0 else 'text-danger' }} money">
          {{ '+' if mf.pnl >= 0 else '' }}₹{{ inr(mf.pnl) }}
          <span class="text-[10px] ml-1 px-1 py-0.5 rounded {{ 'bg-[#10B981]/10' if mf.pnl >= 0 else 'bg-[#EF4444]/10' }}">{{ '{:+.2f}'.format(mf.pnl_pct) }}%</span>
        </div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Avg NAV</div>
        <div class="font-semibold text-white tabular-nums money">₹{{ inr(mf.avg_nav, 4) }}</div>
        <div class="text-[11px] mt-0.5 {{ 'text-success' if mf.nav >= mf.avg_nav else 'text-danger' }}">{{ 'Above' if mf.nav >= mf.avg_nav else 'Below' }} avg</div>
      </div>
    </div>
    <div class="text-[11px] text-muted border-t border-[#1e2d4a] px-4 py-2.5">
      {{ mf.notes + ' ' if mf.notes else '' }}Update <code>mydata/manual_holdings.json</code> → <code>units</code> and <code>invested</code> after new purchases.
    </div>
  </div>
</div>
{% endfor %}
{% endif %}

<!-- ── Gold card ───────────────────────────────────────────────────────────── -->
{% if gold %}
{% set cid = 'gold' %}
<div class="card border-accent-gold" id="card-{{ cid }}">
  <div class="card-toggle p-4 flex justify-between items-center" onclick="toggleCard('{{ cid }}')">
    <div class="flex items-center gap-2.5">
      <div class="w-2.5 h-2.5 rounded-full bg-[#F59E0B]"></div>
      <div>
        <div class="font-semibold text-white text-[14px] leading-tight">Paytm Gold</div>
        <div class="text-[10px] text-muted mt-0.5 uppercase tracking-wider">24K · IBJA Rate · Manual</div>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <div class="text-right">
        <div class="font-bold text-white text-[15px] tabular-nums money">₹{{ inr(gold.current_value) }}</div>
        <div class="text-[11px] text-muted">{{ gold.price_source }} <span class="money">₹{{ inr(gold.price_per_gram, 2) }}/g</span> · {{ '{:.4f}'.format(gold.grams) }}g</div>
      </div>
      <span class="chevron material-symbols-outlined text-muted text-[18px]">expand_less</span>
    </div>
  </div>
  <div id="card-body-{{ cid }}" class="border-t border-[#1e2d4a]">
    <div class="grid grid-cols-2 sm:grid-cols-4 divide-x divide-[#1e2d4a]">
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Grams</div>
        <div class="font-semibold text-white tabular-nums">{{ '{:.4f}'.format(gold.grams) }}g</div>
        <div class="text-[11px] text-muted mt-0.5">SIP <span class="money">₹{{ inr(gold.monthly_sip) }}/mo</span></div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Invested</div>
        <div class="font-semibold text-white tabular-nums money">₹{{ inr(gold.invested) }}</div>
        <div class="text-[11px] text-muted mt-0.5">Avg <span class="money">₹{{ inr(gold.avg_buy_price, 2) }}/g</span></div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">Current</div>
        <div class="font-semibold text-white tabular-nums money">₹{{ inr(gold.current_value) }}</div>
      </div>
      <div class="p-4">
        <div class="text-[10px] text-muted uppercase tracking-wider mb-1">P&amp;L</div>
        <div class="font-semibold tabular-nums {{ 'text-success' if gold.pnl >= 0 else 'text-danger' }} money">
          {{ '+' if gold.pnl >= 0 else '' }}₹{{ inr(gold.pnl) }}
          <span class="text-[10px] ml-1 px-1 py-0.5 rounded {{ 'bg-[#10B981]/10' if gold.pnl >= 0 else 'bg-[#EF4444]/10' }}">{{ '{:+.2f}'.format(gold.pnl_pct) }}%</span>
        </div>
      </div>
    </div>
    {% if gold.chart_svg %}
    <div class="border-t border-[#1e2d4a] px-4 pt-4 pb-2">
      <div class="text-[10px] text-muted uppercase tracking-wider mb-2">30-Day Gold Price Trend (₹/gram)</div>
      {{ gold.chart_svg | safe }}
      {% if gold.history_30 %}
      <div class="flex justify-between text-[10px] text-muted mt-1">
        <span>{{ gold.history_30[0].date }}</span>
        <span>min <span class="money">₹{{ inr(gold.price_min) }}</span> · max <span class="money">₹{{ inr(gold.price_max) }}</span></span>
        <span>{{ gold.history_30[-1].date }}</span>
      </div>
      {% endif %}
    </div>
    {% endif %}
    {% if gold.history_7 %}
    <div class="border-t border-[#1e2d4a] px-4 pt-4 pb-2">
      <div class="text-[10px] text-muted uppercase tracking-wider mb-2">7-Day Price Table</div>
      <table class="data-table">
        <thead><tr>
          <th>Date</th><th class="r">Price/g</th><th class="r">Day Change</th>
          <th class="r">%</th><th class="r">Your Value</th>
        </tr></thead>
        <tbody>
          {% for row in gold.history_7 %}
          <tr>
            <td>{{ row.date }}</td>
            <td class="r money">₹{{ inr(row.price, 2) }}</td>
            {% if row.chg is not none %}
            <td class="r {{ 'text-success' if row.chg >= 0 else 'text-danger' }} money">{{ '+' if row.chg >= 0 else '' }}₹{{ inr(row.chg, 2) }}</td>
            <td class="r {{ 'text-success' if row.chg >= 0 else 'text-danger' }}">{{ '{:+.2f}'.format(row.chg_pct) }}%</td>
            {% else %}
            <td class="r text-muted">—</td><td class="r text-muted">—</td>
            {% endif %}
            <td class="r money">₹{{ inr(row.price * gold.grams) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="text-[11px] text-muted border-t border-[#1e2d4a] px-4 py-2.5">
      Monthly SIP of <span class="money">₹{{ inr(gold.monthly_sip) }}</span> on the {{ gold.sip_day }}st of each month.
      Update <code>mydata/manual_holdings.json</code> → <code>grams</code> and <code>invested</code> after each SIP.
    </div>
    {% endif %}
  </div>
</div>
{% endif %}

</div>
</main>

<script>
// ── Privacy mask ─────────────────────────────────────────────────────────────
let _masked = false;
function toggleMask() {
  _masked = !_masked;
  document.body.classList.toggle('masked', _masked);
  document.getElementById('eye-icon').textContent = _masked ? 'visibility_off' : 'visibility';
}

// ── Collapsible cards ────────────────────────────────────────────────────────
function toggleCard(id) {
  const card = document.getElementById('card-' + id);
  const body = document.getElementById('card-body-' + id);
  if (!body) return;
  const collapsed = body.classList.toggle('hidden');
  if (card) card.classList.toggle('card-collapsed', collapsed);
}

// ── Diversification donut ─────────────────────────────────────────────────────
(function(){
  const canvas = document.getElementById('diversify-donut');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const cx=80, cy=80, R=58, SW=15;
  const data  = {{ diversification | tojson }};
  const total = {{ diversification_total }};

  // Track
  ctx.beginPath(); ctx.arc(cx,cy,R,0,2*Math.PI);
  ctx.strokeStyle='#080e1c'; ctx.lineWidth=SW+4; ctx.stroke();

  let startAngle = -Math.PI/2;
  data.forEach(cat => {
    if (cat.value <= 0) return;
    const slice = (cat.pct / 100) * 2 * Math.PI;
    const endA  = startAngle + slice - 0.03;
    // Glow
    ctx.beginPath(); ctx.arc(cx,cy,R,startAngle,endA);
    ctx.strokeStyle=cat.color; ctx.lineWidth=SW+10; ctx.globalAlpha=0.12; ctx.stroke();
    ctx.globalAlpha=1;
    // Arc
    ctx.beginPath(); ctx.arc(cx,cy,R,startAngle,endA);
    ctx.strokeStyle=cat.color; ctx.lineWidth=SW; ctx.stroke();
    startAngle += slice;
  });

  // Center label
  ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.font='bold 10px Inter,sans-serif'; ctx.fillStyle='#E2E8FF';
  const s = total >= 1e7 ? '₹'+(total/1e7).toFixed(2)+'Cr' : '₹'+(total/1e5).toFixed(1)+'L';
  ctx.fillText(s, cx, cy-7);
  ctx.font='8px Inter,sans-serif'; ctx.fillStyle='#6B7FA3';
  ctx.fillText('ALLOC', cx, cy+7);
})();
</script>
</body>
</html>"""


def _load_broker_data(broker: str) -> dict | None:
    """Load the encrypted broker snapshot written by daily_review."""
    enc_path = os.path.join(_MYDATA, f'{broker}_data.json.enc')
    try:
        return read_encrypted(enc_path)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'  [webhook] could not decrypt {broker} data: {e}')
        return None


def _fire_ring_svg(pct: float, r: int = 54, size: int = 128) -> str:
    """SVG arc ring for FIRE progress. pct is 0–100."""
    import math
    cx = cy = size // 2
    circ   = 2 * math.pi * r
    filled = min(pct / 100, 1.0) * circ
    offset = circ - filled
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1e2235" stroke-width="12"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="url(#fg)" stroke-width="12"'
        f' stroke-linecap="round" stroke-dasharray="{circ:.2f}" stroke-dashoffset="{offset:.2f}"'
        f' transform="rotate(-90 {cx} {cy})"/>'
        f'<defs><linearGradient id="fg" x1="0%" y1="0%" x2="100%" y2="0%">'
        f'<stop offset="0%" stop-color="#4338ca"/>'
        f'<stop offset="100%" stop-color="#a5b4fc"/>'
        f'</linearGradient></defs>'
        f'</svg>'
    )


def _build_fire_context(mf_funds: list[dict], gold_ctx: dict | None) -> dict | None:
    """Aggregate all holdings for a full-portfolio FIRE calculation."""
    from agent.fire_analyser import fire_target, years_to_fire, MONTHLY_INVESTMENT

    paytm   = _load_broker_data('paytm')
    zerodha = _load_broker_data('zerodha')

    def equity_only(data: dict | None) -> float:
        if not data:
            return 0.0
        return sum(
            h.get('current_value', 0) for h in data.get('snapshot', {}).get('holdings', [])
            if h.get('source', 'broker') not in ('manual_gold', 'manual_mf', 'manual_chit')
        )

    paytm_equity   = equity_only(paytm)
    zerodha_equity = equity_only(zerodha)
    mf_value       = sum(m['current_value'] for m in mf_funds)
    mf_invested    = sum(m['invested']       for m in mf_funds)
    gold_value     = gold_ctx['current_value'] if gold_ctx else 0.0
    gold_invested  = gold_ctx['invested']      if gold_ctx else 0.0

    total  = paytm_equity + zerodha_equity + mf_value + gold_value
    target = fire_target()
    gap    = max(0.0, target - total)
    pct    = min(100.0, total / target * 100) if target > 0 else 0.0
    yrs    = years_to_fire(total)

    breakdown = []
    if mf_value > 0:
        breakdown.append({
            'label': 'Mutual Fund', 'value': mf_value, 'color': '#818cf8',
            'pnl_pct': (mf_value - mf_invested) / mf_invested * 100 if mf_invested else None,
        })
    if paytm_equity > 0:
        breakdown.append({'label': 'Paytm Equity', 'value': paytm_equity, 'color': '#60a5fa', 'pnl_pct': None})
    if gold_value > 0:
        breakdown.append({
            'label': 'Paytm Gold', 'value': gold_value, 'color': '#f59e0b',
            'pnl_pct': (gold_value - gold_invested) / gold_invested * 100 if gold_invested else None,
        })
    if zerodha_equity > 0:
        breakdown.append({'label': 'Zerodha', 'value': zerodha_equity, 'color': '#34d399', 'pnl_pct': None})

    return {
        'target':             target,
        'current':            total,
        'gap':                gap,
        'progress_pct':       pct,
        'years_to_fire':      yrs,
        'monthly_investment': MONTHLY_INVESTMENT,
        'breakdown':          breakdown,
        'ring_svg':    _fire_ring_svg(pct),
        'ring_svg_sm': _fire_ring_svg(pct, r=30, size=72),
    }


def _build_mf_context() -> list[dict]:
    """Read manual_holdings.json MF entries, fetch live NAV from AMFI, return list for template."""
    manual_file = os.path.join(_MYDATA, 'manual_holdings.json')
    if not os.path.exists(manual_file):
        return []
    try:
        manual = json.load(open(manual_file))
    except Exception:
        return []

    entries = [mf for mf in manual.get('mutual_funds', []) if float(mf.get('units', 0) or 0) > 0]
    if not entries:
        return []

    scheme_codes = [str(mf.get('scheme_code', '')).strip() for mf in entries]
    nav_map      = _fetch_navs_amfi(scheme_codes)
    today        = __import__('datetime').date.today().isoformat()

    result = []
    for mf, scheme in zip(entries, scheme_codes):
        units    = float(mf.get('units', 0))
        invested = float(mf.get('invested', 0) or 0)
        nav      = nav_map.get(scheme) or _fetch_nav_mfapi(scheme)
        if not nav:
            continue
        current_value = units * nav
        pnl           = current_value - invested
        result.append({
            'name':          mf.get('name', scheme),
            'scheme_code':   scheme,
            'units':         units,
            'invested':      invested,
            'nav':           nav,
            'nav_date':      today,
            'current_value': current_value,
            'pnl':           pnl,
            'pnl_pct':       (pnl / invested * 100) if invested > 0 else 0,
            'avg_nav':       (invested / units) if units > 0 else 0,
            'notes':         mf.get('notes', ''),
        })
    return result


def _build_chit_context() -> list[dict]:
    """Read manual_holdings.json chit entries → list for the template.
    invested = explicit, else monthly_sip × months_paid; value = explicit, else invested."""
    manual_file = os.path.join(_MYDATA, 'manual_holdings.json')
    if not os.path.exists(manual_file):
        return []
    try:
        manual = json.load(open(manual_file))
    except Exception:
        return []

    result = []
    for c in manual.get('chits', []):
        monthly     = float(c.get('monthly_sip', 0) or 0)
        months_paid = int(c.get('months_paid', 0) or 0)
        invested      = float(c.get('invested', 0) or 0) or (monthly * months_paid)
        current_value = float(c.get('current_value', 0) or 0) or invested
        pnl = current_value - invested
        result.append({
            'name':          c.get('platform', 'Chit Fund'),
            'chit_value':    float(c.get('chit_value', 0) or 0),
            'tenure_months': int(c.get('tenure_months', 0) or 0),
            'monthly_sip':   monthly,
            'months_paid':   months_paid,
            'invested':      invested,
            'current_value': current_value,
            'pnl':           pnl,
            'pnl_pct':       (pnl / invested * 100) if invested > 0 else 0,
            'notes':         c.get('notes', ''),
        })
    return result


def _build_gold_context() -> dict | None:
    """Load manual_holdings.json + price history → gold template context dict."""
    manual_file = os.path.join(_MYDATA, 'manual_holdings.json')
    if not os.path.exists(manual_file):
        return None
    try:
        manual = json.load(open(manual_file))
    except Exception:
        return None

    gold_entries = manual.get('gold', [])
    if not gold_entries:
        return None

    g          = gold_entries[0]
    grams      = float(g.get('grams', 0) or 0)
    invested   = float(g.get('invested', 0) or 0)
    monthly_sip = float(g.get('monthly_sip', 0) or 0)
    sip_day    = g.get('sip_day', 1)

    price_per_gram = get_gold_price() or 0
    history_30 = load_gold_history(days=30)
    current_value  = grams * price_per_gram
    pnl            = current_value - invested
    pnl_pct        = (pnl / invested * 100) if invested > 0 else 0
    avg_buy_price  = (invested / grams) if grams > 0 else 0

    prices     = [h['price'] for h in history_30]
    price_min  = min(prices) if prices else 0
    price_max  = max(prices) if prices else 0

    # Build 7-day table with day-over-day changes
    history_7  = history_30[-7:]
    table_rows = []
    for i, entry in enumerate(history_7):
        prev = history_7[i - 1]['price'] if i > 0 else None
        chg  = entry['price'] - prev if prev is not None else None
        chg_pct = (chg / prev * 100) if (prev and chg is not None) else None
        table_rows.append({
            'date':    entry['date'],
            'price':   entry['price'],
            'chg':     chg,
            'chg_pct': chg_pct,
        })

    chart_svg = build_svg_chart(history_30)

    return {
        'grams':         grams,
        'invested':      invested,
        'monthly_sip':   monthly_sip,
        'sip_day':       sip_day,
        'price_per_gram': price_per_gram,
        'price_source':    'IBJA 24K live rate',
        'current_value': current_value,
        'pnl':           pnl,
        'pnl_pct':       pnl_pct,
        'avg_buy_price': avg_buy_price,
        'price_min':     price_min,
        'price_max':     price_max,
        'history_30':    history_30,
        'history_7':     table_rows,
        'chart_svg':     chart_svg,
    }


@app.route('/dashboard_main', methods=['GET'])
def dashboard_main():
    brokers = []
    for broker in ('paytm', 'zerodha'):
        data = _load_broker_data(broker)
        if data:
            data['fire_sugg_formatted'] = [
                {
                    'action':          'ADD SIP',
                    'name':            s.get('instrument', ''),
                    'quantity':        1,
                    'estimated_value': s.get('suggested_sip', 0),
                    'reason':          s.get('reason', ''),
                }
                for s in data.get('fire_sugg', [])
            ]
            # Compute equity-only total: exclude manual_gold/manual_mf holdings
            equity_only = sum(
                h.get('current_value', 0)
                for h in data['snapshot'].get('holdings', [])
                if h.get('source', 'broker') not in ('manual_gold', 'manual_mf', 'manual_chit')
            )
            data['display_total'] = equity_only + data['snapshot'].get('available_cash', 0)
            brokers.append(data)

    # Always show Zerodha slot even with no data yet
    if not any(b.get('broker') == 'zerodha' for b in brokers):
        brokers.append({
            'broker': 'zerodha', 'label': 'Zerodha', 'generated_at': '—',
            'snapshot': {'holdings': [], 'total_equity': 0, 'available_cash': 0, 'total_portfolio': 0, 'sips': []},
            'fire_sugg_formatted': [], 'rebalance': [], 'display_total': 0, 'placeholder': True,
        })

    gold      = _build_gold_context()
    mf_funds  = _build_mf_context()
    fire      = _build_fire_context(mf_funds, gold)
    generated = next((b['generated_at'] for b in brokers if not b.get('placeholder')), 'No data')

    chit_funds = _build_chit_context()
    broker_total    = sum(b['display_total'] for b in brokers)
    mf_total        = sum(m['current_value'] for m in mf_funds)
    gold_total      = gold['current_value'] if gold else 0.0
    chit_total      = sum(c['current_value'] for c in chit_funds)
    total_portfolio = broker_total + mf_total + gold_total + chit_total
    mf_invested     = sum(m['invested'] for m in mf_funds)
    mf_summary      = None
    if mf_total > 0:
        mf_pnl = mf_total - mf_invested
        mf_summary = {
            'current_value': mf_total,
            'invested':      mf_invested,
            'pnl':           mf_pnl,
            'pnl_pct':       (mf_pnl / mf_invested * 100) if mf_invested else 0.0,
        }
    chit_invested = sum(c['invested'] for c in chit_funds)
    chit_summary  = None
    if chit_total > 0:
        chit_summary = {
            'current_value': chit_total,
            'invested':      chit_invested,
            'pnl':           chit_total - chit_invested,
            'pnl_pct':       ((chit_total - chit_invested) / chit_invested * 100) if chit_invested else 0.0,
        }
    diversification_total = broker_total + gold_total

    # Compute diversification across all portfolios vs FIRE targets
    _CAT_DEFS = {
        'Equity':         {'color': '#6366F1', 'target': 30.0},
        'Gold':           {'color': '#F59E0B', 'target': 10.0},
        'Mid & Small Cap':{'color': '#c084fc', 'target': 20.0},
        'International':  {'color': '#60a5fa', 'target': 10.0},
        'Debt':           {'color': '#94a3b8', 'target': 25.0},
        'Cash':           {'color': '#475569', 'target':  5.0},
    }
    _cats = {k: {'value': 0.0, 'color': v['color'], 'target_pct': v['target'], 'items': []}
             for k, v in _CAT_DEFS.items()}

    def _cat_add(key, val, name, broker_label):
        _cats[key]['value'] += val
        _cats[key]['items'].append({'name': name, 'broker': broker_label, 'value': val})

    for b in brokers:
        if b.get('placeholder'):
            continue
        for h in b['snapshot'].get('holdings', []):
            if h.get('source') in ('manual_gold', 'manual_mf', 'manual_chit'):
                continue
            uname = h['name'].upper()
            val   = h.get('current_value', 0)
            if any(k in uname for k in ('GOLD', 'BEES')):
                _cat_add('Gold', val, h['name'], b['label'])
            elif any(k in uname for k in ('MIDCAP', 'SMALLCAP', 'NIFTYMID', 'NIFTY MID')):
                _cat_add('Mid & Small Cap', val, h['name'], b['label'])
            elif any(k in uname for k in ('NASDAQ', 'N100', 'MON100', 'INTL', 'US ETF')):
                _cat_add('International', val, h['name'], b['label'])
            elif any(k in uname for k in ('DEBT', 'LIQUID', 'BOND', 'GSEC', 'GILT', 'OVERNIGHT')):
                _cat_add('Debt', val, h['name'], b['label'])
            else:
                _cat_add('Equity', val, h['name'], b['label'])
        cash = b['snapshot'].get('available_cash', 0)
        if cash > 100:
            _cat_add('Cash', cash, 'Cash', b['label'])

    if gold:
        _cat_add('Gold', gold['current_value'], 'Paytm Gold', 'Paytm')

    diversification = []
    for name, cat in _cats.items():
        pct    = cat['value'] / diversification_total * 100 if diversification_total > 0 else 0.0
        target = cat['target_pct']
        status = 'over' if pct > target + 2 else ('under' if pct < target - 2 else 'ok')
        diversification.append({
            'name': name, 'value': cat['value'], 'pct': round(pct, 1),
            'target_pct': target, 'color': cat['color'],
            'items': cat['items'], 'status': status,
        })
    diversification.sort(key=lambda x: x['value'], reverse=True)

    return render_template_string(
        _DASHBOARD_HTML, brokers=brokers, generated=generated,
        gold=gold, mf_funds=mf_funds, fire=fire,
        mf_summary=mf_summary, chit_summary=chit_summary, total_portfolio=total_portfolio,
        diversification_total=diversification_total,
        diversification=diversification,
    ), 200


# ---------------------------------------------------------------------------
# FIRE visualization design concepts (served at /fire-designs)
# ---------------------------------------------------------------------------

_FIRE_DESIGN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FIRE Visualization — Pick Your Style</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#03060f;color:#e0e8ff;font-family:'Inter',sans-serif;overflow-x:hidden}
section{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 24px;border-bottom:1px solid rgba(30,50,80,0.45)}
.badge{font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:rgba(120,160,220,.40);margin-bottom:10px;font-family:'JetBrains Mono',monospace}
.dtitle{font-size:26px;font-weight:700;margin-bottom:6px}
.dsub{font-size:13px;color:rgba(140,170,220,.50);max-width:380px;text-align:center;margin-bottom:32px}
.nav{position:fixed;right:16px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;z-index:50}
.dot{width:8px;height:8px;border-radius:50%;background:rgba(80,120,200,.18);cursor:pointer;transition:all .2s;border:1px solid rgba(80,120,200,.25)}
.dot.on,.dot:hover{background:rgba(100,165,255,.75);transform:scale(1.4)}
canvas{display:block;border-radius:4px}
</style>
</head>
<body>
<div class="nav" id="nav">
  <div class="dot on" onclick="go(0)" title="A · ₹ Pulse Core"></div>
  <div class="dot"    onclick="go(1)" title="B · Liquid Gold"></div>
  <div class="dot"    onclick="go(2)" title="C · Wealth Chakra"></div>
  <div class="dot"    onclick="go(3)" title="D · Terminal Bloom"></div>
  <div class="dot"    onclick="go(4)" title="E · Rupee Nova"></div>
</div>

<section id="s0">
  <div class="badge">Concept A</div>
  <div class="dtitle" style="color:#FFD060">₹ Pulse Core</div>
  <div class="dsub">Concentric gold rings orbit a central Rupee. The arc builds your corpus progress; particle sparks mark the frontier.</div>
  <canvas id="ca" width="340" height="340"></canvas>
</section>

<section id="s1">
  <div class="badge">Concept B</div>
  <div class="dtitle" style="color:#FFA820">Liquid Gold Vessel</div>
  <div class="dsub">Molten gold rises inside a circular vessel as your corpus grows. Bubbles rise through the liquid ₹.</div>
  <canvas id="cb" width="340" height="340"></canvas>
</section>

<section id="s2">
  <div class="badge">Concept C</div>
  <div class="dtitle" style="color:#FF9C30">Wealth Chakra</div>
  <div class="dsub">24-spoke radial design inspired by the Ashoka Chakra. Each spoke ignites gold as corpus builds.</div>
  <canvas id="cc" width="340" height="340"></canvas>
</section>

<section id="s3">
  <div class="badge">Concept D</div>
  <div class="dtitle" style="color:#00FF88">₹ Terminal Bloom</div>
  <div class="dsub">Bloomberg meets FIRE. Animated corpus-trajectory bars on a glowing phosphor trading terminal.</div>
  <canvas id="cd" width="560" height="300" style="border-radius:6px;"></canvas>
</section>

<section id="s4">
  <div class="badge">Concept E</div>
  <div class="dtitle" style="background:linear-gradient(135deg,#a855f7,#ff6b6b,#ffd700);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Rupee Nova</div>
  <div class="dsub">The ₹ at the heart of a supernova. Particle intensity mirrors your corpus progress — dramatic and unmissable.</div>
  <canvas id="ce" width="400" height="400"></canvas>
</section>

<script>
const PCT   = {{ fire.progress_pct | default(15) }};
const YEARS = {{ fire.years_to_fire | default(8) }};
const CUR   = {{ fire.current | default(500000) }};
const TGT   = {{ fire.target | default(22500000) }};
const SIP   = {{ fire.monthly_investment | default(127000) }};
const PI=Math.PI,cos=Math.cos,sin=Math.sin;

function inr(n){n=Math.round(n);const s=String(n);if(s.length<=3)return s;let r=s.slice(-3),rem=s.slice(0,-3);while(rem.length>2){r=rem.slice(-2)+','+r;rem=rem.slice(0,-2);}return(rem?rem+',':'')+r;}

function go(i){document.getElementById('s'+i).scrollIntoView({behavior:'smooth'});}
const dots=document.querySelectorAll('.dot');
const obs=new IntersectionObserver(entries=>{
  entries.forEach(e=>{if(e.isIntersecting&&e.intersectionRatio>0.5){const i=parseInt(e.target.id.slice(1));dots.forEach((d,j)=>d.classList.toggle('on',j===i));}});
},{threshold:0.5});
[0,1,2,3,4].forEach(i=>obs.observe(document.getElementById('s'+i)));

/* ═══════════════════════════════════════════════════════════════
   A: ₹ PULSE CORE — gold progress arc + glowing rupee + sparks
   ═══════════════════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('ca'),ctx=cv.getContext('2d');
  const W=340,H=340,cx=170,cy=170,T0=performance.now();
  const sparks=Array.from({length:32},()=>({life:Math.random(),spd:0.4+Math.random()*0.7}));
  function frame(now){
    const t=(now-T0)/1000,pulse=(sin(t*2.2)+1)/2;
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createRadialGradient(cx,cy,0,cx,cy,170);
    bg.addColorStop(0,'rgba(32,18,0,.6)');bg.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
    // rotating dashed rings
    [[130,.07,'rgba(255,165,0,.10)'],[114,-.11,'rgba(255,190,30,.09)']].forEach(([r,spd,c])=>{
      ctx.save();ctx.translate(cx,cy);ctx.rotate(t*spd);
      ctx.beginPath();ctx.arc(0,0,r,0,2*PI);
      ctx.strokeStyle=c;ctx.lineWidth=1;ctx.setLineDash([8,16]);ctx.stroke();ctx.setLineDash([]);ctx.restore();
    });
    // track
    ctx.beginPath();ctx.arc(cx,cy,100,0,2*PI);
    ctx.strokeStyle='rgba(28,12,0,.92)';ctx.lineWidth=14;ctx.stroke();
    // arc
    const progA=-PI/2+2*PI*Math.max(PCT,.5)/100;
    ctx.beginPath();ctx.arc(cx,cy,100,-PI/2,progA);
    ctx.strokeStyle=`rgba(255,155,0,${.12+pulse*.08})`;ctx.lineWidth=30;ctx.stroke();
    ctx.beginPath();ctx.arc(cx,cy,100,-PI/2,progA);
    ctx.strokeStyle=`rgba(255,205,50,${.22+pulse*.10})`;ctx.lineWidth=18;ctx.stroke();
    const ag=ctx.createLinearGradient(cx,cy-100,cx+100*cos(progA),cy+100*sin(progA));
    ag.addColorStop(0,'rgba(160,85,0,.85)');ag.addColorStop(.6,'#FFA500');ag.addColorStop(1,'#FFD700');
    ctx.beginPath();ctx.arc(cx,cy,100,-PI/2,progA);
    ctx.strokeStyle=ag;ctx.lineWidth=10;ctx.shadowBlur=24;ctx.shadowColor='#FFB800';ctx.stroke();ctx.shadowBlur=0;
    ctx.beginPath();ctx.arc(cx,cy,100,-PI/2,progA);
    ctx.strokeStyle='rgba(255,248,180,.48)';ctx.lineWidth=2;ctx.stroke();
    // inner rings
    [80,60].forEach(r=>{ctx.beginPath();ctx.arc(cx,cy,r,0,2*PI);ctx.strokeStyle='rgba(255,150,0,.06)';ctx.lineWidth=1;ctx.stroke();});
    // sparks near tip
    const tipA=progA;
    sparks.forEach((s,i)=>{
      s.life+=s.spd*0.016;if(s.life>1)s.life=0;
      const off=(i-16)*0.008,sa=tipA+off,sr=100+s.life*18;
      const px=cx+sr*cos(sa),py=cy+sr*sin(sa);
      ctx.beginPath();ctx.arc(px,py,1.5*(1-s.life),0,2*PI);
      ctx.fillStyle=`rgba(255,210,60,${(1-s.life)*.75})`;ctx.fill();
    });
    // tip dot
    ctx.beginPath();ctx.arc(cx+100*cos(progA),cy+100*sin(progA),5+pulse*2.5,0,2*PI);
    ctx.fillStyle='#FFFCE0';ctx.shadowBlur=20+pulse*14;ctx.shadowColor='#FFD700';ctx.fill();ctx.shadowBlur=0;
    // rupee symbol
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font=`bold 70px Georgia,serif`;
    ctx.shadowBlur=32+pulse*22;ctx.shadowColor='#FFB800';
    ctx.fillStyle=`hsl(42,100%,${50+pulse*14}%)`;ctx.fillText('₹',cx,cy-2);ctx.shadowBlur=0;
    // labels
    ctx.font='bold 14px "JetBrains Mono",monospace';ctx.fillStyle=`rgba(255,200,80,.68)`;
    ctx.fillText(PCT.toFixed(1)+'%',cx,cy+46);
    ctx.font='9px monospace';ctx.fillStyle='rgba(255,155,40,.38)';
    ctx.fillText(YEARS.toFixed(1)+' YRS  ·  ₹'+inr(CUR),cx,cy+62);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

/* ═══════════════════════════════════════════════════════════════
   B: LIQUID GOLD VESSEL — molten gold fills a circular vessel
   ═══════════════════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('cb'),ctx=cv.getContext('2d');
  const W=340,H=340,cx=170,cy=170,R=145,T0=performance.now();
  const fillF=Math.max(PCT,1)/100;
  const bubbles=Array.from({length:22},()=>({
    x:cx+(Math.random()-.5)*220,y:cy+R-Math.random()*R*1.6,
    r:1.2+Math.random()*2.8,spd:.25+Math.random()*.6}));
  function frame(now){
    const t=(now-T0)/1000,pulse=(sin(t*1.8)+1)/2;
    ctx.clearRect(0,0,W,H);
    // clip to vessel circle
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,R,0,2*PI);ctx.clip();
    const bg=ctx.createRadialGradient(cx,cy,0,cx,cy,R);
    bg.addColorStop(0,'#0a0500');bg.addColorStop(1,'#040200');
    ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
    const fillTop=cy+R-2*R*fillF;
    // liquid body
    const lg=ctx.createLinearGradient(0,fillTop,0,cy+R);
    lg.addColorStop(0,'rgba(255,175,15,.88)');lg.addColorStop(.35,'rgba(220,110,0,.82)');
    lg.addColorStop(.7,'rgba(170,62,0,.78)');lg.addColorStop(1,'rgba(110,32,0,.72)');
    ctx.beginPath();ctx.moveTo(0,fillTop);
    for(let x=0;x<=W;x+=3){
      const w=sin(x*.024+t*2.3)*7+sin(x*.041-t*1.6)*3.5;
      ctx.lineTo(x,fillTop+w);
    }
    ctx.lineTo(W,H+5);ctx.lineTo(0,H+5);ctx.closePath();
    ctx.fillStyle=lg;ctx.fill();
    // shimmer on wave surface
    ctx.beginPath();ctx.moveTo(0,fillTop);
    for(let x=0;x<=W;x+=3){ctx.lineTo(x,fillTop+sin(x*.024+t*2.3)*7+sin(x*.041-t*1.6)*3.5);}
    ctx.strokeStyle=`rgba(255,238,110,${.28+pulse*.22})`;ctx.lineWidth=2;ctx.stroke();
    // bubbles
    bubbles.forEach(b=>{
      b.y-=b.spd*.35;if(b.y<fillTop-5){b.y=cy+R-3;b.x=cx+(Math.random()-.5)*200;}
      if(b.y>fillTop){
        ctx.beginPath();ctx.arc(b.x,b.y,b.r,0,2*PI);
        ctx.strokeStyle='rgba(255,210,80,.32)';ctx.lineWidth=.8;ctx.stroke();
      }
    });
    // subsurface glow
    const sg=ctx.createRadialGradient(cx,cy+R*.2,0,cx,cy+R*.2,R*.85);
    sg.addColorStop(0,`rgba(255,110,0,${.14+pulse*.05})`);sg.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=sg;ctx.fillRect(0,fillTop,W,H);
    ctx.restore();
    // vessel border
    ctx.beginPath();ctx.arc(cx,cy,R,0,2*PI);
    ctx.strokeStyle=`rgba(255,${138+pulse*38},0,${.38+pulse*.14})`;ctx.lineWidth=3;
    ctx.shadowBlur=22+pulse*16;ctx.shadowColor='rgba(255,130,0,.5)';ctx.stroke();ctx.shadowBlur=0;
    ctx.beginPath();ctx.arc(cx,cy,R+9,0,2*PI);
    ctx.strokeStyle='rgba(255,130,0,.07)';ctx.lineWidth=1;ctx.setLineDash([7,15]);ctx.stroke();ctx.setLineDash([]);
    // level marker
    ctx.beginPath();ctx.moveTo(cx-R-16,fillTop);ctx.lineTo(cx-R-4,fillTop);
    ctx.strokeStyle=`rgba(255,190,55,${.42+pulse*.18})`;ctx.lineWidth=1.5;ctx.stroke();
    ctx.textAlign='right';ctx.textBaseline='middle';ctx.font='8px "JetBrains Mono",monospace';
    ctx.fillStyle='rgba(255,180,50,.40)';ctx.fillText(PCT.toFixed(1)+'%',cx-R-18,fillTop);
    // rupee in liquid
    const ry=Math.min(fillTop-18,cy-32);
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font='bold 66px Georgia,serif';
    ctx.shadowBlur=pulse>0.65?28:10;ctx.shadowColor='#FFD700';
    ctx.fillStyle=`rgba(255,${218+pulse*37},${55+pulse*38},${.72+pulse*.25})`;
    ctx.fillText('₹',cx,Math.max(ry,cy-38));ctx.shadowBlur=0;
    // bottom label
    ctx.font='bold 15px "JetBrains Mono",monospace';ctx.fillStyle=`rgba(255,195,75,${.58+pulse*.18})`;
    ctx.fillText(PCT.toFixed(1)+'% filled',cx,cy+R+22);
    ctx.font='9px monospace';ctx.fillStyle='rgba(195,130,38,.42)';
    ctx.fillText('TARGET ₹'+inr(TGT)+'  ·  ₹'+inr(CUR)+' now',cx,cy+R+38);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

/* ═══════════════════════════════════════════════════════════════
   C: WEALTH CHAKRA — 24-spoke Ashoka-inspired radial fill
   ═══════════════════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('cc'),ctx=cv.getContext('2d');
  const W=340,H=340,cx=170,cy=170,T0=performance.now();
  const SPOKES=24,SEGS=8,filledSpokes=Math.round(SPOKES*PCT/100);
  function frame(now){
    const t=(now-T0)/1000,pulse=(sin(t*2.0)+1)/2;
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createRadialGradient(cx,cy,0,cx,cy,170);
    bg.addColorStop(0,'rgba(22,8,0,.55)');bg.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
    ctx.save();ctx.translate(cx,cy);ctx.rotate(t*.035);
    // spokes
    for(let s=0;s<SPOKES;s++){
      const a=(2*PI/SPOKES)*s-PI/2,lit=s<filledSpokes;
      for(let seg=0;seg<SEGS;seg++){
        const r1=22+seg*14,r2=r1+11,hw=.042;
        ctx.beginPath();ctx.arc(0,0,r2,a-hw,a+hw);ctx.arc(0,0,r1,a+hw,a-hw,true);ctx.closePath();
        if(lit){
          const iv=(seg+1)/SEGS,hue=36+seg*4;
          ctx.fillStyle=`hsla(${hue},100%,${40+iv*24}%,${.55+iv*.38})`;
          ctx.shadowBlur=5+iv*9;ctx.shadowColor=`hsl(${hue},100%,58%)`;
        }else{
          ctx.fillStyle='rgba(38,18,4,.48)';ctx.shadowBlur=0;
        }
        ctx.fill();ctx.shadowBlur=0;
      }
      if(lit){
        const tr=22+SEGS*14+9;
        ctx.beginPath();ctx.arc(tr*cos(a),tr*sin(a),2.8,0,2*PI);
        ctx.fillStyle=`rgba(255,215,75,${.48+pulse*.4})`;
        ctx.shadowBlur=9+pulse*9;ctx.shadowColor='#FFD700';ctx.fill();ctx.shadowBlur=0;
      }
    }
    // outer rim arc
    const rimA=-PI/2+2*PI*Math.max(PCT,.5)/100;
    ctx.beginPath();ctx.arc(0,0,145,-PI/2,rimA);
    ctx.strokeStyle='rgba(255,145,0,.07)';ctx.lineWidth=18;ctx.stroke();
    ctx.beginPath();ctx.arc(0,0,145,-PI/2,rimA);
    ctx.strokeStyle=`rgba(255,175,28,${.22+pulse*.10})`;ctx.lineWidth=8;
    ctx.shadowBlur=14;ctx.shadowColor='rgba(255,140,0,.5)';ctx.stroke();ctx.shadowBlur=0;
    ctx.restore();
    // center disc
    ctx.beginPath();ctx.arc(cx,cy,21,0,2*PI);
    ctx.fillStyle='#080300';ctx.fill();
    ctx.beginPath();ctx.arc(cx,cy,21,0,2*PI);
    ctx.strokeStyle=`rgba(255,175,28,${.24+pulse*.14})`;ctx.lineWidth=1.5;ctx.stroke();
    // rupee
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font='bold 20px Georgia,serif';
    ctx.shadowBlur=14+pulse*8;ctx.shadowColor='#FFB800';
    ctx.fillStyle=`hsl(42,100%,${58+pulse*14}%)`;ctx.fillText('₹',cx,cy);ctx.shadowBlur=0;
    // labels
    ctx.font='bold 14px "JetBrains Mono",monospace';ctx.fillStyle='rgba(255,185,55,.62)';
    ctx.fillText(PCT.toFixed(1)+'%',cx,cy+163);
    ctx.font='9px monospace';ctx.fillStyle='rgba(195,125,28,.38)';
    ctx.fillText(YEARS.toFixed(1)+' YRS  ·  TARGET ₹'+inr(TGT),cx,cy+179);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

/* ═══════════════════════════════════════════════════════════════
   D: TERMINAL BLOOM — trading terminal projection bars + ticker
   ═══════════════════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('cd'),ctx=cv.getContext('2d');
  const W=560,H=300,T0=performance.now();
  const r=0.01,pmt=SIP;
  const bars=Array.from({length:13},(_,i)=>{
    const mo=i*9,fv=CUR*Math.pow(1+r,mo)+pmt*(Math.pow(1+r,mo)-1)/r;
    return Math.min(fv,TGT*1.05);
  });
  const maxB=Math.max(...bars);
  const ticker=['NIFTY +0.82%','SENSEX +0.91%','GOLD +0.40%','₹85.2/USD',
    'FIRE '+PCT.toFixed(1)+'%','CORPUS ₹'+inr(CUR),'TARGET ₹'+inr(TGT),
    'SIP ₹'+inr(SIP)+'/mo','YRS '+YEARS.toFixed(1)];
  let tx0=W,scanY=0;
  function frame(now){
    const t=(now-T0)/1000,pulse=(Math.sin(t*2.2)+1)/2;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle='#010904';ctx.fillRect(0,0,W,H);
    // scanlines
    for(let y=0;y<H;y+=4){ctx.fillStyle='rgba(0,0,0,.18)';ctx.fillRect(0,y,W,2);}
    scanY=(scanY+.5)%H;
    ctx.fillStyle='rgba(0,255,120,.03)';ctx.fillRect(0,scanY,W,3);
    // left panel — corpus amount
    const lw=225;
    ctx.textAlign='left';ctx.textBaseline='top';
    ctx.font='9px "JetBrains Mono",monospace';ctx.fillStyle='rgba(0,220,100,.38)';
    ctx.fillText('FIRE CORPUS',18,18);
    ctx.font=`bold 40px "JetBrains Mono",monospace`;
    ctx.fillStyle=`rgba(0,255,130,${.72+pulse*.2})`;
    ctx.shadowBlur=14+pulse*8;ctx.shadowColor='rgba(0,255,100,.45)';
    ctx.fillText('₹'+inr(CUR),18,36);ctx.shadowBlur=0;
    ctx.font='9px "JetBrains Mono",monospace';ctx.fillStyle='rgba(0,195,75,.42)';
    ctx.fillText('of ₹'+inr(TGT)+' target',18,86);
    // horizontal progress bar
    const pbx=18,pby=108,pbw=lw-10,pbh=26;
    ctx.fillStyle='rgba(0,36,14,.85)';ctx.fillRect(pbx,pby,pbw,pbh);
    const pf=ctx.createLinearGradient(pbx,0,pbx+pbw*PCT/100,0);
    pf.addColorStop(0,'rgba(0,165,55,.62)');pf.addColorStop(1,`rgba(0,255,105,${.68+pulse*.15})`);
    ctx.fillStyle=pf;ctx.fillRect(pbx,pby,pbw*PCT/100,pbh);
    ctx.strokeStyle='rgba(0,175,65,.22)';ctx.lineWidth=1;ctx.strokeRect(pbx,pby,pbw,pbh);
    // % label in bar
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font='bold 14px "JetBrains Mono",monospace';
    ctx.fillStyle=`rgba(0,255,120,${.52+pulse*.2})`;
    ctx.fillText(PCT.toFixed(1)+'%  ·  '+YEARS.toFixed(1)+' yrs',pbx+pbw/2,pby+pbh/2);
    // right panel — trajectory bars
    const bx0=255,by0=18,bH=H-58,bW=W-bx0-14;
    const bw=Math.floor((bW-bars.length*3)/bars.length);
    ctx.textAlign='left';ctx.textBaseline='top';
    ctx.font='7px "JetBrains Mono",monospace';ctx.fillStyle='rgba(0,195,75,.36)';
    ctx.fillText('CORPUS TRAJECTORY · 9-MO STEPS',bx0,8);
    bars.forEach((v,i)=>{
      const bh=Math.round(v/maxB*bH),bx=bx0+i*(bw+3),by=by0+bH-bh;
      const isCur=i===0;
      const g=ctx.createLinearGradient(0,by,0,by+bh);
      if(isCur){g.addColorStop(0,`rgba(0,255,130,${.65+pulse*.2})`);g.addColorStop(1,'rgba(0,145,55,.5)');}
      else{g.addColorStop(0,'rgba(0,215,95,.33)');g.addColorStop(1,'rgba(0,110,45,.22)');}
      ctx.fillStyle=g;ctx.fillRect(bx,by,bw,bh);
      if(isCur){
        ctx.shadowBlur=8;ctx.shadowColor='rgba(0,255,100,.5)';
        ctx.strokeStyle=`rgba(0,255,130,${.48+pulse*.28})`;ctx.lineWidth=1.5;ctx.strokeRect(bx,by,bw,bh);ctx.shadowBlur=0;
      }
      // target line
      if(v>=TGT*.998&&i>0&&i<bars.length-1){
        const ty=by0+bH-Math.round(TGT/maxB*bH);
        ctx.strokeStyle=`rgba(0,255,95,${.38+pulse*.18})`;ctx.lineWidth=1;ctx.setLineDash([4,7]);
        ctx.beginPath();ctx.moveTo(bx0,ty);ctx.lineTo(W-10,ty);ctx.stroke();ctx.setLineDash([]);
        ctx.textAlign='right';ctx.font='7px monospace';ctx.fillStyle='rgba(0,230,85,.48)';
        ctx.fillText('FIRE',W-12,ty-9);ctx.textAlign='left';
      }
    });
    // x-axis
    ctx.textAlign='center';ctx.font='7px "JetBrains Mono",monospace';ctx.fillStyle='rgba(0,155,65,.32)';
    bars.forEach((_,i)=>ctx.fillText(i===0?'NOW':'+'+Math.round(i*.75)+'Y',bx0+i*(bw+3)+bw/2,by0+bH+5));
    // ticker
    ctx.fillStyle='rgba(0,28,10,.92)';ctx.fillRect(0,H-30,W,30);
    ctx.strokeStyle='rgba(0,170,65,.18)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,H-30);ctx.lineTo(W,H-30);ctx.stroke();
    tx0-=.65;if(tx0<-ticker.join('   ').length*8)tx0=W;
    ctx.textAlign='left';ctx.textBaseline='middle';ctx.font='10px "JetBrains Mono",monospace';
    let tx=tx0;
    ticker.forEach(item=>{
      ctx.fillStyle=item.includes('+')?'rgba(0,255,120,.70)':'rgba(0,195,85,.50)';
      ctx.fillText(item,tx,H-15);tx+=ctx.measureText(item).width+36;
    });
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

/* ═══════════════════════════════════════════════════════════════
   E: RUPEE NOVA — supernova particle burst, corpus = intensity
   ═══════════════════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('ce'),ctx=cv.getContext('2d');
  const W=400,H=400,cx=200,cy=200,T0=performance.now();
  const frac=Math.max(PCT,2)/100;
  const PCNT=200;
  const pts=Array.from({length:PCNT},(_,i)=>{
    const a=(2*PI/PCNT)*i+Math.random()*.18;
    return{a,baseA:a,spd:.4+Math.random()*1.1,dist:18+Math.random()*165*frac,
      r:1.2+Math.random()*2,hue:30+Math.random()*55,life:Math.random(),
      decay:.006+Math.random()*.013,orb:Math.random()<.28};
  });
  function frame(now){
    const t=(now-T0)/1000,pulse=(sin(t*2.0)+1)/2;
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createRadialGradient(cx,cy,0,cx,cy,200);
    bg.addColorStop(0,'rgba(16,4,38,.72)');bg.addColorStop(.5,'rgba(5,1,18,.58)');bg.addColorStop(1,'rgba(0,0,4,0)');
    ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
    // nebula haze
    [175,130,88].forEach((r,i)=>{
      ctx.beginPath();ctx.arc(cx,cy,r,0,2*PI);
      ctx.strokeStyle=`rgba(${118+i*28},${36+i*18},${200-i*28},.04)`;
      ctx.lineWidth=18-i*3;ctx.stroke();
    });
    // particles
    pts.forEach(p=>{
      p.life-=p.decay;
      if(p.life<=0){p.life=1;p.dist=16+Math.random()*165*frac;p.a=p.baseA+(Math.random()-.5)*.28;}
      const drift=p.orb?sin(t*p.spd*.5+p.baseA)*.28:0;
      const px=cx+p.dist*cos(p.a+drift+t*p.spd*.04);
      const py=cy+p.dist*sin(p.a+drift+t*p.spd*.04);
      const al=p.life*Math.min(p.dist/55,1);
      const pg=ctx.createRadialGradient(px,py,0,px,py,p.r*2.2);
      pg.addColorStop(0,`hsla(${p.hue},100%,82%,${al})`);
      pg.addColorStop(.45,`hsla(${p.hue},100%,55%,${al*.58})`);
      pg.addColorStop(1,`hsla(${p.hue-18},80%,28%,0)`);
      ctx.beginPath();ctx.arc(px,py,p.r*2.2,0,2*PI);ctx.fillStyle=pg;ctx.fill();
    });
    // outer progress arc
    const progA=-PI/2+2*PI*Math.max(PCT,.5)/100;
    [[24,.07],[16,.14],[9,.38]].forEach(([lw,a])=>{
      ctx.beginPath();ctx.arc(cx,cy,158,-PI/2,progA);
      ctx.strokeStyle=`rgba(185,80,255,${a+pulse*.05})`;ctx.lineWidth=lw;ctx.stroke();
    });
    // tip dot on arc
    ctx.beginPath();ctx.arc(cx+158*cos(progA),cy+158*sin(progA),4+pulse*2,0,2*PI);
    ctx.fillStyle='#fff';ctx.shadowBlur=14+pulse*12;ctx.shadowColor='#fff';ctx.fill();ctx.shadowBlur=0;
    // central nova burst
    const ng=ctx.createRadialGradient(cx,cy,0,cx,cy,75);
    ng.addColorStop(0,`rgba(255,255,210,${.88+pulse*.10})`);
    ng.addColorStop(.18,`rgba(255,205,55,${.52+pulse*.10})`);
    ng.addColorStop(.45,'rgba(195,75,0,.22)');
    ng.addColorStop(.75,'rgba(95,18,175,.08)');
    ng.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=ng;ctx.fillRect(0,0,W,H);
    // rupee
    ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.font='bold 76px Georgia,serif';
    ctx.shadowBlur=38+pulse*28;ctx.shadowColor='rgba(255,200,50,.92)';
    ctx.fillStyle=`rgba(255,${214+pulse*41},${72+pulse*42},${.9+pulse*.1})`;
    ctx.fillText('₹',cx,cy);ctx.shadowBlur=0;
    // labels
    ctx.font='bold 15px "JetBrains Mono",monospace';
    ctx.fillStyle=`rgba(195,135,255,${.52+pulse*.2})`;
    ctx.fillText(PCT.toFixed(1)+'%',cx,cy+52);
    ctx.font='9px monospace';ctx.fillStyle='rgba(152,95,215,.35)';
    ctx.fillText(YEARS.toFixed(1)+' YRS  ·  ₹'+inr(CUR),cx,cy+68);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Route: preview dashboard (/dashboard_pp) — LOCAL ONLY.
# The SAME live dashboard as /dashboard_main, but served for reviewing develop
# before promotion. In the deploy pipeline the preview webhook (:5002, develop
# worktree) serves this. Any request arriving via the Cloudflare tunnel/relay
# (which sets Cf-Connecting-Ip) is rejected, so dashboard_pp is never public on
# either instance.
# ---------------------------------------------------------------------------

def _via_tunnel() -> bool:
    return bool(request.headers.get('Cf-Connecting-Ip')
                or request.headers.get('Cf-Ray')
                or request.headers.get('X-Forwarded-For'))


@app.route('/dashboard_pp', methods=['GET'])
def dashboard_pp():
    if _via_tunnel():
        return 'Not found.', 404          # local-only: not reachable through the relay
    return dashboard_main()


# ---------------------------------------------------------------------------
# Route: FIRE visualization design picker (/fire-designs)
# ---------------------------------------------------------------------------

@app.route('/fire-designs', methods=['GET'])
def fire_designs():
    import json as _j
    fire_data = {
        'current': 690718, 'target': 22500000, 'gap': 21809282,
        'progress_pct': 30.7, 'years_to_fire': 8.2, 'monthly_investment': 127000,
    }
    for broker in ('paytm', 'zerodha'):
        path = os.path.join(_MYDATA, f'{broker}_data.json')
        if os.path.exists(path):
            try:
                with open(path) as f:
                    d = _j.load(f)
                    if 'fire' in d:
                        fire_data.update(d['fire'])
                        break
            except Exception:
                pass
    return render_template_string(_FIRE_DESIGN_HTML, fire=fire_data), 200


# ---------------------------------------------------------------------------
# Route 5: FIRE ring design preview
# ---------------------------------------------------------------------------

@app.route('/fire-preview', methods=['GET'])
def fire_preview():
    import json as _j
    fire_data = {
        'current': 690718, 'target': 22500000, 'gap': 21809282,
        'progress_pct': 30.7, 'years_to_fire': 18.2,
        'monthly_investment': 127000,
    }
    for broker in ('paytm', 'zerodha'):
        path = os.path.join(_MYDATA, f'{broker}_data.json')
        if os.path.exists(path):
            with open(path) as f:
                d = _j.load(f)
                if 'fire' in d:
                    fire_data.update(d['fire'])
                    break
    pct = fire_data.get('progress_pct', 30.7)
    return render_template_string(_FIRE_PREVIEW_HTML, fire=fire_data, pct=pct), 200


# ---------------------------------------------------------------------------
# Route 6: Health probe
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok'}, 200


if __name__ == '__main__':
    port = int(os.getenv('WEBHOOK_PORT', 5001))

    # Suppress server fingerprinting — don't leak Werkzeug/Python versions.
    import werkzeug.serving as _ws
    _ws.WSGIRequestHandler.server_version = 'portfolio'
    _ws.WSGIRequestHandler.sys_version = ''

    # Bind to loopback when a tunnel fronts the app; the cloudflared tunnel
    # connects to localhost, so there is no need to listen on all interfaces.
    host = os.getenv('WEBHOOK_BIND', '127.0.0.1')
    app.run(host=host, port=port, debug=False)
