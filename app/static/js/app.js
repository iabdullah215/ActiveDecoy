document.addEventListener("DOMContentLoaded", () => {
  const connectionForm = document.querySelector("[data-connection-form]");
  const deceptionForm = document.querySelector("[data-deception-form]");
  const monitoringTable = document.querySelector("[data-monitoring-table]");
  const graphPanel = document.querySelector("[data-graph-panel]");

  const badgeClass = (status) => {
    const map = {
      ok: "badge--ok",
      connected: "badge--connected",
      degraded: "badge--degraded",
      error: "badge--error",
      failed: "badge--failed",
      skipped: "badge--skipped",
      pending: "badge--pending",
      not_connected: "badge--not_connected",
    };
    return `badge ${map[status] || "badge--pending"}`;
  };

  const updateConnectionUI = (payload) => {
    const checklist = payload.checklist || {};
    const ldap = checklist.ldap || {};
    const hypervisor = checklist.hypervisor || {};
    const bridge = checklist.bridge || {};

    const setStatus = (card, badgeEl, msgEl, item) => {
      if (!badgeEl || !msgEl) return;
      const status = item.status || "pending";
      badgeEl.textContent = status;
      badgeEl.className = badgeClass(status);
      msgEl.textContent = item.message || "—";
      if (card) {
        card.classList.remove("is-ok", "is-error");
        if (status === "ok") card.classList.add("is-ok");
        else if (status === "error") card.classList.add("is-error");
      }
    };

    setStatus(
      document.querySelector("[data-status-ldap]"),
      document.querySelector("[data-status-ldap-badge]"),
      document.querySelector("[data-status-ldap-msg]"),
      ldap,
    );
    setStatus(
      document.querySelector("[data-status-hypervisor]"),
      document.querySelector("[data-status-hypervisor-badge]"),
      document.querySelector("[data-status-hypervisor-msg]"),
      hypervisor,
    );
    setStatus(
      document.querySelector("[data-status-bridge]"),
      document.querySelector("[data-status-bridge-badge]"),
      document.querySelector("[data-status-bridge-msg]"),
      { status: bridge.status || "not_connected", message: bridge.message || payload.message },
    );

    const debugEl = document.querySelector("[data-connection-debug]");
    if (debugEl) {
      const lines = [
        ...(payload.ldap_result?.debug || []),
        ...(payload.hypervisor_result?.debug || []),
      ];
      debugEl.textContent = lines.length ? lines.join("\n") : "No diagnostic output.";
    }
  };

  const setLoading = (loading) => {
    const label = document.querySelector("[data-test-label]");
    if (!label) return;
    label.innerHTML = loading
      ? '<span class="spinner"></span> Validating…'
      : "Validate connection";
  };

  const formToUnchecked = (formData) => {
    if (!formData.has("ldap_use_ssl")) formData.set("ldap_use_ssl", "false");
    if (!formData.has("auto_test_on_load")) formData.set("auto_test_on_load", "false");
    return formData;
  };

  const postForm = async (url, formData) => {
    const response = await fetch(url, { method: "POST", body: formData });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed (${response.status})`);
    }
    return response.json();
  };

  const toggleHypervisorFields = () => {
    const select = document.querySelector("[data-hypervisor-type]");
    if (!select) return;
    const isUtm = select.value === "utm";
    document.querySelector("[data-field=wrapper]")?.classList.toggle("u-hidden", !isUtm);
    document.querySelector("[data-field=endpoint]")?.classList.toggle("u-hidden", isUtm);
    document.querySelector("[data-field=hv-user]")?.classList.toggle("u-hidden", isUtm);
    document.querySelector("[data-field=hv-pass]")?.classList.toggle("u-hidden", isUtm);
  };

  if (connectionForm) {
    toggleHypervisorFields();
    document.querySelector("[data-hypervisor-type]")?.addEventListener("change", toggleHypervisorFields);

    const runTest = async (url) => {
      setLoading(true);
      try {
        const payload = await postForm(url, formToUnchecked(new FormData(connectionForm)));
        updateConnectionUI(payload);
        return payload;
      } catch (error) {
        const debugEl = document.querySelector("[data-connection-debug]");
        if (debugEl) debugEl.textContent = error.message;
        throw error;
      } finally {
        setLoading(false);
      }
    };

    connectionForm.addEventListener("submit", (e) => {
      e.preventDefault();
      runTest("/api/connection/test");
    });

    connectionForm.querySelector('[data-action="save"]')?.addEventListener("click", async () => {
      setLoading(true);
      try {
        await postForm("/api/connection/save", formToUnchecked(new FormData(connectionForm)));
        const debugEl = document.querySelector("[data-connection-debug]");
        if (debugEl) debugEl.textContent = "Profile saved.";
      } finally {
        setLoading(false);
      }
    });

    connectionForm.querySelector('[data-action="retest"]')?.addEventListener("click", () => {
      runTest("/api/connection/retest");
    });

    connectionForm.querySelector('[data-action="enumerate"]')?.addEventListener("click", async () => {
      const label = document.querySelector("[data-test-label]");
      if (label) label.innerHTML = '<span class="spinner"></span> Importing…';
      try {
        const formData = new FormData();
        formData.set("sync_to_graph", "true");
        formData.set("replace", "true");
        const payload = await postForm("/api/connection/enumerate", formData);
        const debugEl = document.querySelector("[data-connection-debug]");
        if (debugEl) {
          const lines = [
            payload.message || "",
            ...(payload.debug || []),
          ].filter(Boolean);
          debugEl.textContent = lines.join("\n") || "Directory import finished.";
        }
        const summary = payload.summary || {};
        document.querySelectorAll("[data-dir-stat]").forEach((el) => {
          const key = el.getAttribute("data-dir-stat");
          if (key && key in summary) el.textContent = summary[key];
        });
        const badge = document.querySelector("[data-directory-badge]");
        if (badge) {
          badge.textContent = payload.success ? "Imported" : "Error";
          badge.className = `badge ${payload.success ? "badge--connected" : "badge--error"}`;
        }
        const msg = document.querySelector("[data-directory-message]");
        if (msg) {
          msg.textContent = summary.domain
            ? `Domain: ${summary.domain}`
            : (payload.message || "Import finished.");
        }
      } catch (error) {
        const debugEl = document.querySelector("[data-connection-debug]");
        if (debugEl) debugEl.textContent = error.message;
      } finally {
        if (label) label.textContent = "Validate connection";
      }
    });

    connectionForm.querySelector('[data-action="disconnect"]')?.addEventListener("click", async () => {
      const payload = await postForm("/api/connection/disconnect", new FormData());
      updateConnectionUI({ checklist: {}, message: payload.message });
    });

    (async () => {
      try {
        const res = await fetch("/api/connection/profile");
        if (!res.ok) return;
        const data = await res.json();
        if (data.checklist && Object.keys(data.checklist).length) {
          updateConnectionUI({ checklist: data.checklist, bridge_state: data.bridge_state });
        }
        const autoTest = connectionForm.querySelector('[name="auto_test_on_load"]')?.checked;
        const host = connectionForm.querySelector('[name="ldap_host"]')?.value?.trim();
        if (autoTest && host) {
          const retest = await postForm("/api/connection/retest", new FormData());
          updateConnectionUI(retest);
        }
      } catch {
        /* optional */
      }
    })();
  }

  if (deceptionForm) {
    const resultEl = document.querySelector("[data-deception-result]");
    const showResult = (payload) => {
      if (resultEl) resultEl.textContent = JSON.stringify(payload, null, 2);
    };

    deceptionForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const formData = new FormData(deceptionForm);
      if (!formData.has("sync_to_graph")) formData.set("sync_to_graph", "false");
      if (!formData.has("provision_ad")) formData.set("provision_ad", "false");
      if (!formData.has("dry_run")) formData.set("dry_run", "false");
      const res = await fetch("/api/deception/deploy", { method: "POST", body: formData });
      const payload = await res.json();
      showResult(payload);
      if (graphPanel) graphPanel.style.outline = "2px solid var(--primary)";
    });

    document.querySelector('[data-action="preflight"]')?.addEventListener("click", async () => {
      const res = await fetch("/api/deception/preflight");
      showResult(await res.json());
    });

    document.querySelector('[data-action="teardown"]')?.addEventListener("click", async () => {
      if (!window.confirm("Tear down AD objects from the last Active Directory deployment?")) return;
      const formData = new FormData();
      formData.set("dry_run", "false");
      const res = await fetch("/api/deception/teardown", { method: "POST", body: formData });
      showResult(await res.json());
    });
  }

  if (monitoringTable) {
    const filters = document.querySelector("[data-monitoring-filters]");
    const messageEl = document.querySelector("[data-monitoring-message]");
    const feedState = document.querySelector("[data-mon-feed-state]");
    let refreshTimer = null;
    let eventSource = null;

    const severityBadge = (severity) => {
      const map = {
        critical: "badge--error",
        high: "badge--degraded",
        medium: "badge--pending",
        info: "badge--ok",
      };
      return `badge ${map[severity] || "badge--pending"}`;
    };

    const escapeHtml = (value) =>
      String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
      })[ch]);

    const setMessage = (text) => {
      if (messageEl) messageEl.textContent = text;
    };

    const updateStats = (stats) => {
      if (!stats) return;
      document.querySelectorAll("[data-mon-stat]").forEach((el) => {
        const key = el.getAttribute("data-mon-stat");
        if (key in stats) el.textContent = stats[key];
      });
    };

    const healthBadgeClass = (health) => {
      if (health === "healthy") return "badge badge--connected";
      if (health === "stale") return "badge badge--pending";
      return "badge badge--error";
    };

    const loadAgents = async () => {
      const listEl = document.querySelector("[data-agent-list]");
      const badgeEl = document.querySelector("[data-agent-health-badge]");
      const vmEl = document.querySelector("[data-agent-vm]");
      if (!listEl) return;
      try {
        const res = await fetch("/api/agents");
        if (!res.ok) throw new Error(`Agent status failed (${res.status})`);
        const payload = await res.json();
        if (badgeEl) {
          badgeEl.textContent = `${payload.healthy || 0}/${payload.total || 0} healthy`;
          badgeEl.className =
            payload.healthy > 0 ? "badge badge--connected" : "badge badge--pending";
        }
        if (vmEl && payload.registered_vm_name) {
          vmEl.textContent = `Hypervisor VM: ${payload.registered_vm_name}`;
        }
        const agents = payload.agents || [];
        if (!agents.length) {
          listEl.innerHTML = `<li class="data-list__row">
            <span class="data-list__label">No agents</span>
            <span class="data-list__value data-list__value--muted">Waiting for heartbeat…</span>
          </li>`;
          return;
        }
        listEl.innerHTML = agents
          .map(
            (agent) => `<li class="data-list__row">
              <span class="data-list__label">${escapeHtml(agent.agent_id)}</span>
              <span class="data-list__value">
                <span class="${healthBadgeClass(agent.health)}">${escapeHtml(agent.health)}</span>
                ${escapeHtml(agent.hostname || "—")} · ${agent.events_forwarded || 0} fwd
              </span>
            </li>`
          )
          .join("");
      } catch (error) {
        listEl.innerHTML = `<li class="data-list__row">
          <span class="data-list__label">Error</span>
          <span class="data-list__value data-list__value--warn">${escapeHtml(error.message)}</span>
        </li>`;
      }
    };

    const renderEvents = (events) => {
      if (!events.length) {
        monitoringTable.innerHTML = '<tr><td colspan="7">No events match the current filters.</td></tr>';
        return;
      }
      monitoringTable.innerHTML = events
        .map((event) => {
          const time = new Date(event.timestamp).toLocaleTimeString();
          const honeyRow = event.honey_object ? ' class="is-honey"' : "";
          const detail = event.honey_object
            ? `${escapeHtml(event.description)}`
            : escapeHtml(event.description || event.label);
          const ackCell = event.honey_object
            ? event.acknowledged
              ? '<span class="badge badge--skipped">acked</span>'
              : `<button type="button" class="btn btn--secondary btn--xs" data-ack="${event.uid}">Ack</button>`
            : "";
          return `<tr${honeyRow}>
            <td>${escapeHtml(time)}</td>
            <td>${event.event_id}</td>
            <td><span class="${severityBadge(event.severity)}">${escapeHtml(event.severity)}</span></td>
            <td title="${escapeHtml(event.actor)}">${escapeHtml(event.actor)}</td>
            <td title="${escapeHtml(event.target)}">${escapeHtml(event.target)}</td>
            <td title="${detail}">${detail}</td>
            <td>${ackCell}</td>
          </tr>`;
        })
        .join("");
    };

    const filterQuery = () => {
      const params = new URLSearchParams();
      if (!filters) return params;
      const severity = filters.querySelector('[name="severity"]')?.value;
      const eventId = filters.querySelector('[name="event_id"]')?.value;
      const honeyOnly = filters.querySelector('[name="honey_only"]')?.checked;
      if (severity) params.set("severity", severity);
      if (eventId) params.set("event_id", eventId);
      if (honeyOnly) params.set("honey_only", "true");
      params.set("limit", "50");
      return params;
    };

    const loadEvents = async () => {
      try {
        const res = await fetch(`/api/monitoring/events?${filterQuery()}`);
        if (!res.ok) throw new Error(`Feed request failed (${res.status})`);
        const payload = await res.json();
        renderEvents(payload.events || []);
        updateStats(payload.stats);
        loadAgents();
        if (feedState && !(eventSource && eventSource.readyState === 1)) {
          feedState.textContent = "Live";
          feedState.className = "badge badge--connected";
        }
      } catch (error) {
        if (feedState) {
          feedState.textContent = "Error";
          feedState.className = "badge badge--error";
        }
        setMessage(error.message);
      }
    };

    const stopStream = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };

    const startStream = () => {
      stopStream();
      const enabled = filters?.querySelector('[name="live_stream"]')?.checked;
      if (!enabled || typeof EventSource === "undefined") return;
      eventSource = new EventSource("/api/monitoring/stream");
      eventSource.addEventListener("ready", () => {
        if (feedState) {
          feedState.textContent = "Streaming";
          feedState.className = "badge badge--connected";
        }
      });
      eventSource.addEventListener("monitoring", () => {
        loadEvents();
      });
      eventSource.onerror = () => {
        if (feedState) {
          feedState.textContent = "Reconnecting";
          feedState.className = "badge badge--pending";
        }
      };
    };

    const scheduleRefresh = () => {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = null;
      const enabled = filters?.querySelector('[name="auto_refresh"]')?.checked;
      const streaming = filters?.querySelector('[name="live_stream"]')?.checked;
      if (enabled && !streaming) refreshTimer = setInterval(loadEvents, 8000);
    };

    filters?.addEventListener("change", () => {
      loadEvents();
      scheduleRefresh();
      startStream();
    });

    monitoringTable.addEventListener("click", async (e) => {
      const button = e.target.closest("[data-ack]");
      if (!button) return;
      const formData = new FormData();
      formData.set("uid", button.getAttribute("data-ack"));
      const res = await fetch("/api/monitoring/acknowledge", { method: "POST", body: formData });
      const payload = await res.json();
      updateStats(payload.stats);
      setMessage(payload.success ? `Acknowledged event ${formData.get("uid")}.` : payload.message);
      loadEvents();
    });

    document.querySelector('[data-action="simulate"]')?.addEventListener("click", async () => {
      const formData = new FormData();
      formData.set("count", "3");
      const res = await fetch("/api/monitoring/simulate", { method: "POST", body: formData });
      const payload = await res.json();
      setMessage(payload.message);
      updateStats(payload.stats);
      loadEvents();
    });

    document.querySelector('[data-action="ack-all"]')?.addEventListener("click", async () => {
      const formData = new FormData();
      formData.set("ack_all", "true");
      const res = await fetch("/api/monitoring/acknowledge", { method: "POST", body: formData });
      const payload = await res.json();
      setMessage(`Acknowledged ${payload.updated} honey alert(s).`);
      updateStats(payload.stats);
      loadEvents();
    });

    document.querySelector('[data-action="refresh"]')?.addEventListener("click", loadEvents);

    loadEvents();
    scheduleRefresh();
    startStream();
  }

  const vizFilters = document.querySelector("[data-viz-filters]");
  const graphCanvas = document.querySelector("[data-graph-canvas]");
  if (vizFilters && graphCanvas) {
    const tableBody = document.querySelector("[data-viz-table]");
    const stateBadge = document.querySelector("[data-viz-state]");
    const sourceBadge = document.querySelector("[data-viz-source]");
    const messageEl = document.querySelector("[data-viz-message]");
    const selectionEl = document.querySelector("[data-viz-selection]");
    const ctx = graphCanvas.getContext("2d");

    const colorFor = (node) => {
      const type = node.object_type || "";
      if (type.startsWith("Honey")) return "#3b82f6";
      if (type === "ADTrust") return "#f59e0b";
      if (type.startsWith("AD")) return "#94a3b8";
      return "#64748b";
    };

    const state = {
      nodes: [],
      edges: [],
      positions: new Map(),
      dragId: null,
      panX: 0,
      panY: 0,
      scale: 1,
      simTicks: 0,
    };

    const resizeCanvas = () => {
      const rect = graphCanvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      graphCanvas.width = Math.max(640, Math.floor(rect.width * dpr));
      graphCanvas.height = Math.floor(520 * dpr);
      graphCanvas.style.width = `${Math.max(640, Math.floor(rect.width))}px`;
      graphCanvas.style.height = "520px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const filterQuery = () => {
      const params = new URLSearchParams();
      params.set("kind", vizFilters.querySelector('[name="kind"]')?.value || "all");
      const q = vizFilters.querySelector('[name="q"]')?.value?.trim();
      const role = vizFilters.querySelector('[name="role"]')?.value?.trim();
      if (q) params.set("q", q);
      if (role) params.set("role", role);
      if (vizFilters.querySelector('[name="active_only"]')?.checked) params.set("active_only", "true");
      if (vizFilters.querySelector('[name="honey_only"]')?.checked) params.set("honey_only", "true");
      params.set("limit", "150");
      return params;
    };

    const layoutNodes = (nodes) => {
      const width = graphCanvas.clientWidth || 900;
      const height = 520;
      const cx = width / 2;
      const cy = height / 2;
      nodes.forEach((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
        const radius = 40 + (index % 5) * 28 + Math.min(160, nodes.length * 4);
        state.positions.set(node.id, {
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
          vx: 0,
          vy: 0,
        });
      });
    };

    const stepSimulation = () => {
      const nodes = state.nodes;
      if (!nodes.length) return;
      for (let i = 0; i < nodes.length; i += 1) {
        const a = state.positions.get(nodes[i].id);
        for (let j = i + 1; j < nodes.length; j += 1) {
          const b = state.positions.get(nodes[j].id);
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const rep = 2200 / (dist * dist);
          dx = (dx / dist) * rep;
          dy = (dy / dist) * rep;
          a.vx += dx;
          a.vy += dy;
          b.vx -= dx;
          b.vy -= dy;
        }
      }
      state.edges.forEach((edge) => {
        const a = state.positions.get(edge.source);
        const b = state.positions.get(edge.target);
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - 110) * 0.01;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });
      nodes.forEach((node) => {
        if (state.dragId === node.id) return;
        const p = state.positions.get(node.id);
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x += p.vx;
        p.y += p.vy;
      });
    };

    const draw = () => {
      const width = graphCanvas.clientWidth || 900;
      const height = 520;
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(state.panX, state.panY);
      ctx.scale(state.scale, state.scale);

      state.edges.forEach((edge) => {
        const a = state.positions.get(edge.source);
        const b = state.positions.get(edge.target);
        if (!a || !b) return;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = "rgba(148, 163, 184, 0.45)";
        ctx.lineWidth = 1.2;
        ctx.stroke();
      });

      state.nodes.forEach((node) => {
        const p = state.positions.get(node.id);
        if (!p) return;
        const radius = node.object_type?.startsWith("Honey") ? 11 : 9;
        ctx.beginPath();
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = colorFor(node);
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = "rgba(15, 23, 42, 0.85)";
        ctx.stroke();
        ctx.fillStyle = "rgba(226, 232, 240, 0.95)";
        ctx.font = "11px Inter, system-ui, sans-serif";
        ctx.fillText(String(node.name || "").slice(0, 22), p.x + 12, p.y + 4);
      });
      ctx.restore();
    };

    const animate = () => {
      if (state.simTicks > 0) {
        stepSimulation();
        state.simTicks -= 1;
      }
      draw();
      requestAnimationFrame(animate);
    };

    const renderTable = (nodes) => {
      if (!tableBody) return;
      if (!nodes.length) {
        tableBody.innerHTML = '<tr><td colspan="4">No nodes match the current filters.</td></tr>';
        return;
      }
      tableBody.innerHTML = nodes
        .map((node) => `<tr>
          <td title="${escapeHtml(node.name)}">${escapeHtml(node.name)}</td>
          <td title="${escapeHtml(node.role)}">${escapeHtml(node.role || "")}</td>
          <td>${escapeHtml(node.object_type || "")}</td>
          <td>${escapeHtml(node.color || "")}</td>
        </tr>`)
        .join("");
    };

    const escapeHtml = (value) =>
      String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
      })[ch]);

    const updateStats = (counts, source) => {
      document.querySelectorAll("[data-viz-stat]").forEach((el) => {
        const key = el.getAttribute("data-viz-stat");
        if (counts && key in counts) el.textContent = counts[key];
      });
      if (sourceBadge) {
        sourceBadge.textContent = source === "neo4j" ? "Live" : source === "preview" ? "Preview" : source;
        sourceBadge.className = `badge ${source === "neo4j" ? "badge--connected" : "badge--pending"}`;
      }
    };

    const loadTopology = async () => {
      if (stateBadge) {
        stateBadge.textContent = "Loading";
        stateBadge.className = "badge badge--pending";
      }
      try {
        const res = await fetch(`/api/graph/topology?${filterQuery()}`);
        if (!res.ok) throw new Error(`Topology request failed (${res.status})`);
        const payload = await res.json();
        state.nodes = payload.nodes || [];
        state.edges = payload.edges || [];
        layoutNodes(state.nodes);
        state.simTicks = 80;
        renderTable(state.nodes);
        updateStats(payload.counts || {}, payload.source || "preview");
        if (stateBadge) {
          stateBadge.textContent = payload.source === "neo4j" ? "Live" : "Preview";
          stateBadge.className = `badge ${payload.source === "neo4j" ? "badge--connected" : "badge--pending"}`;
        }
        if (messageEl) {
          messageEl.textContent = state.nodes.length
            ? `Showing ${state.nodes.length} node(s), ${state.edges.length} edge(s).`
            : "No nodes match filters — import directory or deploy honey objects.";
        }
      } catch (error) {
        if (stateBadge) {
          stateBadge.textContent = "Error";
          stateBadge.className = "badge badge--error";
        }
        if (messageEl) messageEl.textContent = error.message;
      }
    };

    const eventPos = (event) => {
      const rect = graphCanvas.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left - state.panX) / state.scale,
        y: (event.clientY - rect.top - state.panY) / state.scale,
      };
    };

    const findNodeAt = (x, y) => {
      for (let i = state.nodes.length - 1; i >= 0; i -= 1) {
        const node = state.nodes[i];
        const p = state.positions.get(node.id);
        if (!p) continue;
        const dx = p.x - x;
        const dy = p.y - y;
        if (dx * dx + dy * dy <= 14 * 14) return node;
      }
      return null;
    };

    graphCanvas.addEventListener("pointerdown", (event) => {
      const pos = eventPos(event);
      const hit = findNodeAt(pos.x, pos.y);
      if (hit) {
        state.dragId = hit.id;
        graphCanvas.classList.add("is-dragging");
        if (selectionEl) {
          selectionEl.textContent = `${hit.name} · ${hit.object_type} · ${hit.role || "no role"}`;
        }
        graphCanvas.setPointerCapture(event.pointerId);
      }
    });

    graphCanvas.addEventListener("pointermove", (event) => {
      if (!state.dragId) return;
      const pos = eventPos(event);
      const p = state.positions.get(state.dragId);
      if (!p) return;
      p.x = pos.x;
      p.y = pos.y;
      p.vx = 0;
      p.vy = 0;
    });

    const endDrag = () => {
      state.dragId = null;
      graphCanvas.classList.remove("is-dragging");
    };
    graphCanvas.addEventListener("pointerup", endDrag);
    graphCanvas.addEventListener("pointercancel", endDrag);

    graphCanvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      const delta = event.deltaY > 0 ? 0.92 : 1.08;
      state.scale = Math.min(2.5, Math.max(0.45, state.scale * delta));
    }, { passive: false });

    vizFilters.addEventListener("change", loadTopology);
    vizFilters.addEventListener("input", (event) => {
      if (event.target?.name === "q" || event.target?.name === "role") {
        clearTimeout(vizFilters._timer);
        vizFilters._timer = setTimeout(loadTopology, 250);
      }
    });
    document.querySelector('[data-action="viz-refresh"]')?.addEventListener("click", loadTopology);

    resizeCanvas();
    window.addEventListener("resize", () => {
      resizeCanvas();
      draw();
    });
    loadTopology();
    animate();
  }
});
