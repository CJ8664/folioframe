/* FolioFrame photo picker.
 *
 * Ported from the spectraframe-ux-photo-picker UX mockup: thumbnail grid,
 * click-to-preview (original + simulated six-color e-ink), and the 3:4
 * editor (pan, zoom, 90-degree rotation, brightness/contrast, reset,
 * apply). The e-ink simulation (calibrated palette, CIELAB matching,
 * serpentine Floyd-Steinberg dithering) and the no-band crop math are
 * verbatim from the mockup.
 *
 * Production differences from the mockup:
 * - Photos come from /api/photos (the user's Google Photos cache), not
 *   bundled samples. No select/deselect: a tile click opens the preview
 *   directly (there is no server-side "selected set" to keep in sync).
 * - Apply POSTs the rendered 1200x1600 JPEG to /api/photos/<id>/edit,
 *   which replaces the cached photo so the frame picks it up.
 * - Theme is handled by the shared folioframe.css + ffThemeToggle().
 */
(function () {
  'use strict';

  var photoGrid = document.getElementById('photoGrid');
  var photoCount = document.getElementById('photoCount');
  var photoEmpty = document.getElementById('photoEmpty');
  var previewShell = document.getElementById('previewShell');
  var previewClose = document.getElementById('previewClose');
  var previewEdit = document.getElementById('previewEdit');
  var previewOriginal = document.getElementById('previewOriginal');
  var previewName = document.getElementById('previewName');
  var einkCanvas = document.getElementById('einkCanvas');
  var renderState = document.getElementById('renderState');
  var editorShell = document.getElementById('editorShell');
  var editorClose = document.getElementById('editorClose');
  var editorCancel = document.getElementById('editorCancel');
  var editorApply = document.getElementById('editorApply');
  var cropStage = document.getElementById('cropStage');
  var editorCanvas = document.getElementById('editorCanvas');
  var zoomRange = document.getElementById('zoomRange');
  var brightnessRange = document.getElementById('brightnessRange');
  var contrastRange = document.getElementById('contrastRange');
  var zoomValue = document.getElementById('zoomValue');
  var brightnessValue = document.getElementById('brightnessValue');
  var contrastValue = document.getElementById('contrastValue');
  var rotateButton = document.getElementById('rotateButton');
  var resetAdjustments = document.getElementById('resetAdjustments');
  var rotationValue = document.getElementById('rotationValue');
  var editorName = document.getElementById('editorName');
  var editorStatus = document.getElementById('editorStatus');

  var CSRF = '';
  var photos = {};            // id -> {id, name}
  var lastFocused = null;
  var renderToken = 0;
  var activePreviewId = null;
  var editId = null;
  var editImage = null;
  var editState = { zoom: 1, rotation: 0, brightness: 100, contrast: 100, panX: 0, panY: 0 };
  var dragState = null;
  var pinchState = null;

  /* Calibrated six-color Spectra 6 palette (from the UX mockup). */
  var palette = [
    { rgb: [31, 34, 38] },
    { rgb: [185, 199, 201] },
    { rgb: [35, 63, 142] },
    { rgb: [53, 86, 58] },
    { rgb: [98, 32, 30] },
    { rgb: [193, 187, 30] }
  ];

  function thumbUrl(id) { return '/api/photos/' + encodeURIComponent(id) + '/thumb'; }
  function fullUrl(id) { return '/api/photos/' + encodeURIComponent(id) + '/full'; }

  /* Hint tooltips are handled by the shared HINT_JS snippet. */

  /* ---------- photo list ---------- */
  function prettyName(id) {
    return id.replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ');
  }

  async function loadPhotos() {
    var res;
    try {
      res = await fetch('/api/photos');
    } catch (e) {
      photoEmpty.hidden = false;
      photoEmpty.textContent = 'Could not reach the server. Please reload.';
      return;
    }
    var j = await res.json().catch(function () { return { ok: false }; });
    if (!j.ok) {
      photoEmpty.hidden = false;
      photoEmpty.textContent = 'Could not load your photos. Please reload.';
      return;
    }
    photoGrid.innerHTML = '';
    photos = {};
    (j.photos || []).forEach(function (p) {
      photos[p.id] = { id: p.id, name: p.name || prettyName(p.id) };
      var tile = document.createElement('button');
      tile.className = 'photo-tile';
      tile.type = 'button';
      tile.dataset.photoId = p.id;
      tile.setAttribute('aria-label', 'Preview ' + photos[p.id].name + ' on e-ink');
      var img = document.createElement('img');
      img.loading = 'lazy';
      img.src = thumbUrl(p.id);
      img.alt = photos[p.id].name;
      var label = document.createElement('span');
      label.className = 'photo-name';
      label.textContent = photos[p.id].name;
      tile.appendChild(img);
      tile.appendChild(label);
      photoGrid.appendChild(tile);
    });
    var n = (j.photos || []).length;
    photoCount.textContent = n + (n === 1 ? ' photo' : ' photos');
    if (!n) {
      photoEmpty.hidden = false;
      photoEmpty.innerHTML = 'No photos here yet. Pick some in <a href="/">Google Photos</a> ' +
        'on the console, then come back — they will show up ready to preview and edit.';
    }
  }

  photoGrid.addEventListener('click', function (event) {
    var tile = event.target.closest('[data-photo-id]');
    if (!tile) return;
    openPreview(tile.dataset.photoId, tile);
  });

  /* ---------- e-ink simulation (verbatim from the UX mockup) ---------- */
  function srgbToLinear(value) {
    value /= 255;
    return value <= .04045 ? value / 12.92 : Math.pow((value + .055) / 1.055, 2.4);
  }

  function rgbToLab(rgb) {
    var r = srgbToLinear(rgb[0]);
    var g = srgbToLinear(rgb[1]);
    var b = srgbToLinear(rgb[2]);
    var x = (r * .4124564 + g * .3575761 + b * .1804375) / .95047;
    var y = (r * .2126729 + g * .7151522 + b * .0721750);
    var z = (r * .0193339 + g * .1191920 + b * .9503041) / 1.08883;
    function pivot(n) { return n > .008856 ? Math.cbrt(n) : (7.787 * n) + (16 / 116); }
    x = pivot(x); y = pivot(y); z = pivot(z);
    return [(116 * y) - 16, 500 * (x - y), 200 * (y - z)];
  }

  palette.forEach(function (color) { color.lab = rgbToLab(color.rgb); });

  function tone(value) {
    var normalized = Math.max(0, Math.min(1, value / 255));
    var smooth = normalized * normalized * (3 - 2 * normalized);
    return 255 * ((normalized * .72) + (smooth * .28));
  }

  function toneMap(r, g, b) {
    var luminance = (.2126 * r) + (.7152 * g) + (.0722 * b);
    var saturation = 1.08;
    return [
      tone(luminance + ((r - luminance) * saturation)),
      tone(luminance + ((g - luminance) * saturation)),
      tone(luminance + ((b - luminance) * saturation))
    ];
  }

  function nearestPalette(r, g, b) {
    var lab = rgbToLab([r, g, b]);
    var best = palette[0];
    var bestDistance = Infinity;
    palette.forEach(function (color) {
      var dl = lab[0] - color.lab[0];
      var da = lab[1] - color.lab[1];
      var db = lab[2] - color.lab[2];
      var distance = (dl * dl) + (da * da) + (db * db);
      if (distance < bestDistance) { bestDistance = distance; best = color; }
    });
    return best.rgb;
  }

  function addError(buffer, width, height, x, y, error, weight) {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    var index = ((y * width) + x) * 3;
    buffer[index] += error[0] * weight;
    buffer[index + 1] += error[1] * weight;
    buffer[index + 2] += error[2] * weight;
  }

  function ditherImage(image, token) {
    if (token !== renderToken) return;
    var width = 360;
    var height = 480;
    var work = document.createElement('canvas');
    work.width = width;
    work.height = height;
    var context = work.getContext('2d', { willReadFrequently: true });
    context.fillStyle = '#B9C7C9';
    context.fillRect(0, 0, width, height);
    /* Preview the same full-bleed contract as the editor: center-crop with
       cover fit so an uncovered display edge can never appear. */
    var fit = Math.max(width / image.naturalWidth, height / image.naturalHeight) * 1.001;
    var drawWidth = Math.max(1, image.naturalWidth * fit);
    var drawHeight = Math.max(1, image.naturalHeight * fit);
    var offsetX = (width - drawWidth) / 2;
    var offsetY = (height - drawHeight) / 2;
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.drawImage(image, offsetX, offsetY, drawWidth, drawHeight);

    var imageData = context.getImageData(0, 0, width, height);
    var source = imageData.data;
    var buffer = new Float32Array(width * height * 3);
    var i;
    for (i = 0; i < width * height; i += 1) {
      var mapped = toneMap(source[i * 4], source[(i * 4) + 1], source[(i * 4) + 2]);
      buffer[i * 3] = mapped[0];
      buffer[(i * 3) + 1] = mapped[1];
      buffer[(i * 3) + 2] = mapped[2];
    }

    for (var y = 0; y < height; y += 1) {
      var leftToRight = y % 2 === 0;
      var start = leftToRight ? 0 : width - 1;
      var end = leftToRight ? width : -1;
      var step = leftToRight ? 1 : -1;
      for (var x = start; x !== end; x += step) {
        var pixelIndex = ((y * width) + x) * 3;
        var oldR = Math.max(0, Math.min(255, buffer[pixelIndex]));
        var oldG = Math.max(0, Math.min(255, buffer[pixelIndex + 1]));
        var oldB = Math.max(0, Math.min(255, buffer[pixelIndex + 2]));
        var next = nearestPalette(oldR, oldG, oldB);
        var outIndex = ((y * width) + x) * 4;
        source[outIndex] = next[0];
        source[outIndex + 1] = next[1];
        source[outIndex + 2] = next[2];
        source[outIndex + 3] = 255;
        var error = [oldR - next[0], oldG - next[1], oldB - next[2]];
        addError(buffer, width, height, x + step, y, error, 7 / 16);
        addError(buffer, width, height, x - step, y + 1, error, 3 / 16);
        addError(buffer, width, height, x, y + 1, error, 5 / 16);
        addError(buffer, width, height, x + step, y + 1, error, 1 / 16);
      }
    }
    if (token !== renderToken) return;
    einkCanvas.width = width;
    einkCanvas.height = height;
    einkCanvas.getContext('2d').putImageData(imageData, 0, 0);
    renderState.hidden = true;
  }

  /* ---------- preview panel ---------- */
  function openPreview(id, trigger) {
    var photo = photos[id];
    if (!photo) return;
    activePreviewId = id;
    lastFocused = trigger || document.activeElement;
    previewName.textContent = photo.name;
    previewOriginal.alt = photo.name;
    renderState.textContent = 'Rendering preview…';
    renderState.hidden = false;
    previewShell.classList.add('is-open');
    previewShell.setAttribute('aria-hidden', 'false');
    var token = ++renderToken;
    var image = new Image();
    image.onload = function () {
      previewOriginal.src = fullUrl(id);
      requestAnimationFrame(function () {
        window.setTimeout(function () { ditherImage(image, token); }, 20);
      });
    };
    image.onerror = function () {
      if (token === renderToken) renderState.textContent = 'Preview unavailable';
    };
    image.src = fullUrl(id);
    previewClose.focus();
  }

  function closePreview() {
    renderToken += 1;
    previewShell.classList.remove('is-open');
    previewShell.setAttribute('aria-hidden', 'true');
    renderState.hidden = false;
    renderState.textContent = 'Rendering preview…';
    if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  }

  previewClose.addEventListener('click', closePreview);
  previewShell.addEventListener('click', function (event) {
    if (event.target === previewShell) closePreview();
  });
  previewEdit.addEventListener('click', function () {
    if (activePreviewId) openEditor(activePreviewId, previewEdit);
  });

  /* ---------- editor (no-band crop math verbatim from the mockup) ---------- */
  function rotatedSize() {
    var quarterTurn = editState.rotation % 180 !== 0;
    return {
      width: quarterTurn ? editImage.naturalHeight : editImage.naturalWidth,
      height: quarterTurn ? editImage.naturalWidth : editImage.naturalHeight
    };
  }

  function coverScale() {
    var size = rotatedSize();
    /* A tiny overscan absorbs sub-pixel rasterization at exact crop edges.
       All pan limits use this same scale, so the safety margin is preserved. */
    return Math.max(1200 / size.width, 1600 / size.height) * 1.001;
  }

  function clampPan() {
    if (!editImage) return;
    var size = rotatedSize();
    var scale = coverScale() * editState.zoom;
    var maxX = Math.max(0, ((size.width * scale) - 1200) / 2);
    var maxY = Math.max(0, ((size.height * scale) - 1600) / 2);
    editState.panX = Math.max(-maxX, Math.min(maxX, editState.panX));
    editState.panY = Math.max(-maxY, Math.min(maxY, editState.panY));
  }

  function drawEdited(targetCanvas) {
    if (!editImage) return;
    var context = targetCanvas.getContext('2d');
    var sx = targetCanvas.width / 1200;
    var sy = targetCanvas.height / 1600;
    clampPan();
    context.save();
    context.clearRect(0, 0, targetCanvas.width, targetCanvas.height);
    context.scale(sx, sy);
    context.translate(600 + editState.panX, 800 + editState.panY);
    context.rotate(editState.rotation * Math.PI / 180);
    var scale = coverScale() * editState.zoom;
    context.scale(scale, scale);
    context.filter = 'brightness(' + editState.brightness + '%) contrast(' + editState.contrast + '%)';
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.drawImage(editImage, -editImage.naturalWidth / 2, -editImage.naturalHeight / 2);
    context.restore();
  }

  function renderEditor() {
    if (!editImage) return;
    zoomRange.value = String(Math.round(editState.zoom * 100));
    brightnessRange.value = String(editState.brightness);
    contrastRange.value = String(editState.contrast);
    zoomValue.textContent = Math.round(editState.zoom * 100) + '%';
    brightnessValue.textContent = editState.brightness + '%';
    contrastValue.textContent = editState.contrast + '%';
    rotationValue.textContent = editState.rotation + '°';
    drawEdited(editorCanvas);
  }

  function openEditor(id, trigger) {
    var photo = photos[id];
    if (!photo) return;
    editId = id;
    lastFocused = trigger || document.activeElement;
    editorName.textContent = photo.name + ' · 1200 × 1600';
    editorStatus.textContent = '';
    editorStatus.classList.remove('err');
    editState = { zoom: 1, rotation: 0, brightness: 100, contrast: 100, panX: 0, panY: 0 };
    editorShell.classList.add('is-open');
    editorShell.setAttribute('aria-hidden', 'false');
    var image = new Image();
    image.onload = function () { editImage = image; renderEditor(); };
    image.onerror = function () { editorName.textContent = 'This photo could not be opened.'; };
    image.src = fullUrl(id);
    editorClose.focus();
  }

  function closeEditor() {
    editorShell.classList.remove('is-open');
    editorShell.setAttribute('aria-hidden', 'true');
    editImage = null;
    editId = null;
    dragState = null;
    pinchState = null;
    cropStage.classList.remove('is-dragging');
    if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
  }

  function setStatus(msg, isErr) {
    editorStatus.textContent = msg;
    editorStatus.classList.toggle('err', !!isErr);
  }

  function applyEditor() {
    if (!editImage || !editId) return;
    setStatus('Saving…');
    editorApply.disabled = true;
    var output = document.createElement('canvas');
    output.width = 1200;
    output.height = 1600;
    drawEdited(output);
    output.toBlob(function (blob) {
      if (!blob) {
        editorApply.disabled = false;
        setStatus('Could not render the edited photo.', true);
        return;
      }
      fetch('/api/photos/' + encodeURIComponent(editId) + '/edit', {
        method: 'POST',
        headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'image/jpeg' },
        body: blob
      }).then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
        .then(function (j) {
          editorApply.disabled = false;
          if (!j.ok) {
            setStatus(j.error || 'Save failed. Please try again.', true);
            return;
          }
          /* Bust the tile + preview caches so the edited photo shows. */
          var bust = 't=' + Date.now();
          var tileImg = photoGrid.querySelector('[data-photo-id="' + CSS.escape(editId) + '"] img');
          if (tileImg) tileImg.src = thumbUrl(editId) + '?' + bust;
          previewOriginal.src = fullUrl(editId) + '?' + bust;
          var reopenId = (activePreviewId === editId && previewShell.classList.contains('is-open')) ? editId : null;
          closeEditor();
          if (reopenId) openPreview(reopenId, null);
        })
        .catch(function () {
          editorApply.disabled = false;
          setStatus('Could not reach the server.', true);
        });
    }, 'image/jpeg', .92);
  }

  function updateRange(input) {
    if (input === zoomRange) editState.zoom = Number(input.value) / 100;
    if (input === brightnessRange) editState.brightness = Number(input.value);
    if (input === contrastRange) editState.contrast = Number(input.value);
    renderEditor();
  }

  function pointDistance(a, b) {
    var dx = a.clientX - b.clientX;
    var dy = a.clientY - b.clientY;
    return Math.sqrt((dx * dx) + (dy * dy));
  }

  function startPan(clientX, clientY) {
    dragState = { x: clientX, y: clientY, panX: editState.panX, panY: editState.panY };
    cropStage.classList.add('is-dragging');
  }

  function movePan(clientX, clientY) {
    if (!dragState) return;
    var scaleX = 1200 / cropStage.clientWidth;
    var scaleY = 1600 / cropStage.clientHeight;
    editState.panX = dragState.panX + ((clientX - dragState.x) * scaleX);
    editState.panY = dragState.panY + ((clientY - dragState.y) * scaleY);
    renderEditor();
  }

  [zoomRange, brightnessRange, contrastRange].forEach(function (input) {
    input.addEventListener('input', function () { updateRange(input); });
  });
  resetAdjustments.addEventListener('click', function () {
    editState.brightness = 100;
    editState.contrast = 100;
    renderEditor();
  });
  rotateButton.addEventListener('click', function () {
    editState.rotation = (editState.rotation + 90) % 360;
    editState.panX = 0;
    editState.panY = 0;
    renderEditor();
  });
  cropStage.addEventListener('wheel', function (event) {
    if (!editorShell.classList.contains('is-open')) return;
    event.preventDefault();
    editState.zoom = Math.max(1, Math.min(3, editState.zoom * (event.deltaY < 0 ? 1.08 : .92)));
    renderEditor();
  }, { passive: false });
  editorCanvas.addEventListener('keydown', function (event) {
    var distance = event.shiftKey ? 96 : 24;
    if (event.key === 'ArrowLeft') editState.panX -= distance;
    else if (event.key === 'ArrowRight') editState.panX += distance;
    else if (event.key === 'ArrowUp') editState.panY -= distance;
    else if (event.key === 'ArrowDown') editState.panY += distance;
    else return;
    event.preventDefault();
    renderEditor();
  });
  cropStage.addEventListener('pointerdown', function (event) {
    if (event.pointerType === 'touch') return;
    cropStage.setPointerCapture(event.pointerId);
    startPan(event.clientX, event.clientY);
  });
  cropStage.addEventListener('pointermove', function (event) {
    if (event.pointerType !== 'touch') movePan(event.clientX, event.clientY);
  });
  function endPointer(event) {
    if (event.pointerType === 'touch') return;
    dragState = null;
    cropStage.classList.remove('is-dragging');
  }
  cropStage.addEventListener('pointerup', endPointer);
  cropStage.addEventListener('pointercancel', endPointer);
  cropStage.addEventListener('touchstart', function (event) {
    if (event.touches.length === 1) {
      pinchState = null;
      startPan(event.touches[0].clientX, event.touches[0].clientY);
    } else if (event.touches.length === 2) {
      dragState = null;
      pinchState = { distance: pointDistance(event.touches[0], event.touches[1]), zoom: editState.zoom };
    }
  }, { passive: false });
  cropStage.addEventListener('touchmove', function (event) {
    event.preventDefault();
    if (event.touches.length === 1 && dragState) {
      movePan(event.touches[0].clientX, event.touches[0].clientY);
    } else if (event.touches.length === 2 && pinchState) {
      editState.zoom = Math.max(1, Math.min(3, pinchState.zoom * pointDistance(event.touches[0], event.touches[1]) / pinchState.distance));
      renderEditor();
    }
  }, { passive: false });
  cropStage.addEventListener('touchend', function () {
    dragState = null;
    pinchState = null;
    cropStage.classList.remove('is-dragging');
  });
  editorClose.addEventListener('click', closeEditor);
  editorCancel.addEventListener('click', closeEditor);
  editorApply.addEventListener('click', applyEditor);
  editorShell.addEventListener('click', function (event) {
    if (event.target === editorShell) closeEditor();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && editorShell.classList.contains('is-open')) closeEditor();
    else if (event.key === 'Escape' && previewShell.classList.contains('is-open')) closePreview();
    else if (event.key === 'Escape') closeHints();
  });

  /* ---------- boot ---------- */
  async function init() {
    var s = await (await fetch('/api/session')).json().catch(function () { return { ok: false }; });
    if (!s.ok) { location.href = '/'; return; }
    CSRF = s.csrf || '';
    loadPhotos();
  }
  init();
}());
