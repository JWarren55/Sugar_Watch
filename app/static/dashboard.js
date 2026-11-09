(() => {
    const carousel = document.querySelector(".dashboard-carousel");
    const slides = [...carousel.children];
    const tabs = [...document.querySelectorAll("[data-slide]")];
    const arrows = [...document.querySelectorAll("[data-direction]")];
    const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
    let current = 0;

    function offset(slide) {
        return slide.offsetLeft - slides[0].offsetLeft;
    }

    function update(index) {
        current = index;
        slides.forEach((slide, i) => { slide.inert = i !== current; });
        tabs.forEach((tab, i) => tab.setAttribute("aria-pressed", String(i === current)));
        arrows[0].disabled = current === 0;
        arrows[1].disabled = current === slides.length - 1;
        carousel.style.height = `${Math.ceil(slides[current].getBoundingClientRect().height)}px`;
    }

    function go(index) {
        if (index < 0 || index >= slides.length) return;
        carousel.scrollTo({left: offset(slides[index]), behavior: reduceMotion.matches ? "instant" : "smooth"});
    }

    tabs.forEach((button, index) => button.addEventListener("click", () => go(index)));
    arrows.forEach(button => button.addEventListener("click", () => go(current + Number(button.dataset.direction))));
    carousel.addEventListener("scroll", () => {
        const nearest = slides.reduce((best, slide, index) =>
            Math.abs(offset(slide) - carousel.scrollLeft) < Math.abs(offset(slides[best]) - carousel.scrollLeft) ? index : best, 0);
        if (nearest !== current) update(nearest);
    }, {passive: true});
    carousel.addEventListener("keydown", event => {
        if (event.target !== carousel || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        go(current + (event.key === "ArrowRight" ? 1 : -1));
    });
    const resize = new ResizeObserver(() => update(current));
    slides.forEach(slide => resize.observe(slide));
    update(0);

    const dialog = document.getElementById("add-entry");
    document.getElementById("open-add").addEventListener("click", () => dialog.showModal());

    const format = new Intl.NumberFormat(undefined, {maximumFractionDigits: 2});
    const date = new Intl.DateTimeFormat(undefined, {month: "short", day: "numeric"});
    const dateTime = new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"});
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const statuses = [...document.querySelectorAll("[data-summary-status]")];
    const nutrients = [...document.querySelectorAll("[data-nutrient]")];

    function renderMacroGoals(goals) {
        const macros = ["carbs", "protein", "fat"];
        const energy = [goals.carbs * 4, goals.protein * 4, goals.fat * 9];
        const total = energy.reduce((sum, value) => sum + value, 0);
        const pie = document.getElementById("macro-pie");
        const note = document.getElementById("macro-note");
        const legend = document.querySelector(".macro-legend");
        pie.hidden = legend.hidden = !total;
        note.hidden = Boolean(total);
        if (!total) return;
        const percent = energy.map(value => value / total * 100);
        let start = 0;
        const stops = macros.map((name, index) => {
            const end = start + percent[index];
            const stop = `var(--${name}) ${start}% ${end}%`;
            start = end;
            legend.querySelector(`[data-macro="${name}"] strong`).textContent = `${Math.round(percent[index])}%`;
            return stop;
        });
        pie.style.background = `conic-gradient(${stops.join(", ")})`;
    }

    function renderSummary(data) {
        document.querySelectorAll("[data-summary-date]").forEach(node => {
            node.textContent = `· ${date.format(new Date(`${data.date}T12:00:00`))}`;
        });
        for (const row of nutrients) {
            const key = row.dataset.nutrient;
            const value = data.nutrition[key];
            const goal = data.goals[key];
            const unit = key === "calories" ? "kcal" : "g";
            const total = value === null ? "Unknown" : `${format.format(value)} ${unit}`;
            row.querySelector("[data-total]").textContent = goal ? `${total} / ${format.format(goal)} ${unit}` : total;
            const progress = row.querySelector("progress");
            progress.hidden = !goal || value === null;
            if (!progress.hidden) progress.value = Math.min(100, value / goal * 100);
        }
        const note = document.getElementById("nutrition-note");
        note.textContent = data.incomplete_food_entries ? "Some food entries have missing nutrition values. Totals show the values recorded." : "";
        renderMacroGoals(data.goals);
        document.getElementById("daily-heart").textContent = data.heart_rate === null ? "—" : `${format.format(data.heart_rate)} bpm`;
        document.getElementById("daily-energy").textContent = data.active_energy === null ? "—" : `${format.format(data.active_energy)} kcal`;
        const sleep = data.sleep_minutes;
        document.getElementById("daily-sleep").textContent = sleep === null ? "—" : `${Math.floor(sleep / 60)}h ${sleep % 60}m`;
        document.getElementById("apple-updated").textContent = data.apple_updated ? `Last Apple Health import · ${dateTime.format(new Date(data.apple_updated))}` : "No Apple Health import yet.";
    }

    let request;
    async function loadSummary() {
        request?.abort();
        const controller = new AbortController();
        request = controller;
        try {
            const response = await fetch(`/dashboard/summary?zone=${encodeURIComponent(zone)}`, {
                headers: {Accept: "application/json"}, cache: "no-store", signal: controller.signal
            });
            if (!response.ok) throw new Error("Could not load dashboard totals.");
            const summary = await response.json();
            if (controller.signal.aborted) return;
            renderSummary(summary);
            statuses.forEach(status => { status.hidden = true; });
        } catch (error) {
            if (controller.signal.aborted) return;
            statuses.forEach(status => {
                status.hidden = false;
                status.textContent = "Could not load today’s totals. Refresh to try again.";
            });
        }
    }
    loadSummary();
    setInterval(() => { if (!document.hidden) loadSummary(); }, 5 * 60 * 1000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) loadSummary(); });
})();
