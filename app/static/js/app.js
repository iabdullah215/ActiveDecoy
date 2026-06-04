document.addEventListener("DOMContentLoaded", () => {
  const connectionForm = document.querySelector("[data-connection-form]");
  const deceptionForm = document.querySelector("[data-deception-form]");
  const monitoringPanel = document.querySelector("[data-monitoring-panel]");
  const graphPanel = document.querySelector("[data-graph-panel]");

  const showJson = (container, payload) => {
    if (!container) return;
    container.textContent = JSON.stringify(payload, null, 2);
  };

  const badgeClass = (status) => {
    const map = {
      ok: "ad-badge-connected",
      connected: "ad-badge-connected",
      degraded: "ad-badge-degraded",
      error: "ad-badge-failed",
      failed: "ad-badge-failed",
      skipped: "ad-badge-not_connected",
      pending: "ad-badge-not_connected",
      not_connected: "ad-badge-not_connected",
    };
    return map[status] || "ad-badge-not_connected";
  };

  const updateConnectionUI = (payload) => {
    const checklist = payload.checklist || {};
    const ldap = checklist.ldap || {};
    const hypervisor = checklist.hypervisor || {};
    const bridge = checklist.bridge || {};

    const ldapCard = document.querySelector("[data-status-ldap]");
    const hvCard = document.querySelector("[data-status-hypervisor]");
    const bridgeCard = document.querySelector("[data-status-bridge]");

    const setStatus = (card, badgeEl, msgEl, item) => {
      if (!badgeEl || !msgEl) return;
      const status = item.status || "pending";
      badgeEl.textContent = status;
      badgeEl.className = `ad-badge ${badgeClass(status)}`;
      msgEl.textContent = item.message || "—";
      if (card) {
        card.classList.remove("is-ok", "is-error", "is-skipped");
        if (status === "ok") card.classList.add("is-ok");
        else if (status === "error") card.classList.add("is-error");
        else if (status === "skipped") card.classList.add("is-skipped");
      }
    };

    setStatus(
      ldapCard,
      document.querySelector("[data-status-ldap-badge]"),
      document.querySelector("[data-status-ldap-msg]"),
      ldap,
    );
    setStatus(
      hvCard,
      document.querySelector("[data-status-hypervisor-badge]"),
      document.querySelector("[data-status-hypervisor-msg]"),
      hypervisor,
    );
    setStatus(
      bridgeCard,
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
      debugEl.textContent = lines.length ? lines.join("\n") : "No debug output.";
    }
  };

  const setLoading = (loading) => {
    const label = document.querySelector("[data-test-label]");
    if (!label) return;
    if (loading) {
      label.innerHTML = '<span class="ad-spinner inline-block"></span> Testing…';
    } else {
      label.textContent = "Validate Connection";
    }
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
    const type = select.value;
    const wrapper = document.querySelector("[data-field=wrapper]");
    const endpoint = document.querySelector("[data-field=endpoint]");
    const hvUser = document.querySelector("[data-field=hv-user]");
    const hvPass = document.querySelector("[data-field=hv-pass]");

    const isUtm = type === "utm";
    wrapper?.classList.toggle("hidden", !isUtm);
    endpoint?.classList.toggle("hidden", isUtm);
    hvUser?.classList.toggle("hidden", isUtm);
    hvPass?.classList.toggle("hidden", isUtm);
  };

  if (connectionForm) {
    toggleHypervisorFields();
    document.querySelector("[data-hypervisor-type]")?.addEventListener("change", toggleHypervisorFields);

    const runTest = async (url) => {
      setLoading(true);
      try {
        const formData = formToUnchecked(new FormData(connectionForm));
        const payload = await postForm(url, formData);
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

    connectionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await runTest("/api/connection/test");
    });

    connectionForm.querySelector("[data-action=save]")?.addEventListener("click", async () => {
      setLoading(true);
      try {
        const formData = formToUnchecked(new FormData(connectionForm));
        const payload = await postForm("/api/connection/save", formData);
        const debugEl = document.querySelector("[data-connection-debug]");
        if (debugEl) debugEl.textContent = "Profile saved to session.";
        updateConnectionUI({ checklist: {}, message: payload.success ? "Profile saved." : "" });
      } finally {
        setLoading(false);
      }
    });

    connectionForm.querySelector("[data-action=retest]")?.addEventListener("click", async () => {
      setLoading(true);
      try {
        const payload = await postForm("/api/connection/retest", new FormData());
        updateConnectionUI(payload);
      } finally {
        setLoading(false);
      }
    });

    connectionForm.querySelector("[data-action=disconnect]")?.addEventListener("click", async () => {
      const payload = await postForm("/api/connection/disconnect", new FormData());
      updateConnectionUI({
        checklist: {},
        message: payload.message,
        bridge_state: payload.bridge_state,
      });
    });

    const initConnection = async () => {
      try {
        const response = await fetch("/api/connection/profile");
        if (!response.ok) return;
        const data = await response.json();
        if (data.checklist && Object.keys(data.checklist).length) {
          updateConnectionUI({ checklist: data.checklist, bridge_state: data.bridge_state });
        }
        const autoTest = connectionForm.querySelector("[name=auto_test_on_load]")?.checked;
        const host = connectionForm.querySelector("[name=ldap_host]")?.value?.trim();
        if (autoTest && host) {
          const retestPayload = await postForm("/api/connection/retest", new FormData());
          updateConnectionUI(retestPayload);
        }
      } catch {
        /* profile load is best-effort */
      }
    };

    initConnection();
  }

  if (deceptionForm) {
    deceptionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(deceptionForm);
      if (!formData.has("sync_to_graph")) formData.set("sync_to_graph", "false");
      const response = await fetch("/api/deception/deploy", { method: "POST", body: formData });
      const payload = await response.json();
      showJson(document.querySelector("[data-deception-result]"), payload);
      if (graphPanel) graphPanel.classList.add("ring-2", "ring-cyan-400/30");
    });
  }

  if (monitoringPanel) {
    fetch("/api/monitoring/events")
      .then((response) => response.json())
      .then((payload) => showJson(monitoringPanel, payload))
      .catch((error) => showJson(monitoringPanel, { error: error.message }));
  }
});
