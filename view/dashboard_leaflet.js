import { leaflet as L } from "nicegui-leaflet";
import { loadResource } from "../../static/utils/resources.js";
import { cleanObject } from "../../static/utils/json.js";

export default {
  template: "<div></div>",
  props: { center: Array, zoom: Number, options: Object, drawControl: Object, resourcePath: String, hideDrawnItems: Boolean, additionalResources: Array },
  async mounted() {
    await this.$nextTick();
    await loadResource(window.path_prefix + `${this.resourcePath}/leaflet/leaflet.css`);
    window.L = L;
    await Promise.all(this.additionalResources.map((resource) => loadResource(resource)));
    if (this.drawControl) await Promise.all([
      loadResource(window.path_prefix + `${this.resourcePath}/leaflet-draw/leaflet.draw.css`),
      loadResource(window.path_prefix + `${this.resourcePath}/leaflet-draw/leaflet.draw.js`),
    ]);
    this.map = L.map(this.$el, { ...this.options, center: this.center, zoom: this.zoom });
    for (const type of ["baselayerchange", "overlayadd", "overlayremove", "zoomlevelschange", "resize", "unload", "viewreset", "load", "zoomstart", "movestart", "zoom", "move", "zoomend", "moveend", "popupopen", "popupclose", "autopanstart", "tooltipopen", "tooltipclose", "locationerror", "locationfound", "click", "dblclick", "mousedown", "mouseup", "mouseover", "mouseout", "mousemove", "contextmenu", "keypress", "keydown", "keyup", "preclick", "zoomanim"]) {
      this.map.on(type, (e) => this.$emit(`map-${type}`, {
        ...e, originalEvent: undefined, target: undefined, sourceTarget: undefined,
        center: [e.target.getCenter().lat, e.target.getCenter().lng], zoom: e.target.getZoom(),
      }));
    }
    for (const type of ["layeradd", "layerremove"]) this.map.on(type, (e) => this.$emit(`map-${type}`, { id: e.layer.id, leaflet_id: e.layer._leaflet_id }));
    if (this.drawControl) {
      for (const key in L.Draw.Event) {
        const type = L.Draw.Event[key];
        this.map.on(type, async (e) => {
          await this.$nextTick();
          const cleanedObject = cleanObject(e, ["_map", "_events", "_eventParents", "_handlers", "_mapToAdd", "_initHooksCalled"]);
          this.$emit(type, { ...cleanedObject, target: undefined, sourceTarget: undefined });
        });
      }
      const originalType = window.type; window.type = "Feature";
      const drawnItems = new L.FeatureGroup(); window.type = originalType; this.map.addLayer(drawnItems);
      const dc = this.drawControl && typeof this.drawControl === "object" ? this.drawControl : {};
      const drawOptions = dc.draw === true || dc.draw === undefined ? {} : dc.draw || {};
      let editOptions = dc.edit === true || dc.edit === undefined ? {} : dc.edit || {};
      if (typeof editOptions === "object" && "edit" in editOptions) { const { edit: _ignored, ...rest } = editOptions; editOptions = rest; }
      const drawControl = new L.Control.Draw({ draw: drawOptions, edit: { ...editOptions, featureGroup: drawnItems } });
      this.map.addControl(drawControl);
      if (!this.hideDrawnItems) this.map.on("draw:created", (e) => drawnItems.addLayer(e.layer));
    }
    const connectInterval = setInterval(async () => { if (window.socket.id === undefined) return; this.$emit("init"); clearInterval(connectInterval); }, 100);
    this.observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) this.run_map_method("invalidateSize", { pan: false }); });
    this.observer.observe(this.$el);
    this.resizeObserver = new ResizeObserver(() => {
      this.map?.invalidateSize({ pan: false });
      this.$emit("map-size", { width: this.$el.clientWidth, height: this.$el.clientHeight });
    });
    this.resizeObserver.observe(this.$el);
    this.$emit("map-ready", { width: this.$el.clientWidth, height: this.$el.clientHeight });
  },
  unmounted() { this.observer?.disconnect(); this.resizeObserver?.disconnect(); },
  methods: {
    add_layer(layer, id) {
      let obj = L; for (const part of layer.type.split(".")) obj = obj[part];
      const leafLayer = obj(...layer.args); leafLayer.id = id;
      this.layersById ??= new Map(); this.layersById.set(id, leafLayer);
      // This event is attached to the exact Leaflet layer, before map bubbling.
      // It emits only non-sensitive diagnostic fields and the authoritative id.
      leafLayer.on("click", (e) => this.$emit("station-select", {
        marker_id: id, event_type: e.type, target_id: e.target?.id ?? null,
        source_target_id: e.sourceTarget?.id ?? null,
      }));
      leafLayer.addTo(this.map);
    },
    configure_layers(bindings) {
      // A full dashboard has nearly 2,000 markers. Configure their static
      // popup/tooltip content in one browser command after reconnect instead
      // of scheduling thousands of individual NiceGUI messages.
      this.stationMarkerIds = new Set(bindings.map(({ id }) => id));
      for (const { id, popup, tooltip } of bindings) {
        const layer = this.layersById?.get(id);
        if (!layer) continue;
        layer.bindPopup(popup);
        layer.bindTooltip(tooltip);
      }
      if (this.pendingStationVisibleIds !== undefined) this.apply_station_visibility();
    },
    remove_layer(id) { this.map.eachLayer((layer) => layer.id === id && this.map.removeLayer(layer)); },
    set_layer_visible(id, visible) {
      const layer = this.layersById?.get(id);
      if (!layer) return;
      if (visible && !this.map.hasLayer(layer)) layer.addTo(this.map);
      if (!visible && this.map.hasLayer(layer)) this.map.removeLayer(layer);
    },
    set_layers_visible(visibleIds) {
      this.pendingStationVisibleIds = new Set(visibleIds);
      // A filter can arrive during reconnect before station bindings are
      // configured. Keep it pending rather than treating tile/overlay layers
      // as station markers; configure_layers applies it once ready.
      if (!this.stationMarkerIds) return;
      this.apply_station_visibility();
    },
    apply_station_visibility() {
      const visible = this.pendingStationVisibleIds;
      if (!visible) return;
      for (const id of this.stationMarkerIds ?? []) {
        const layer = this.layersById?.get(id);
        if (!layer) continue;
        if (visible.has(id) && !this.map.hasLayer(layer)) layer.addTo(this.map);
        if (!visible.has(id) && this.map.hasLayer(layer)) this.map.removeLayer(layer);
      }
    },
    clear_layers() { this.map.eachLayer((layer) => this.map.removeLayer(layer)); },
    run_map_method(name, ...args) {
      if (name.startsWith(":")) { name = name.slice(1); args = args.map((arg) => new Function(`return (${arg})`)()); }
      return runMethod(this.map, name, args);
    },
    run_layer_method(id, name, ...args) {
      // Filtered-out layers are deliberately removed from Leaflet's map, but
      // retained here so live state/popup updates still reach them before they
      // become visible again.
      const layer = this.layersById?.get(id);
      if (!layer) return null;
      if (name.startsWith(":")) {
        name = name.slice(1);
        args = args.map((arg) => new Function(`return (${arg})`)());
      }
      return runMethod(layer, name, args);
    },
  },
};
