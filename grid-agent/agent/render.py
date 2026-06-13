"""Per-state Leaflet blueprint renders for the Grid2Op topology."""

import json
import math
import os

from agent.labels import substation_label
from agent.render_template import render_grid_blueprint_html


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAYOUT_DIR = os.path.join(ROOT, "data")
BLUEPRINT_BOUNDS = ((0.0, 0.0), (1000.0, 1000.0))


class GridRenderer:
    def __init__(self, observation_space, out_dir):
        self.name_sub = observation_space.name_sub
        self.substations = self._build_substations(len(self.name_sub))
        self.out_dir = out_dir
        self.layout_path = os.path.join(
            LAYOUT_DIR, f"grid2op_layout_{len(self.name_sub)}.json"
        )
        os.makedirs(out_dir, exist_ok=True)

    def render(self, obs, tag, focus_subs=None):
        """Write {tag}_full.html and {tag}_zoom.html; return absolute paths."""
        full = self._write(self._html(obs, focus_subs=None), f"{tag}_full.html")
        zoom = self._write(self._html(obs, focus_subs=focus_subs), f"{tag}_zoom.html")
        return full, zoom

    def _build_substations(self, n_sub):
        substations = []
        for sub_id in range(n_sub):
            grid_name = self.name_sub[sub_id] if sub_id < len(self.name_sub) else sub_id
            substations.append({"id": sub_id, "grid_name": str(grid_name)})
        return substations

    def _html(self, obs, focus_subs=None):
        data = self._render_data(obs, focus_subs)
        payload = json.dumps(data, separators=(",", ":"))
        subtitle = (
            f"max rho {data['max_rho']:.2f} | {data['n_overloaded']} overloaded | "
            f"{data['n_lines']} real Grid2Op lines"
        )
        return render_grid_blueprint_html(payload, subtitle)

    def _render_data(self, obs, focus_subs=None):
        focus = {int(sub) for sub in focus_subs or []}
        all_edges = self._edges(obs)
        degree = self._degree(all_edges)
        incident_rho = self._incident_rho(obs)
        coordinates = self._layout(obs, all_edges, degree)
        visible_subs = self._visible_substations(focus)
        nodes = self._render_nodes(coordinates, degree, incident_rho, visible_subs, focus)
        lines = self._render_lines(obs, nodes, visible_subs)

        return {
            "max_rho": round(float(obs.rho.max()), 4),
            "n_overloaded": int((obs.rho > 1.0).sum()),
            "n_lines": len(lines),
            "focus": bool(focus),
            "bounds": self._bounds(nodes),
            "nodes": nodes,
            "lines": lines,
        }

    def _render_nodes(self, coordinates, degree, incident_rho, visible_subs, focus):
        nodes = []
        for site in self.substations:
            sub_id = site["id"]
            if sub_id not in visible_subs:
                continue
            x, y = coordinates[sub_id]
            nodes.append(
                {
                    **site,
                    "label": substation_label(sub_id, degree[sub_id], incident_rho[sub_id]),
                    "x": x,
                    "y": y,
                    "degree": degree[sub_id],
                    "incident_rho": round(incident_rho[sub_id], 4),
                    "focus": sub_id in focus,
                }
            )
        return nodes

    def _render_lines(self, obs, nodes, visible_subs):
        nodes_by_id = {node["id"]: node for node in nodes}
        lines = []
        for line_id, rho in enumerate(obs.rho):
            from_sub = int(obs.line_or_to_subid[line_id])
            to_sub = int(obs.line_ex_to_subid[line_id])
            if from_sub not in visible_subs or to_sub not in visible_subs:
                continue
            from_site = nodes_by_id[from_sub]
            to_site = nodes_by_id[to_sub]
            lines.append(
                {
                    "id": int(line_id),
                    "rho": round(float(rho), 4),
                    "online": bool(obs.line_status[line_id]),
                    "from_label": from_site["label"],
                    "to_label": to_site["label"],
                    "path": [
                        [from_site["y"], from_site["x"]],
                        [to_site["y"], to_site["x"]],
                    ],
                }
            )
        return lines

    def _visible_substations(self, focus):
        if focus:
            return set(focus)
        return {site["id"] for site in self.substations}

    def _edges(self, obs):
        edges = []
        for line_id in range(len(obs.rho)):
            a = int(obs.line_or_to_subid[line_id])
            b = int(obs.line_ex_to_subid[line_id])
            if a != b:
                edges.append((a, b))
        return edges

    def _degree(self, edges):
        degree = [0 for _ in self.substations]
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        return degree

    def _incident_rho(self, obs):
        incident = [0.0 for _ in self.substations]
        for line_id, rho in enumerate(obs.rho):
            a = int(obs.line_or_to_subid[line_id])
            b = int(obs.line_ex_to_subid[line_id])
            incident[a] = max(incident[a], float(rho))
            incident[b] = max(incident[b], float(rho))
        return incident

    def _layout(self, obs, edges, degree):
        signature = self._topology_signature(edges)
        cached = self._load_layout(signature)
        if cached:
            return cached

        coordinates = self._spring_layout(edges, degree)
        self._save_layout(signature, coordinates)
        return coordinates

    def _load_layout(self, signature):
        try:
            with open(self.layout_path) as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if payload.get("signature") != signature:
            return None
        raw_coords = payload.get("coordinates", {})
        if len(raw_coords) != len(self.substations):
            return None
        return {
            int(sub_id): (float(point["x"]), float(point["y"]))
            for sub_id, point in raw_coords.items()
        }

    def _save_layout(self, signature, coordinates):
        os.makedirs(os.path.dirname(self.layout_path), exist_ok=True)
        payload = {
            "signature": signature,
            "coordinates": {
                str(sub_id): {"x": x, "y": y}
                for sub_id, (x, y) in sorted(coordinates.items())
            },
        }
        tmp = self.layout_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, self.layout_path)

    def _topology_signature(self, edges):
        normalized = sorted((min(a, b), max(a, b)) for a, b in edges)
        return f"layout=v2;n={len(self.substations)};edges={normalized}"

    def _spring_layout(self, edges, degree):
        n_sub = len(self.substations)
        positions = self._initial_positions(n_sub, degree)
        neighbors = self._neighbors(edges, n_sub)
        area = 1.0
        k = math.sqrt(area / max(1, n_sub))
        temperature = 0.11
        for iteration in range(520):
            disp = [[0.0, 0.0] for _ in range(n_sub)]
            self._apply_repulsion(positions, disp, n_sub, k)
            self._apply_attraction(positions, disp, edges, k)
            self._apply_displacements(positions, disp, n_sub, temperature)
            temperature *= 0.992
            self._pull_all_to_center(positions)
            if iteration % 40 == 0:
                self._pull_hubs_to_center(positions, degree)
                self._push_leaves_outward(positions, degree, neighbors)

        return self._normalize_positions(positions)

    def _neighbors(self, edges, n_sub):
        neighbors = [set() for _ in range(n_sub)]
        for a, b in edges:
            neighbors[a].add(b)
            neighbors[b].add(a)
        return neighbors

    def _apply_repulsion(self, positions, disp, n_sub, k):
        for i in range(n_sub):
            xi, yi = positions[i]
            for j in range(i + 1, n_sub):
                xj, yj = positions[j]
                dx = xi - xj
                dy = yi - yj
                dist = math.hypot(dx, dy) + 0.001
                force = (k * k) / dist
                fx = dx / dist * force
                fy = dy / dist * force
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy

    def _apply_attraction(self, positions, disp, edges, k):
        for a, b in edges:
            ax, ay = positions[a]
            bx, by = positions[b]
            dx = ax - bx
            dy = ay - by
            dist = math.hypot(dx, dy) + 0.001
            force = (dist * dist) / k
            fx = dx / dist * force
            fy = dy / dist * force
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy

    def _apply_displacements(self, positions, disp, n_sub, temperature):
        for sub_id in range(n_sub):
            dx, dy = disp[sub_id]
            length = math.hypot(dx, dy)
            if length > 0:
                scale = min(length, temperature) / length
                x, y = positions[sub_id]
                positions[sub_id] = (x + dx * scale, y + dy * scale)

    def _initial_positions(self, n_sub, degree):
        max_degree = max(degree) or 1
        positions = {}
        for sub_id in range(n_sub):
            angle = math.radians((sub_id * 137.508) % 360.0)
            hub_bias = 1.0 - degree[sub_id] / max_degree
            radius = 0.12 + 0.38 * hub_bias + 0.08 * ((sub_id * 17) % 7) / 6
            positions[sub_id] = (
                0.5 + math.cos(angle) * radius,
                0.5 + math.sin(angle) * radius,
            )
        return positions

    def _pull_hubs_to_center(self, positions, degree):
        max_degree = max(degree) or 1
        for sub_id, deg in enumerate(degree):
            strength = (deg / max_degree) ** 2 * 0.012
            x, y = positions[sub_id]
            positions[sub_id] = (
                x + (0.5 - x) * strength,
                y + (0.5 - y) * strength,
            )

    def _pull_all_to_center(self, positions):
        for sub_id, (x, y) in positions.items():
            positions[sub_id] = (
                x + (0.5 - x) * 0.0015,
                y + (0.5 - y) * 0.0015,
            )

    def _push_leaves_outward(self, positions, degree, neighbors):
        for sub_id, deg in enumerate(degree):
            if deg > 1 or not neighbors[sub_id]:
                continue
            neighbor = next(iter(neighbors[sub_id]))
            nx, ny = positions[neighbor]
            x, y = positions[sub_id]
            dx = x - nx
            dy = y - ny
            length = math.hypot(dx, dy) or 1.0
            positions[sub_id] = (
                x + dx / length * 0.012,
                y + dy / length * 0.012,
            )

    def _normalize_positions(self, positions):
        xs = [point[0] for point in positions.values()]
        ys = [point[1] for point in positions.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 0.001)
        span_y = max(max_y - min_y, 0.001)
        normalized = {}
        for sub_id, (x, y) in positions.items():
            out_x = 70.0 + ((x - min_x) / span_x) * 860.0
            out_y = 70.0 + ((y - min_y) / span_y) * 860.0
            normalized[sub_id] = (round(out_x, 3), round(out_y, 3))
        return normalized

    def _bounds(self, nodes):
        if not nodes:
            return [list(BLUEPRINT_BOUNDS[0]), list(BLUEPRINT_BOUNDS[1])]
        xs = [node["x"] for node in nodes]
        ys = [node["y"] for node in nodes]
        pad_x = max(50.0, (max(xs) - min(xs)) * 0.14)
        pad_y = max(50.0, (max(ys) - min(ys)) * 0.14)
        return [
            [min(ys) - pad_y, min(xs) - pad_x],
            [max(ys) + pad_y, max(xs) + pad_x],
        ]

    def _write(self, html, filename):
        path = os.path.join(self.out_dir, filename)
        with open(path, "w") as f:
            f.write(html)
        return path
