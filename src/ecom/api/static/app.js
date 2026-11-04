// Olist retail dashboard. Every figure comes from the API on the same origin;
// nothing is computed here except layout. All text is inserted with
// textContent, never innerHTML, so data cannot inject markup.
"use strict";

const STATUS = {
  "Urgent": { color: "--status-critical", icon: "!", darkInk: false },
  "Monitor": { color: "--status-warning", icon: "~", darkInk: true },
  "Healthy": { color: "--status-good", icon: "✓", darkInk: false },
  "Insufficient data": { color: "--status-none", icon: "?", darkInk: true },
};
const PAGE_SIZE = 25;

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const intFmt = new Intl.NumberFormat("en-US");
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const monthFmt = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value;
    else if (key === "className") node.className = value;
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function statusBadge(status) {
  const spec = STATUS[status] || STATUS["Insufficient data"];
  const icon = el("span", {
    className: "icon" + (spec.darkInk ? " dark-ink" : ""),
    text: spec.icon,
    style: `background: var(${spec.color})`,
    "aria-hidden": "true",
  });
  return el("span", { className: "status-badge" }, [icon, status]);
}

// ---------------------------------------------------------------- tooltip
const tooltip = $("tooltip");
function showTooltip(event, lines) {
  tooltip.replaceChildren(...lines.map(([text, strong]) =>
    el("div", { className: strong ? "t-value" : "", text })));
  const x = Math.min(event.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
  const y = Math.min(event.clientY + 14, window.innerHeight - tooltip.offsetHeight - 8);
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
  tooltip.style.opacity = "1";
}
function hideTooltip() { tooltip.style.opacity = "0"; }

// ---------------------------------------------------------------- headline
function renderTiles(overview) {
  const tiles = [
    ["Delivered revenue", `R$ ${compactFmt.format(overview.revenue_brl)}`, "inside the analysis window"],
    ["Delivered orders", intFmt.format(overview.orders_in_window), `avg R$ ${overview.average_order_value_brl.toFixed(2)}`],
    ["Multi-product orders", `${overview.multi_product_share_pct}%`, "orders with 2+ distinct products"],
    ["Co-purchase pairs", intFmt.format(overview.cooccurrence_pairs), `${intFmt.format(overview.graph_products)} products connected`],
    ["Urgent restocks", intFmt.format(statusCount(overview.inventory, "Urgent")), `of ${intFmt.format(overview.inventory.total)} seller-products`],
  ];
  $("tiles").replaceChildren(...tiles.map(([label, value, note]) =>
    el("div", { className: "card tile" }, [
      el("div", { className: "label", text: label }),
      el("div", { className: "value", text: value }),
      el("div", { className: "note", text: note }),
    ])));
}

function statusCount(summary, status) {
  const row = summary.by_status.find((s) => s.status === status);
  return row ? row.count : 0;
}

// ---------------------------------------------------------------- orders line
function renderOrdersChart(months) {
  const svg = d3.select("#orders-chart");
  const width = svg.node().clientWidth || 640;
  const height = 280;
  const margin = { top: 16, right: 56, bottom: 28, left: 48 };
  svg.attr("viewBox", `0 0 ${width} ${height}`).attr("height", height).selectAll("*").remove();

  const data = months.map((m) => ({ date: new Date(m.month), value: m.order_count }));
  const x = d3.scaleUtc().domain(d3.extent(data, (d) => d.date)).range([margin.left, width - margin.right]);
  const y = d3.scaleLinear().domain([0, d3.max(data, (d) => d.value)]).nice().range([height - margin.bottom, margin.top]);

  svg.append("g").selectAll("line").data(y.ticks(4)).join("line")
    .attr("class", (d) => (d === 0 ? "baseline" : "gridline"))
    .attr("x1", margin.left).attr("x2", width - margin.right)
    .attr("y1", (d) => y(d)).attr("y2", (d) => y(d));
  svg.append("g").selectAll("text").data(y.ticks(4)).join("text")
    .attr("x", margin.left - 8).attr("y", (d) => y(d)).attr("dy", "0.32em")
    .attr("text-anchor", "end").text((d) => (d >= 10000 ? compactFmt.format(d) : intFmt.format(d)));
  svg.append("g").selectAll("text").data(x.ticks(width < 500 ? 3 : 6)).join("text")
    .attr("x", (d) => x(d)).attr("y", height - 8).attr("text-anchor", "middle")
    .text((d) => monthFmt.format(d));

  const line = d3.line().x((d) => x(d.date)).y((d) => y(d.value)).curve(d3.curveMonotoneX);
  const area = d3.area().x((d) => x(d.date)).y0(y(0)).y1((d) => y(d.value)).curve(d3.curveMonotoneX);
  svg.append("path").datum(data).attr("d", area).attr("fill", css("--series-1-wash"));
  svg.append("path").datum(data).attr("d", line).attr("fill", "none")
    .attr("stroke", css("--series-1")).attr("stroke-width", 2)
    .attr("stroke-linejoin", "round").attr("stroke-linecap", "round");

  const last = data[data.length - 1];
  svg.append("circle").attr("cx", x(last.date)).attr("cy", y(last.value)).attr("r", 4)
    .attr("fill", css("--series-1")).attr("stroke", css("--surface")).attr("stroke-width", 2);
  svg.append("text").attr("x", x(last.date) + 8).attr("y", y(last.value)).attr("dy", "0.32em")
    .style("fill", css("--text-secondary")).text(intFmt.format(last.value));

  const crosshair = svg.append("line").attr("class", "baseline").style("opacity", 0)
    .attr("y1", margin.top).attr("y2", height - margin.bottom);
  const marker = svg.append("circle").attr("r", 4).attr("fill", css("--series-1"))
    .attr("stroke", css("--surface")).attr("stroke-width", 2).style("opacity", 0);
  svg.append("rect").attr("x", margin.left).attr("y", margin.top)
    .attr("width", width - margin.left - margin.right).attr("height", height - margin.top - margin.bottom)
    .attr("fill", "transparent")
    .on("pointermove", (event) => {
      const [px] = d3.pointer(event);
      const date = x.invert(px);
      const i = d3.bisector((d) => d.date).center(data, date);
      const d = data[i];
      crosshair.attr("x1", x(d.date)).attr("x2", x(d.date)).style("opacity", 1);
      marker.attr("cx", x(d.date)).attr("cy", y(d.value)).style("opacity", 1);
      showTooltip(event, [[monthFmt.format(d.date)], [`${intFmt.format(d.value)} orders`, true]]);
    })
    .on("pointerleave", () => { crosshair.style("opacity", 0); marker.style("opacity", 0); hideTooltip(); });

  $("orders-table").replaceChildren(
    el("thead", {}, [el("tr", {}, [el("th", { text: "Month" }), el("th", { className: "num", text: "Orders" })])]),
    el("tbody", {}, data.map((d) => el("tr", {}, [
      el("td", { text: monthFmt.format(d.date) }),
      el("td", { className: "num", text: intFmt.format(d.value) }),
    ]))),
  );
}

// ---------------------------------------------------------------- status
function renderStatus(summary) {
  const bar = $("status-bar");
  bar.setAttribute("aria-label", summary.by_status.map((s) => `${s.status} ${s.count} (${s.share_pct}%)`).join(", "));
  bar.replaceChildren(...summary.by_status.filter((s) => s.count > 0).map((s) => {
    const spec = STATUS[s.status];
    const seg = el("div", {
      className: "seg" + (spec.darkInk ? " dark-ink" : ""),
      style: `flex: ${s.count} 1 0; background: var(${spec.color})`,
      tabindex: "0",
    });
    seg.addEventListener("pointermove", (e) => showTooltip(e, [[s.status], [`${intFmt.format(s.count)} · ${s.share_pct}%`, true]]));
    seg.addEventListener("pointerleave", hideTooltip);
    // Print the share inside only when there is room for it.
    requestAnimationFrame(() => { if (seg.clientWidth > 48) seg.textContent = `${Math.round(s.share_pct)}%`; });
    return seg;
  }));
  $("status-legend").replaceChildren(...summary.by_status.map((s) =>
    el("span", { className: "key" }, [statusBadge(s.status), el("span", { className: "mono", text: intFmt.format(s.count) })])));
}

function renderCategories(rows) {
  const svg = d3.select("#category-chart");
  const width = svg.node().clientWidth || 400;
  const barHeight = 16;
  const gap = 10;
  const labelWidth = Math.min(190, width * 0.5);
  const height = rows.length * (barHeight + gap);
  svg.attr("viewBox", `0 0 ${width} ${height}`).attr("height", height).selectAll("*").remove();
  if (!rows.length) return;

  const x = d3.scaleLinear().domain([0, d3.max(rows, (d) => d.urgent_count)]).range([0, width - labelWidth - 40]);
  const g = svg.selectAll("g").data(rows).join("g")
    .attr("transform", (_, i) => `translate(0, ${i * (barHeight + gap)})`);
  g.append("text").attr("x", labelWidth - 8).attr("y", barHeight / 2).attr("dy", "0.32em")
    .attr("text-anchor", "end").style("fill", css("--text-secondary"))
    .text((d) => d.category.replaceAll("_", " "));
  g.append("path").attr("fill", css("--series-1"))
    .attr("d", (d) => roundedBar(labelWidth, 0, Math.max(x(d.urgent_count), 2), barHeight, 4));
  g.append("text").attr("x", (d) => labelWidth + x(d.urgent_count) + 6).attr("y", barHeight / 2)
    .attr("dy", "0.32em").text((d) => d.urgent_count);
  g.append("rect").attr("width", width).attr("height", barHeight + gap).attr("y", -gap / 2)
    .attr("fill", "transparent")
    .on("pointermove", (e, d) => showTooltip(e, [[d.category.replaceAll("_", " ")], [`${d.urgent_count} urgent`, true]]))
    .on("pointerleave", hideTooltip)
    .on("click", (_, d) => { $("f-status").value = "Urgent"; $("f-category").value = d.category; loadInventory(0); });
}

// Horizontal bar: square at the baseline (left), 4px rounded at the data end.
function roundedBar(x0, y0, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  return `M${x0},${y0}H${x0 + w - rr}A${rr},${rr} 0 0 1 ${x0 + w},${y0 + rr}` +
    `V${y0 + h - rr}A${rr},${rr} 0 0 1 ${x0 + w - rr},${y0 + h}H${x0}Z`;
}

// ---------------------------------------------------------------- inventory
let inventoryOffset = 0;

async function loadInventory(offset) {
  inventoryOffset = Math.max(0, offset);
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: inventoryOffset });
  if ($("f-status").value) params.set("status", $("f-status").value);
  if ($("f-category").value) params.set("category", $("f-category").value);
  if ($("f-seller").value.trim()) params.set("seller_id", $("f-seller").value.trim());
  const table = $("inventory-table");
  try {
    const page = await api(`/inventory?${params}`);
    renderInventory(page);
  } catch (err) {
    table.replaceChildren(el("caption", { className: "error", text: `Could not load inventory: ${err.message}` }));
  }
}

