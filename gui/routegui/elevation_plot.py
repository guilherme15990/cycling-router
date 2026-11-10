"""Grafico de altimetria em ``tk.Canvas`` (sem matplotlib)."""

from __future__ import annotations

import tkinter as tk
from typing import Sequence

from elevation import ElevationStats

BACKGROUND = "#0d1117"
GRID = "#21262d"
AXIS = "#8b949e"
TEXT = "#c9d1d9"
FILL = "#1f6feb"


class ElevationPlot(tk.Frame):
    """Perfil de elevacao x distancia."""

    def __init__(self, master: tk.Misc, *, height: int = 190) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(
            self, height=height, bg=BACKGROUND, highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self._stats: ElevationStats | None = None
        self._title = ""
        self._color = FILL
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

    # ------------------------------------------------------------------ API
    def show_message(self, text: str) -> None:
        self._stats = None
        self._title = text
        self.redraw()

    def set_profile(
        self, stats: ElevationStats | None, title: str = "", color: str = FILL
    ) -> None:
        self._stats = stats
        self._title = title
        self._color = color
        self.redraw()

    # --------------------------------------------------------------- desenho
    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())

        c.create_text(8, 8, text=self._title, anchor="nw", fill=TEXT,
                      font=("Segoe UI", 9, "bold"))

        profile = self._stats.profile if self._stats else ()
        if len(profile) < 2:
            c.create_text(
                w / 2, h / 2, text="sem dados de altimetria",
                fill=AXIS, font=("Segoe UI", 9),
            )
            return

        left, right = 52, w - 16
        top, bottom = 30, h - 26
        if right - left < 10 or bottom - top < 10:
            return

        distances = [sample.distance_m for sample in profile]
        heights = [sample.elevation_m for sample in profile]
        total_d = distances[-1] or 1.0
        lo, hi = min(heights), max(heights)
        span = (hi - lo) or 1.0
        lo -= span * 0.05
        hi += span * 0.05
        span = hi - lo

        def px(distance: float) -> float:
            return left + (distance / total_d) * (right - left)

        def py(height: float) -> float:
            return bottom - ((height - lo) / span) * (bottom - top)

        # grade horizontal + rotulos de altitude
        for index in range(5):
            frac = index / 4.0
            y = bottom - frac * (bottom - top)
            c.create_line(left, y, right, y, fill=GRID)
            value = lo + frac * span
            c.create_text(left - 6, y, text=f"{value:.0f}", anchor="e",
                          fill=AXIS, font=("Segoe UI", 8))

        # preenchimento sob a curva
        polygon = [px(distances[0]), bottom]
        for distance, height in zip(distances, heights):
            polygon += [px(distance), py(height)]
        polygon += [px(distances[-1]), bottom]
        c.create_polygon(*polygon, fill=self._color, stipple="gray25", outline="")

        # curva
        line = []
        for distance, height in zip(distances, heights):
            line += [px(distance), py(height)]
        c.create_line(*line, fill=self._color, width=2)

        # eixo e rotulos
        c.create_line(left, bottom, right, bottom, fill=AXIS)
        c.create_text(left, h - 8, text="0", anchor="w", fill=AXIS,
                      font=("Segoe UI", 8))
        c.create_text(right, h - 8, text=f"{total_d / 1000.0:.2f} km", anchor="e",
                      fill=AXIS, font=("Segoe UI", 8))

        if self._stats:
            c.create_text(
                right, 8,
                text=(
                    f"subida {self._stats.gain_m:.0f} m  "
                    f"descida {self._stats.loss_m:.0f} m  "
                    f"min {self._stats.min_elevation_m:.0f}  "
                    f"max {self._stats.max_elevation_m:.0f}"
                ),
                anchor="ne", fill=AXIS, font=("Segoe UI", 8),
            )
