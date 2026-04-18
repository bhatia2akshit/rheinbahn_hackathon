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
const conversationMeta = document.getElementById("conversation-meta");
const conversationBox = document.getElementById("conversation-box");
const conversationEvent = document.getElementById("conversation-event");

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

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function renderConversation(data) {
    if (!conversationBox || !conversationMeta || !conversationEvent) {
        return;
    }

    const status = data.status || "idle";
    const sessionId = data.session_id || "-";
    conversationMeta.textContent = `Status: ${status} | Session: ${sessionId}`;

    const messages = Array.isArray(data.messages) ? data.messages : [];
    if (!messages.length) {
        conversationBox.innerHTML = `<p class="conversation-empty">Noch keine Konversation vorhanden.</p>`;
    } else {
        conversationBox.innerHTML = messages
            .map((message) => {
                const role = message.role === "ai" ? "KI" : "Fahrer";
                const roleClass = message.role === "ai" ? "ai" : "driver";
                return `<div class="conversation-line ${roleClass}"><strong>${role}:</strong> ${escapeHtml(message.text || "")}</div>`;
            })
            .join("");
        conversationBox.scrollTop = conversationBox.scrollHeight;
    }

    if (data.event) {
        conversationEvent.textContent = JSON.stringify(data.event, null, 2);
    } else {
        conversationEvent.textContent = "Noch kein Event erstellt.";
    }
}

async function refreshVoiceConversation() {
    if (!conversationBox || !conversationMeta || !conversationEvent) {
        return;
    }
    try {
        const response = await fetch("/api/voice/conversation");
        if (!response.ok) {
            return;
        }
        const data = await response.json();
        renderConversation(data);
    } catch (error) {
        // Ignore transient polling errors for now.
    }
}

setInterval(refreshVoiceConversation, 1500);
refreshVoiceConversation();