function renderInventory(page) {
  const headers = [["Status"], ["Product"], ["Category"], ["Seller"], ["State"],
    ["Stock", "num"], ["Reorder below", "num"], ["Days left", "num"], ["Lead time", "num"], ["Sold / day", "num"]];
  const head = el("thead", {}, [el("tr", {}, headers.map(([t, c]) => el("th", { className: c || "", text: t })))]);
  const body = el("tbody");
  if (!page.items.length) {
    body.append(el("tr", {}, [el("td", { colspan: headers.length, className: "empty", text: "No seller-products match these filters." })]));
  }
  for (const item of page.items) {
    const row = el("tr", { className: "clickable", tabindex: "0" }, [
      el("td", {}, [statusBadge(item.status)]),
      el("td", { className: "wrap", text: item.product_name }),
      el("td", { className: "wrap", text: (item.category || "unknown").replaceAll("_", " ") }),
      el("td", { className: "mono", text: item.seller_id.slice(0, 8) }),
      el("td", { text: item.seller_state || "" }),
      el("td", { className: "num", text: item.current_quantity }),
      el("td", { className: "num", text: item.reorder_point.toFixed(2) }),
      el("td", { className: "num", text: item.days_of_inventory.toFixed(1) }),
      el("td", { className: "num", text: `${item.lead_time_days}d` }),
      el("td", { className: "num", text: item.daily_sales_rate.toFixed(3) }),
    ]);
    row.title = `seller ${item.seller_id}`;
    const open = () => openProduct(item.product_id);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    body.append(row);
  }
  $("inventory-table").replaceChildren(head, body);
  const end = Math.min(page.offset + page.limit, page.total_found);
  $("page-info").textContent = page.total_found
    ? `${intFmt.format(page.offset + 1)}–${intFmt.format(end)} of ${intFmt.format(page.total_found)}`
    : "";
  $("prev").disabled = page.offset === 0;
  $("next").disabled = end >= page.total_found;
}

