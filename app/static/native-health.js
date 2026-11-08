/* Explicit, user-triggered native Health ZIP upload. No health data in localStorage. */
(() => {
    const form = document.getElementById('native-health-form');
    if (!form) return;
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        const file = document.getElementById('native-health-file').files[0];
        const status = document.getElementById('native-health-status');
        const button = document.getElementById('native-health-submit');
        if (!file || file.size > 100 * 1024 * 1024) {
            status.textContent = 'Choose an Apple Health export.zip smaller than 100 MB.';
            return;
        }
        button.disabled = true;
        status.textContent = 'Uploading and importing your history. Keep this page open; a large history can take several minutes.';
        try {
            const response = await fetch('/integrations/apple-health/native-import', {
                method: 'POST', credentials: 'same-origin', redirect: 'error',
                headers: {'Content-Type': 'application/zip', 'Accept': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content},
                body: file
            });
            const result = await response.json();
            if (!response.ok) {
                const detail = Array.isArray(result.detail) ? result.detail.join(' ') : result.detail;
                throw new Error(typeof detail === 'string' ? detail : 'The import could not finish. Try again while signed in.');
            }
            status.textContent = `Import finished: ${result.sleep} sleep records, ${result.metric} activity/heart samples, and ${result.workout} workouts added; ${result.updated} updated and ${result.skipped} already saved. Open View your sleep above or Check upload status.`;
            document.getElementById('native-health-file').value = '';
        } catch (error) {
            status.textContent = error instanceof TypeError ? 'The connection was interrupted. Reconnect to Wi-Fi and try the file again; repeats are safe.' : error.message;
        } finally {
            button.disabled = false;
        }
    });
})();
