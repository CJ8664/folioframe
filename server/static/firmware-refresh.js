(function () {
  'use strict';

  var button = document.getElementById('firmware-refresh');
  var status = document.getElementById('firmware-refresh-status');
  if (!button || !status) return;

  function show(message, state) {
    status.textContent = message;
    status.className = 'fine' + (state ? ' ' + state : '');
  }

  button.addEventListener('click', async function () {
    button.disabled = true;
    show('Checking GitHub Releases for firmware...', '');
    try {
      var response = await fetch('/api/firmware/refresh', {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
      });
      var result = await response.json();
      if (!response.ok || !result.ok) {
        throw new Error(result.error || 'Firmware check failed.');
      }

      if (result.updated ||
          (result.status === 'cached' &&
           result.previous_status === 'updated')) {
        show('Firmware v' + result.version + ' is ready. Reloading...', '');
        window.setTimeout(function () { window.location.reload(); }, 1000);
        return;
      }
      if (result.status === 'in_progress') {
        show('A firmware check is already running. Try again shortly.', '');
      } else if (result.status === 'local_ahead') {
        show('This server already has a newer firmware build.', '');
      } else if (result.version) {
        show('Firmware is up to date (v' + result.version + ').', '');
      } else {
        show('Firmware check completed.', '');
      }
    } catch (error) {
      show(error && error.message
        ? error.message
        : 'Could not check for firmware updates.', 'err');
    } finally {
      button.disabled = false;
    }
  });
})();
