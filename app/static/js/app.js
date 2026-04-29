document.addEventListener("DOMContentLoaded", () => {
  const connectionForm = document.querySelector("[data-connection-form]");
  const deceptionForm = document.querySelector("[data-deception-form]");
  const monitoringPanel = document.querySelector("[data-monitoring-panel]");
  const graphPanel = document.querySelector("[data-graph-panel]");

  const showResult = (container, payload) => {
    if (!container) {
      return;
    }
    container.textContent = JSON.stringify(payload, null, 2);
  };

  if (connectionForm) {
    connectionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(connectionForm);
      const response = await fetch("/api/connection/test", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      showResult(document.querySelector("[data-connection-result]"), payload);
    });
  }

  if (deceptionForm) {
    deceptionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(deceptionForm);
      const response = await fetch("/api/deception/deploy", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      showResult(document.querySelector("[data-deception-result]"), payload);
      if (graphPanel) {
        graphPanel.classList.add("ring-2", "ring-cyan-400/30");
      }
    });
  }

  if (monitoringPanel) {
    fetch("/api/monitoring/events")
      .then((response) => response.json())
      .then((payload) => {
        showResult(monitoringPanel, payload);
      })
      .catch((error) => {
        showResult(monitoringPanel, { error: error.message });
      });
  }
});
