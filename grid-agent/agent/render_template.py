"""Leaflet HTML template for grid blueprint renders."""

from __future__ import annotations


GRID_BLUEPRINT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grid Topology Blueprint</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html, body, #map {{ height: 100%; margin: 0; background: #071019; }}
  body {{ font: 13px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  .leaflet-container {{
    background:
      linear-gradient(rgba(120,150,190,.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(120,150,190,.035) 1px, transparent 1px),
      #071019;
    background-size: 28px 28px;
    color: #e7edf5;
  }}
  .leaflet-control-attribution {{ display: none; }}
  .hud {{
    position: absolute; z-index: 500; top: 12px; left: 12px;
    display: flex; flex-direction: column; gap: 8px; pointer-events: none;
  }}
  .panel {{
    width: max-content; max-width: min(560px, calc(100vw - 40px));
    background: rgba(7,16,25,.88); border: 1px solid rgba(231,237,245,.16);
    border-radius: 6px; box-shadow: 0 12px 36px rgba(0,0,0,.34);
    backdrop-filter: blur(8px);
  }}
  .title {{ padding: 10px 12px; }}
  .title b {{
    display: block; font-size: 13px; letter-spacing: .12em; text-transform: uppercase;
    color: #e7edf5; margin-bottom: 2px;
  }}
  .title span {{ color: #9aa6ba; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }}
  .legend {{ padding: 8px 10px; display: flex; flex-wrap: wrap; gap: 9px 14px; }}
  .legend span {{ color: #b8c2d4; font-size: 11px; white-space: nowrap; }}
  .swatch {{
    display: inline-block; width: 18px; height: 3px; margin-right: 6px;
    vertical-align: middle; border-radius: 2px;
  }}
  .node-label {{
    color: #e7edf5; font: 600 10px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
    text-shadow: 0 1px 4px #000, 0 0 8px #000; white-space: nowrap;
  }}
  .leaflet-tooltip {{
    background: rgba(7,16,25,.94); border: 1px solid rgba(231,237,245,.18);
    color: #e7edf5; box-shadow: 0 8px 24px rgba(0,0,0,.32);
  }}
</style>
</head>
<body>
<div id="map"></div>
<div class="hud">
  <div class="panel title">
    <b>Grid Topology Blueprint</b>
    <span>{subtitle}</span>
  </div>
  <div class="panel legend">
    <span><i class="swatch" style="background:#2fe6cf"></i>safe</span>
    <span><i class="swatch" style="background:#ffb020"></i>near limit</span>
    <span><i class="swatch" style="background:#ff5a4d"></i>overloaded</span>
    <span>node size = real line degree</span>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const state = {payload};

const map = L.map('map', {{
  crs: L.CRS.Simple,
  preferCanvas: true,
  zoomControl: true,
  attributionControl: false
}});

map.createPane('grid-lines');
map.createPane('grid-nodes');
map.getPane('grid-lines').style.zIndex = 430;
map.getPane('grid-nodes').style.zIndex = 460;

const gridLineLayer = L.layerGroup([], {{pane: 'grid-lines'}}).addTo(map);
const gridNodeLayer = L.layerGroup([], {{pane: 'grid-nodes'}}).addTo(map);

function rhoColor(rho) {{
  if (rho >= 1.0) return '#ff5a4d';
  if (rho >= 0.85) return '#ffb020';
  return '#2fe6cf';
}}

state.lines.forEach(line => {{
  const polyline = L.polyline(line.path, {{
    pane: 'grid-lines',
    color: rhoColor(line.rho),
    weight: 2,
    opacity: line.rho >= 1.0 ? .98 : line.rho >= 0.85 ? .88 : .54,
    dashArray: line.online ? null : '6 6'
  }}).addTo(gridLineLayer);
  polyline.bindTooltip(
    `<b>Line ${{line.id}}</b><br>${{line.from_label}} -> ${{line.to_label}}<br>` +
    `rho: ${{line.rho.toFixed(2)}}<br>status: ${{line.online ? 'online' : 'offline'}}`,
    {{sticky: true}}
  );
}});

state.nodes.forEach(node => {{
  const marker = L.circleMarker([node.y, node.x], {{
    pane: 'grid-nodes',
    radius: Math.min(10, 3.5 + node.degree * 1.15),
    color: node.focus ? '#ffffff' : '#071019',
    weight: node.focus ? 2 : 1,
    fillColor: rhoColor(node.incident_rho),
    fillOpacity: .96,
    opacity: .98
  }}).addTo(gridNodeLayer);
  marker.bindTooltip(
    `<b>${{node.label}}</b><br>Grid2Op: ${{node.grid_name}}<br>` +
    `substation id: ${{node.id}}<br>degree: ${{node.degree}}<br>` +
    `worst incident rho: ${{node.incident_rho.toFixed(2)}}`,
    {{sticky: true}}
  );
  if (node.focus || node.degree >= 5 || node.incident_rho >= .85) {{
    L.marker([node.y, node.x], {{
      pane: 'grid-nodes',
      interactive: false,
      icon: L.divIcon({{
        className: 'node-label',
        html: node.label,
        iconSize: [130, 18],
        iconAnchor: [-9, 20]
      }})
    }}).addTo(gridNodeLayer);
  }}
}});

map.fitBounds(state.bounds, {{padding: [46, 46], maxZoom: state.focus ? 1 : 0}});

L.control.layers(
  {{}},
  {{
    'Real Grid2Op lines': gridLineLayer,
    'Substations': gridNodeLayer
  }},
  {{collapsed: true}}
).addTo(map);
</script>
</body>
</html>
"""


def render_grid_blueprint_html(payload: str, subtitle: str) -> str:
    return GRID_BLUEPRINT_TEMPLATE.format(payload=payload, subtitle=subtitle)
