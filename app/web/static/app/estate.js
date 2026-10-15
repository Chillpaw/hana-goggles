/* Estate map: every view and leaf source with their dependency edges, drawn with
   Cytoscape + dagre, data flowing left to right (sources on the left).
   Reads its elements from <script type="application/json" id="estate-data">.
   Loads nothing from the network: the libraries are vendored, links point at this server,
   and the PNG export is made in the browser. Conventions follow viewgraph.js. */
(function () {
  "use strict";

  var BAD = "#b42318";
  var WARN = "#a15c00";
  var LEAF_COLOUR = "#7f8c9d";
  var UNSET = "#bab0ac";
  var MATCH = "#e15759";
  var PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#9c755f", "#76b7b2"];

  /* Colour modes. Fixed colours where the values carry meaning; other values take the
     palette in order of first appearance (sorted, so the legend is stable). */
  var MODES = {
    parse_status: {
      title: "parse status",
      fixed: { ok: "#2d6a2d", partial: "#d68a00", failed: BAD },
      order: ["ok", "partial", "failed"]
    },
    view_type: { title: "view type", fixed: { unknown: UNSET }, order: ["graphical", "scripted", "unknown"] },
    data_category: { title: "data category", fixed: { UNKNOWN: UNSET },
                     order: ["CUBE", "DIMENSION", "DEFAULT", "UNKNOWN"] },
    signoff: {
      title: "sign-off",
      fixed: { "": "#c9ced6", draft: "#d68a00", reviewed: "#1f5fbf", approved: "#2d6a2d" },
      order: ["", "draft", "reviewed", "approved"],
      names: { "": "no note" }
    }
  };
  var LEAF_NAMES = {
    table: "table",
    table_function: "table function",
    external_view: "view outside this folder",
    unknown: "unknown source"
  };

  function isView(d) { return d.kind === "view"; }

  function valueOf(d, mode) {
    var v = d[mode];
    return (v === null || v === undefined) ? "" : String(v);
  }

  function colourTable(nodes, mode) {
    var spec = MODES[mode];
    var values = {};
    nodes.forEach(function (n) { if (isView(n.data)) { values[valueOf(n.data, mode)] = true; } });
    var ordered = spec.order.filter(function (v) { return values[v]; });
    Object.keys(values).sort().forEach(function (v) {
      if (ordered.indexOf(v) < 0) { ordered.push(v); }
    });
    var table = {};
    var next = 0;
    ordered.forEach(function (v) {
      if (Object.prototype.hasOwnProperty.call(spec.fixed, v)) {
        table[v] = spec.fixed[v];
      } else {
        table[v] = PALETTE[next % PALETTE.length];
        next += 1;
      }
    });
    return { order: ordered, colours: table };
  }

  function label(d) {
    var text = d.label;
    if (isView(d)) {
      if (d.in_cycle) { text = "⟳ " + text; }
      if (d.warning_count > 0) { text += "  ⚠ " + d.warning_count; }
    } else if (d.marker) {
      text += "\n(" + d.marker + ")";
    }
    return text;
  }

  function swatch(container, cls, colour, text) {
    var item = document.createElement("span");
    var sw = document.createElement("span");
    sw.className = "swatch" + (cls ? " " + cls : "");
    if (colour) { sw.style.background = colour; }
    item.appendChild(sw);
    item.appendChild(document.createTextNode(text));
    container.appendChild(item);
  }

  function buildLegend(container, nodes, mode, table) {
    if (!container) { return; }
    container.textContent = "";
    var spec = MODES[mode];
    var head = document.createElement("strong");
    head.textContent = "Views by " + spec.title + ":";
    container.appendChild(head);
    table.order.forEach(function (v) {
      var name = (spec.names && spec.names[v]) || v || "(none)";
      swatch(container, "", table.colours[v], name);
    });
    var kinds = {};
    var anyCycle = false;
    var anyAmbiguous = false;
    nodes.forEach(function (n) {
      if (!isView(n.data)) { kinds[n.data.kind] = true; }
      if (n.data.in_cycle) { anyCycle = true; }
      if (n.data.ambiguous) { anyAmbiguous = true; }
    });
    Object.keys(kinds).sort().forEach(function (k) {
      swatch(container, "leaf", LEAF_COLOUR, "leaf source: " + (LEAF_NAMES[k] || k));
    });
    if (anyCycle) { swatch(container, "cycle", null, "⟳ part of a cycle"); }
    if (anyAmbiguous) { swatch(container, "ambiguous", null, "ambiguous: several views match"); }
    swatch(container, "match", null, "search match");
    var warn = document.createElement("span");
    warn.textContent = "⚠ n = warnings in that view";
    container.appendChild(warn);
  }

  function count(n, noun) { return n + " " + noun + (n === 1 ? "" : "s"); }

  function addFact(dl, term, value) {
    var dt = document.createElement("dt");
    dt.textContent = term;
    var dd = document.createElement("dd");
    dd.textContent = value;
    dl.appendChild(dt);
    dl.appendChild(dd);
  }

  function addLink(parent, href, text, download) {
    var a = document.createElement("a");
    a.href = href;
    a.textContent = text;
    if (download) { a.setAttribute("download", ""); }
    parent.appendChild(a);
    return a;
  }

  function showInfo(panel, node) {
    if (!panel) { return; }
    panel.textContent = "";
    if (!node) {
      var hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = "Click a view to see its details.";
      panel.appendChild(hint);
      return;
    }
    var d = node.data();
    var h = document.createElement("h3");
    h.textContent = d.label;
    panel.appendChild(h);
    var dl = document.createElement("dl");
    var up = node.predecessors("node");
    var down = node.successors("node");
    if (isView(d)) {
      addFact(dl, "Type", (d.view_type || "?") + ", " + (d.data_category || "?"));
      addFact(dl, "Parse", (d.parse_status || "?") +
              (d.coverage_pct === null ? "" : " (" + Math.round(d.coverage_pct) + "% understood)"));
      addFact(dl, "Sign-off", (d.signoff || "no note") + (d.stale ? " (stale)" : ""));
      addFact(dl, "Warnings", String(d.warning_count === null ? "?" : d.warning_count));
      if (d.in_cycle) { addFact(dl, "Cycle", "This view is part of a cycle of views that read each other."); }
      addFact(dl, "Upstream (all levels)", count(up.filter('[kind = "view"]').length, "view") + ", " +
              count(up.filter('[kind != "view"]').length, "leaf source"));
      addFact(dl, "Downstream (all levels)", count(down.length, "view"));
    } else {
      addFact(dl, "Kind", LEAF_NAMES[d.kind] || d.kind);
      if (d.marker) { addFact(dl, "Note", d.marker); }
      addFact(dl, "Read by (all levels)", count(down.filter('[kind = "view"]').length, "view"));
    }
    panel.appendChild(dl);
    if (d.url) {
      var p = document.createElement("p");
      addLink(p, d.url, "Open view", false);
      p.appendChild(document.createTextNode(" · "));
      addLink(p, d.mmd_url, "Mermaid (.mmd)", true);
      panel.appendChild(p);
    }
  }

  function init() {
    var dataEl = document.getElementById("estate-data");
    var container = document.getElementById("estate");
    if (!dataEl || !container) { return; }
    if (typeof cytoscape === "undefined") {
      container.textContent = "The graph library did not load. The deploy order below lists every view.";
      return;
    }
    var elements = JSON.parse(dataEl.textContent);
    var nodes = elements.filter(function (e) { return e.data.source === undefined; });
    var modeSelect = document.getElementById("colour-by");
    var mode = (modeSelect && MODES[modeSelect.value]) ? modeSelect.value : "parse_status";
    var table = colourTable(nodes, mode);

    var cy = cytoscape({
      container: container,
      elements: elements,
      wheelSensitivity: 0.3,
      minZoom: 0.05,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            "shape": "round-rectangle",
            "background-color": function (n) {
              var d = n.data();
              if (!isView(d)) { return LEAF_COLOUR; }
              return table.colours[valueOf(d, mode)] || UNSET;
            },
            "label": function (n) { return label(n.data()); },
            "color": "#ffffff",
            "text-outline-color": "#1d2330",
            "text-outline-width": 1,
            "font-size": 12,
            "font-family": "system-ui, sans-serif",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": 180,
            "width": "label",
            "height": "label",
            "padding": "8px",
            "border-width": 1,
            "border-color": "#ffffff"
          }
        },
        { selector: 'node[kind != "view"]', style: { "shape": "barrel", "font-size": 11 } },
        { selector: 'node[kind = "external_view"], node[kind = "unknown"]',
          style: { "border-width": 2, "border-color": WARN, "border-style": "dotted" } },
        { selector: "node[?ambiguous]",
          style: { "border-width": 3, "border-color": WARN, "border-style": "dashed" } },
        { selector: "node[?in_cycle]",
          style: { "border-width": 4, "border-color": BAD, "border-style": "dashed" } },
        {
          selector: "edge",
          style: {
            "width": 1.2,
            "line-color": "#b8bfcb",
            "target-arrow-color": "#b8bfcb",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "text-background-color": "#fbfcfd",
            "text-background-opacity": 1,
            "text-background-padding": 2
          }
        },
        { selector: "edge[?internal]",
          style: { "width": 2, "line-color": "#5d6675", "target-arrow-color": "#5d6675" } },
        { selector: "edge[?ambiguous]",
          style: { "line-style": "dashed", "line-color": WARN, "target-arrow-color": WARN,
                   "label": "ambiguous", "font-size": 10, "color": WARN } },
        { selector: "edge[?in_cycle]",
          style: { "width": 3, "line-color": BAD, "target-arrow-color": BAD,
                   "label": "cycle", "font-size": 10, "color": BAD } },
        { selector: ".hidden-leaf", style: { "display": "none" } },
        { selector: ".faded", style: { "opacity": 0.15 } },
        { selector: "node.focus", style: { "overlay-color": "#1f5fbf", "overlay-opacity": 0.25,
                                           "overlay-padding": 6 } },
        { selector: "node.match", style: { "border-width": 4, "border-color": MATCH,
                                           "border-style": "solid" } }
      ],
      layout: layoutOptions()
    });
    cy.fit(undefined, 20);
    window.cy = cy;  // for debugging and browser checks

    var legend = document.getElementById("legend");
    var info = document.getElementById("estate-info");
    buildLegend(legend, nodes, mode, table);

    if (modeSelect) {
      modeSelect.addEventListener("change", function () {
        mode = MODES[modeSelect.value] ? modeSelect.value : "parse_status";
        table = colourTable(nodes, mode);
        cy.style().update();
        buildLegend(legend, nodes, mode, table);
      });
    }

    var leavesBox = document.getElementById("show-leaves");
    if (leavesBox) {
      leavesBox.addEventListener("change", function () {
        var leafPart = leafElements();
        if (leavesBox.checked) {
          leafPart.removeClass("hidden-leaf");
        } else {
          leafPart.addClass("hidden-leaf");
        }
        // Explicit sets: ":visible" may still reflect the old style at this point.
        var shown = shownElements();
        shown.layout(layoutOptions()).run();
        cy.fit(shown, 20);
      });
    }

    function leafElements() {
      var leaves = cy.nodes('[kind != "view"]');
      return leaves.union(leaves.connectedEdges());
    }

    function shownElements() {
      return (leavesBox && !leavesBox.checked) ? cy.elements().not(leafElements()) : cy.elements();
    }

    function clearFocus() {
      cy.elements().removeClass("faded focus");
      showInfo(info, null);
    }

    cy.on("tap", "node", function (evt) {
      var node = evt.target;
      var keep = node.predecessors().union(node.successors()).union(node);
      cy.elements().addClass("faded").removeClass("focus");
      keep.removeClass("faded");
      node.addClass("focus");
      showInfo(info, node);
    });
    cy.on("tap", function (evt) {
      if (evt.target === cy) { clearFocus(); }
    });
    cy.on("dbltap", "node", function (evt) {
      var url = evt.target.data("url");
      if (url) { window.location.assign(url); }
    });

    var search = document.getElementById("search");
    var count = document.getElementById("search-count");
    if (search) {
      search.addEventListener("input", function () {
        var needle = search.value.trim().toLowerCase();
        cy.nodes().removeClass("match");
        if (!needle) {
          if (count) { count.textContent = ""; }
          return;
        }
        var hits = cy.nodes().filter(function (n) {
          return String(n.data("label")).toLowerCase().indexOf(needle) >= 0 ||
                 String(n.id()).toLowerCase().indexOf(needle) >= 0;
        });
        hits.addClass("match");
        if (count) { count.textContent = hits.length + (hits.length === 1 ? " match" : " matches"); }
      });
      search.addEventListener("keydown", function (evt) {
        if (evt.key === "Enter") {
          evt.preventDefault();
          var hits = cy.nodes(".match").intersection(shownElements());
          if (hits.length) { cy.animate({ fit: { eles: hits, padding: 60 } }, { duration: 300 }); }
        }
      });
    }

    var fit = document.getElementById("fit");
    if (fit) { fit.addEventListener("click", function () { cy.fit(shownElements(), 20); }); }

    var exportButton = document.getElementById("png-export");
    var pngLink = document.getElementById("png-link");
    if (exportButton && pngLink) {
      exportButton.addEventListener("click", function () {
        // scale 2 for a sharp image, reduced if the canvas would pass browser size limits
        var box = shownElements().boundingBox();
        var scale = Math.min(2, 16000 / Math.max(box.w, 1), 16000 / Math.max(box.h, 1));
        var url = cy.png({ full: true, scale: scale, bg: "#ffffff" });
        pngLink.href = url;
        pngLink.hidden = false;
        pngLink.click();
      });
    }

    window.addEventListener("resize", function () { cy.resize(); });
  }

  function layoutOptions() {
    return { name: "dagre", rankDir: "LR", nodeSep: 30, rankSep: 80, padding: 20 };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
