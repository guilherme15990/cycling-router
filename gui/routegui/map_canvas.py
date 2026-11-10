"""Canvas de mapa: tiles de fundo, rotas e marcadores, com pan/zoom.

Renderizacao sem compositing: cada tile vira um ``tk.PhotoImage`` colocado no
``Canvas`` (``create_image``). As rotas e marcadores sao itens vetoriais por
cima. Os tiles faltantes sao baixados em threads de trabalho e inseridos quando
chegam (a thread apenas devolve bytes; a ``PhotoImage`` e criada na thread do
Tk).
"""

from __future__ import annotations

import base64
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Sequence

from .proj import TILE_SIZE, WebMercatorView
from .tiles import OSM_LAYER, TileCache, TileLayer

ROUTE_COLORS = (
    "#2ecc71",
    "#f39c12",
    "#3498db",
    "#9b59b6",
    "#e74c3c",
    "#16a085",
)


@dataclass
class RouteOverlay:
    """Polilinha de uma rota em coordenadas ``(lat, lon)``."""

    coords: tuple[tuple[float, float], ...]
    color: str = "#2ecc71"


@dataclass
class Marker:
    """Marcador de origem/destino."""

    lat: float
    lon: float
    label: str
    color: str = "#e74c3c"


class MapCanvas(tk.Frame):
    """Widget de mapa interativo."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        layer: TileLayer = OSM_LAYER,
        cache: TileCache | None = None,
        on_click: Callable[[float, float], None] | None = None,
        on_view_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(
            self, bg="#101418", highlightthickness=0, width=800, height=600
        )
        self.canvas.pack(fill="both", expand=True)

        self.layer = layer
        self.cache = cache or TileCache(_default_cache_dir(), layer)
        self.on_click = on_click
        self.on_view_change = on_view_change

        self.view = WebMercatorView()
        self.routes: list[RouteOverlay] = []
        self.markers: list[Marker] = []
        self.highlight_index: int | None = 0
        self.status_text = ""

        self._tile_images: dict[tuple[int, int, int], tk.PhotoImage] = {}
        self._requested: set[tuple[int, int, int]] = set()
        self._incoming: "queue.Queue[tuple[tuple[int, int, int], bytes]]" = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tiles")

        self._press: tuple[int, int] | None = None
        self._dragged = False
        self._redraw_scheduled = False

        self._bind_events()
        self.after(80, self._drain_incoming)

    # ------------------------------------------------------------------ API
    def set_center(self, lat: float, lon: float, zoom: int | None = None) -> None:
        if zoom is not None:
            self.view.zoom = int(max(self.view.min_zoom, min(self.view.max_zoom, zoom)))
        self.view.set_center(lon, lat)
        self.redraw()

    def fit_bounds(
        self, south: float, west: float, north: float, east: float
    ) -> None:
        self.view.fit_bounds(south, west, north, east)
        self.redraw()

    def set_routes(
        self, routes: Sequence[RouteOverlay], *, highlight: int | None = 0
    ) -> None:
        self.routes = list(routes)
        self.highlight_index = highlight
        self.redraw()

    def set_markers(self, markers: Sequence[Marker]) -> None:
        self.markers = list(markers)
        self.redraw()

    # -------------------------------------------------------------- eventos
    def _bind_events(self) -> None:
        c = self.canvas
        c.bind("<Configure>", self._on_configure)
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom(1, e))  # X11
        c.bind("<Button-5>", lambda e: self._zoom(-1, e))  # X11

    def _on_configure(self, event: tk.Event) -> None:
        if event.width == self.view.width and event.height == self.view.height:
            return
        self.view.width = max(1, event.width)
        self.view.height = max(1, event.height)
        self.redraw()

    def _on_press(self, event: tk.Event) -> None:
        self._press = (event.x, event.y)
        self._dragged = False

    def _on_motion(self, event: tk.Event) -> None:
        if self._press is None:
            return
        dx = event.x - self._press[0]
        dy = event.y - self._press[1]
        if abs(dx) + abs(dy) < 3 and not self._dragged:
            return
        self._dragged = True
        self.view.pan_by_pixels(dx, dy)
        self._press = (event.x, event.y)
        self.redraw()

    def _on_release(self, event: tk.Event) -> None:
        if not self._dragged and self.on_click is not None:
            lat, lon = self.view.canvas_to_latlon(event.x, event.y)
            self.on_click(lat, lon)
        self._press = None
        self._dragged = False

    def _on_wheel(self, event: tk.Event) -> None:
        step = 1 if event.delta > 0 else -1
        self._zoom(step, event)

    def _zoom(self, step: int, event: tk.Event) -> None:
        before = self.view.zoom
        self.view.zoom_by(step, event.x, event.y)
        if self.view.zoom != before:
            self.redraw()

    # ------------------------------------------------------------- desenho
    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._draw_tiles()
        self._draw_routes()
        self._draw_markers()

    def _draw_tiles(self) -> None:
        view = self.view
        xs, ys = view.tile_range()
        for tile_y in ys:
            for tile_x in xs:
                key = (view.zoom, tile_x, tile_y)
                image = self._tile_images.get(key)
                if image is None:
                    self._request_tile(key)
                    continue
                ox, oy = view.tile_canvas_origin(tile_x, tile_y)
                self.canvas.create_image(ox, oy, image=image, anchor="nw")

    def _request_tile(self, key: tuple[int, int, int]) -> None:
        if key in self._requested:
            return
        self._requested.add(key)
        z, x, y = key
        self._executor.submit(self._fetch_tile, z, x, y)

    def _fetch_tile(self, z: int, x: int, y: int) -> None:
        try:
            data = self.cache.get(z, x, y)
        except Exception:
            data = None
        if data:
            self._incoming.put(((z, x, y), data))

    def _drain_incoming(self) -> None:
        added = False
        while True:
            try:
                key, data = self._incoming.get_nowait()
            except queue.Empty:
                break
            try:
                image = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
            except tk.TclError:
                continue
            self._tile_images[key] = image
            added = True
        if added:
            self.redraw()
        self.after(80, self._drain_incoming)

    def _draw_routes(self) -> None:
        for index, overlay in enumerate(self.routes):
            if len(overlay.coords) < 2:
                continue
            points = [
                coordinate
                for lat, lon in overlay.coords
                for coordinate in self.view.latlon_to_canvas(lat, lon)
            ]
            highlighted = self.highlight_index is None or index == self.highlight_index
            width = 6 if highlighted else 3
            color = overlay.color
            if not highlighted:
                self.canvas.create_line(
                    *points, fill=color, width=width + 3, stipple="gray50"
                )
            self.canvas.create_line(
                *points, fill=color, width=width, capstyle="round", joinstyle="round"
            )

    def _draw_markers(self) -> None:
        for marker in self.markers:
            x, y = self.view.latlon_to_canvas(marker.lat, marker.lon)
            r = 7
            self.canvas.create_oval(
                x - r, y - r, x + r, y + r, fill=marker.color, outline="white", width=2
            )
            self.canvas.create_text(
                x, y, text=marker.label, fill="white", font=("Segoe UI", 8, "bold")
            )

    # --------------------------------------------------------------- util
    def destroy(self) -> None:  # pragma: no cover - depende do Tk
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()


def _default_cache_dir():
    from .tiles import default_cache_root

    return default_cache_root()
