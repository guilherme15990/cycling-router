"""Janela principal da GUI: controles, mapa, rotas e altimetria.

Arquitetura de threads: Tk so roda na thread principal. Trabalho lento (baixar
o grafo, rodar a busca, buscar tiles Terrarium) roda em threads e devolve o
resultado por uma fila; a thread principal drena a fila em ``after``.
"""

from __future__ import annotations

# Permite executar este arquivo diretamente (``python app.py``): sem o pacote,
# os imports relativos abaixo falham. Nesse caso, reenviamos para o pacote
# ``routegui`` e paramos por aqui.
if __package__ in (None, ""):
    import sys
    from pathlib import Path

    _GUI_ROOT = Path(__file__).resolve().parent.parent
    _SRC = _GUI_ROOT.parent / "src"
    for _path in (str(_GUI_ROOT), str(_SRC)):
        if _path not in sys.path:
            sys.path.insert(0, _path)
    from routegui.app import main

    raise SystemExit(main())

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from elevation import ElevationStats, build_elevation_profile

from .engine_bridge import (
    EngineSettings,
    RouteComputation,
    RoutingEngine,
    graph_bounds,
    load_graph,
)
from .elevation_plot import ElevationPlot
from .map_canvas import ROUTE_COLORS, MapCanvas, Marker, RouteOverlay
from .terrain import TerrariumElevation
from .tiles import TERRARIUM_LAYER, TileCache, default_cache_root

PROFILE_ORDER = ("fastest", "shortest", "flattest", "balanced", "electric")
PROFILE_LABELS = {
    "fastest": "Mais rapido",
    "shortest": "Mais curto",
    "flattest": "Mais plano",
    "balanced": "Equilibrado",
    "electric": "Eletrico",
}
DEFAULT_GRAPH = "data/se.json"


