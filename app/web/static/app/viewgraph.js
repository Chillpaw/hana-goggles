/* View graph: draws one view's steps with Cytoscape + dagre, data flowing upwards
   (sources at the bottom, output at the top, like the HANA modeller).
   Reads its elements from <script type="application/json" id="graph-data">.
   Loads nothing from the network: the libraries are vendored and the node panel comes
   from this server through htmx. */
(function () {
  "use strict";

  var COLOURS = {
    datasource: "#7f8c9d",
    projection: "#4e79a7",
    join: "#f28e2b",
    union: "#59a14f",
    aggregation: "#b07aa1",
    rank: "#edc948",
    script_statement: "#9c755f",
    opaque: "#bab0ac",
    output: "#1d2330",
    missing: "#ffffff"
  };
  var LABELS = {
    datasource: "source",
    projection: "projection",
    join: "join",
    union: "union",
    aggregation: "aggregation",
    rank: "rank",
    script_statement: "script statement",
    opaque: "unrecognised",
    output: "output",
    missing: "missing (edge to an undefined step)"
  };
  var BAD = "#b42318";

  function label(d) {
    var text = d.label;
    if (d.warning_count > 0) {
      text += "  ⚠ " + d.warning_count;
    }
    return text;
  }

  function buildLegend(container, nodes) {
    if (!container) { return; }
    var seen = {};
    var anyBad = false;
    var anyOpenable = false;
    nodes.forEach(function (n) {
      seen[n.data.node_type] = true;
      if (n.data.understood === false) { anyBad = true; }
      if (n.data.view_url) { anyOpenable = true; }
    });
    Object.keys(COLOURS).forEach(function (type) {
      if (!seen[type]) { return; }
      var item = document.createElement("span");
      var swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = COLOURS[type];
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(LABELS[type] || type));
      container.appendChild(item);
    });
    if (anyBad) {
      var bad = document.createElement("span");
      var badSwatch = document.createElement("span");
      badSwatch.className = "swatch not-understood";
      bad.appendChild(badSwatch);
      bad.appendChild(document.createTextNode("not fully understood by the parser"));
      container.appendChild(bad);
    }
    if (anyOpenable) {
      var open = document.createElement("span");
      var openSwatch = document.createElement("span");
      openSwatch.className = "swatch openable";
      open.appendChild(openSwatch);
      open.appendChild(document.createTextNode("view in this project (double-click to open)"));
      container.appendChild(open);
    }
    var warn = document.createElement("span");
    warn.appendChild(document.createTextNode("⚠ n = warnings on that step"));
    container.appendChild(warn);
  }

  function init() {
    var dataEl = document.getElementById("graph-data");
    var container = document.getElementById("graph");
    if (!dataEl || !container) { return; }
    if (typeof cytoscape === "undefined") {
      container.textContent = "The graph library did not load. See the Steps tab.";
      return;
    }
    var elements = JSON.parse(dataEl.textContent);
    var nodes = elements.filter(function (e) { return e.data.source === undefined; });

    var cy = cytoscape({
      container: container,
      elements: elements,
      wheelSensitivity: 0.3,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            "shape": "round-rectangle",
            "background-color": function (n) { return COLOURS[n.data("node_type")] || "#cccccc"; },
            "label": function (n) { return label(n.data()); },
            "color": "#ffffff",
            "font-size": 12,
            "font-family": "system-ui, sans-serif",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": 150,
            "width": "label",
            "height": 26,
            "padding": "8px",
            "border-width": 1,
            "border-color": "#ffffff"
          }
        },
        { selector: 'node[node_type = "datasource"]', style: { "shape": "barrel" } },
        { selector: 'node[node_type = "missing"]', style: { "color": BAD } },
        { selector: 'node[node_type = "rank"]', style: { "color": "#1d2330" } },
        { selector: 'node[node_type = "opaque"]', style: { "color": "#1d2330" } },
        {
          selector: "node[?view_url]",
          style: { "border-width": 2, "border-color": "#1f5fbf", "border-style": "double" }
        },
        {
          selector: "node[!understood]",
          style: { "border-width": 3, "border-color": BAD, "border-style": "dashed" }
        },
        {
          selector: "node:selected",
          style: { "overlay-color": "#1f5fbf", "overlay-opacity": 0.25, "overlay-padding": 4 }
        },
        {
          selector: "edge",
          style: {
            "width": 1.5,
            "line-color": "#9aa3b2",
            "target-arrow-color": "#9aa3b2",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "label": function (e) {
              var n = e.data("column_count");
              return n ? n + (n === 1 ? " col" : " cols") : "";
            },
            "font-size": 10,
            "color": "#5d6675",
            "text-background-color": "#fbfcfd",
            "text-background-opacity": 1,
            "text-background-padding": 2
          }
        }
      ],
      layout: { name: "dagre", rankDir: "BT", nodeSep: 40, rankSep: 50, padding: 20 }
    });
    cy.fit(undefined, 20);
    window.cy = cy;  // for debugging and browser checks

    buildLegend(document.getElementById("legend"), nodes);

    cy.on("tap", "node", function (evt) {
      var url = evt.target.data("panel_url");
      if (url && typeof htmx !== "undefined") {
        htmx.ajax("GET", url, "#node-panel");
      }
    });
    cy.on("dbltap", "node", function (evt) {
      var url = evt.target.data("view_url");
      if (url) {
        window.location.assign(url);
      }
    });
    window.addEventListener("resize", function () { cy.resize(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
