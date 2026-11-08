document.querySelectorAll('[data-copy-health]').forEach(button => {
    button.addEventListener('click', async () => {
        const input = document.getElementById(button.dataset.copyHealth);
        const status = document.getElementById(input.id === 'health-endpoint' ? 'health-endpoint-status' : 'health-copy-status');
        try {
            await navigator.clipboard.writeText(input.value);
            if (status) status.textContent = input.id === 'health-endpoint' ? 'URL copied. Paste it into your shortcut.' : 'Connection key copied. Paste it into the Authorization header value in your shortcut.';
            else button.textContent = 'Copied';
        } catch {
            input.focus();
            input.select();
            if (status) status.textContent = 'Copy the selected value using your browser copy command.';
        }
    });
});
const show = document.getElementById('health-show-token');
if (show) show.addEventListener('click', () => {
    const input = document.getElementById('health-authorization');
    input.type = input.type === 'password' ? 'text' : 'password';
    show.textContent = input.type === 'password' ? 'Show connection key' : 'Hide connection key';
});
