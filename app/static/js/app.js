const form = document.getElementById("incident-form");
const errorEl = document.getElementById("form-error");
const resultPanel = document.getElementById("result-panel");

const outOriginal = document.getElementById("out-original");
const outCategories = document.getElementById("out-categories");
const outAction = document.getElementById("out-action");
const outDepartment = document.getElementById("out-department");
const outPhone = document.getElementById("out-phone");
const outSummary = document.getElementById("out-summary");
const outScript = document.getElementById("out-script");

const actionLabels = {
    call_police: "Polizei kontaktieren (Simulation)",
};

function showError(message) {
    errorEl.hidden = false;
    errorEl.textContent = message;
}

function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
}

function renderResult(data) {
    outOriginal.textContent = data.original_input;
    outCategories.textContent = data.selected_categories.join(", ");
    outAction.textContent = actionLabels[data.selected_action] || data.selected_action;
    outDepartment.textContent = data.police_department
        ? `${data.police_department.name} (${data.police_department.city})`
        : "Keine zuständige Dienststelle gefunden";
    outPhone.textContent = data.police_phone_number || "Keine Telefonnummer verfügbar";
    outSummary.textContent = data.summary;
    outScript.textContent = data.generated_script;
    resultPanel.hidden = false;
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();

    const rawText = document.getElementById("raw_text").value.trim();
    const postalCode = document.getElementById("postal_code").value.trim();

    if (!/^\d{5}$/.test(postalCode)) {
        showError("Bitte eine gültige 5-stellige deutsche Postleitzahl eingeben.");
        return;
    }

    if (rawText.length < 5) {
        showError("Bitte eine aussagekräftige Vorfallsbeschreibung eingeben.");
        return;
    }

    try {
        const response = await fetch("/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_text: rawText, postal_code: postalCode }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: "Unbekannter Fehler" }));
            showError(err.detail || "Analyse fehlgeschlagen.");
            return;
        }

        const data = await response.json();
        renderResult(data);
    } catch (error) {
        showError("Server nicht erreichbar. Bitte prüfen, ob die App läuft.");
    }
});

document.querySelectorAll(".sample-btn").forEach((button) => {
    button.addEventListener("click", () => {
        document.getElementById("raw_text").value = button.dataset.text || "";
        document.getElementById("postal_code").value = button.dataset.plz || "";
    });
});

console.log("RheinBahn Dashboard Loaded");
