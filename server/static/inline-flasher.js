/* FolioFrame inline flasher — custom UI on esptool-js (no modal dialog).
 *
 * ES module: imports the vendored esptool-js bundle directly.
 * Loaded via <script type="module"> on the /flash page.
 *
 * Flow: Connect -> fetch manifest -> download parts -> ESPLoader.main()
 *       -> writeFlash with progress -> hard_reset -> done.
 */
import * as esptooljs from './esptool-js-bundle.js';
(function () {
  'use strict';

  var goBtn = document.getElementById('flash-go');
  var verSel = document.getElementById('fwver');
  var statusEl = document.getElementById('flash-status');
  var progressWrap = document.getElementById('flash-progress-wrap');
  var progressBar = document.getElementById('flash-progress-bar');
  var progressLabel = document.getElementById('flash-progress-label');
  var logEl = document.getElementById('flash-log');

  if (!goBtn) return; // not on the flash page

  function manifestUrl() {
    var v = verSel ? verSel.value : '';
    return '/flash/manifest.json' + (v ? '?version=' + encodeURIComponent(v) : '');
  }

  function setStatus(msg, cls) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = 'flash-status ' + (cls || '');
  }

  function log(msg) {
    if (!logEl) return;
    var line = document.createElement('div');
    line.className = 'flash-log-line';
    line.textContent = msg;
    logEl.appendChild(line);
    logEl.scrollTop = logEl.scrollHeight;
  }

  function setProgress(pct, label) {
    if (progressWrap) progressWrap.hidden = false;
    if (progressBar) progressBar.style.width = Math.min(100, Math.max(0, pct)) + '%';
    if (progressLabel) progressLabel.textContent = label || '';
  }

  function resetUI() {
    if (logEl) logEl.innerHTML = '';
    setProgress(0, '');
    if (progressWrap) progressWrap.hidden = true;
    goBtn.disabled = false;
    goBtn.textContent = 'Connect & flash';
  }

  // Terminal interface for ESPLoader — routes to our inline log console.
  function makeTerminal() {
    return {
      clean: function () { if (logEl) logEl.innerHTML = ''; },
      writeLine: function (data) { log(data); },
      write: function (data) { log(data); }
    };
  }

  async function downloadPart(url) {
    log('Downloading ' + url + ' ...');
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('Failed to download ' + url + ' (HTTP ' + resp.status + ')');
    var buf = await resp.arrayBuffer();
    log('  -> ' + (buf.byteLength / 1024).toFixed(1) + ' KB');
    return new Uint8Array(buf);
  }

  goBtn.addEventListener('click', async function () {
    // Preconditions
    if (!('serial' in navigator)) {
      setStatus('Web Serial is not available. Use Chrome, Edge, or Opera on a computer (HTTPS required).', 'err');
      return;
    }
    if (!esptooljs || !esptooljs.ESPLoader || !esptooljs.Transport) {
      setStatus('Flasher engine failed to load. Reload the page.', 'err');
      return;
    }

    goBtn.disabled = true;
    goBtn.textContent = 'Flashing...';
    if (logEl) logEl.innerHTML = '';
    setStatus('Requesting serial port...', '');
    setProgress(0, 'Connecting');

    var port = null;
    var transport = null;

    try {
      // 1. Port selection
      try {
        port = await navigator.serial.requestPort();
      } catch (e) {
        setStatus('Port selection cancelled.', 'muted');
        resetUI();
        return;
      }

      // 2. Fetch manifest
      setStatus('Fetching firmware manifest...', '');
      log('Fetching manifest: ' + manifestUrl());
      var mResp = await fetch(manifestUrl());
      if (!mResp.ok) throw new Error('Manifest fetch failed (HTTP ' + mResp.status + ')');
      var manifest = await mResp.json();
      var build = (manifest.builds && manifest.builds[0]) || null;
      if (!build || !build.parts || !build.parts.length) {
        throw new Error('Manifest has no firmware parts');
      }
      log('Firmware: ' + manifest.name + ' v' + manifest.version + ' (' + build.parts.length + ' parts)');

      // 3. Download firmware parts
      setStatus('Downloading firmware...', '');
      var fileArray = [];
      for (var i = 0; i < build.parts.length; i++) {
        var part = build.parts[i];
        var data = await downloadPart(part.path);
        fileArray.push({ data: data, address: part.offset });
      }

      // 4. Open port and create loader
      setStatus('Connecting to device...', '');
      log('Opening serial port...');
      transport = new esptooljs.Transport(port, true);
      var loader = new esptooljs.ESPLoader({
        transport: transport,
        baudrate: 115200,
        terminal: makeTerminal(),
        debugLogging: false
      });

      log('Connecting to ESP32-S3 (resetting into bootloader)...');
      var chipName = await loader.main();
      log('Connected: ' + chipName);
      // Safety: verify this is an ESP32-S3 before flashing
      if (chipName && chipName.toUpperCase().indexOf('ESP32-S3') === -1 &&
          chipName.toUpperCase().indexOf('ESP32S3') === -1) {
        throw new Error('Unexpected chip: ' + chipName + '. Expected ESP32-S3. Aborting for safety.');
      }
      setStatus('Connected to ' + chipName + ' — flashing...', '');

      // 5. Flash with progress
      var totalBytes = fileArray.reduce(function (acc, f) { return acc + f.data.length; }, 0);
      await loader.writeFlash({
        fileArray: fileArray,
        flashMode: 'dio',
        flashFreq: '40m',
        flashSize: '8MB',
        eraseAll: false,
        compress: true,
        reportProgress: function (fileIndex, written, total) {
          // written/total is per-file; compute overall progress
          var fileBase = 0;
          for (var j = 0; j < fileIndex; j++) fileBase += fileArray[j].data.length;
          var overall = fileBase + written;
          var pct = (overall / totalBytes) * 100;
          setProgress(pct, 'Flashing part ' + (fileIndex + 1) + '/' + fileArray.length +
            ' — ' + pct.toFixed(1) + '%');
        }
      });

      // 6. Reset device
      setProgress(100, 'Done — resetting device');
      log('Flash complete. Resetting device...');
      await loader.after('hard_reset');

      setStatus('Firmware v' + manifest.version + ' flashed successfully! The frame will reboot.', 'ok');
      log('Done. You can now close this page or flash another device.');
    } catch (e) {
      var msg = (e && e.message) ? e.message : String(e);
      setStatus('Flash failed: ' + msg, 'err');
      log('ERROR: ' + msg);
    } finally {
      if (transport) {
        try { await transport.disconnect(); } catch (e) { /* ignore */ }
      } else if (port) {
        try { await port.close(); } catch (e) { /* ignore */ }
      }
      goBtn.disabled = false;
      goBtn.textContent = 'Connect & flash';
    }
  });

  // Version selector: just updates the manifest URL for the next run.
  if (verSel) {
    verSel.addEventListener('change', function () {
      log('Selected firmware v' + verSel.value + ' (applies to next flash)');
    });
  }

  // --- Serial monitor: live logs at 115200 baud, no flashing ---
  var serialBtn = document.getElementById('serial-go');
  var serialPort = null;
  var serialReading = false;

  function setSerialBtn(running) {
    if (!serialBtn) return;
    serialBtn.disabled = false;
    serialBtn.textContent = running ? 'Stop logs' : 'View serial logs';
  }

  async function stopSerial() {
    serialReading = false;
    if (serialPort) {
      try { await serialPort.close(); } catch (e) { /* ignore */ }
      serialPort = null;
    }
    setSerialBtn(false);
    setStatus('Serial monitor stopped.', 'muted');
  }

  if (serialBtn) {
    serialBtn.addEventListener('click', async function () {
      if (serialReading) { await stopSerial(); return; }
      if (!('serial' in navigator)) {
        setStatus('Web Serial is not available. Use Chrome, Edge, or Opera on a computer (HTTPS required).', 'err');
        return;
      }
      var port = null;
      try {
        port = await navigator.serial.requestPort();
      } catch (e) {
        return; // user cancelled
      }
      try {
        await port.open({ baudRate: 115200 });
      } catch (e) {
        setStatus('Could not open port: ' + (e.message || e), 'err');
        return;
      }
      serialPort = port;
      serialReading = true;
      setSerialBtn(true);
      if (logEl) logEl.innerHTML = '';
      setStatus('Serial monitor running at 115200 baud — reset the frame to see boot logs.', 'ok');
      log('--- serial monitor started (115200 baud) ---');

      var decoder = new TextDecoder();
      var buf = '';
      try {
        while (serialReading && port.readable) {
          var reader = port.readable.getReader();
          try {
            while (true) {
              var result = await reader.read();
              if (result.done) break;
              buf += decoder.decode(result.value, { stream: true });
              var lines = buf.split('\n');
              buf = lines.pop(); // keep partial line
              for (var i = 0; i < lines.length; i++) {
                var line = lines[i].replace(/\r$/, '');
                if (line.length) log(line);
              }
            }
          } catch (e) {
            // read error — port may have been closed
          } finally {
            reader.releaseLock();
          }
          if (!serialReading) break;
          await new Promise(function (r) { setTimeout(r, 200); });
        }
      } finally {
        if (buf.length) log(buf.replace(/\r$/, ''));
        log('--- serial monitor stopped ---');
        await stopSerial();
      }
    });
  }
})();
