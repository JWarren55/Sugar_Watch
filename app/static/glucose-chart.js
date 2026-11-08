// Draw only this account's recorded points; no third-party chart service or CDN.
(() => {
    const root = document.getElementById("glucose-chart");
    if (!root) return;
    const canvas = document.getElementById("chart-canvas");
    const status = document.getElementById("chart-status");
    const inspection = document.getElementById("chart-inspection");
    const slider = document.getElementById("chart-reading");
    const output = document.getElementById("chart-reading-value");
    const buttons = [...root.querySelectorAll("[data-chart-hours]")];
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const shortTime = new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit"
    });
    const fullTime = new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short"
    });
    let hours = 12;
    let controller;
    let data;
    let selectReading = () => {};

    function node(tag, attrs = {}, text) {
        const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
        for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function draw() {
        if (!data) return;
        const points = data.readings.map(row => ({
            time: new Date(row.time),
            glucose: row.glucose
        }));
        const width = Math.max(280, canvas.clientWidth);
        const height = 320;
        const left = 60,
            right = 18,
            top = 22,
            bottom = 68;
        const plotWidth = width - left - right,
            plotHeight = height - top - bottom;
        const start = new Date(data.start).getTime(),
            end = new Date(data.end).getTime();
        const maximum = Math.max(180, ...points.map(point => point.glucose));
        const step = Math.ceil(maximum / 125) * 25;
        const ceiling = Math.ceil((maximum + 20) / step) * step;
        const x = instant => left + (instant - start) / (end - start) * plotWidth;
        const y = value => top + plotHeight * (1 - value / ceiling);
        const svg = node("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-labelledby": "glucose-svg-title glucose-svg-description"
        });
        svg.append(node("title", {
            id: "glucose-svg-title"
        }, `Glucose over the past ${data.hours} hours`));
        svg.append(node("desc", {
            id: "glucose-svg-description"
        }, `${points.length} recorded readings. Time runs left to right; glucose in milligrams per deciliter runs bottom to top. Use the reading slider for individual values.`));
        for (let tick = 0; tick <= ceiling; tick += step) {
            svg.append(node("line", {
                x1: left,
                x2: width - right,
                y1: y(tick),
                y2: y(tick),
                class: "chart-grid"
            }));
            svg.append(node("text", {
                x: left - 10,
                y: y(tick) + 4,
                "text-anchor": "end"
            }, tick));
        }
        const ticks = width < 500 ? 2 : 4;
        for (let i = 0; i <= ticks; i++) {
            const instant = start + (end - start) * i / ticks;
            const anchor = i === 0 ? "start" : i === ticks ? "end" : "middle";
            svg.append(node("text", {
                x: x(instant),
                y: height - bottom + 24,
                "text-anchor": anchor
            }, shortTime.format(new Date(instant))));
        }
        svg.append(node("line", {
            x1: left,
            x2: width - right,
            y1: y(0),
            y2: y(0),
            class: "chart-axis"
        }));
        svg.append(node("text", {
            x: 16,
            y: top + plotHeight / 2,
            transform: `rotate(-90 16 ${top + plotHeight / 2})`,
            "text-anchor": "middle"
        }, "Glucose (mg/dL)"));
        svg.append(node("text", {
            x: left + plotWidth / 2,
            y: height - 10,
            "text-anchor": "middle"
        }, `Time · ${zone}`));
        let path = "";
        for (let i = 0; i < points.length; i++) {
            const point = points[i];
            const gap = i === 0 || point.time - points[i - 1].time > 20 * 60 * 1000;
            path += `${gap ? "M" : "L"}${x(point.time.getTime())},${y(point.glucose)} `;
        }
        if (points.length) {
            svg.append(node("path", {
                d: path,
                class: "chart-line"
            }));
            for (const point of points) svg.append(node("circle", {
                cx: x(point.time.getTime()),
                cy: y(point.glucose),
                r: 2.2,
                class: "chart-point"
            }));
            const marker = node("circle", {
                r: 5,
                class: "chart-selected"
            });
            svg.append(marker);
            selectReading = index => {
                index = Math.max(0, Math.min(points.length - 1, index));
                const point = points[index];
                slider.value = index;
                marker.setAttribute("cx", x(point.time.getTime()));
                marker.setAttribute("cy", y(point.glucose));
                const detail = `${fullTime.format(point.time)} · ${point.glucose} mg/dL`;
                output.textContent = detail;
                slider.setAttribute("aria-valuetext", detail);
            };
            slider.max = points.length - 1;
            slider.disabled = points.length === 1;
            inspection.hidden = false;
            selectReading(Math.min(Number(slider.value), points.length - 1));
            svg.addEventListener("pointermove", event => {
                const bounds = svg.getBoundingClientRect();
                const instant = start + (((event.clientX - bounds.left) * width / bounds.width - left) / plotWidth) * (end - start);
                let nearest = 0;
                points.forEach((point, index) => {
                    if (Math.abs(point.time - instant) < Math.abs(points[nearest].time - instant)) nearest = index;
                });
                selectReading(nearest);
            });
        } else {
            inspection.hidden = true;
            svg.append(node("text", {
                x: left + plotWidth / 2,
                y: top + plotHeight / 2,
                "text-anchor": "middle"
            }, "No readings in this time range"));
        }
        canvas.replaceChildren(svg);
    }

    async function load() {
        if (controller) controller.abort();
        const request = new AbortController();
        controller = request;
        const selectedHours = hours;
        data = undefined;
        canvas.replaceChildren();
        inspection.hidden = true;
        canvas.setAttribute("aria-busy", "true");
        status.textContent = "Loading glucose readings…";
        buttons.forEach(button => button.setAttribute("aria-pressed", Number(button.dataset.chartHours) === hours ? "true" : "false"));
        try {
            const response = await fetch(`/glucose/chart?hours=${selectedHours}`, {
                headers: {
                    Accept: "application/json"
                },
                credentials: "same-origin",
                cache: "no-store",
                signal: request.signal
            });
            if (response.status === 401) throw new Error("Your session expired. Sign in again to view the chart.");
            if (!response.ok) throw new Error("Unable to load the chart. Try Refresh chart.");
            const result = await response.json();
            if (request.signal.aborted) return;
            data = result;
            slider.value = Math.max(0, data.readings.length - 1);
            draw();
            const latest = data.readings.at(-1);
            status.textContent = `${data.readings.length} readings · Past ${selectedHours} hours` + (latest ? ` · Latest: ${fullTime.format(new Date(latest.time))}` : "");
        } catch (error) {
            if (!request.signal.aborted) status.textContent = error instanceof TypeError ? "Couldn’t reach Sugar Watch. Try Refresh chart." : error.message;
        } finally {
            if (!request.signal.aborted) canvas.setAttribute("aria-busy", "false");
        }
    }
    buttons.forEach(button => button.addEventListener("click", () => {
        hours = Number(button.dataset.chartHours);
        load();
    }));
    slider.addEventListener("input", () => selectReading(Number(slider.value)));
    document.getElementById("chart-refresh").addEventListener("click", load);
    new ResizeObserver(draw).observe(canvas);
    setInterval(() => {
        if (!document.hidden) load();
    }, 5 * 60 * 1000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) load();
    });
    load();
})();
