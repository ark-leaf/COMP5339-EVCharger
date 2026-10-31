import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("view/dashboard_leaflet.js", "utf8");
assert.ok(!source.includes("dashboard_leaflet_methods.mjs"), "no unregistered adjacent module import");
const match = source.match(/run_layer_method\(id, name, \.\.\.args\) \{([\s\S]*?)\n    \},\n  \},/);
assert.ok(match, "production run_layer_method must be present");

const calls = [];
const runMethod = (layer, name, args) => {
  calls.push({ layer, name, args });
  return `${name}:${args.length}`;
};
const actualMethod = new Function("runMethod", `return function(id, name, ...args) {${match[1]}\n};`)(runMethod);
const hiddenLayer = { id: "hidden-7" };
const component = { layersById: new Map([["hidden-7", hiddenLayer]]) };

assert.equal(actualMethod.call(component, "hidden-7", "setStyle", { color: "#16875D" }), "setStyle:1");
assert.equal(actualMethod.call(component, "hidden-7", "bindPopup", "fresh popup"), "bindPopup:1");
assert.equal(actualMethod.call(component, "hidden-7", "bindTooltip", "fresh tooltip"), "bindTooltip:1");
assert.equal(actualMethod.call(component, "hidden-7", ":setStyle", "({color: '#2563EB'})"), "setStyle:1");
assert.equal(actualMethod.call(component, "missing", "setStyle", { color: "#000" }), null);
assert.equal(calls.length, 4);
assert.ok(calls.every((call) => call.layer === hiddenLayer));

function productionMethod(name, nextName, parameters) {
  const expression = new RegExp(`${name}\\([^)]*\\) \\{([\\s\\S]*?)\\n    \\},\\n    ${nextName}`);
  const result = source.match(expression);
  assert.ok(result, `production ${name} must be present`);
  return new Function(`return function ${name}(${parameters}) {${result[1]}\n};`)();
}

const configureLayers = productionMethod("configure_layers", "remove_layer", "bindings");
const setLayersVisible = productionMethod("set_layers_visible", "apply_station_visibility", "visibleIds");
const applyStationVisibility = productionMethod("apply_station_visibility", "clear_layers", "");
const attached = new Set();
const makeLayer = (name) => ({ name, addTo(map) { attached.add(this); return this; }, bindPopup() {}, bindTooltip() {} });
const tile = makeLayer("osm-tile");
const overlay = makeLayer("non-station-overlay");
const stationA = makeLayer("station-a");
const stationB = makeLayer("station-b");
attached.add(tile); attached.add(overlay); attached.add(stationA); attached.add(stationB);
const visibilityComponent = {
  layersById: new Map([["tile", tile], ["overlay", overlay], ["station-a", stationA], ["station-b", stationB]]),
  map: { hasLayer: (layer) => attached.has(layer), removeLayer: (layer) => attached.delete(layer) },
  configure_layers: configureLayers,
  set_layers_visible: setLayersVisible,
  apply_station_visibility: applyStationVisibility,
};
visibilityComponent.set_layers_visible(["station-b"]); // pending before configure
assert.ok(attached.has(tile) && attached.has(overlay));
visibilityComponent.configure_layers([{ id: "station-a", popup: "a", tooltip: "a" }, { id: "station-b", popup: "b", tooltip: "b" }]);
assert.ok(attached.has(tile) && attached.has(overlay));
assert.ok(!attached.has(stationA) && attached.has(stationB)); // Unknown/Charging/Available filters all use this path
visibilityComponent.set_layers_visible(["station-a"]);
assert.ok(attached.has(tile) && attached.has(overlay));
assert.ok(attached.has(stationA) && !attached.has(stationB));
visibilityComponent.set_layers_visible(["station-a", "station-b"]); // Reset / All Statuses
assert.ok(attached.has(tile) && attached.has(overlay) && attached.has(stationA) && attached.has(stationB));