// ---------------------------------------------------------------- explorer
let searchTimer = null;
let sellerTimer = null;

async function runSearch(query) {
  const list = $("search-results");
  if (!query.trim()) { list.replaceChildren(); return; }
  try {
    const result = await api(`/products/search?${new URLSearchParams({ q: query, limit: 40 })}`);
    if (!result.results.length) {
      list.replaceChildren(el("li", { className: "empty", text: "No products in a matching category." }));
      return;
    }
    // Results arrive most-connected first; most Olist products were never bought
    // with another, so say which ones are dead ends before anyone clicks them.
    list.replaceChildren(...result.results.map((item) => {
      const reach = item.degree ? `bought with ${item.degree}` : "no co-purchases";
      const tag = item.match_type === "expanded" ? `with a match · ${item.weight} orders` : reach;
      const li = productListItem(item.product_name, tag, item.product_id);
      if (!item.degree) li.classList.add("dead");
      return li;
    }));
  } catch (err) {
    list.replaceChildren(el("li", { className: "error", text: err.message }));
  }
}

function productListItem(name, tag, productId) {
  const li = el("li", { tabindex: "0", "data-id": productId }, [
    el("span", { text: name }),
    el("span", { className: "tag", text: tag }),
  ]);
  li.addEventListener("click", () => openProduct(productId));
  li.addEventListener("keydown", (e) => { if (e.key === "Enter") openProduct(productId); });
  return li;
}

