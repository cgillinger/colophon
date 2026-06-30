/* ------------------------------------------------------------------ *
 * book-modal.js — Single-book detail modal
 *
 * Owns the #bookModal flow: opening a book, populating the form +
 * display mirror, reading-state controls (mark read / reset), metadata
 * fetch (synchronous via Calibre + SSE per-source), AI suggestions,
 * cover search/apply, save, delete-from-modal, and the modal feedback
 * helpers.
 *
 * Reads from window.* helpers exposed by batch.js:
 *   _esc, _cleanDate, _applyFieldLabel, _resultLabel, _resultTooltip
 *
 * Window-mirrored state (bulk-result-modal.js reads these):
 *   _modalItemId, _modalDirty, _modalAllCandidates
 *
 * Local state (IIFE-scoped):
 *   _modalSSESource, _coverUrlBase, _LANG_LABEL,
 *   _modalFieldInputMap, _modalI18n (hard-coded SE strings — pre-
 *   existing un-i18n'd block, preserved verbatim)
 *
 * Reads i18n from window.__colophonConfig.i18n (modal* keys added,
 * plus reuse of statusUnread/Reading/Finished and batchField* keys
 * for shared field labels).
 *
 * Exposes every top-level function on window for HTML onclick and
 * cross-module calls (see trailing publish block).
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    /* State (window-mirrored where bulk-result-modal also reads) */
    window._modalItemId       = null;
    window._modalDirty        = false;
    window._modalAllCandidates = [];
    var _modalSSESource = null;
    var _coverUrlBase = window.__colophonConfig.urls.coverItemBase;

    /* --- Fetch-depth chooser (Snabb / Normal / Djup → fast / more / deep) ---
     * Mirrors the standalone single-book page. The chosen mode is passed as
     * ?mode= on the bulk/stream fetch; the backend resolves the saved default
     * (METADATA_FETCH_MODE) when absent. */
    function _modalDefaultMode() {
        return (window.__colophonConfig && window.__colophonConfig.fetchMode) || 'more';
    }
    var _modalFetchModeSel = _modalDefaultMode();
    function _setModalFetchMode(mode) {
        var box = document.getElementById('modalFetchMode');
        if (!box) return;
        box.querySelectorAll('.fetch-mode-btn').forEach(function (b) {
            var on = b.getAttribute('data-mode') === mode;
            b.classList.toggle('active', on);
            if (on) _modalFetchModeSel = mode;
        });
    }
    function _initModalFetchMode() {
        var box = document.getElementById('modalFetchMode');
        if (!box) return;
        if (!box._wired) {
            box._wired = true;
            box.querySelectorAll('.fetch-mode-btn').forEach(function (b) {
                b.addEventListener('click', function () {
                    _setModalFetchMode(b.getAttribute('data-mode'));
                });
            });
        }
        _setModalFetchMode(_modalDefaultMode());
    }

    /* Live coverage banner: a running ✓/✗ over the essential fields plus the
     * sources that have reported, updated per tier as the pipeline escalates.
     * Driven by the pipeline's `stage: 'coverage'` SSE events. */
    function _renderModalCoverage(d) {
        var banner = document.getElementById('modalCoverageBanner');
        if (!banner) return;
        var labels = {
            title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor,
            description: _i18n.batchFieldSynopsis, cover: _i18n.batchFieldCover,
            series: _i18n.batchFieldSeries
        };
        var cov = d.coverage || {};
        var fields = d.essential_fields || Object.keys(cov);
        var chips = fields.map(function (f) {
            var ok = !!cov[f];
            return '<span class="' + (ok ? 'cov-ok' : 'cov-miss') + '">' +
                (ok ? '✓' : '✗') + ' ' + _esc(labels[f] || f) + '</span>';
        }).join(' ');
        var line = (_i18n.coverageTier || 'Tier') + ' ' +
            (d.tier_index || 1) + '/' + (d.tier_total || 1);
        if (d.sources && d.sources.length) {
            line += ' · ' + (_i18n.coverageSources || 'sources') + ': ' + d.sources.join(', ');
        }
        banner.innerHTML = '<div class="cov-line">' + line + '</div>' +
            '<div class="cov-fields">' + chips + '</div>';
        banner.style.display = 'block';
    }

    function openBookModal(itemId, forceDisplay) {
        window._modalItemId = itemId;
        window._modalDirty = false;
        window._modalAllCandidates = [];
        var modalEl = document.getElementById('bookModal');
        var box = modalEl.querySelector('.modal-box');
        // Shelf-view opens in display mode by default. Other views open in
        // edit. forceDisplay overrides that (used by the "Reading now" cards
        // so a "continue reading" click always lands in the contemplative
        // display modal — with the "Läs" button — regardless of the view).
        if (box) {
            if (forceDisplay || (typeof _viewMode !== 'undefined' && _viewMode === 'shelf')) {
                box.classList.add('display-mode');
            } else {
                box.classList.remove('display-mode');
            }
        }
        modalEl.style.display = 'flex';
        var mp = document.getElementById('modalProgress');
        if (mp) { mp.innerHTML = ''; mp.style.display = 'none'; }
        var covBanner = document.getElementById('modalCoverageBanner');
        if (covBanner) { covBanner.style.display = 'none'; covBanner.innerHTML = ''; }
        _initModalFetchMode();
        window._modalSourceDetails = {};
        var closeBtn = document.getElementById('modalCloseBtn');
        if (closeBtn) closeBtn.textContent = _mt('close');
        var saveBtn = document.getElementById('modalSaveBtn');
        if (saveBtn) saveBtn.textContent = _mt('save');
        setModalFeedback('info', _mt('loading'));

        fetch('/metadata/' + itemId + '/json', { cache: 'no-store' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                _populateModal(itemId, data);
                clearModalFeedback();
            })
            .catch(function() {
                setModalFeedback('error', 'Kunde inte ladda metadata.');
            });
    }

    function _populateModal(itemId, data) {
        var coverEl = document.getElementById('modalCover');
        if (data.cover_path) {
            coverEl.innerHTML = '<img src="' + _coverUrlBase + '/' + itemId + '?t=' + Date.now() + '" alt="" onerror="this.parentNode.innerHTML=\'📖\';">';
        } else {
            coverEl.innerHTML = '📖';
        }
        var size = data.size_bytes ? _fmtBytes(data.size_bytes) : '—';
        var ext = (data.extension || '').replace('.', '').toUpperCase();
        document.getElementById('modalFileInfo').innerHTML = (data.file_name || '—') + '<br>' + ext + ' · ' + size;

        // Gate the "Read in browser" button to formats foliate-js can open
        // (EPUB + MOBI/AZW3; keep in sync with READABLE_EXTENSIONS in
        // routes/reader.py). The CSS only shows it in display-mode, so a
        // `readable` class here is the second half of the gate.
        var readBtn = document.getElementById('modalReadBtn');
        var READABLE_EXTS = ['.epub', '.mobi', '.azw3', '.azw'];
        if (readBtn) readBtn.classList.toggle('readable', READABLE_EXTS.indexOf((data.extension || '').toLowerCase()) !== -1);

        document.getElementById('modalTitle').value         = data.title          || '';
        document.getElementById('modalAuthor').value        = data.author         || '';
        document.getElementById('modalSeries').value        = data.series         || '';
        document.getElementById('modalSeriesIndex').value   = data.series_index   || '';
        document.getElementById('modalIsbn').value          = data.isbn           || '';
        document.getElementById('modalPublisher').value     = data.publisher      || '';
        document.getElementById('modalLanguage').value      = data.language       || '';
        document.getElementById('modalGenres').value        = data.genres         || '';
        document.getElementById('modalPublishedDate').value = _cleanDate(data.published_date || '');
        document.getElementById('modalDescription').value   = data.description    || '';

        if (window.initAuthorCombobox) window.initAuthorCombobox(itemId, data);

        document.getElementById('modalAiBtn').style.display = data.ai_configured ? 'inline-flex' : 'none';
        var findSeriesBtn = document.getElementById('modalFindSeriesBtn');
        if (findSeriesBtn) findSeriesBtn.style.display = data.ai_configured ? '' : 'none';

        _populateDisplayMirror(data, size, ext);
        _populateReadingState(data);
        _populateRating(itemId, data.user_rating || 0);
    }

    /* Star rating: hovering highlights, clicking persists. Click on the
       × clears the rating. Rating reflects user judgment only — no
       external/community rating is fetched. */
    function _populateRating(itemId, rating) {
        var wrap = document.getElementById('modalRating');
        if (!wrap) return;
        wrap.dataset.itemId = itemId;
        wrap.dataset.value = rating || 0;
        _paintStars(wrap, rating || 0);
    }
    function _paintStars(wrap, value) {
        var stars = wrap.querySelectorAll('.rating-star');
        stars.forEach(function (s) {
            var v = parseInt(s.dataset.value, 10);
            s.classList.toggle('rating-active', v <= value && value > 0);
        });
    }
    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('#modalRating .rating-star, #modalRating .rating-clear');
        if (!btn) return;
        var wrap = btn.closest('#modalRating');
        var itemId = wrap.dataset.itemId;
        if (!itemId) return;
        var newVal = parseInt(btn.dataset.value, 10);
        wrap.dataset.value = newVal;
        _paintStars(wrap, newVal);
        fetch('/metadata/' + itemId + '/rate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rating: newVal })
        }).then(function (r) { return r.json(); })
          .then(function (data) {
              /* Mirror in the table row too if visible. */
              var row = document.querySelector('tr[data-item-id="' + itemId + '"]');
              if (row) row.dataset.userRating = data.rating || '';
              var cell = row && row.querySelector('.rating-cell');
              if (cell) cell.innerHTML = _renderTableStars(data.rating || 0);
          });
    });
    function _renderTableStars(value) {
        if (!value) return '';
        var s = '';
        for (var i = 1; i <= 5; i++) s += (i <= value ? '★' : '☆');
        return '<span class="table-rating">' + s + '</span>';
    }
    document.addEventListener('mouseover', function (e) {
        var btn = e.target.closest && e.target.closest('#modalRating .rating-star');
        if (!btn) return;
        var wrap = btn.closest('#modalRating');
        _paintStars(wrap, parseInt(btn.dataset.value, 10));
    });
    document.addEventListener('mouseleave', function (e) {
        var wrap = e.target.closest && e.target.closest('#modalRating .rating-stars');
        if (!wrap) return;
        var modalWrap = wrap.closest('#modalRating');
        _paintStars(modalWrap, parseInt(modalWrap.dataset.value, 10) || 0);
    }, true);

    /* Display-mode mirror: populate read-only typographic elements alongside
       the form fields. Same data source, just nicer presentation. */
    var _LANG_LABEL = {
        'en': 'English', 'sv': 'Svenska', 'no': 'Norsk', 'da': 'Dansk',
        'fi': 'Suomi', 'de': 'Deutsch', 'fr': 'Français', 'es': 'Español'
    };
    function _setDisplayHidden(el, hidden) {
        if (!el) return;
        el.style.display = hidden ? 'none' : '';
    }
    function _populateDisplayMirror(data, size, ext) {
        var titleEl = document.getElementById('modalTitleDisplay');
        if (titleEl) titleEl.textContent = data.title || '—';

        var editHeader = document.getElementById('modalEditHeaderTitle');
        if (editHeader) editHeader.textContent = data.title || '—';

        var authorEl = document.getElementById('modalAuthorDisplay');
        if (authorEl) {
            authorEl.innerHTML = '';
            if (data.author) {
                var bySpan = document.createElement('span');
                bySpan.className = 'by';
                bySpan.textContent = _i18n.modalBy;
                authorEl.appendChild(bySpan);
                // One link per author (names are comma-separated). Clicking
                // filters the library to that author's books.
                String(data.author).split(',').map(function (n) {
                    return n.trim();
                }).filter(Boolean).forEach(function (name, i) {
                    if (i > 0) authorEl.appendChild(document.createTextNode(', '));
                    var a = document.createElement('a');
                    a.className = 'author-link';
                    a.href = '#';
                    a.textContent = name;
                    a.addEventListener('click', function (e) {
                        e.preventDefault();
                        filterByAuthor(name);
                    });
                    authorEl.appendChild(a);
                });
            }
            _setDisplayHidden(authorEl, !data.author);
        }

        var seriesEl = document.getElementById('modalSeriesDisplay');
        if (seriesEl) {
            if (data.series) {
                var s = data.series;
                if (data.series_index) s += ' · ' + _i18n.modalBook + ' ' + data.series_index;
                seriesEl.textContent = s;
            }
            _setDisplayHidden(seriesEl, !data.series);
        }

        var metaEl = document.getElementById('modalMetaDisplay');
        if (metaEl) {
            var parts = [];
            if (data.publisher) parts.push(_esc(data.publisher));
            var year = (data.published_date || '').slice(0, 4);
            if (year && /^\d{4}$/.test(year)) parts.push(year);
            if (data.language && _LANG_LABEL[data.language]) {
                parts.push(_LANG_LABEL[data.language]);
            } else if (data.language) {
                parts.push(_esc(data.language));
            }
            var metaHtml = parts.join('<span class="sep">·</span>');
            if (data.isbn) {
                if (metaHtml) metaHtml += '<br>';
                metaHtml += '<span class="label">ISBN</span>' + _esc(data.isbn);
            }
            metaEl.innerHTML = metaHtml;
            _setDisplayHidden(metaEl, !metaHtml);
        }

        var genresEl = document.getElementById('modalGenresDisplay');
        if (genresEl) {
            genresEl.innerHTML = '';
            var hasGenres = false;
            if (data.genres) {
                var genres = String(data.genres).split(',').map(function(g) {
                    return g.trim();
                }).filter(function(g) { return g.length > 0; });
                genres.forEach(function(g) {
                    var chip = document.createElement('span');
                    chip.className = 'display-genre-chip';
                    chip.textContent = g;
                    genresEl.appendChild(chip);
                });
                hasGenres = genres.length > 0;
            }
            _setDisplayHidden(genresEl, !hasGenres);
        }

        var fileEl = document.getElementById('modalFileInfoDisplay');
        if (fileEl) {
            fileEl.textContent = (ext || '—') + ' · ' + (size || '—');
        }

        var descEl = document.getElementById('modalDescriptionDisplay');
        if (descEl) {
            if (data.description) {
                descEl.textContent = data.description;
                descEl.classList.remove('empty');
            } else {
                descEl.textContent = _i18n.modalNoSynopsis;
                descEl.classList.add('empty');
            }
        }
    }

    /* Rebuild the synthetic "data" object the display mirror expects, sourced
       from the form fields (which are authoritative after a save). */
    function _displayDataFromForm() {
        return {
            title:          document.getElementById('modalTitle').value,
            author:         document.getElementById('modalAuthor').value,
            series:         document.getElementById('modalSeries').value,
            series_index:   document.getElementById('modalSeriesIndex').value,
            isbn:           document.getElementById('modalIsbn').value,
            publisher:      document.getElementById('modalPublisher').value,
            language:       document.getElementById('modalLanguage').value,
            genres:         document.getElementById('modalGenres').value,
            published_date: document.getElementById('modalPublishedDate').value,
            description:    document.getElementById('modalDescription').value
        };
    }

    /* Toggle between display ("shelf reading view") and edit (form) modes. */
    function toggleModalMode() {
        var box = document.querySelector('#bookModal .modal-box');
        if (!box) return;
        var goingToDisplay = !box.classList.contains('display-mode');
        if (goingToDisplay) {
            // Sync display elements from current form values so any unsaved
            // edits made before toggling are also reflected.
            var fileInfo = document.getElementById('modalFileInfo');
            var parts = (fileInfo && fileInfo.innerText) ? fileInfo.innerText.split('\n') : ['', ''];
            var fileMeta = (parts[1] || '').split('·');
            var ext = (fileMeta[0] || '').trim();
            var size = (fileMeta[1] || '').trim();
            _populateDisplayMirror(_displayDataFromForm(), size, ext);
        }
        box.classList.toggle('display-mode');
        box.scrollTop = 0;
    }

    /* ---------------- Phase 3 — Reading state ---------------- */

    var _READ_STATUS_LABEL = {
        'ReadyToRead': _i18n.statusUnread,
        'Reading':     _i18n.statusReading,
        'Finished':    _i18n.statusFinished
    };

    function _fmtDate(iso) {
        if (!iso) return '—';
        try {
            var d = new Date(iso);
            if (isNaN(d.getTime())) return iso.slice(0, 10);
            return d.toLocaleDateString();
        } catch (e) {
            return iso.slice(0, 10);
        }
    }

    function _populateReadingState(data) {
        var box = document.getElementById('modalReadingState');
        if (!box) return;
        box.style.display = '';
        var status = data.read_status || 'ReadyToRead';
        box.classList.toggle('is-finished', status === 'Finished');

        var badge = document.getElementById('modalReadStatusBadge');
        badge.textContent = _READ_STATUS_LABEL[status] || status;
        badge.className = 'reading-state-badge s-' + status;

        var pct = data.read_progress;
        if (pct === null || pct === undefined || isNaN(pct)) {
            pct = (status === 'Finished') ? 100 : 0;
        }
        document.getElementById('modalReadFill').style.width = pct + '%';
        document.getElementById('modalReadPercent').textContent =
            (status === 'ReadyToRead') ? '—' : (Math.round(pct) + '%');

        var dates = [];
        if (data.read_started_at) {
            dates.push(_i18n.modalStarted + ': ' + _fmtDate(data.read_started_at));
        }
        if (data.read_finished_at) {
            dates.push(_i18n.statusFinished + ': ' + _fmtDate(data.read_finished_at));
        }
        if (data.times_started && data.times_started > 1) {
            dates.push(_i18n.modalTimesStarted + ': ' + data.times_started);
        }
        if (data.read_last_modified) {
            dates.push(_i18n.modalLastUpdate + ': ' + _fmtDate(data.read_last_modified));
        }
        document.getElementById('modalReadDates').textContent = dates.join('  ·  ');
    }

    function markReadManually() {
        if (!window._modalItemId) return;
        var btn = document.getElementById('modalMarkReadBtn');
        if (btn) btn.disabled = true;
        fetch('/metadata/' + window._modalItemId + '/mark-read', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(j) {
                if (j && j.ok) {
                    setModalFeedback('success', _i18n.modalMarkedFinished);
                    // Re-fetch so dates and progress reflect server state.
                    fetch('/metadata/' + window._modalItemId + '/json', { cache: 'no-store' })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            _populateReadingState(data);
                            _syncReadStateToRow(window._modalItemId, data);
                        });
                }
            })
            .catch(function() {
                setModalFeedback('error', _i18n.modalCouldNotUpdateRead);
            })
            .finally(function() { if (btn) btn.disabled = false; });
    }
    window.markReadManually = markReadManually;

    // Open the in-browser reader for the book currently in the modal. The
    // reader page handles progress sync back to the same reading-state the
    // Kobo uses, so reading here and on a Kobo stay in lock-step.
    function openReader() {
        if (!window._modalItemId) return;
        window.location.href = '/reader/' + window._modalItemId;
    }
    window.openReader = openReader;

    function resetReadingState() {
        if (!window._modalItemId) return;
        var btn = document.getElementById('modalResetReadBtn');
        if (btn) btn.disabled = true;
        fetch('/metadata/' + window._modalItemId + '/reset-read', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(j) {
                if (j && j.ok) {
                    setModalFeedback('success', _i18n.modalReadStateCleared);
                    fetch('/metadata/' + window._modalItemId + '/json', { cache: 'no-store' })
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            _populateReadingState(data);
                            _syncReadStateToRow(window._modalItemId, data);
                        });
                }
            })
            .catch(function() {
                setModalFeedback('error', _i18n.modalCouldNotUpdateRead);
            })
            .finally(function() { if (btn) btn.disabled = false; });
    }
    window.resetReadingState = resetReadingState;

    function _syncReadStateToRow(itemId, data) {
        var row = document.querySelector('#bookTableBody tr[data-item-id="' + itemId + '"]');
        if (!row) return;
        row.dataset.readStatus = data.read_status || 'ReadyToRead';
        row.dataset.readProgress = (data.read_progress === null || data.read_progress === undefined)
            ? '' : data.read_progress;
        if (typeof _viewMode !== 'undefined' && _viewMode === 'shelf'
            && typeof refreshShelfView === 'function') {
            refreshShelfView();
        }
    }

    function _getSelectedFields() {
        var checks = document.querySelectorAll('.modal-field-check:checked');
        return Array.from(checks).map(function(cb) { return cb.value; });
    }

    function _getModalSmartReplace() {
        return ['title', 'author', 'isbn', 'publisher', 'genres', 'published_date', 'description'];
    }

    function toggleModalFields(checked) {
        document.querySelectorAll('.modal-field-check').forEach(function(cb) {
            cb.checked = checked;
        });
    }

    function toggleAllFields(checked) {
        toggleModalFields(checked);
    }

    function _applyFetchedToModal(candidate, selectedFields) {
        if (selectedFields.indexOf('title') !== -1 && candidate.title)
            document.getElementById('modalTitle').value = candidate.title;
        if (selectedFields.indexOf('author') !== -1 && candidate.author)
            document.getElementById('modalAuthor').value = candidate.author;
        if (selectedFields.indexOf('series') !== -1 && candidate.series)
            document.getElementById('modalSeries').value = candidate.series;
        if (selectedFields.indexOf('series') !== -1 && candidate.series_index)
            document.getElementById('modalSeriesIndex').value = candidate.series_index;
        if (selectedFields.indexOf('isbn') !== -1 && candidate.isbn)
            document.getElementById('modalIsbn').value = candidate.isbn;
        if (selectedFields.indexOf('publisher') !== -1 && candidate.publisher)
            document.getElementById('modalPublisher').value = candidate.publisher;
        if (selectedFields.indexOf('language') !== -1 && candidate.language)
            document.getElementById('modalLanguage').value = candidate.language;
        if (selectedFields.indexOf('description') !== -1 && candidate.description)
            document.getElementById('modalDescription').value = candidate.description;
        if (selectedFields.indexOf('genres') !== -1 && candidate.genres) {
            var genreEl = document.getElementById('modalGenres');
            if (genreEl) genreEl.value = candidate.genres;
        }
        if (selectedFields.indexOf('published_date') !== -1 && candidate.published_date) {
            var pdEl = document.getElementById('modalPublishedDate');
            if (pdEl) pdEl.value = _cleanDate(candidate.published_date);
        }
    }

    // ============================================================
    // SHARED FUNCTIONS — used by BOTH the single-book modal and batch
    // Change with care — test both flows!
    // Affected: _renderModalSourceDetail, _applyFetchedToModal,
    //          saveMetadata, fetchAiMetadata, _populateModal,
    //          _cleanDate (lib/util, definierad i batch-sektionen)
    // ============================================================
    // Field list + labels for the per-source coverage breakdown. Defined
    // locally here (bulk-result-modal.js keeps its own IIFE-scoped copies);
    // the label map is built at call time so _i18n is guaranteed populated.
    var _bpAllFields = ['title', 'author', 'description', 'isbn', 'publisher', 'series', 'genres', 'published_date', 'cover'];

    function _renderModalSourceDetail(container, sourceDetails) {
        if (!container) return;
        if (!sourceDetails || sourceDetails.length === 0) return;

        var _bpFieldLabels = {
            title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor, description: _i18n.batchFieldSynopsis,
            isbn: 'ISBN', publisher: _i18n.batchFieldPublisher, series: _i18n.batchFieldSeries,
            genres: _i18n.batchFieldGenre, published_date: _i18n.modalFieldPublished, cover: _i18n.batchFieldCover
        };

        var html = '';
        sourceDetails.forEach(function(sd) {
            var iconClass = sd.ok ? 'ti-check' : 'ti-x';
            var iconColor = sd.ok ? 'var(--accent-green)' : 'var(--text-tertiary)';

            html += '<div class="bp-source-row">';
            html += '<div class="bp-source-icon"><i class="ti ' + iconClass + '" style="font-size:14px;color:' + iconColor + '"></i></div>';
            html += '<div class="bp-source-name">' + _esc(sd.source || '') + '</div>';
            html += '<div class="bp-fields">';

            if (sd.ok && sd.fields_found && sd.fields_found.length > 0) {
                _bpAllFields.forEach(function(f) {
                    var found = sd.fields_found.indexOf(f) !== -1;
                    var icon = found ? '<i class="ti ti-check" style="font-size:11px"></i> ' : '';
                    if (found) {
                        html += '<span class="bp-field-tag bp-field-found bp-field-clickable" data-field="' + f + '" data-source="' + _esc(sd.source || '') + '">'
                            + icon + _esc(_bpFieldLabels[f]) + '</span>';
                    } else {
                        html += '<span class="bp-field-tag bp-field-missing">' + _esc(_bpFieldLabels[f]) + '</span>';
                    }
                });
            } else {
                // Show the source's own message (e.g. an auth/rate-limit error)
                // rather than a generic "no matches" — makes failures diagnosable.
                var failMsg = (!sd.ok && sd.message) ? _esc(sd.message) : _i18n.noMatches;
                html += '<span class="bp-field-tag bp-field-missing">' + failMsg + '</span>';
            }

            html += '</div></div>';
        });

        container.innerHTML = html;
        container.addEventListener('click', function(e) {
            var tag = e.target.closest('.bp-field-clickable');
            if (!tag) return;

            var fieldKey = tag.dataset.field;
            var sourceName = tag.dataset.source;
            if (!fieldKey || !sourceName) return;

            var candidate = null;
            for (var i = 0; i < window._modalAllCandidates.length; i++) {
                var c = window._modalAllCandidates[i];
                var cSource = (c.source || '').toLowerCase();
                var sName = sourceName.toLowerCase();
                if (cSource === sName || cSource.indexOf(sName) !== -1 || sName.indexOf(cSource) !== -1) {
                    if (c[fieldKey] && c[fieldKey].toString().trim()) {
                        candidate = c;
                        break;
                    }
                }
            }

            if (!candidate) {
                console.warn('Ingen kandidat hittad for kalla:', sourceName, 'falt:', fieldKey,
                    'Tillgangliga:', window._modalAllCandidates.map(function(c) { return c.source; }));
                return;
            }

            var value = candidate[fieldKey].toString().trim();

            var fieldToInputId = {
                title: 'modalTitle',
                author: 'modalAuthor',
                series: 'modalSeries',
                series_index: 'modalSeriesIndex',
                isbn: 'modalIsbn',
                publisher: 'modalPublisher',
                language: 'modalLanguage',
                genres: 'modalGenres',
                published_date: 'modalPublishedDate',
                description: 'modalDescription'
            };
            var inputId = fieldToInputId[fieldKey];
            if (!inputId) return;

            var inputEl = document.getElementById(inputId);
            if (!inputEl) return;

            inputEl.value = value;

            document.querySelectorAll('.modal-input.source-highlight').forEach(function(el) {
                el.classList.remove('source-highlight');
            });
            inputEl.classList.add('source-highlight');
            inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            container.querySelectorAll('.bp-field-clickable').forEach(function(t) {
                t.classList.remove('bp-field-active');
            });
            tag.classList.add('bp-field-active');
        });
    }

    var _modalFieldInputMap = {
        title:          'modalTitle',
        author:         'modalAuthor',
        description:    'modalDescription',
        isbn:           'modalIsbn',
        publisher:      'modalPublisher',
        series:         'modalSeries',
        genres:         'modalGenres',
        published_date: 'modalPublishedDate'
    };

    function _modalFieldTagClick(sourceName, fieldKey) {
        var inputId = _modalFieldInputMap[fieldKey];
        if (!inputId) return;

        var sourceNameLower = (sourceName || '').toLowerCase();
        var candidate = null;
        for (var i = 0; i < window._modalAllCandidates.length; i++) {
            var c = window._modalAllCandidates[i];
            var cSource = (c.source || '').toLowerCase();
            if (cSource.indexOf(sourceNameLower) !== -1 || sourceNameLower.indexOf(cSource) !== -1) {
                candidate = c;
                break;
            }
        }
        if (!candidate) {
            console.warn('[colophon] No candidate found for source:', sourceName,
                'available:', window._modalAllCandidates.map(function(c) { return c.source; }));
            return;
        }

        var value = candidate[fieldKey];
        if (value == null || value === '') return;

        var inputEl = document.getElementById(inputId);
        if (!inputEl) return;
        inputEl.value = value;

        if (fieldKey === 'series' && candidate.series_index != null) {
            var siEl = document.getElementById('modalSeriesIndex');
            if (siEl) siEl.value = candidate.series_index;
        }

        document.querySelectorAll('.modal-input.source-highlight').forEach(function(el) {
            el.classList.remove('source-highlight');
        });
        inputEl.classList.add('source-highlight');
        inputEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function toggleModalProgressDetail(itemId, icon) {
        var detail = document.getElementById('mp-detail-' + itemId);
        if (!detail) return;
        var expanded = detail.classList.toggle('expanded');
        if (icon) icon.classList.toggle('open', expanded);
        if (expanded) {
            var details = window._modalSourceDetails && window._modalSourceDetails[itemId];
            if (details) _renderModalSourceDetail(detail, details);
        }
    }

    var _modalI18n = {
        sv: {
            fetchBtn: '<i class="ti ti-search"></i> Hämta metadata',
            abortBtn: '<i class="ti ti-x"></i> Avbryt',
            close: 'Stäng',
            save: 'Spara',
            saved: 'Sparad!',
            searchAborted: 'Sökning avbruten.',
            loading: 'Laddar...',
            titleRequired: 'Titel får inte vara tom.',
            saving: 'Sparar…',
            saveFailed: 'Sparning misslyckades.',
            selectField: 'Välj minst ett fält.',
            saveBtnSaving: 'Sparar...',
            saveBtnSuccess: '✓ Sparat!',
            saveBtnError: '✗ Misslyckades',
            confirmDeleteBook: 'Radera "{title}" permanent?\n\nBoken tas bort från biblioteket och filen raderas från disk.',
            deleting: 'Raderar…',
            deleteFailed: 'Radering misslyckades.',
            deleteFileError: 'Boken raderad från biblioteket, men filen kunde inte tas bort: {error}',
            searching: 'Söker…',
            seriesLabel: 'Serie',
            aiNoSeries: 'AI hittade ingen serieinformation.',
            aiSeriesFound: '🤖 AI-förslag:',
            fetchFailed: 'Hämtning misslyckades.'
        },
        en: {
            fetchBtn: '<i class="ti ti-search"></i> Fetch metadata',
            abortBtn: '<i class="ti ti-x"></i> Cancel',
            close: 'Close',
            save: 'Save',
            saved: 'Saved!',
            searchAborted: 'Search cancelled.',
            loading: 'Loading...',
            titleRequired: 'Title is required.',
            saving: 'Saving…',
            saveFailed: 'Save failed.',
            selectField: 'Select at least one field.',
            saveBtnSaving: 'Saving...',
            saveBtnSuccess: '✓ Saved!',
            saveBtnError: '✗ Failed',
            confirmDeleteBook: 'Permanently delete "{title}"?\n\nThe book will be removed from the library and the file deleted from disk.',
            deleting: 'Deleting…',
            deleteFailed: 'Delete failed.',
            deleteFileError: 'Book removed from library, but the file could not be deleted: {error}',
            searching: 'Searching…',
            seriesLabel: 'Series',
            aiNoSeries: 'AI found no series information.',
            aiSeriesFound: '🤖 AI suggestion:',
            fetchFailed: 'Fetch failed.'
        }
    };
    function _mt(key) {
        var lang = document.documentElement.lang === 'en' ? 'en' : 'sv';
        return _modalI18n[lang][key] || _modalI18n['sv'][key] || key;
    }

    function _setFetchingState(fetching) {
        var btn = document.getElementById('modalFetchBtn');
        if (!btn) return;
        if (fetching) {
            btn.dataset.fetching = '1';
            btn.disabled = false;
            btn.classList.remove('primary');
            btn.classList.add('btn-danger-outline');
            btn.innerHTML = _mt('abortBtn');
            btn.onclick = abortMetadata;
        } else {
            delete btn.dataset.fetching;
            btn.disabled = false;
            btn.classList.remove('btn-danger-outline');
            btn.classList.add('primary');
            btn.innerHTML = _mt('fetchBtn');
            btn.onclick = fetchMetadata;
        }
    }

    function abortMetadata() {
        if (_modalSSESource) {
            try { _modalSSESource.close(); } catch(e) {}
            _modalSSESource = null;
        }
        fetch('/metadata/abort', {method: 'POST'}).catch(function(){});
        _setFetchingState(false);
        _setModalBusy(false);
        var progressEl = document.getElementById('modalProgress');
        if (progressEl) { progressEl.style.display = 'none'; }
        setModalFeedback('info', _mt('searchAborted'));
    }

    function fetchMetadata() {
        var id = window._modalItemId;
        var selectedFields = _getSelectedFields();
        if (selectedFields.length === 0) {
            setModalFeedback('error', _mt('selectField'));
            return;
        }
        var smartReplace = _getModalSmartReplace();
        var progressEl = document.getElementById('modalProgress');

        if (!window.EventSource) {
            setModalFeedback('info', _i18n.fetching);
            _setFetchingState(true);
            _setModalBusy(true);
            var url = '/metadata/' + id + '/fetch-json'
                + '?smart_replace=' + encodeURIComponent(smartReplace.join(','));
            fetch(url, { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    _setFetchingState(false);
                    _setModalBusy(false);
                    if (!data.ok) {
                        var msg = data.error === 'no_match' ? _i18n.noSecureMatches : (_i18n.scanError + ' ' + data.error);
                        setModalFeedback('error', msg);
                        return;
                    }
                    _applyFetchedToModal(data.fetched || {}, selectedFields);
                    var src = data.source ? ' (' + data.source + ')' : '';
                    setModalFeedback('success', _i18n.metadataFetched + src + '. ' + _i18n.reviewAndSave);
                })
                .catch(function() {
                    _setFetchingState(false);
                    _setModalBusy(false);
                    setModalFeedback('error', _i18n.fetchFailed);
                });
            return;
        }

        _setFetchingState(true);
        _setModalBusy(true);
        var covBanner = document.getElementById('modalCoverageBanner');
        if (covBanner) { covBanner.style.display = 'none'; covBanner.innerHTML = ''; }
        progressEl.style.display = 'block';
        progressEl.innerHTML =
            '<div style="font-weight:500; margin-bottom:4px;">' + _i18n.searchingMetadata + '</div>' +
            '<div class="hint" style="font-size:12px; margin-bottom:8px;">' +
            _i18n.scoreShort + ' <span class="bp-ok">' + _i18n.modalScoreStrong + '</span> · ' +
            '<span class="bp-warn">' + _i18n.modalScoreReview + '</span> · ' +
            '<span class="bp-uncertain">' + _i18n.modalScoreUncertain + '</span> · ' +
            '<span class="bp-fail">' + _i18n.modalScoreNoMatch + '</span></div>' +
            '<table id="modalProgressTable" style="width:100%; border-collapse:collapse; font-size:13px;">' +
            '<thead><tr>' +
            '<th style="text-align:left; padding:8px 12px; border-bottom:1px solid var(--border-light); background:var(--bg-secondary); color:var(--text-secondary); font-size:12px; text-transform:uppercase; vertical-align:middle;">' + _i18n.modalThTitle + '</th>' +
            '<th style="text-align:center; padding:8px 12px; border-bottom:1px solid var(--border-light); background:var(--bg-secondary); color:var(--text-secondary); font-size:12px; text-transform:uppercase; vertical-align:middle;">GOOGLE</th>' +
            '<th style="text-align:center; padding:8px 12px; border-bottom:1px solid var(--border-light); background:var(--bg-secondary); color:var(--text-secondary); font-size:12px; text-transform:uppercase; vertical-align:middle;">CALIBRE</th>' +
            '<th style="text-align:center; padding:8px 12px; border-bottom:1px solid var(--border-light); background:var(--bg-secondary); color:var(--text-secondary); font-size:12px; text-transform:uppercase; vertical-align:middle;">' + _i18n.modalThScore + '</th>' +
            '<th style="text-align:center; padding:8px 12px; border-bottom:1px solid var(--border-light); background:var(--bg-secondary); color:var(--text-secondary); font-size:12px; text-transform:uppercase; vertical-align:middle;">' + _i18n.modalThResult + '</th>' +
            '</tr></thead>' +
            '<tbody id="modalProgressBody"></tbody>' +
            '</table>';
        var fb = document.getElementById('modalFeedback');
        if (fb) fb.style.display = 'none';
        if (!window._modalSourceDetails) window._modalSourceDetails = {};

        var url = '/metadata/bulk/stream?item_ids=' + id + '&max_items=1'
            + '&smart_replace=' + encodeURIComponent(smartReplace.join(','))
            + '&mode=' + encodeURIComponent(_modalFetchModeSel);
        var sseSource = new EventSource(url);
        _modalSSESource = sseSource;

        sseSource.onmessage = function(e) {
            var d;
            try { d = JSON.parse(e.data); } catch(ex) { return; }

            if (d.type === 'book_start') {
                var body = document.getElementById('modalProgressBody');
                if (!body) return;
                var title = d.title || 'Bok';
                if (title.length > 45) title = title.substring(0, 45) + '…';
                var fmtHtml = '';
                if (d.formats && d.formats.length > 0) {
                    fmtHtml = ' ' + d.formats.map(function(f) {
                        return '<span class="format-badge">' + _esc(f) + '</span>';
                    }).join(' ');
                }
                var expandIcon = ' <i class="ti ti-chevron-down bp-expand-icon open" onclick="toggleModalProgressDetail(' + d.item_id + ', this)" title="' + _i18n.showSourceDetails + '"></i>';
                var tr = document.createElement('tr');
                tr.id = 'mp-row-' + d.item_id;
                tr.className = 'bp-active';
                tr.innerHTML =
                    '<td style="padding:8px 12px; vertical-align:middle; border-bottom:1px solid var(--border-light);">' + _esc(title) + fmtHtml + expandIcon + '</td>' +
                    '<td id="mp-google-' + d.item_id + '" style="text-align:center; padding:8px 12px; vertical-align:middle; border-bottom:1px solid var(--border-light);"><span class="bp-spinner"></span></td>' +
                    '<td id="mp-calibre-' + d.item_id + '" style="text-align:center; padding:8px 12px; vertical-align:middle; border-bottom:1px solid var(--border-light);"><span class="bp-spinner"></span></td>' +
                    '<td id="mp-score-' + d.item_id + '" style="text-align:center; padding:8px 12px; vertical-align:middle; border-bottom:1px solid var(--border-light); color:var(--text-tertiary);">—</td>' +
                    '<td id="mp-result-' + d.item_id + '" style="text-align:center; padding:8px 12px; vertical-align:middle; border-bottom:1px solid var(--border-light); color:var(--text-tertiary);">—</td>';
                body.appendChild(tr);
                window._modalSourceDetails[d.item_id] = [];
                var detailTr = document.createElement('tr');
                detailTr.id = 'mp-detail-row-' + d.item_id;
                detailTr.innerHTML = '<td colspan="5" style="padding:0; border-bottom:1px solid var(--border-light);"><div id="mp-detail-' + d.item_id + '" class="bp-source-detail expanded"></div></td>';
                body.appendChild(detailTr);
            }

            if (d.type === 'progress') {
                if (d.stage === 'coverage') { _renderModalCoverage(d); return; }
                var itemId = d.item_id;
                var stageMap = { google_books: 'google', calibre: 'calibre' };
                var key = stageMap[d.stage];
                if (key) {
                    var cell = document.getElementById('mp-' + key + '-' + itemId);
                    if (cell) {
                        if (d.status === 'searching') {
                            cell.innerHTML = '<span class="bp-spinner"></span>';
                        } else if (d.status === 'skipped') {
                            cell.innerHTML = '<span class="bp-skip" title="' + _esc(d.message || '') + '">–</span>';
                        } else {
                            var n = d.candidates_found || 0;
                            cell.innerHTML = d.status === 'ok'
                                ? '<span class="bp-ok">✓ ' + n + '</span>'
                                : '<span class="bp-fail">✗</span>';
                        }
                    }
                }
                if (d.source_details && d.source_details.length > 0) {
                    if (!window._modalSourceDetails[itemId]) window._modalSourceDetails[itemId] = [];
                    d.source_details.forEach(function(sd) { window._modalSourceDetails[itemId].push(sd); });
                    var detailEl = document.getElementById('mp-detail-' + itemId);
                    if (detailEl) _renderModalSourceDetail(detailEl, window._modalSourceDetails[itemId]);
                }
                // Progressive fill: as soon as Wikipedia + Google Books finish,
                // populate the modal so users have something to look at while
                // the slower Calibre lookup is still running.
                if (d.stage === 'fast_preview' && d.payload) {
                    _applyFetchedToModal(d.payload, selectedFields);
                }
            }

            if (d.type === 'aborted') {
                sseSource.close(); _modalSSESource = null;
                _setFetchingState(false);
                _setModalBusy(false);
                progressEl.style.display = 'none';
                setModalFeedback('info', _i18n.searchAbortedShort);
                return;
            }

            if (d.type === 'book_done') {
                sseSource.close(); _modalSSESource = null;
                _setFetchingState(false);
                _setModalBusy(false);
                var itemId = d.item_id;
                window._modalAllCandidates = d.all_candidates || [];

                if (d.source_details && d.source_details.length > 0) {
                    window._modalSourceDetails[itemId] = d.source_details;
                    var detailEl = document.getElementById('mp-detail-' + itemId);
                    if (detailEl) _renderModalSourceDetail(detailEl, window._modalSourceDetails[itemId]);
                }

                var scoreCell = document.getElementById('mp-score-' + itemId);
                if (scoreCell && d.score != null) {
                    var s = d.score;
                    var cls = s >= 90 ? 'bp-ok' : s >= 70 ? 'bp-warn' : s >= 50 ? 'bp-uncertain' : 'bp-fail';
                    scoreCell.innerHTML = '<span class="' + cls + '" style="font-weight:500;">' + Math.round(s) + '</span>';
                }

                var resultCell = document.getElementById('mp-result-' + itemId);
                if (resultCell) {
                    var label = _resultLabel(d);
                    var tip = _resultTooltip(d);
                    resultCell.innerHTML = tip
                        ? '<span title="' + _esc(tip) + '">' + label + '</span>'
                        : label;
                }

                var header = progressEl.querySelector('div:first-child');
                if (header) header.textContent = _i18n.searchDone;

                _applyFetchedToModal(d.candidate || {}, selectedFields);
                var src = d.source ? ' (' + d.source + ')' : '';
                var score = d.score ? ' · ' + _i18n.scoreShort + ' ' + Math.round(d.score) : '';
                setModalFeedback('success', _i18n.metadataFetched + src + score + '. ' + _i18n.reviewAndSave);
            }

            if (d.type === 'done') { sseSource.close(); _modalSSESource = null; }
        };
        sseSource.onerror = function() {
            sseSource.close(); _modalSSESource = null;
            _setFetchingState(false);
            _setModalBusy(false);
            progressEl.style.display = 'none';
            setModalFeedback('error', _i18n.searchFailed);
        };
    }

    var AI_FIELD_ORDER = ['series', 'series_index', 'title', 'author', 'publisher', 'language', 'genres', 'published_date', 'description'];
    var AI_FIELD_LABELS = {
        series: _i18n.batchFieldSeries, series_index: _i18n.modalFieldSeriesNumber, title: _i18n.batchFieldTitle,
        author: _i18n.batchFieldAuthor, publisher: _i18n.batchFieldPublisher, language: _i18n.batchFieldLanguage,
        genres: _i18n.batchFieldGenre, published_date: _i18n.batchFieldPublicationDate, description: _i18n.batchFieldSynopsis
    };
    var AI_FIELD_EL_IDS = {
        series: 'modalSeries', series_index: 'modalSeriesIndex',
        title: 'modalTitle', author: 'modalAuthor',
        publisher: 'modalPublisher', language: 'modalLanguage',
        genres: 'modalGenres', published_date: 'modalPublishedDate',
        description: 'modalDescription'
    };

    function fetchAiMetadata() {
        var id = window._modalItemId;
        var selectedFields = _getSelectedFields();
        if (selectedFields.length === 0) {
            setModalFeedback('error', _i18n.chooseAtLeastOneFieldShort);
            return;
        }
        var smartReplace = _getModalSmartReplace();
        _setModalBusy(true);

        var progressEl = document.getElementById('modalProgress');
        progressEl.style.display = 'block';
        progressEl.innerHTML = '<div style="margin-bottom:4px;font-weight:500;">' + _i18n.askingAi + '</div>'
            + '<div class="progress-bar" style="height:6px;border-radius:3px;overflow:hidden;background:var(--bg-tertiary);">'
            + '<div style="width:100%;height:100%;background:var(--accent-purple);animation:pulse 1.5s ease-in-out infinite;"></div>'
            + '</div>';

        var fieldsParam = encodeURIComponent(selectedFields.join(','));
        var smartParam = encodeURIComponent(smartReplace.join(','));
        var currentValues = {
            title:          document.getElementById('modalTitle').value.trim(),
            author:         document.getElementById('modalAuthor').value.trim(),
            series:         document.getElementById('modalSeries').value.trim(),
            series_index:   document.getElementById('modalSeriesIndex').value.trim(),
            isbn:           document.getElementById('modalIsbn').value.trim(),
            publisher:      document.getElementById('modalPublisher').value.trim(),
            language:       document.getElementById('modalLanguage').value.trim(),
            genres:         document.getElementById('modalGenres').value.trim(),
            published_date: document.getElementById('modalPublishedDate').value.trim(),
            description:    document.getElementById('modalDescription').value.trim()
        };
        fetch('/metadata/' + id + '/ai-json?fields=' + fieldsParam + '&smart_replace=' + smartParam, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_values: currentValues })
        })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                _setModalBusy(false);
                progressEl.style.display = 'none';
                if (!data.ok) {
                    var msgs = {
                        not_configured: _i18n.aiNotConfigured,
                        auth:           _i18n.aiAuth,
                        timeout:        _i18n.aiTimeout,
                        rate_limit:     _i18n.aiRateLimit,
                        invalid_json:   _i18n.aiInvalidJson,
                        no_valid_fields: _i18n.aiNoValidFields
                    };
                    setModalFeedback('error', msgs[data.error] || 'AI-fel: ' + data.error);
                    return;
                }

                var suggestions = data.suggestions;
                var rows = [];

                AI_FIELD_ORDER.forEach(function(key) {
                    var s = suggestions[key];
                    if (!s) return;
                    var elId = AI_FIELD_EL_IDS[key];
                    var currentEl = elId ? document.getElementById(elId) : null;
                    var currentVal = currentEl ? currentEl.value.trim() : '';
                    var newVal = String(s.value || '').trim();
                    if (!newVal || newVal === currentVal) return;

                    rows.push({
                        key: key,
                        label: AI_FIELD_LABELS[key] || key,
                        current: currentVal,
                        value: newVal,
                        confidence: s.confidence,
                        reason: s.reason || '',
                        defaultCheck: s.confidence === 'high'
                    });
                });

                if (rows.length === 0) {
                    setModalFeedback('info', _i18n.aiNoNewSuggestions);
                    return;
                }

                _showAiReviewModal(rows);
            })
            .catch(function() {
                _setModalBusy(false);
                progressEl.style.display = 'none';
                setModalFeedback('error', 'AI-anropet misslyckades.');
            });
    }

    function _showAiReviewModal(rows) {
        var modal = document.getElementById('bulkResultModal');
        var head = document.getElementById('brmHead');
        var body = document.getElementById('brmBody');
        var titleEl = document.getElementById('brmTitle');

        if (titleEl) titleEl.textContent = _i18n.aiReview;

        head.innerHTML = '<tr>'
            + '<th style="width:18%;">' + _i18n.modalThField + '</th>'
            + '<th style="width:36%;" class="brm-th-current">' + _i18n.currentHeader + '</th>'
            + '<th style="width:10%;" class="brm-th-pick">' + _i18n.useSource + '</th>'
            + '<th style="width:36%;" class="brm-th-fetched">' + _i18n.modalThAi + '</th>'
            + '</tr>';

        body.innerHTML = '';
        rows.forEach(function(row) {
            var tr = document.createElement('tr');
            var checked = row.defaultCheck ? 'checked' : '';

            var aiCell = '<div style="color:var(--accent-green);font-weight:500;">' + _esc(row.value) + '</div>';
            if (row.reason) {
                aiCell += '<details style="margin-top:4px;">'
                    + '<summary style="font-size:12px;color:var(--text-secondary);cursor:pointer;list-style:none;display:flex;align-items:center;gap:4px;">'
                    + '<i class="ti ti-info-circle" style="font-size:14px;"></i> AI-resonemang'
                    + '</summary>'
                    + '<p style="font-size:12px;color:var(--text-secondary);margin:4px 0 0;line-height:1.4;">'
                    + _esc(row.reason) + '</p>'
                    + '</details>';
            }

            tr.innerHTML = '<td><strong>' + _esc(row.label) + '</strong></td>'
                + '<td class="brm-td-current" style="color:var(--accent-red);">' + _esc(row.current || '(tomt)') + '</td>'
                + '<td class="brm-td-pick" style="text-align:center;">'
                +   '<input type="checkbox" class="ai-review-check" data-key="' + row.key + '" ' + checked + '>'
                + '</td>'
                + '<td class="brm-td-fetched">' + aiCell + '</td>';
            body.appendChild(tr);
        });

        var saveBtn = document.getElementById('brmSaveBtn');
        saveBtn.textContent = _i18n.applySelected || 'Apply selected';
        saveBtn.onclick = function() { _applyAiReviewSelections(rows); };

        modal.style.display = 'flex';
    }

    function _applyAiReviewSelections(rows) {
        var checks = document.querySelectorAll('.ai-review-check');
        var applied = 0;

        checks.forEach(function(chk) {
            if (!chk.checked) return;
            var key = chk.dataset.key;
            var row = rows.find(function(r) { return r.key === key; });
            if (!row) return;

            var elId = AI_FIELD_EL_IDS[key];
            var el = elId ? document.getElementById(elId) : null;
            if (el) {
                el.value = key === 'published_date' ? _cleanDate(row.value) : row.value;
                applied++;
            }
        });

        document.getElementById('bulkResultModal').style.display = 'none';

        var saveBtn = document.getElementById('brmSaveBtn');
        saveBtn.textContent = _i18n.saveSelected || 'Save selected';
        saveBtn.onclick = saveBulkResult;

        setModalFeedback('success', _i18n.aiFieldsApplied.replace('{count}', applied));
    }

    function _saveButtonFeedback(success) {
        var btn = document.getElementById('modalSaveBtn');
        if (!btn) return;
        btn.disabled = false;
        btn.classList.remove('btn-save-saving');
        var cls = success ? 'btn-save-success' : 'btn-save-error';
        var text = success ? _mt('saveBtnSuccess') : _mt('saveBtnError');
        var duration = success ? 2000 : 3000;
        var original = btn._savedOriginalHTML || btn.innerHTML;
        btn.innerHTML = text;
        btn.classList.add(cls);
        setTimeout(function() {
            btn.classList.remove(cls);
            btn.innerHTML = original;
        }, duration);
    }

    function saveMetadata() {
        var id = window._modalItemId;
        var title = document.getElementById('modalTitle').value.trim();
        if (!title) { setModalFeedback('error', _mt('titleRequired')); return; }
        var payload = {
            title:          title,
            author:         document.getElementById('modalAuthor').value.trim(),
            series:         document.getElementById('modalSeries').value.trim(),
            series_index:   document.getElementById('modalSeriesIndex').value.trim(),
            isbn:           document.getElementById('modalIsbn').value.trim(),
            publisher:      document.getElementById('modalPublisher').value.trim(),
            language:       document.getElementById('modalLanguage').value.trim(),
            genres:         document.getElementById('modalGenres').value.trim(),
            published_date: _cleanDate(document.getElementById('modalPublishedDate').value.trim()),
            description:    document.getElementById('modalDescription').value.trim()
        };

        // Registry combobox: a staged pick rides along as author_id; an
        // explicit "Create new" runs the server-side fuzzy guard first
        // (and may be cancelled by the user — then the save is aborted).
        var authorSel = window.getModalAuthorSelection
            ? window.getModalAuthorSelection()
            : { author_id: null, create_new: false };
        if (authorSel.author_id) payload.author_id = authorSel.author_id;

        var btn = document.getElementById('modalSaveBtn');
        if (btn) {
            btn._savedOriginalHTML = btn.innerHTML;
            btn.innerHTML = _mt('saveBtnSaving');
            btn.classList.add('btn-save-saving');
        }
        setModalFeedback('info', _mt('saving'));
        _setModalBusy(true);

        var pre = (authorSel.create_new && window.confirmAuthorCreateIfNeeded)
            ? window.confirmAuthorCreateIfNeeded(id, payload.author)
            : Promise.resolve(true);

        pre.then(function(proceed) {
            if (!proceed) {
                _setModalBusy(false);
                _saveButtonFeedback(false);
                clearModalFeedback();
                var authorInput = document.getElementById('modalAuthor');
                if (authorInput) authorInput.focus();
                return;
            }
            return fetch('/metadata/' + id + '/save-json', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                _setModalBusy(false);
                if (!data.ok) {
                    setModalFeedback('error', _i18n.errorWithMsg.replace('{msg}', data.error || _i18n.unknownError));
                    _saveButtonFeedback(false);
                    return;
                }
                _updateTableRow(id, payload);
                if (window.updateRowAuthorFlag) window.updateRowAuthorFlag(id, data.author_status);
                window._modalDirty = true;
                _updateUnsyncedPill(1);
                setModalFeedback('success', _mt('saved'));
                setTimeout(clearModalFeedback, 3000);
                _saveButtonFeedback(true);
            });
        })
            .catch(function() {
                _setModalBusy(false);
                setModalFeedback('error', _mt('saveFailed'));
                _saveButtonFeedback(false);
            });
    }

    function _updateTableRow(itemId, data) {
        // Scope to #bookTableBody so batch-review rows with the same data-item-id are never matched.
        var tbody = document.getElementById('bookTableBody');
        var row = (tbody || document).querySelector('tr[data-item-id="' + itemId + '"]');
        if (!row) return;

        var titleEl = row.querySelector('.book-title');
        if (titleEl && data.title) {
            titleEl.textContent = data.title;
            row.dataset.title = data.title.toLowerCase();

            // Update the series/publisher meta line that sits beneath the title.
            var titleTd = titleEl.parentElement;
            if (titleTd) {
                var metaEl = titleTd.querySelector('.meta');
                var seriesText = '';
                if (data.series) {
                    seriesText = data.series;
                    if (data.series_index) seriesText += ' · ' + data.series_index;
                    if (data.publisher) seriesText += ' · ' + data.publisher;
                } else if (data.publisher) {
                    seriesText = data.publisher;
                }
                if (metaEl) {
                    if (seriesText) {
                        metaEl.textContent = seriesText;
                    } else {
                        metaEl.remove();
                    }
                } else if (seriesText) {
                    var newMeta = document.createElement('div');
                    newMeta.className = 'meta';
                    newMeta.textContent = seriesText;
                    titleTd.appendChild(newMeta);
                }
            }
        }
        var authorEl = row.querySelector('.author-cell');
        if (authorEl) {
            authorEl.textContent = data.author || _i18n.unknownAuthor;
            row.dataset.author = (data.author || '').toLowerCase();
            row.dataset.hasAuthor = data.author ? '1' : '0';
        }
        var genresEl = row.querySelector('.genres-cell');
        if (genresEl) {
            genresEl.innerHTML = data.genres
                ? '<span class="meta">' + _modalEsc(data.genres) + '</span>'
                : '<span class="meta">—</span>';
            row.dataset.genres = (data.genres || '').toLowerCase();
            row.dataset.hasGenres = data.genres ? '1' : '0';
        }
        var publishedEl = row.querySelector('.published-cell');
        if (publishedEl) {
            var pd = (data.published_date || '').toString();
            if (pd) {
                var label = pd.length >= 10 ? pd.substring(0, 4) : pd;
                publishedEl.innerHTML =
                    '<span class="meta" title="' + _modalEsc(pd) + '">'
                    + _modalEsc(label) + '</span>';
            } else {
                publishedEl.innerHTML = '<span class="meta">—</span>';
            }
            row.dataset.published = pd;
            row.dataset.hasPublished = pd ? '1' : '0';
        }
        row.dataset.hasSeries = data.series ? '1' : '0';
        row.dataset.hasPublisher = data.publisher ? '1' : '0';
        row.dataset.unsynced = '1';
    }

    function _updateUnsyncedPill(delta) {
        var pill = document.getElementById('libraryChipUnsynced');
        if (!pill) {
            if (delta <= 0) return;
            var bar = document.getElementById('paginationStats');
            if (!bar) return;
            pill = document.createElement('span');
            pill.className = 'stats-badge';
            pill.id = 'libraryChipUnsynced';
            pill.onclick = function(e) { toggleBadgeFilter('unsynced', '1', e); };
            bar.appendChild(document.createTextNode(' · '));
            bar.appendChild(pill);
        }
        var text = pill.textContent.trim();
        var current = parseInt(text) || 0;
        var newCount = current + delta;
        if (newCount <= 0) {
            pill.style.display = 'none';
        } else {
            pill.style.display = '';
            pill.textContent = newCount + ' osynkade';
        }
    }

    function filterByAuthor(name) {
        // Close the book view, then drive the existing library search so the
        // current view (shelf/table/series) refreshes to this author's books.
        closeBookModal();
        var el = document.getElementById('filterSearch');
        if (el) {
            el.value = name;
            if (window.applyFilters) window.applyFilters();
        }
        window.scrollTo(0, 0);
    }
    window.filterByAuthor = filterByAuthor;

    function closeBookModal() {
        if (_modalSSESource) {
            try { _modalSSESource.close(); } catch(e) {}
            _modalSSESource = null;
            fetch('/metadata/abort', {method: 'POST'}).catch(function(){});
        }
        _setFetchingState(false);
        _setModalBusy(false);
        if (window._modalDirty) {
            // A structural edit (e.g. renaming a series) needs a fresh server
            // render to re-group / re-sort / re-filter and refresh the sidebar
            // counts — something the in-place row patch can't guarantee (that
            // was the iPad bug: edit a series, leave the modal, stale data).
            // The URL already encodes view/filters/search, so the reload
            // returns to the same context; stash the scroll so it's not lost.
            // Especially important on iPad, where there's no easy manual reload.
            try { sessionStorage.setItem('colophonRestoreScroll', String(window.scrollY)); } catch (e) {}
            // Take over scroll restoration so the browser's own doesn't fight
            // ours after the reload (core.js restores, then flips back to auto).
            try { history.scrollRestoration = 'manual'; } catch (e) {}
            window._modalDirty = false;
            window.location.reload();
            return;
        }
        window._modalDirty = false;
        document.getElementById('bookModal').style.display = 'none';
        window._modalItemId = null;
        var progressEl = document.getElementById('modalProgress');
        if (progressEl) { progressEl.style.display = 'none'; progressEl.innerHTML = ''; }
        clearModalFeedback();
        // Hide cover search results
        var cr = document.getElementById('modalCoverResults');
        if (cr) cr.style.display = 'none';
        var cg = document.getElementById('modalCoverGrid');
        if (cg) cg.innerHTML = '';
        // If we were opened on top of the series modal, restore its z-index
        // and refresh it (read status may have changed).
        var sm = document.getElementById('seriesModal');
        if (sm && sm.classList.contains('with-book-modal')) {
            sm.classList.remove('with-book-modal');
            if (_seriesModalName) _renderSeriesModal(_seriesModalName);
        }
    }

    /* -------------------------------------------------------------------- */
    /* Cover search                                                          */
    /* -------------------------------------------------------------------- */
    function searchCovers() {
        var id = window._modalItemId;
        if (!id) return;

        var btn = document.getElementById('modalCoverSearchBtn');
        var grid = document.getElementById('modalCoverGrid');
        var container = document.getElementById('modalCoverResults');

        btn.disabled = true;
        btn.innerHTML = '<i class="ti ti-loader-2" style="animation:spin 1s linear infinite;"></i> ' + _i18n.searchingDots;

        fetch('/metadata/' + id + '/covers/search-json', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-photo-search"></i> ' + _i18n.searchCovers;

                var sourceLine = '';
                if (data.sources && data.sources.length > 0) {
                    sourceLine = '<div style="font-size:11px; color:var(--text-tertiary); margin-bottom:6px;">'
                        + _i18n.searched + ' ' + data.sources.map(_esc).join(' · ') + '</div>';
                }

                if (!data.ok || !data.count) {
                    grid.innerHTML = sourceLine + '<div style="font-size:11px;color:var(--text-secondary);padding:6px 0;">Inga omslag hittades.</div>';
                    container.style.display = 'block';
                    return;
                }

                grid.innerHTML = sourceLine;
                data.candidates.forEach(function(c) {
                    var card = document.createElement('div');
                    card.className = 'cover-search-card';
                    card.title = _esc(c.note || '') + ' (' + _esc(c.source || '') + ')';

                    var thumb = c.thumbnail_url || c.cover_url || '';
                    card.innerHTML =
                        '<img src="' + _esc(thumb) + '" alt="" '
                        + 'onerror="this.closest(\'.cover-search-card\').style.display=\'none\'">'
                        + '<div class="cover-search-label">' + _esc(c.source || '') + '</div>';

                    card.onclick = function() {
                        grid.querySelectorAll('.cover-search-card').forEach(function(d) {
                            d.classList.remove('selected');
                        });
                        card.classList.add('selected');
                        applyCoverFromSearch(id, c.cover_url, c.source);
                    };

                    grid.appendChild(card);
                });

                container.style.display = 'block';
            })
            .catch(function() {
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-photo-search"></i> ' + _i18n.searchCovers;
                setModalFeedback('error', _i18n.coverSearchFailed);
            });
    }

    function applyCoverFromSearch(itemId, coverUrl, source) {
        setModalFeedback('info', 'Laddar ner omslag…');

        fetch('/metadata/' + itemId + '/cover/apply-json', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cover_url: coverUrl, source: source || '' })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.ok) {
                var errMsg = 'Omslaget kunde inte sparas: ' + (data.error || 'okänt fel');
                setModalFeedback('error', errMsg);
                console.error('[cover-apply]', errMsg, data);
                return;
            }
            // Refresh cover thumbnail in modal
            var coverEl = document.getElementById('modalCover');
            coverEl.innerHTML = '<img src="' + _coverUrlBase + '/' + itemId + '?t=' + Date.now() + '" alt="" onerror="this.parentNode.innerHTML=\'📖\';">';
            // Refresh thumbnail in the book list row
            var listImg = document.querySelector('tr[data-item-id="' + itemId + '"] .cover img');
            if (listImg) listImg.src = _coverUrlBase + '/' + itemId + '?t=' + Date.now();
            window._modalDirty = true;
            setModalFeedback('success', 'Omslag sparat' + (data.source ? ' (' + data.source + ')' : '') + '.');
            document.getElementById('modalCoverResults').style.display = 'none';

            // Update row data so filters reflect the new cover
            var row = document.querySelector('tr[data-item-id="' + itemId + '"]');
            if (row) {
                row.dataset.hasCover = '1';
            }

            // Decrement missing cover chip
            var mcPill = document.getElementById('libraryChipMissingCover');
            if (mcPill) {
                var mcText = mcPill.textContent.trim();
                var mcCount = parseInt(mcText) || 0;
                mcCount--;
                if (mcCount <= 0) {
                    mcPill.style.display = 'none';
                } else {
                    mcPill.textContent = mcCount + ' missing cover';
                    // Handle Swedish translation
                    if (mcText.indexOf('saknar') !== -1) {
                        mcPill.textContent = mcCount + ' saknar omslag';
                    }
                }
            }
        })
        .catch(function(err) {
            var errMsg = 'Omslaget kunde inte sparas: ' + (err.message || 'nätverksfel');
            setModalFeedback('error', errMsg);
            console.error('[cover-apply]', errMsg, err);
        });
    }

    function findSeriesAi() {
        var id = window._modalItemId;
        if (!id) return;

        var btn = document.getElementById('modalFindSeriesBtn');
        var origHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="ti ti-loader-2" style="animation:spin 1s linear infinite;"></i> ' + _mt('searching');

        var currentValues = {
            title: document.getElementById('modalTitle').value.trim(),
            author: document.getElementById('modalAuthor').value.trim(),
            series: document.getElementById('modalSeries').value.trim(),
            series_index: document.getElementById('modalSeriesIndex').value.trim(),
            isbn: document.getElementById('modalIsbn').value.trim(),
            publisher: document.getElementById('modalPublisher').value.trim(),
            language: document.getElementById('modalLanguage').value.trim(),
            description: document.getElementById('modalDescription').value.trim()
        };

        fetch('/metadata/' + id + '/ai-json?fields=series,series_index', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_values: currentValues })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.innerHTML = origHTML;

            if (!data.ok) {
                var errKey = 'ai' + data.error.charAt(0).toUpperCase() + data.error.slice(1);
                setModalFeedback('error', _i18n[errKey] || _mt('fetchFailed'));
                return;
            }

            var s = data.suggestions || {};
            var applied = [];

            if (s.series && s.series.value) {
                document.getElementById('modalSeries').value = s.series.value;
                applied.push(_mt('seriesLabel') + ': ' + s.series.value);
            }
            if (s.series_index && s.series_index.value) {
                document.getElementById('modalSeriesIndex').value = s.series_index.value;
                applied.push('#' + s.series_index.value);
            }

            if (applied.length === 0) {
                setModalFeedback('info', _mt('aiNoSeries'));
                return;
            }

            var reason = (s.series && s.series.reason) || '';
            var msg = _mt('aiSeriesFound') + ' ' + applied.join(', ');
            if (reason) msg += ' — ' + reason;
            setModalFeedback('success', msg);
            setTimeout(clearModalFeedback, 6000);
        })
        .catch(function() {
            btn.disabled = false;
            btn.innerHTML = origHTML;
            setModalFeedback('error', _mt('fetchFailed'));
        });
    }

    function deleteBookFromModal() {
        var id = window._modalItemId;
        if (!id) return;

        var title = (document.getElementById('modalTitle').value || '').trim() || 'denna bok';

        if (!confirm(_mt('confirmDeleteBook').replace('{title}', title))) return;

        _setModalBusy(true);
        setModalFeedback('info', _mt('deleting'));

        var formData = new FormData();
        formData.append('delete_file', '1');

        fetch('/metadata/' + id + '/delete', {
            method: 'POST',
            body: formData
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _setModalBusy(false);
            if (!data.ok) {
                setModalFeedback('error', _mt('deleteFailed'));
                return;
            }

            var row = document.querySelector('#bookTableBody tr[data-item-id="' + id + '"]');
            if (row) row.remove();

            renderGroupedView();
            window._modalDirty = false;
            closeBookModal();

            if (data.file_error) {
                alert(_mt('deleteFileError').replace('{error}', data.file_error));
            }
        })
        .catch(function() {
            _setModalBusy(false);
            setModalFeedback('error', _mt('deleteFailed'));
        });
    }

    function _modalEsc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function setModalFeedback(type, msg) {
        var el = document.getElementById('modalFeedback');
        // Don't let info messages overwrite a recent error
        if (type === 'info' && el._errorUntil && Date.now() < el._errorUntil) return;
        el.style.display = 'block';
        el.className = 'modal-feedback modal-feedback-' + type;
        el.textContent = msg;
        if (type === 'error') {
            el._errorUntil = Date.now() + 5000;
        }
    }
    function clearModalFeedback() {
        var el = document.getElementById('modalFeedback');
        el.style.display = 'none';
        el.className = 'modal-feedback';
    }
    function _setModalBusy(busy) {
        var fetchBtn = document.getElementById('modalFetchBtn');
        // While the fetch button is in "Avbryt" mode it must stay clickable.
        if (fetchBtn && fetchBtn.dataset.fetching !== '1') {
            fetchBtn.disabled = busy;
        }
        document.getElementById('modalAiBtn').disabled = busy;
        var saveBtn = document.getElementById('modalSaveBtn');
        if (saveBtn) saveBtn.disabled = busy;
    }
    function _fmtBytes(b) {
        if (b < 1024)    return b + ' B';
        if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
        return (b / 1048576).toFixed(1) + ' MB';
    }
    document.getElementById('bookModal').addEventListener('click', function(e) {
        if (e.target === this) closeBookModal();
    });

    /* ------------------------------------------------------------------ */
    /* Publish all entry points on window for HTML onclick + cross-module */
    /* ------------------------------------------------------------------ */
    window.openBookModal = openBookModal;
    window._populateModal = _populateModal;
    window._setDisplayHidden = _setDisplayHidden;
    window._populateDisplayMirror = _populateDisplayMirror;
    window._displayDataFromForm = _displayDataFromForm;
    window.toggleModalMode = toggleModalMode;
    window._fmtDate = _fmtDate;
    window._populateReadingState = _populateReadingState;
    window.markReadManually = markReadManually;
    window.resetReadingState = resetReadingState;
    window._syncReadStateToRow = _syncReadStateToRow;
    window._getSelectedFields = _getSelectedFields;
    window._getModalSmartReplace = _getModalSmartReplace;
    window.toggleModalFields = toggleModalFields;
    window.toggleAllFields = toggleAllFields;
    window._applyFetchedToModal = _applyFetchedToModal;
    window._renderModalSourceDetail = _renderModalSourceDetail;
    window._modalFieldTagClick = _modalFieldTagClick;
    window.toggleModalProgressDetail = toggleModalProgressDetail;
    window._mt = _mt;
    window._setFetchingState = _setFetchingState;
    window.abortMetadata = abortMetadata;
    window.fetchMetadata = fetchMetadata;
    window.fetchAiMetadata = fetchAiMetadata;
    window._showAiReviewModal = _showAiReviewModal;
    window._applyAiReviewSelections = _applyAiReviewSelections;
    window._saveButtonFeedback = _saveButtonFeedback;
    window.saveMetadata = saveMetadata;
    window._updateTableRow = _updateTableRow;
    window._updateUnsyncedPill = _updateUnsyncedPill;
    window.closeBookModal = closeBookModal;
    window.searchCovers = searchCovers;
    window.applyCoverFromSearch = applyCoverFromSearch;
    window.findSeriesAi = findSeriesAi;
    window.deleteBookFromModal = deleteBookFromModal;
    window._modalEsc = _modalEsc;
    window.setModalFeedback = setModalFeedback;
    window.clearModalFeedback = clearModalFeedback;
    window._setModalBusy = _setModalBusy;
    window._fmtBytes = _fmtBytes;
})(window, document);
