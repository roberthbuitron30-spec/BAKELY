from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ICONOS_LINEA = {"ALMIDON": "wheat", "BEBIDA": "wine", "COMUN": "package"}


@register.filter
def get_item(d, key):
    if d is None:
        return None
    return d.get(key)


@register.filter
def icono_linea(linea):
    return ICONOS_LINEA.get(linea, "box")


@register.filter
def estado_css(estado):
    """Estado de equipo/lote → clase de borde iluminado."""
    return {
        "OPERANDO": "glow-ok", "LIBERADO": "glow-ok", "CONFIRMADO": "glow-ok",
        "ALERTA": "glow-alert", "RECHAZADO": "glow-alert", "RETENIDO": "glow-alert", "ERROR": "glow-alert",
        "CUARENTENA": "glow-warn", "LIMPIEZA": "glow-warn", "PREP": "glow-warn", "PROC": "glow-info",
        "MANT": "glow-muted", "LIBRE": "glow-muted",
    }.get(str(estado), "glow-muted")


@register.simple_tag
def gauge(valor, minimo, maximo, etiqueta="", unidad="", escala_min=None, escala_max=None, size=120):
    """
    Dial circular SVG (270°). La franja verde marca el rango de especificación [minimo, maximo];
    la aguja se pinta en rojo si el valor sale del rango.
    """
    try:
        v = float(valor) if valor is not None else None
        lo, hi = float(minimo), float(maximo)
    except (TypeError, ValueError):
        return ""
    span = hi - lo or 1
    smin = float(escala_min) if escala_min is not None else lo - span * 0.5
    smax = float(escala_max) if escala_max is not None else hi + span * 0.5
    if smin < 0 <= lo:
        smin = 0

    def ang(x):
        x = max(smin, min(smax, x))
        return -135 + (x - smin) / ((smax - smin) or 1) * 270

    import math
    r, cx, cy = 46, 60, 60

    def punto(a, rr=r):
        rad = math.radians(a - 90)
        return cx + rr * math.cos(rad), cy + rr * math.sin(rad)

    def arco(a1, a2):
        x1, y1 = punto(a1)
        x2, y2 = punto(a2)
        grande = 1 if (a2 - a1) > 180 else 0
        return f"M{x1:.1f},{y1:.1f} A{r},{r} 0 {grande} 1 {x2:.1f},{y2:.1f}"

    fuera = v is not None and not (lo <= v <= hi)
    color = "var(--c-alert)" if fuera else "var(--c-ok)"
    aguja = ""
    texto = "—"
    if v is not None:
        nx, ny = punto(ang(v), r - 8)
        aguja = (f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="{color}" stroke-width="3" '
                 f'stroke-linecap="round" class="gauge-needle"/>')
        texto = (f"{v:.1f}" if abs(v) < 1000 else f"{v:.0f}").replace(".", ",")
    svg = f"""
<svg viewBox="0 0 120 112" width="{size}" height="{int(size * 112 / 120)}" class="gauge {'gauge-alert' if fuera else ''}"
     role="img" aria-label="{etiqueta} {texto} {unidad}, rango {lo}–{hi}">
  <path d="{arco(-135, 135)}" fill="none" stroke="var(--c-track)" stroke-width="9" stroke-linecap="round"/>
  <path d="{arco(ang(lo), ang(hi))}" fill="none" stroke="var(--c-ok-soft)" stroke-width="9"/>
  {aguja}
  <circle cx="{cx}" cy="{cy}" r="4" fill="{color}"/>
  <text x="60" y="88" text-anchor="middle" class="gauge-val" fill="{color}">{texto}<tspan class="gauge-unit"> {unidad}</tspan></text>
  <text x="60" y="104" text-anchor="middle" class="gauge-lbl">{etiqueta}</text>
</svg>"""
    return mark_safe(svg)


@register.simple_tag
def tank(porcentaje, estado="LIBRE", width=56, height=92):
    """Silueta de tanque con nivel de llenado animado."""
    p = max(0, min(100, int(porcentaje or 0)))
    h_liq = 72 * p / 100
    y = 12 + 72 - h_liq
    color = "var(--c-alert)" if estado == "ALERTA" else "var(--c-info)"
    return mark_safe(f"""
<svg viewBox="0 0 56 92" width="{width}" height="{height}" class="tank" aria-label="Nivel {p}%">
  <defs><clipPath id="tk{p}{estado}"><rect x="6" y="12" width="44" height="72" rx="10"/></clipPath></defs>
  <rect x="6" y="12" width="44" height="72" rx="10" fill="var(--c-track)"/>
  <g clip-path="url(#tk{p}{estado})">
    <rect x="0" y="{y:.1f}" width="56" height="{h_liq + 2:.1f}" fill="{color}" opacity=".55" class="tank-liquid"/>
  </g>
  <rect x="6" y="12" width="44" height="72" rx="10" fill="none" stroke="var(--c-border-strong)"/>
  <rect x="22" y="4" width="12" height="8" rx="2" fill="var(--c-border-strong)"/>
  <text x="28" y="54" text-anchor="middle" class="tank-pct">{p}%</text>
</svg>""")


@register.filter
def spec_rango(limites, var):
    r = (limites or {}).get(var)
    return r if r and len(r) == 2 else None


@register.filter
def dec(v, n=1):
    """Número con decimales fijos y formato local (es-EC: 1.234,50)."""
    from django.utils.formats import number_format
    try:
        return number_format(Decimal(str(v)), int(n), use_l10n=True, force_grouping=True)
    except Exception:
        return "—"


@register.filter
def etiqueta(clave):
    """humedad_max_pct → 'Humedad máx. (%)'"""
    t = str(clave).replace("_pct", " (%)").replace("_c", " (°C)").replace("_max", " máx.").replace("_min", " mín.")
    return t.replace("_", " ").capitalize()


VARIABLES = {"TEMP": ("Temperatura", "°C"), "PH": ("pH", ""), "BRIX": ("Brix", "°Bx"), "DENS": ("Densidad", "g/mL"),
             "ABV": ("Alcohol en flujo", "%"), "TVAP": ("Vapor", "°C"), "HUM": ("Humedad", "%"),
             "NIVEL": ("Nivel", "L"), "PRES": ("Presión", "bar")}


@register.filter
def var_nombre(codigo):
    return VARIABLES.get(codigo, (codigo, ""))[0]


@register.filter
def var_unidad(codigo):
    return VARIABLES.get(codigo, ("", ""))[1]
