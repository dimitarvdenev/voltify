"""Per-state Plotly renders: full grid overview plus affected-area zoom."""

import os

from grid2op.PlotGrid import PlotPlotly


class GridRenderer:
    def __init__(self, observation_space, out_dir):
        self.plot = PlotPlotly(observation_space)
        self.layout = self.plot._grid_layout
        self.name_sub = observation_space.name_sub
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def render(self, obs, tag, focus_subs=None):
        """Write {tag}_full.html and {tag}_zoom.html; return absolute paths."""
        full = self._write(self.plot.plot_obs(obs), f"{tag}_full.html")
        zoom_fig = self.plot.plot_obs(obs)
        if focus_subs:
            points = [
                self.layout[self.name_sub[sub]]
                for sub in focus_subs
                if self.name_sub[sub] in self.layout
            ]
            if points:
                xs, ys = [point[0] for point in points], [point[1] for point in points]
                pad_x = max(20.0, 0.4 * (max(xs) - min(xs)))
                pad_y = max(20.0, 0.4 * (max(ys) - min(ys)))
                zoom_fig.update_layout(
                    xaxis_range=[min(xs) - pad_x, max(xs) + pad_x],
                    yaxis_range=[min(ys) - pad_y, max(ys) + pad_y],
                )
        zoom = self._write(zoom_fig, f"{tag}_zoom.html")
        return full, zoom

    def _write(self, fig, filename):
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        path = os.path.join(self.out_dir, filename)
        fig.write_html(path, include_plotlyjs="cdn", full_html=True)
        return path