class App:
    """Controlador da interface."""

    def __init__(self, root: tk.Tk, graph_path: str | None = None) -> None:
        self.root = root
        self.root.title("Roteamento ciclistico - GUI de teste")
        self.root.geometry("1280x860")

        self.engine: RoutingEngine | None = None
        self.origin: tuple[float, float] | None = None
        self.destination: tuple[float, float] | None = None
        self.computation: RouteComputation | None = None
        self.selected_index: int | None = None
        self._profile_cache: dict[str, ElevationStats] = {}

        self._results: "queue.Queue[tuple[Callable, bool, object]]" = queue.Queue()

        cache_root = default_cache_root()
        self.terrain_cache = TileCache(cache_root, TERRARIUM_LAYER)

        self._build_widgets()

        if graph_path:
            self.graph_path_var.set(graph_path)
        self.root.after(120, self._load_graph)
        self.root.after(100, self._poll_results)

    # ------------------------------------------------------------- widgets
    def _build_widgets(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.grid(row=0, column=0, sticky="ew")

        ttk.Label(toolbar, text="Grafo:").pack(side="left")
        self.graph_path_var = tk.StringVar(value=DEFAULT_GRAPH)
        ttk.Entry(toolbar, textvariable=self.graph_path_var, width=22).pack(
            side="left", padx=(4, 4)
        )
        ttk.Button(toolbar, text="Carregar", command=self._load_graph).pack(side="left")

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="Perfil:").pack(side="left")
        self.profile_var = tk.StringVar(value=PROFILE_LABELS["fastest"])
        profile_box = ttk.Combobox(
            toolbar,
            textvariable=self.profile_var,
            values=[PROFILE_LABELS[key] for key in PROFILE_ORDER],
            state="readonly",
            width=12,
        )
        profile_box.pack(side="left", padx=(4, 8))

        ttk.Label(toolbar, text="N rotas:").pack(side="left")
        self.max_routes_var = tk.StringVar(value="3")
        ttk.Spinbox(
            toolbar, from_=1, to=8, textvariable=self.max_routes_var, width=3
        ).pack(side="left", padx=(4, 8))

        ttk.Label(toolbar, text="v0 (m/s):").pack(side="left")
        self.initial_speed_var = tk.StringVar(value="0")
        ttk.Entry(
            toolbar, textvariable=self.initial_speed_var, width=5
        ).pack(side="left", padx=(4, 8))

        ttk.Button(toolbar, text="Roteirizar", command=self._start_route).pack(
            side="left", padx=(4, 4)
        )
        ttk.Button(toolbar, text="Limpar", command=self._clear_all).pack(side="left")

        # ------------------------------------------------- painel lateral
        body = ttk.Frame(self.root)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.map = MapCanvas(body, on_click=self._on_map_click)
        self.map.grid(row=0, column=0, sticky="nsew")

        side = ttk.Frame(body, padding=6, width=340)
        side.grid(row=0, column=1, sticky="nsew")
        side.grid_propagate(False)
        side.rowconfigure(3, weight=1)

        ttk.Label(
            side,
            text="Clique no mapa: 1o = origem (A), 2o = destino (B).",
            wraplength=320,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        # parametros fisicos
        physics = ttk.LabelFrame(side, text="Fisica", padding=4)
        physics.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.mass_var = tk.StringVar(value="75")
        self.power_var = tk.StringVar(value="200")
        self.bike_mass_var = tk.StringVar(value="12")
        self.safe_speed_var = tk.StringVar(value="22")
        self.unlimited_var = tk.BooleanVar(value=False)
        self.terrain_zoom_var = tk.StringVar(value="12")

        rows = (
            ("Massa ciclista (kg)", self.mass_var),
            ("Potencia sustentavel (W)", self.power_var),
            ("Massa bicicleta (kg)", self.bike_mass_var),
            ("Teto velocidade (m/s)", self.safe_speed_var),
            ("Zoom altimetria (0-15)", self.terrain_zoom_var),
        )
        for index, (label, variable) in enumerate(rows):
            ttk.Label(physics, text=label).grid(
                row=index, column=0, sticky="w", padx=(0, 4)
            )
            ttk.Entry(physics, textvariable=variable, width=8).grid(
                row=index, column=1, sticky="e"
            )
        physics.columnconfigure(1, weight=1)
        ttk.Checkbutton(
            physics, text="Teto ilimitado", variable=self.unlimited_var
        ).grid(row=len(rows), column=0, columnspan=2, sticky="w")

        # resultados
        ttk.Label(side, text="Rotas selecionadas").grid(
            row=2, column=0, sticky="w", pady=(4, 2)
        )
        columns = ("rank", "time", "dist", "asc", "wh")
        self.routes_tree = ttk.Treeview(
            side, columns=columns, show="headings", height=6
        )
        for column, heading, width in (
            ("rank", "#", 34),
            ("time", "tempo (s)", 70),
            ("dist", "dist (km)", 70),
            ("asc", "subida (m)", 74),
            ("wh", "energia (Wh)", 78),
        ):
            self.routes_tree.heading(column, text=heading)
            self.routes_tree.column(column, width=width, anchor="e")
        self.routes_tree.grid(row=3, column=0, sticky="nsew")
        self.routes_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        ttk.Label(side, text="Explicacao").grid(
            row=4, column=0, sticky="w", pady=(6, 2)
        )
        self.explanation = tk.Text(side, height=8, wrap="word", state="disabled")
        self.explanation.grid(row=5, column=0, sticky="nsew")
        side.rowconfigure(5, weight=1)

        # ---------------------------------------------------- altimetria
        self.elevation = ElevationPlot(self.root, height=190)
        self.elevation.grid(row=2, column=0, sticky="ew")
        self.elevation.show_message("clique origem e destino no mapa")

        # ---------------------------------------------------- barra de status
        self.status_var = tk.StringVar(value="iniciando...")
        status = ttk.Label(
            self.root, textvariable=self.status_var, anchor="w", relief="sunken",
            padding=(6, 2),
        )
        status.grid(row=3, column=0, sticky="ew")

    # --------------------------------------------------------- assincrono
    def _run_async(
        self,
        fn: Callable[[], object],
        on_ok: Callable[[object], None],
        *,
        busy: str | None = None,
    ) -> None:
        if busy is not None:
            self._set_status(busy)

        def worker() -> None:
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001 - exibido na barra
                self._results.put((on_ok, False, exc))
            else:
                self._results.put((on_ok, True, value))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self) -> None:
        while True:
            try:
                on_ok, ok, value = self._results.get_nowait()
            except queue.Empty:
                break
            if ok:
                on_ok(value)
            else:
                self._set_status(f"erro: {value}")
                self.elevation.show_message(f"erro: {value}")
        self.root.after(90, self._poll_results)

    # ------------------------------------------------------------- grafo
    def _load_graph(self) -> None:
        raw = self.graph_path_var.get().strip().strip('"')
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / raw

        def work() -> object:
            graph = load_graph(path)
            return graph

        def done(graph) -> None:
            self.engine = RoutingEngine(graph)
            south, west, north, east = graph_bounds(graph)
            self.map.fit_bounds(south, west, north, east)
            self._clear_all(keep_graph=True)
            self._set_status(
                f"grafo carregado: {graph.node_count} nos, "
                f"{graph.edge_count} arestas ({path})"
            )

        self._run_async(work, done, busy=f"carregando {path}...")

    # ------------------------------------------------------- interacao mapa
    def _on_map_click(self, lat: float, lon: float) -> None:
        if self.origin is None or self.destination is not None:
            self.origin = (lat, lon)
            self.destination = None
            self._reset_results()
        else:
            self.destination = (lat, lon)
        self._update_markers()
        if self.origin is not None and self.destination is not None:
            self._start_route()

    def _update_markers(self) -> None:
        markers: list[Marker] = []
        if self.origin is not None:
            markers.append(Marker(*self.origin, "A", "#2ecc71"))
        if self.destination is not None:
            markers.append(Marker(*self.destination, "B", "#e74c3c"))
        self.map.set_markers(markers)

    # ------------------------------------------------------------- rota
    def _start_route(self) -> None:
        if self.engine is None:
            self._set_status("carregue um grafo primeiro")
            return
        if self.origin is None or self.destination is None:
            self._set_status("clique origem e destino no mapa")
            return

        settings = self._read_settings()
        profile_id = self._selected_profile()
        try:
            max_routes = int(self.max_routes_var.get())
            initial = float(self.initial_speed_var.get())
        except ValueError:
            self._set_status("N rotas / v0 invalidos")
            return

        origin, destination = self.origin, self.destination
        engine = self.engine
        self._profile_cache.clear()

        def work() -> object:
            return engine.route(
                origin,
                destination,
                profile_id=profile_id,
                max_routes=max_routes,
                initial_speed_mps=initial,
                settings=settings,
            )

        self._run_async(work, self._on_route_done, busy="roteando...")

    def _on_route_done(self, computation: RouteComputation) -> None:
        self.computation = computation
        self.selected_index = None

        # marcadores passam a refletir o ponto realmente ancorado (snapping)
        self.origin = computation.origin_point
        self.destination = computation.destination_point
        self._update_markers()

        overlays = [
            RouteOverlay(route.coords, ROUTE_COLORS[index % len(ROUTE_COLORS)])
            for index, route in enumerate(computation.routes)
        ]
        self.map.set_routes(overlays, highlight=0 if overlays else None)

        self._populate_tree(computation)
        if computation.routes:
            self._select_route(0)
        else:
            self.elevation.show_message("nenhuma rota selecionada")
            self._set_explanation("")
        self._set_status(computation.status())

    def _populate_tree(self, computation: RouteComputation) -> None:
        self.routes_tree.delete(*self.routes_tree.get_children())
        for index, route in enumerate(computation.routes):
            energy = (
                f"{route.energy_wh:.1f}"
                if route.energy_wh is not None
                else "-"
            )
            self.routes_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    route.rank,
                    f"{route.metrics.time_s:.1f}",
                    f"{route.metrics.distance_m / 1000.0:.2f}",
                    f"{route.metrics.ascent_m:.1f}",
                    energy,
                ),
            )

    def _on_tree_select(self, _event: tk.Event) -> None:
        selection = self.routes_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if index == self.selected_index:
            return  # evita reentrada: selection_set dispara este evento
        self._select_route(index)

    def _select_route(self, index: int) -> None:
        if self.computation is None or index >= len(self.computation.routes):
            return
        self.selected_index = index
        children = self.routes_tree.get_children()
        if index < len(children):
            current = self.routes_tree.selection()
            if current != (children[index],):
                self.routes_tree.selection_set(children[index])

        overlays = [
            RouteOverlay(route.coords, ROUTE_COLORS[i % len(ROUTE_COLORS)])
            for i, route in enumerate(self.computation.routes)
        ]
        self.map.set_routes(overlays, highlight=index)

        route = self.computation.routes[index]
        self._set_explanation(_format_explanation(route))
        self._request_profile(index)

    # ------------------------------------------------------- altimetria
    def _request_profile(self, index: int) -> None:
        if self.computation is None:
            return
        route = self.computation.routes[index]
        cached = self._profile_cache.get(route.route_id)
        if cached is not None:
            self._render_profile(index, cached)
            return

        self.elevation.show_message("consultando altimetria Terrarium...")
        coords = route.coords
        try:
            zoom = int(self.terrain_zoom_var.get())
        except ValueError:
            zoom = 12
        zoom = max(0, min(zoom, TERRARIUM_LAYER.max_zoom))
        cache = self.terrain_cache

        def work() -> object:
            provider = TerrariumElevation.from_cache(cache, zoom=zoom)
            return build_elevation_profile(coords, provider, spacing_m=25.0, smoothing=3)

        def done(stats) -> None:
            self._profile_cache[route.route_id] = stats
            if self.selected_index == index:
                self._render_profile(index, stats)

        self._run_async(work, done)

    def _render_profile(self, index: int, stats: ElevationStats) -> None:
        if self.computation is None:
            return
        route = self.computation.routes[index]
        color = ROUTE_COLORS[index % len(ROUTE_COLORS)]
        title = f"Altimetria - {route.route_id} ({self.computation.profile_title})"
        if len(stats.profile) < 2:
            self.elevation.set_profile(stats, title + "  [sem tiles Terrarium]", color)
        else:
            self.elevation.set_profile(stats, title, color)

    # ------------------------------------------------------------- estado
    def _read_settings(self) -> EngineSettings:
        defaults = EngineSettings()

        def as_float(variable: tk.StringVar, fallback: float) -> float:
            try:
                return float(variable.get())
            except (TypeError, ValueError):
                return fallback

        ceiling: float | None
        if self.unlimited_var.get():
            ceiling = None
        else:
            ceiling = as_float(self.safe_speed_var, defaults.safe_max_speed_mps or 22.0)

        power = as_float(self.power_var, defaults.sustainable_power_w)
        return EngineSettings(
            cyclist_mass_kg=as_float(self.mass_var, defaults.cyclist_mass_kg),
            max_power_w=max(power, defaults.max_power_w),
            sustainable_power_w=power,
            frontal_area_m2=defaults.frontal_area_m2,
            bicycle_mass_kg=as_float(self.bike_mass_var, defaults.bicycle_mass_kg),
            safe_max_speed_mps=ceiling,
        )

    def _selected_profile(self) -> str:
        label = self.profile_var.get()
        for key, text in PROFILE_LABELS.items():
            if text == label:
                return key
        return "fastest"

    def _reset_results(self) -> None:
        self.computation = None
        self.selected_index = None
        self._profile_cache.clear()
        self.map.set_routes([])
        self.routes_tree.delete(*self.routes_tree.get_children())
        self._set_explanation("")
        self.elevation.show_message("clique origem e destino no mapa")

    def _clear_all(self, keep_graph: bool = False) -> None:
        self.origin = None
        self.destination = None
        self._reset_results()
        self.map.set_markers([])
        if not keep_graph:
            self.engine = None
            self._set_status("limpo")

    def _set_explanation(self, text: str) -> None:
        self.explanation.configure(state="normal")
        self.explanation.delete("1.0", "end")
        self.explanation.insert("1.0", text)
        self.explanation.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def shutdown(self) -> None:
        self.map.destroy()


def _format_explanation(route) -> str:
    lines = []
    if route.headline:
        lines.append(route.headline)
    lines.append(route.summary())
    if route.battery_note:
        lines.append("")
        lines.append(route.battery_note)
    if route.details:
        lines.append("")
        lines.extend(f"- {item}" for item in route.details)
    if route.tradeoffs:
        lines.append("")
        lines.extend(f"! {item}" for item in route.tradeoffs)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    graph_path = argv[0] if argv else None

    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    app = App(root, graph_path=graph_path)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.shutdown(), root.destroy()))
    root.mainloop()
    return 0