async function openProduct(productId) {
  history.replaceState(null, "", `#product=${encodeURIComponent(productId)}`);
  $("explorer-card").scrollIntoView({ behavior: "smooth", block: "start" });
  for (const li of document.querySelectorAll("#search-results li")) {
    li.classList.toggle("selected", li.dataset.id === productId);
  }
  const panel = $("product-panel");
  panel.className = "";
  panel.textContent = "Loading…";
  try {
    const [detail, recs, graph] = await Promise.all([
      api(`/products/${encodeURIComponent(productId)}`),
      api(`/products/${encodeURIComponent(productId)}/recommendations?limit=10`),
      api(`/products/${encodeURIComponent(productId)}/graph?max_nodes=40`),
    ]);
    const urgent = detail.inventory.filter((i) => i.status === "Urgent").length;
    panel.replaceChildren(
      el("h2", { text: detail.product_name }),
      el("p", {
        className: "subtitle",
        text: `${(detail.category || "unknown").replaceAll("_", " ")} · bought with ${detail.graph_degree} other products · ` +
          `stocked by ${detail.inventory.length} seller${detail.inventory.length === 1 ? "" : "s"}` +
          (urgent ? ` · ${urgent} urgent` : ""),
      }),
      el("div", { className: "mono", text: detail.product_id }),
    );
    if (detail.graph_degree) {
      $("graph").style.display = "";
      renderRecommendations(recs);
      drawGraph(graph, productId);
    } else {
      $("graph").style.display = "none";
      await renderCategoryFallback(detail.category);
    }
  } catch (err) {
    panel.className = "error";
    panel.textContent = `Could not load product: ${err.message}`;
  }
}

function renderRecommendations(recs) {
  const list = $("recommendations");
  if (!recs.recommendations.length) {
    list.replaceChildren(el("li", { className: "empty", text: "Never bought together with another product. Most Olist orders hold a single item." }));
    return;
  }
  list.replaceChildren(
    el("li", { className: "meta", text: `Bought together with — top ${recs.recommendations.length} of ${recs.total_found}` }),
    ...recs.recommendations.map((r) => productListItem(r.product_name, `${r.weight} order${r.weight === 1 ? "" : "s"}`, r.product_id)),
  );
}

