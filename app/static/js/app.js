document.addEventListener("DOMContentLoaded", () => {
  const connectionForm = document.querySelector("[data-connection-form]");
  const deceptionForm = document.querySelector("[data-deception-form]");
  const monitoringPanel = document.querySelector("[data-monitoring-panel]");
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

  if (monitoringPanel) {
    fetch("/api/monitoring/events")
      .then((r) => r.json())
      .then((p) => { monitoringPanel.textContent = JSON.stringify(p, null, 2); })
      .catch((err) => { monitoringPanel.textContent = err.message; });
  }
});
