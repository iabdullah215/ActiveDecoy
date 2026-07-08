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
    deceptionForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const formData = new FormData(deceptionForm);
      if (!formData.has("sync_to_graph")) formData.set("sync_to_graph", "false");
      const res = await fetch("/api/deception/deploy", { method: "POST", body: formData });
      const payload = await res.json();
      const out = document.querySelector("[data-deception-result]");
      if (out) out.textContent = JSON.stringify(payload, null, 2);
      if (graphPanel) graphPanel.style.outline = "2px solid var(--primary)";
    });
  }

  if (monitoringTable) {
    const filters = document.querySelector("[data-monitoring-filters]");
    const messageEl = document.querySelector("[data-monitoring-message]");
    const feedState = document.querySelector("[data-mon-feed-state]");
    let refreshTimer = null;

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
        if (feedState) {
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

    const scheduleRefresh = () => {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = null;
      const enabled = filters?.querySelector('[name="auto_refresh"]')?.checked;
      if (enabled) refreshTimer = setInterval(loadEvents, 8000);
    };

    filters?.addEventListener("change", () => {
      loadEvents();
      scheduleRefresh();
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
  }
});