// The category tier of the two-tier design: when a product was never bought
// with another, show what its category is bought with and which of its products
// do have co-purchases, so the view always offers somewhere to go next.
async function renderCategoryFallback(category) {
  const list = $("recommendations");
  const note = el("li", { className: "meta", text: "Never bought together with another product, like most Olist items: only 3.3% of orders hold more than one product." });
  if (!category) { list.replaceChildren(note); return; }
  const label = category.replaceAll("_", " ");
  const rel = await api(`/categories/${encodeURIComponent(category)}/related?limit=8`);
  const chips = el("li", { className: "chips" }, rel.related.map((r) => {
    const chip = el("button", { type: "button", className: "chip", text: `${r.category.replaceAll("_", " ")} · ${r.weight}` });
    chip.addEventListener("click", () => { $("search").value = r.category.replaceAll("_", " "); runSearch($("search").value); });
    return chip;
  }));
  list.replaceChildren(
    note,
    el("li", { className: "meta", text: rel.related.length ? `Buyers in ${label} also bought from (orders):` : `No ${label} product was ever bought with another category.` }),
    ...(rel.related.length ? [chips] : []),
    ...(rel.connected_products.length
      ? [el("li", { className: "meta", text: `${label} products that are bought with others:` })]
      : []),
    ...rel.connected_products.map((p) => productListItem(p.name, `bought with ${p.degree}`, p.id)),
  );
}

async function showGlobalGraph() {
  const panel = $("product-panel");
  panel.className = "";
  $("graph").style.display = "";
  try {
    const graph = await api("/products/graph?min_weight=2&max_nodes=80");
    panel.replaceChildren(
      el("h2", { text: "Strongest co-purchase pairs" }),
      el("p", { className: "subtitle", text: `${graph.total_nodes} products, ${graph.total_links} pairs bought together in 2+ orders. Click a node to open it.` }),
    );
    $("recommendations").replaceChildren();
    drawGraph(graph, null);
  } catch (err) {
    panel.className = "error";
    panel.textContent = err.message;
  }
}

let simulation = null;

function drawGraph(data, focusId) {
  if (simulation) simulation.stop();
  const svg = d3.select("#graph");
  svg.selectAll("*").remove();
  const width = svg.node().clientWidth || 600;
  const height = 440;
  svg.attr("viewBox", `0 0 ${width} ${height}`);
  if (!data.nodes.length) {
    svg.append("text").attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
      .text("No co-purchases to draw.");
    return;
  }
  const nodes = data.nodes.map((n) => ({ ...n }));
  const links = data.links.map((l) => ({ ...l }));
  const maxWeight = d3.max(links, (l) => l.weight) || 1;
  const strokeWidth = d3.scaleSqrt().domain([1, maxWeight]).range([1.5, 7]);
  const radius = d3.scaleSqrt().domain([1, d3.max(nodes, (n) => n.degree) || 1]).range([5, 14]);

  const root = svg.append("g");
  const zoom = d3.zoom().scaleExtent([0.3, 4]).on("zoom", (e) => {
    root.attr("transform", e.transform);
    root.selectAll("text").style("font-size", `${12 / e.transform.k}px`);  // labels stay 12px
  });
  svg.call(zoom);

  const link = root.append("g").selectAll("line").data(links).join("line")
    .attr("class", "link").attr("stroke-width", (l) => strokeWidth(l.weight));
  link.on("pointermove", (e, l) => showTooltip(e, [["Bought together"], [`${l.weight} order${l.weight === 1 ? "" : "s"}`, true]]))
    .on("pointerleave", hideTooltip);

  const node = root.append("g").selectAll("circle").data(nodes).join("circle")
    .attr("class", (n) => "node " + (n.id === focusId ? "focus" : "other"))
    .attr("r", (n) => (n.id === focusId ? 14 : radius(Math.max(n.degree, 1))))
    .on("pointermove", (e, n) => showTooltip(e, [[n.name], [(n.category || "unknown").replaceAll("_", " ")], [`${n.degree} co-purchase partners`, true]]))
    .on("pointerleave", hideTooltip)
    .on("click", (_, n) => openProduct(n.id))
    .call(d3.drag()
      .on("start", (e, n) => { if (!e.active) simulation.alphaTarget(0.3).restart(); n.fx = n.x; n.fy = n.y; })
      .on("drag", (e, n) => { n.fx = e.x; n.fy = e.y; })
      .on("end", (e, n) => { if (!e.active) simulation.alphaTarget(0); n.fx = null; n.fy = null; }));

  const label = root.append("g").selectAll("text").data(nodes.filter((n) => n.id === focusId)).join("text")
    .attr("text-anchor", "middle").attr("dy", -20).style("fill", css("--text-primary"))
    .text((n) => n.name);

  simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id((n) => n.id).distance(70))
    .force("charge", d3.forceManyBody().strength(-160))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius((n) => radius(Math.max(n.degree, 1)) + 4))
    .stop();
  const render = () => {
    link.attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y)
      .attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y);
    node.attr("cx", (n) => n.x).attr("cy", (n) => n.y);
    label.attr("x", (n) => n.x).attr("y", (n) => n.y);
  };
  // Settle the layout before drawing (a few ms at <=80 nodes), so it can be
  // fitted at once instead of after seconds of animation. Dragging restarts it.
  simulation.tick(300);
  render();
  fitToView(svg, zoom, nodes, width, height);
  simulation.on("tick", render);
}

