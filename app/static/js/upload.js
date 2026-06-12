/* ------------------------------------------------------------------ *
 * upload.js — In-app book upload (picker + drag-and-drop)
 *
 * Uploads ebook files straight into the library via POST /upload, which
 * ingests them with the scanner's own extract+upsert path — so the user
 * never has to run "Find new books" after dropping a file. Newly added
 * rows come back wearing the "Nytillagt" badge after the reload.
 *
 * Drag-and-drop is wired at the window level, so a file dropped anywhere
 * on the page works in every view (Tabell / Hyllvy / Serie) without each
 * view needing its own drop target.
 *
 * Files upload one request at a time: that gives natural per-file
 * progress and means one bad file can't fail the whole batch.
 *
 * Reads i18n strings from window.__colophonConfig.i18n.
 *
 * Exposes globals consumed by the template (onclick handlers):
 *   openUploadPicker, handleUploadFiles, closeUploadPanel
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    var SUPPORTED = ['.epub', '.mobi', '.azw3', '.kepub', '.pdf', '.cbz', '.cbr'];

    var _uploading = false;
    var _dragDepth = 0;

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _ext(name) {
        var m = /\.[^.]+$/.exec(name || '');
        return m ? m[0].toLowerCase() : '';
    }

    function _supported(name) {
        return SUPPORTED.indexOf(_ext(name)) !== -1;
    }

    /* -------------------- Picker -------------------- */

    function openUploadPicker() {
        var input = document.getElementById('uploadInput');
        if (input) input.click();
        // Close the mobile sidebar drawer if it was open.
        if (typeof closeSidebar === 'function') closeSidebar();
    }
    window.openUploadPicker = openUploadPicker;

    /* -------------------- Progress panel -------------------- */

    function _panel() { return document.getElementById('uploadPanel'); }

    function closeUploadPanel() {
        var p = _panel();
        if (p) p.style.display = 'none';
        var list = document.getElementById('uploadPanelList');
        if (list) list.innerHTML = '';
        var sub = document.getElementById('uploadPanelAuthors');
        if (sub) { sub.textContent = ''; sub.style.display = 'none'; }
    }
    window.closeUploadPanel = closeUploadPanel;

    function _showPanel() {
        var p = _panel();
        if (p) p.style.display = 'block';
        var title = document.getElementById('uploadPanelTitle');
        if (title) title.textContent = _i18n.uploadUploading || 'Uploading…';
        var list = document.getElementById('uploadPanelList');
        if (list) list.innerHTML = '';
        var sub = document.getElementById('uploadPanelAuthors');
        if (sub) { sub.textContent = ''; sub.style.display = 'none'; }
    }

    function _addRow(name) {
        var list = document.getElementById('uploadPanelList');
        if (!list) return null;
        var row = document.createElement('div');
        row.className = 'upload-item upload-item-pending';
        row.innerHTML =
            '<span class="upload-item-name">' + _esc(name) + '</span>' +
            '<span class="upload-item-status"><i class="ti ti-loader-2 upload-spin"></i> ' +
                _esc(_i18n.uploadItemUploading || 'Uploading…') + '</span>';
        list.appendChild(row);
        return row;
    }

    function _statusText(status, reason) {
        if (status === 'added')   return _i18n.uploadItemAdded   || 'Added';
        if (status === 'updated') return _i18n.uploadItemUpdated || 'Updated';
        if (status === 'skipped') return _i18n.uploadItemSkipped || 'Already in library';
        if (reason === 'unsupported') return _i18n.uploadItemUnsupported || 'Unsupported format';
        return _i18n.uploadItemError || 'Failed';
    }

    function _setRow(row, status, reason) {
        if (!row) return;
        var ok   = (status === 'added' || status === 'updated');
        var warn = (status === 'skipped');
        row.className = 'upload-item ' +
            (ok ? 'upload-item-ok' : warn ? 'upload-item-warn' : 'upload-item-error');
        var icon = ok ? 'ti-check' : warn ? 'ti-info-circle' : 'ti-alert-triangle';
        var st = row.querySelector('.upload-item-status');
        if (st) st.innerHTML = '<i class="ti ' + icon + '"></i> ' + _esc(_statusText(status, reason));
    }

    /* -------------------- Upload driver -------------------- */

    function _uploadOne(file) {
        var fd = new FormData();
        fd.append('files', file, file.name);
        return fetch('/upload', { method: 'POST', body: fd })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var res = (data && data.results && data.results[0]) || null;
                if (res) {
                    res.authors = (data && data.authors) || {};
                    return res;
                }
                return { status: 'error', reason: (data && data.error) || 'error' };
            })
            .catch(function (err) {
                return { status: 'error', reason: String(err) };
            });
    }

    function handleUploadFiles(fileList) {
        if (_uploading) return;
        var files = Array.prototype.slice.call(fileList || []);
        var valid = files.filter(function (f) { return _supported(f.name); });

        if (!valid.length) {
            _showPanel();
            var title = document.getElementById('uploadPanelTitle');
            if (title) title.textContent = _i18n.uploadNothingValid || 'No supported files were selected.';
            return;
        }

        _uploading = true;
        _showPanel();

        var rows = valid.map(function (f) { return _addRow(f.name); });
        var counts = { added: 0, updated: 0, skipped: 0, errors: 0 };
        var authorCounts = { linked: 0, new: 0, review: 0, missing: 0 };

        // Sequential chain — one request at a time.
        var chain = Promise.resolve();
        valid.forEach(function (file, i) {
            chain = chain.then(function () {
                return _uploadOne(file).then(function (res) {
                    _setRow(rows[i], res.status, res.reason);
                    if (res.status === 'added') counts.added++;
                    else if (res.status === 'updated') counts.updated++;
                    else if (res.status === 'skipped') counts.skipped++;
                    else counts.errors++;
                    var a = res.authors || {};
                    Object.keys(authorCounts).forEach(function (k) {
                        authorCounts[k] += a[k] || 0;
                    });
                });
            });
        });

        chain.then(function () {
            _uploading = false;
            var title = document.getElementById('uploadPanelTitle');
            var summary = (_i18n.uploadDoneSummary || '{added} added, {skipped} skipped, {errors} failed')
                .replace('{added}', counts.added + counts.updated)
                .replace('{skipped}', counts.skipped)
                .replace('{errors}', counts.errors);
            if (title) title.textContent = summary;

            // Author resolution summary — "known" = auto-linked; "to
            // review" = fuzzy matches + unconfirmed new entries (the
            // queue the "Authors to review" filter collects).
            var sub = document.getElementById('uploadPanelAuthors');
            if (sub) {
                var resolved = authorCounts.linked + authorCounts.new
                    + authorCounts.review + authorCounts.missing;
                if (resolved > 0) {
                    sub.textContent = (_i18n.uploadAuthorsSummary
                        || 'Authors: {known} known · {review} to review · {missing} missing')
                        .replace('{known}', authorCounts.linked)
                        .replace('{review}', authorCounts.review + authorCounts.new)
                        .replace('{missing}', authorCounts.missing);
                    sub.style.display = 'block';
                } else {
                    sub.style.display = 'none';
                }
            }

            // Reload so the new rows appear correctly grouped/sorted and the
            // "Nytillagt" badge shows — but only if something actually landed.
            if (counts.added > 0 || counts.updated > 0) {
                setTimeout(function () {
                    if (title) title.textContent = _i18n.uploadRefreshing || 'Refreshing…';
                    location.reload();
                }, 1400);
            }
        });
    }
    window.handleUploadFiles = handleUploadFiles;

    /* -------------------- Drag-and-drop (window-level) -------------------- */

    var _overlay = document.getElementById('uploadDropOverlay');

    function _isFileDrag(e) {
        if (!e.dataTransfer) return false;
        var types = e.dataTransfer.types;
        if (!types) return false;
        for (var i = 0; i < types.length; i++) {
            if (types[i] === 'Files') return true;
        }
        return false;
    }

    function _showOverlay() { if (_overlay) _overlay.classList.add('active'); }
    function _hideOverlay() { _dragDepth = 0; if (_overlay) _overlay.classList.remove('active'); }

    window.addEventListener('dragenter', function (e) {
        if (!_isFileDrag(e) || _uploading) return;
        e.preventDefault();
        _dragDepth++;
        _showOverlay();
    });

    window.addEventListener('dragover', function (e) {
        if (!_isFileDrag(e) || _uploading) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    });

    window.addEventListener('dragleave', function (e) {
        if (!_isFileDrag(e)) return;
        _dragDepth--;
        if (_dragDepth <= 0) _hideOverlay();
    });

    window.addEventListener('drop', function (e) {
        if (!_isFileDrag(e)) return;
        e.preventDefault();
        _hideOverlay();
        if (_uploading) return;
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
            handleUploadFiles(e.dataTransfer.files);
        }
    });

    /* The non-library-page sidebar link points at <library>#upload; honour
       it by opening the picker once the library view has loaded. */
    if (window.location.hash === '#upload') {
        window.addEventListener('load', function () { openUploadPicker(); });
    }
})(window, document);
