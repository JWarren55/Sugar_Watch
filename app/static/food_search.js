/* Decode product barcodes locally. Only the decoded number is sent to search. */
(() => {
    "use strict";
    const start = document.getElementById("scan-start");
    const stop = document.getElementById("scan-stop");
    const panel = document.getElementById("scanner");
    const video = document.getElementById("scan-video");
    const status = document.getElementById("scan-status");
    const field = document.getElementById("catalog-barcode");
    let controls = null;
    let active = false;
    let generation = 0;
    let timeout = null;
    function closeCamera() {
        active = false;
        generation += 1;
        clearTimeout(timeout);
        if (controls) controls.stop();
        controls = null;
        if (video.srcObject) video.srcObject.getTracks().forEach(track => track.stop());
        video.srcObject = null;
        panel.hidden = true;
        start.disabled = false;
    }
    stop.addEventListener("click", () => { closeCamera(); status.textContent = "Camera stopped. You can enter the barcode numbers instead."; start.focus(); });
    window.addEventListener("pagehide", closeCamera);
    document.addEventListener("visibilitychange", () => { if (document.hidden) closeCamera(); });
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.ZXingBrowser) {
        status.textContent = "Camera scanning is unavailable in this browser. Enter the barcode numbers above.";
        return;
    }
    start.hidden = false;
    start.addEventListener("click", async () => {
        closeCamera();
        active = true;
        const run = generation;
        start.disabled = true;
        panel.hidden = false;
        status.textContent = "Allow camera access, then hold the barcode steady in good light.";
        const reader = new ZXingBrowser.BrowserMultiFormatOneDReader();
        try {
            // Acquire first so cancellation while permission is pending also releases tracks.
            const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } });
            if (!active || run !== generation) { stream.getTracks().forEach(track => track.stop()); return; }
            video.srcObject = stream;
            const pending = await reader.decodeFromStream(stream, video, (result, error, scanControls) => {
                if (!active || run !== generation || !result) return;
                const code = result.getText();
                if (!/^(?:\d{8}|\d{12}|\d{13}|\d{14})$/.test(code)) return;
                scanControls.stop();
                field.value = code;
                closeCamera();
                status.textContent = "Barcode found. Looking up the product…";
                document.getElementById("barcode-form").requestSubmit();
            });
            if (!active || run !== generation) { pending.stop(); return; }
            controls = pending;
            timeout = setTimeout(() => { closeCamera(); status.textContent = "No barcode found yet. Try again with better lighting, or enter its numbers."; }, 60000);
        } catch (error) {
            if (run !== generation) return;
            closeCamera();
            status.textContent = error.name === "NotAllowedError" ? "Camera permission was denied. Allow camera access in browser settings or enter the barcode." : "Unable to start the camera. Close other camera apps or enter the barcode numbers.";
        }
    });
})();
