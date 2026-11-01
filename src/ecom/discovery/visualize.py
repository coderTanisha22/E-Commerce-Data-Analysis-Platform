"""Interactive graph visualizer for product co-occurrence.

Generates standalone, interactive D3.js HTML visualizations of the co-occurrence
graph that can be viewed directly in a browser or embedded as an iframe widget
in any future dashboard (React, Metabase, Streamlit).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ecom.discovery.schemas import GraphDataResponse

logger = logging.getLogger(__name__)

_D3_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      overflow: hidden;
    }}
    #header {{
      position: absolute;
      top: 16px;
      left: 20px;
      z-index: 10;
      background: rgba(15, 23, 42, 0.9);
      backdrop-filter: blur(8px);
      padding: 12px 18px;
      border-radius: 8px;
      border: 1px solid #334155;
      max-width: 400px;
    }}
    h1 {{ margin: 0 0 4px 0; font-size: 16px; font-weight: 600; color: #f1f5f9; }}
    .subtitle {{ font-size: 12px; color: #94a3b8; margin: 0 0 8px 0; }}
    .search-box {{
      width: 100%;
      box-sizing: border-box;
      padding: 7px 10px;
      border-radius: 6px;
      border: 1px solid #475569;
      background: #1e293b;
      color: #f8fafc;
      font-size: 12px;
    }}
    #drawer {{
      position: absolute;
      top: 16px;
      right: 20px;
      z-index: 10;
      width: 330px;
      max-height: calc(100vh - 40px);
      overflow-y: auto;
      background: rgba(15, 23, 42, 0.94);
      backdrop-filter: blur(10px);
      padding: 16px;
      border-radius: 10px;
      border: 1px solid #334155;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }}
    .drawer-title {{ font-size: 14px; font-weight: 600; margin: 0 0 10px 0; color: #38bdf8; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 600;
      background: #334155;
      color: #94a3b8;
    }}
    .rec-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 9px 10px;
      margin-bottom: 7px;
      font-size: 12px;
    }}
    .weight-tag {{
      float: right;
      background: #0284c7;
      color: white;
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
    }}
    #tooltip {{
      position: absolute;
      display: none;
      background: #1e293b;
      border: 1px solid #475569;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      color: #f8fafc;
      pointer-events: none;
      z-index: 30;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }}
    svg {{ width: 100vw; height: 100vh; cursor: grab; }}
    svg:active {{ cursor: grabbing; }}
    .link {{
      stroke: #475569;
      stroke-opacity: 0.6;
      transition: stroke 0.2s, stroke-opacity 0.2s;
    }}
    .link.highlight {{ stroke: #38bdf8; stroke-opacity: 1; }}
    .edge-label {{
      font-size: 10px;
      fill: #94a3b8;
      font-weight: 600;
      pointer-events: none;
      paint-order: stroke;
      stroke: #0f172a;
      stroke-width: 2px;
    }}
    .node-group {{ cursor: pointer; transition: opacity 0.2s; }}
    .node-circle {{
      stroke: #0f172a;
      stroke-width: 1.5px;
      transition: stroke 0.2s, stroke-width 0.2s;
    }}
    .node-group:hover .node-circle {{ stroke: #38bdf8; stroke-width: 3px; }}
    .node-group.selected .node-circle {{ stroke: #f59e0b; stroke-width: 4px; }}
    .node-label {{
      font-size: 10px;
      fill: #e2e8f0;
      pointer-events: none;
      paint-order: stroke;
      stroke: #0f172a;
      stroke-width: 2.5px;
    }}
    .dimmed {{ opacity: 0.12 !important; }}
    .reset-btn {{
      margin-top: 10px;
      width: 100%;
      padding: 7px;
      background: #334155;
      color: #f8fafc;
      border: none;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
    }}
    .reset-btn:hover {{ background: #475569; }}
  </style>
</head>
<body>
  <div id="header">
    <h1>{title}</h1>
    <p class="subtitle" id="stats">Loading co-occurrence data...</p>
    <input type="text" id="search" class="search-box"
      placeholder="Search product name, category, or ID...">
  </div>

  <div id="drawer">
    <h3 class="drawer-title">Bundle & Cross-Sell Inspector</h3>
    <div id="drawer-content">
      <p style="font-size: 12px; color: #94a3b8; margin: 0;">
        Click any product node to inspect its cross-sell bundle recommendations and shared orders.
      </p>
    </div>
  </div>

  <div id="tooltip"></div>
  <svg id="canvas"></svg>

  <script>
    const data = {data_json};
    document.getElementById("stats").innerText =
      `${{data.total_nodes}} products, ${{data.total_links}} cross-sell pairs (showing weights)`;

    const svg = d3.select("#canvas");
    const width = window.innerWidth;
    const height = window.innerHeight;
    const g = svg.append("g");

    const zoom = d3.zoom().scaleExtent([0.1, 4])
      .on("zoom", (e) => g.attr("transform", e.transform));
    svg.call(zoom);

    svg.on("click", (event) => {{
      if (event.target.tagName === "svg") resetSelection();
    }});

    const color = d3.scaleOrdinal(d3.schemeTableau10);
    const tooltip = d3.select("#tooltip");

    const simulation = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links).id(d => d.id)
        .distance(d => Math.max(50, 130 - d.weight * 10)))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2 - 80, height / 2))
      .force("collide", d3.forceCollide().radius(26));

    const linkGroup = g.append("g").attr("class", "links");
    const edgeLabelGroup = g.append("g").attr("class", "edge-labels");
    const nodeGroup = g.append("g").attr("class", "nodes");

    const link = linkGroup.selectAll("line")
      .data(data.links)
      .join("line")
      .attr("class", "link")
      .attr("stroke-width", d => Math.min(8, Math.max(1.5, Math.sqrt(d.weight) * 2)))
      .on("mouseover", (event, d) => {{
        tooltip.style("display", "block")
          .html(`<strong>Co-Purchase Bundle:</strong><br>` +
                `Order Count: <strong>${{d.weight}} orders</strong> together`);
      }})
      .on("mousemove", (event) => {{
        tooltip.style("left", (event.pageX + 14) + "px")
          .style("top", (event.pageY - 28) + "px");
      }})
      .on("mouseout", () => tooltip.style("display", "none"));

    const edgeLabel = edgeLabelGroup.selectAll("text")
      .data(data.links)
      .join("text")
      .attr("class", "edge-label")
      .attr("text-anchor", "middle")
      .text(d => `${{d.weight}}x`);

    const node = nodeGroup.selectAll("g")
      .data(data.nodes)
      .join("g")
      .attr("class", "node-group")
      .call(d3.drag()
        .on("start", (event, d) => {{
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        }})
        .on("drag", (event, d) => {{ d.fx = event.x; d.fy = event.y; }})
        .on("end", (event, d) => {{
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        }}))
      .on("click", (event, d) => {{
        event.stopPropagation();
        selectNode(d);
      }})
      .on("mouseover", (event, d) => {{
        tooltip.style("display", "block")
          .html(`<strong>${{d.name}}</strong><br>` +
                `Category: ${{d.category || 'unknown'}}<br>` +
                `Connected to: <strong>${{d.degree}} cross-sell items</strong>`);
      }})
      .on("mousemove", (event) => {{
        tooltip.style("left", (event.pageX + 14) + "px")
          .style("top", (event.pageY - 28) + "px");
      }})
      .on("mouseout", () => tooltip.style("display", "none"));

    node.append("circle")
      .attr("class", "node-circle")
      .attr("r", d => Math.min(18, Math.max(7, Math.sqrt(d.degree + 1) * 4)))
      .attr("fill", d => color(d.category || "unknown"));

    node.append("text")
      .attr("class", "node-label")
      .attr("x", 12)
      .attr("y", 3)
      .text(d => d.name || `#${{d.id.slice(0, 4)}}`);

    simulation.on("tick", () => {{
      link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x).attr("y2", d => d.target.y);

      edgeLabel
        .attr("x", d => (d.source.x + d.target.x) / 2)
        .attr("y", d => (d.source.y + d.target.y) / 2 - 2);

      node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
    }});

    function selectNode(selected) {{
      const neighborIds = new Set([selected.id]);
      const connectedEdges = data.links.filter(l => {{
        const s = l.source.id || l.source;
        const t = l.target.id || l.target;
        if (s === selected.id) neighborIds.add(t);
        if (t === selected.id) neighborIds.add(s);
        return s === selected.id || t === selected.id;
      }});

      node.classed("selected", d => d.id === selected.id)
          .classed("dimmed", d => !neighborIds.has(d.id));

      link.classed("highlight", l => {{
        const s = l.source.id || l.source;
        const t = l.target.id || l.target;
        return s === selected.id || t === selected.id;
      }}).classed("dimmed", l => {{
        const s = l.source.id || l.source;
        const t = l.target.id || l.target;
        return s !== selected.id && t !== selected.id;
      }});

      edgeLabel.classed("dimmed", l => {{
        const s = l.source.id || l.source;
        const t = l.target.id || l.target;
        return s !== selected.id && t !== selected.id;
      }});

      updateDrawer(selected, connectedEdges);
    }}

    function resetSelection() {{
      node.classed("selected", false).classed("dimmed", false);
      link.classed("highlight", false).classed("dimmed", false);
      edgeLabel.classed("dimmed", false);
      document.getElementById("drawer-content").innerHTML = `
        <p style="font-size: 12px; color: #94a3b8; margin: 0;">
          Click any product node to inspect its cross-sell bundle recommendations and shared orders.
        </p>
      `;
    }}

    function updateDrawer(nodeData, edges) {{
      const sortedEdges = [...edges].sort((a, b) => b.weight - a.weight);
      let html = `
        <div style="margin-bottom: 12px;">
          <div style="font-size: 13px; font-weight: 600; color: #f8fafc;">${{nodeData.name}}</div>
          <div style="font-family: monospace; font-size: 10px; color: #94a3b8; margin: 2px 0;">
            ID: ${{nodeData.id}}
          </div>
          <span class="badge"
            style="background: ${{color(nodeData.category || 'unknown')}}; color: white;">
            ${{nodeData.category || 'unknown'}}
          </span>
          <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">
            Bundle Degree: <strong>${{nodeData.degree}} connected products</strong>
          </div>
        </div>
        <div style="font-weight: 600; font-size: 12px; margin-bottom: 6px; color: #38bdf8;">
          Frequently Bought Together (${{sortedEdges.length}}):
        </div>
      `;

      sortedEdges.forEach(e => {{
        const s = e.source.id || e.source;
        const t = e.target.id || e.target;
        const targetId = s === nodeData.id ? t : s;
        const targetNode = data.nodes.find(n => n.id === targetId) ||
          {{ name: targetId, category: 'unknown' }};
        html += `
          <div class="rec-card">
            <span class="weight-tag">${{e.weight}} orders</span>
            <div style="font-weight: 600; color: #f1f5f9; margin-bottom: 2px;">
              ${{targetNode.name}}
            </div>
            <div style="font-size: 11px; color: #94a3b8;">
              ${{targetNode.category || 'unknown'}}
            </div>
          </div>
        `;
      }});

      html += `<button class="reset-btn" onclick="resetSelection()">Reset Selection</button>`;
      document.getElementById("drawer-content").innerHTML = html;
    }}

    document.getElementById("search").addEventListener("input", (e) => {{
      const query = e.target.value.trim().toLowerCase();
      if (!query) {{
        resetSelection();
        return;
      }}
      const match = data.nodes.find(n =>
        n.id.toLowerCase().includes(query) ||
        (n.category && n.category.toLowerCase().includes(query)) ||
        (n.name && n.name.toLowerCase().includes(query))
      );
      if (match) selectNode(match);
    }});
  </script>
</body>
</html>
"""


def _build_html_template(data_json: str, title: str) -> str:
    """Build self-contained interactive D3.js visualization HTML."""
    return _D3_HTML_TEMPLATE.format(title=title, data_json=data_json)


def render_interactive_graph_html(
    graph_data: GraphDataResponse,
    out_path: Path,
    *,
    title: str = "Product Co-Occurrence Graph",
) -> Path:
    """Render a standalone interactive D3.js HTML visualization.

    Args:
        graph_data: Node-link data generated from ProductGraphService.
        out_path: Destination path for the .html file.
        title: Title banner for the visualizer.

    Returns:
        Path to the generated HTML file.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload_json = json.dumps(graph_data.model_dump())
    html_content = _build_html_template(payload_json, title)
    out_path.write_text(html_content, encoding="utf-8")
    logger.info("rendered interactive graph to %s", out_path)
    return out_path
