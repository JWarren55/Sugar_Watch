(() => {
    const form = document.getElementById("photo-form");
    const fields = document.getElementById("photo-fields");
    const requestButton = document.getElementById("request-estimate");
    const file = document.getElementById("photo-file");
    const selection = document.getElementById("photo-selection");
    const status = document.getElementById("estimate-status");
    const error = document.getElementById("estimate-error");
    const review = document.getElementById("estimate-review");
    const save = document.getElementById("save-estimate");
    const panel = document.getElementById("camera-panel");
    const video = document.getElementById("meal-camera");
    const open = document.getElementById("open-camera");
    const capture = document.getElementById("capture-photo");

    let photo;
    let stream;
    let cameraAttempt = 0;
    let photoAttempt = 0;

    function stopCamera() {
        cameraAttempt++;
        stream?.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        panel.hidden = true;
        capture.disabled = true;
    }

    function jpeg(source, width, height) {
        const scale = Math.min(1, 1280 / Math.max(width, height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(width * scale));
        canvas.height = Math.max(1, Math.round(height * scale));
        const context = canvas.getContext("2d", { alpha: false });
        context.fillStyle = "white";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        return new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.82));
    }

    function clearPhoto() {
        photo = null;
        requestButton.disabled = true;
        review.hidden = true;
        error.textContent = "";
        selection.textContent = "Preparing photo…";
        return ++photoAttempt;
    }

    function selectPhoto(attempt, image, message) {
        if (attempt !== photoAttempt) return;
        if (!image || image.size > Number(form.dataset.maxBytes)) {
            selection.textContent = "Choose a photo or try the camera again.";
            error.textContent = "This photo could not be prepared. Try a smaller JPEG or PNG.";
            return;
        }
        photo = image;
        selection.textContent = message;
        requestButton.disabled = false;
    }

    file.addEventListener("change", async () => {
        stopCamera();
        const chosen = file.files[0];
        if (!chosen) return;
        const attempt = clearPhoto();
        file.value = "";
        let bitmap;
        try {
            bitmap = await createImageBitmap(chosen);
            selectPhoto(attempt, await jpeg(bitmap, bitmap.width, bitmap.height), "Photo selected.");
        } catch {
            selectPhoto(attempt, null);
        } finally {
            bitmap?.close();
        }
    });

    open.addEventListener("click", async () => {
        stopCamera();
        const attempt = cameraAttempt;
        error.textContent = "";
        panel.hidden = false;
        try {
            const camera = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: "environment" } },
                audio: false
            });
            if (attempt !== cameraAttempt) {
                camera.getTracks().forEach(track => track.stop());
                return;
            }
            stream = camera;
            video.srcObject = stream;
            await video.play();
            if (attempt === cameraAttempt) capture.disabled = false;
        } catch {
            if (attempt !== cameraAttempt) return;
            stopCamera();
            error.textContent = "Camera unavailable. Check camera permission or choose a photo.";
        }
    });

    video.addEventListener("loadeddata", () => {
        if (stream) capture.disabled = false;
    });

    capture.addEventListener("click", async () => {
        if (!video.videoWidth || !video.videoHeight) return;
        const attempt = clearPhoto();
        const image = jpeg(video, video.videoWidth, video.videoHeight);
        stopCamera();
        try {
            selectPhoto(attempt, await image, "Photo captured.");
        } catch {
            selectPhoto(attempt, null);
        }
    });

    document.getElementById("close-camera").addEventListener("click", stopCamera);
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) stopCamera();
    });
    window.addEventListener("pagehide", stopCamera);

    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!photo || fields.disabled) return;
        stopCamera();
        const data = new FormData(form);
        data.set("photo", photo, "meal.jpg");
        window.SugarTime.prepare(form, data);
        fields.disabled = true;
        review.hidden = true;
        error.textContent = "";
        status.textContent = "Estimating nutrition…";
        try {
            const response = await fetch(form.action, {
                method: "POST",
                headers: { Accept: "application/json", "X-CSRF-Token": data.get("csrf_token") },
                body: data
            });
            const result = await response.json();
            if (!response.ok) {
                error.textContent = result.detail?.join(" ") || "Could not estimate nutrition.";
                return;
            }
            save.elements.name.value = data.get("name").trim();
            save.elements.timestamp.value = form.elements.timestamp.value;
            for (const nutrient of ["calories", "carbs", "protein", "fat"]) {
                save.elements[nutrient].value = result[nutrient];
            }
            document.getElementById("portion-note").textContent = result.portion_note;
            review.hidden = false;
            document.getElementById("review-heading").focus();
        } catch {
            error.textContent = "Could not get an estimate. Check your connection and try again.";
        } finally {
            fields.disabled = false;
            status.textContent = "";
        }
    });

    form.addEventListener("input", () => { review.hidden = true; });

    const saveButton = save.querySelector("button[type=submit]");
    save.addEventListener("submit", () => { saveButton.disabled = true; });
    window.addEventListener("pageshow", () => { saveButton.disabled = false; });
})();
