"""Testes puros da projecao Web Mercator (sem Tk nem rede)."""

from __future__ import annotations

import math

import pytest

from routegui import proj


def test_world_center_is_half():
    x, y = proj.lonlat_to_world(0.0, 0.0)
    assert x == pytest.approx(0.5)
    assert y == pytest.approx(0.5)


def test_world_roundtrip():
    for lon, lat in ((-46.63, -23.55), (0.0, 0.0), (179.9, 60.0), (-120.0, -45.0)):
        x, y = proj.lonlat_to_world(lon, lat)
        lon2, lat2 = proj.world_to_lonlat(x, y)
        assert lon2 == pytest.approx(lon, abs=1e-9)
        assert lat2 == pytest.approx(lat, abs=1e-6)


def test_zoom_zero_pixel_of_origin_is_128():
    px, py = proj.lonlat_to_pixel(0.0, 0.0, 0)
    assert px == pytest.approx(128.0)
    assert py == pytest.approx(128.0)


def test_tile_indices_known():
    assert proj.lonlat_to_tile(0.0, 0.0, 0) == (0, 0)
    assert proj.lonlat_to_tile(0.0, 0.0, 1) == (1, 1)
    # longitude a leste de Greenwich no zoom 1 cai na coluna 1.
    assert proj.lonlat_to_tile(90.0, 0.0, 1) == (1, 1)
    assert proj.lonlat_to_tile(-90.0, 0.0, 1)[0] == 0


def test_zoom_clamped_extreme_latitude():
    # Nao explode no polo: a latitude e recortada em MAX_LATITUDE.
    assert math.isfinite(proj.lonlat_to_world(0.0, 90.0)[1])
    assert math.isfinite(proj.lonlat_to_world(0.0, -90.0)[1])


def test_view_canvas_roundtrip():
    view = proj.WebMercatorView(
        center_lat=-23.55, center_lon=-46.63, zoom=14, width=800, height=600
    )
    for cx, cy in ((0, 0), (400, 300), (799, 599)):
        lat, lon = view.canvas_to_latlon(cx, cy)
        rx, ry = view.latlon_to_canvas(lat, lon)
        assert rx == pytest.approx(cx, abs=1e-6)
        assert ry == pytest.approx(cy, abs=1e-6)


def test_zoom_at_keeps_cursor_point_fixed():
    view = proj.WebMercatorView(
        center_lat=-23.55, center_lon=-46.63, zoom=13, width=800, height=600
    )
    lat_before, lon_before = view.canvas_to_latlon(650, 120)
    view.zoom_at(15, 650, 120)
    lat_after, lon_after = view.canvas_to_latlon(650, 120)
    # O ponto sob o cursor muda de zoom, mas permanece o mesmo geograficamente.
    assert lon_after == pytest.approx(lon_before, abs=1e-6)
    assert lat_after == pytest.approx(lat_before, abs=1e-6)
    assert view.zoom == 15


def test_tile_range_covers_canvas():
    view = proj.WebMercatorView(
        center_lat=-23.55, center_lon=-46.63, zoom=15, width=640, height=480
    )
    xs, ys = view.tile_range()
    assert len(xs) >= 1 and len(ys) >= 1
    # As tiles devem cobrir toda a area visivel.
    ox, oy = view.origin_pixel()
    covered_x0 = xs.start * proj.TILE_SIZE
    covered_x1 = (xs.stop) * proj.TILE_SIZE
    covered_y0 = ys.start * proj.TILE_SIZE
    covered_y1 = (ys.stop) * proj.TILE_SIZE
    assert covered_x0 <= ox + 1e-6
    assert covered_x1 >= ox + view.width - 1e-6
    assert covered_y0 <= oy + 1e-6
    assert covered_y1 >= oy + view.height - 1e-6


def test_fit_bounds_contains_bounds():
    view = proj.WebMercatorView(width=800, height=600, zoom=3)
    south, west, north, east = -23.5525, -46.6376, -23.5458, -46.6292
    view.fit_bounds(south, west, north, east)
    x0, y0 = view.latlon_to_canvas(north, west)
    x1, y1 = view.latlon_to_canvas(south, east)
    assert 0 <= x0 <= view.width and 0 <= x1 <= view.width
    assert 0 <= y0 <= view.height and 0 <= y1 <= view.height


def test_pan_moves_center_opposite_to_drag():
    view = proj.WebMercatorView(center_lat=0.0, center_lon=0.0, zoom=10)
    before = view.center_pixel()
    view.pan_by_pixels(50.0, 0.0)  # arrasta para a direita
    after = view.center_pixel()
    assert after[0] < before[0]  # o mapa anda; o centro recua