// Zoom so the settled graph fills the panel. A six-node ego
// network otherwise sits small in the middle of 440px of empty space.
function fitToView(svg, zoom, nodes, width, height) {
  const pad = 48;
  const [x0, x1] = d3.extent(nodes, (n) => n.x);
  const [y0, y1] = d3.extent(nodes, (n) => n.y);
  const scale = Math.min(2.5, (width - 2 * pad) / Math.max(x1 - x0, 1), (height - 2 * pad) / Math.max(y1 - y0, 1));
  const transform = d3.zoomIdentity
    .translate(width / 2, height / 2)
    .scale(scale)
    .translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
  svg.call(zoom.transform, transform);
}

// ---------------------------------------------------------------- boot
async function boot() {
  try {
    const [health, overview] = await Promise.all([api("/health"), api("/overview")]);
    const built = health.inventory_generated_at ? new Date(health.inventory_generated_at).toLocaleString() : "unknown";
    $("provenance").textContent =
      `Window ${overview.window_start} to ${overview.window_end} · data built ${built} · ` +
      `${intFmt.format(health.graph_products)} products in the co-purchase graph`;
    renderTiles(overview);
    for (const category of overview.inventory.categories) {
      $("f-category").append(el("option", { value: category, text: category.replaceAll("_", " ") }));
    }
    if (window.d3) {
      renderOrdersChart(overview.orders_by_month);
      renderCategories(overview.inventory.top_urgent_categories);
    } else {
      $("orders-chart").replaceWith(el("p", { className: "error", text: "Charts need D3 from cdnjs, which did not load. The tables still work." }));
    }
    renderStatus(overview.inventory);
  } catch (err) {
    $("provenance").textContent = `Could not reach the API: ${err.message}`;
    $("provenance").className = "provenance error";
  }
  loadInventory(0);

  for (const id of ["f-status", "f-category"]) $(id).addEventListener("change", () => loadInventory(0));
  $("f-seller").addEventListener("input", () => { clearTimeout(sellerTimer); sellerTimer = setTimeout(() => loadInventory(0), 300); });
  $("f-clear").addEventListener("click", () => {
    $("f-status").value = ""; $("f-category").value = ""; $("f-seller").value = ""; loadInventory(0);
  });
  $("prev").addEventListener("click", () => loadInventory(inventoryOffset - PAGE_SIZE));
  $("next").addEventListener("click", () => loadInventory(inventoryOffset + PAGE_SIZE));
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(e.target.value), 250);
  });
  $("show-global").addEventListener("click", () => { if (window.d3) showGlobalGraph(); });

  // A #product=<id> link opens straight onto that product, so views can be shared.
  const linked = new URLSearchParams(location.hash.slice(1)).get("product");
  if (linked && window.d3) openProduct(linked);
}

boot();
