// Keep entered values visible when validation or a database request fails.
document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post")
        return;
    if (form.dataset.nativeSubmit === "true") return;
    event.preventDefault();
    if (form.dataset.saving === "true") return;
    let errors = form.querySelector("[data-form-errors]");
    if (!errors) {
        errors = document.createElement("div");
        errors.dataset.formErrors = "true";
        errors.setAttribute("role", "alert");
        errors.tabIndex = -1;
        form.prepend(errors);
    }
    errors.replaceChildren();
    // Disable submission while the current request is being saved.
    const buttons = [...form.querySelectorAll(
        'button[type="submit"], button:not([type]), input[type="submit"]')];
    const disabled = buttons.map(button => button.disabled);
    const data = new FormData(form, event.submitter);
    if (window.SugarTime) window.SugarTime.prepare(form, data);
    form.dataset.saving = "true";
    buttons.forEach(button => button.disabled = true);
    try {
        // Refresh an expired form only if the same account signed back in.
        if (form.dataset.sessionExpired === "true") {
            const check = await fetch("/session", {
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json"
                }
            });
            if (!check.ok) {
                errors.textContent =
                    "Sign in again in another tab, then retry this form.";
                errors.focus();
                return;
            }
            const session = await check.json();
            const originalUser = document.querySelector('meta[name="current-user-id"]')
                ?.content;
            if (!originalUser || String(session.user_id) !== originalUser) {
                errors.textContent =
                    "The signed-in account changed. Reload the page before saving.";
                errors.focus();
                return;
            }
            data.set("csrf_token", session.csrf_token);
            const tokenInput = form.querySelector('[name="csrf_token"]');
            if (tokenInput) tokenInput.value = session.csrf_token;
            delete form.dataset.sessionExpired;
        }
        const response = await fetch(form.action || location.href, {
            method: "POST",
            body: data,
            credentials: "same-origin",
            headers: {
                "Accept": "application/json"
            }
        });
        // Follow the server redirect after a successful save.
        if (response.ok) {
            location.assign(response.redirected ? response.url : location.href);
            return;
        }
        // Display server errors without clearing the form fields.
        const result = await response.json().catch(() => ({}));
        const messages = Array.isArray(result.detail) ? result.detail : [result
            .detail || "Unable to save. Please check your entry and try again."
        ];
        if (response.status === 401) {
            form.dataset.sessionExpired = "true";
            const link = document.createElement("a");
            link.href = "/login";
            link.target = "_blank";
            link.rel = "noopener";
            link.textContent = "Sign in in a new tab, then retry";
            errors.append(link);
        }
        for (const message of messages) {
            const messageElement = document.createElement("p");
            messageElement.textContent = typeof message === "string" ? message : (
                message.msg || "Check your entry.");
            errors.append(messageElement);
        }
    } catch {
        errors.textContent =
            "Couldn't reach Sugar Watch. Your entry is still here; check the connection and try again.";
    } finally {
        // Re-enable the form so failed requests can be corrected and retried.
        form.dataset.saving = "false";
        buttons.forEach((button, i) => button.disabled = disabled[i]);
    }
    errors.focus();
});
