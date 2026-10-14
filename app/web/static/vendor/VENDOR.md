# Vendored JavaScript

Served from `/static/vendor/`. Never loaded from a CDN at runtime. Checksums are in `SHA256SUMS`.

| File | Package | Version | License | Source |
|---|---|---|---|---|
| htmx.min.js | htmx.org | 1.9.12 | 0BSD | https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js |
| cytoscape.min.js | cytoscape | 3.30.2 | MIT | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| dagre.min.js | dagre | 0.8.5 | MIT | https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js |
| cytoscape-dagre.js | cytoscape-dagre | 2.5.0 | MIT | https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js |

To upgrade: download the new pinned version, regenerate `SHA256SUMS`, and update this table.
