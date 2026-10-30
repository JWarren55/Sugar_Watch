// Store UTC timestamps while showing dates in the viewer's timezone.
(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

    function localValue(date) {
        const pad = value => String(value).padStart(2, "0");
        return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) +
            "T" + pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date
                .getSeconds());
    }
    document.querySelectorAll("time.local-time").forEach(element => {
        const date = new Date(element.dateTime);
        if (!Number.isNaN(date.getTime())) {
            element.textContent = date.toLocaleString(undefined, {
                year: "numeric",
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
                timeZoneName: "short"
            });
            element.title = element.dateTime + " · " + zone;
        }
    });
    document.querySelectorAll('input[type="datetime-local"]').forEach(input => {
        const date = input.dataset.utc ? new Date(input.dataset.utc) : new Date();
        if (!input.value && !Number.isNaN(date.getTime())) input.value = localValue(
            date);
        input.step = "1";
        const form = input.form;
        if (form && !form.querySelector('[name="client_timezone"]')) {
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = "client_timezone";
            hidden.value = zone;
            form.append(hidden);
        }
    });
    window.SugarTime = {
        prepare(form, data) {
            data.set("client_timezone", zone);
            form.querySelectorAll('input[type="datetime-local"]').forEach(input => {
                if (input.name && input.value) {
                    const date = new Date(input.value);
                    if (!Number.isNaN(date.getTime())) data.set(input.name, date
                        .toISOString());
                }
            });
        }
    };
})();
