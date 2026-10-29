"""Leaflet extension with an explicit per-layer station selection event.

NiceGUI 3.18's built-in Leaflet component emits map events but does not expose
Python callbacks on ``GenericLayer`` instances. This component preserves its
API and additionally emits ``station-select`` from the actual Leaflet layer.
"""
from nicegui.elements.leaflet.leaflet import Leaflet


class DashboardLeaflet(Leaflet, component="dashboard_leaflet.js"):
    """A Leaflet map whose GenericLayers emit their own unique layer id on click."""

