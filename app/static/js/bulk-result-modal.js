/* ------------------------------------------------------------------ *
 * bulk-result-modal.js — Per-source detail + the bulk-result review modal
 *
 * Owns the bulk-search result modal (one row in the search-result
 * table opens this; here the user picks per-field values from each
 * source). Plus the small expandable per-source detail rows that show
 * inline below the search-result table during/after batch search.
 *
 * Reads from window.* helpers exposed by batch.js:
 *   _esc, _cleanDate, _applyFieldLabel
 *
 * Reads from window.* state owned by book-modal.js:
 *   _modalItemId, _modalAllCandidates
 *
 * Local state (IIFE-scoped):
 *   _sourceDetails, _bpFieldLabels, _bpAllFields, _brmOverrides
 *
 * i18n: reuses batchField, modalField, batchSkipped/SourceError
 * keys; adds brm* keys for the result classification labels.
 *
 * Exposes all top-level functions on window.
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    /* -------------------------------------------------------------------- */
    /* Per-source detail (expandable progress row)                           */
    /* -------------------------------------------------------------------- */
    var _sourceDetails = {};
    var _bpFieldLabels = {
        title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor, description: _i18n.batchFieldSynopsis,
        isbn: 'ISBN', publisher: _i18n.batchFieldPublisher, series: _i18n.batchFieldSeries,
        genres: _i18n.batchFieldGenre, published_date: _i18n.modalFieldPublished, cover: _i18n.batchFieldCover
    };
    var _bpAllFields = ['title', 'author', 'description', 'isbn', 'publisher', 'series', 'genres', 'published_date', 'cover'];

    function _bpEsc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _renderSourceDetail(itemId) {
        var container = document.getElementById('bp-detail-' + itemId);
        if (!container) return;

        var details = _sourceDetails[itemId] || [];
        if (details.length === 0) {
            container.innerHTML = '<div style="font-size:12px; color:var(--text-tertiary); padding:6px 0;">' + _i18n.sourceDetailsEmpty + '</div>';
            return;
        }

        var html = '';
        details.forEach(function(sd) {
            var iconClass = sd.ok ? 'ti-check' : 'ti-x';
            var iconColor = sd.ok ? 'var(--accent-green)' : 'var(--text-tertiary)';

            html += '<div class="bp-source-row">';
            html += '<div class="bp-source-icon"><i class="ti ' + iconClass + '" style="font-size:14px;color:' + iconColor + '"></i></div>';
            html += '<div class="bp-source-name">' + _bpEsc(sd.source) + '</div>';
            html += '<div class="bp-fields">';

            if (sd.ok && sd.fields_found && sd.fields_found.length > 0) {
                _bpAllFields.forEach(function(f) {
                    var found = sd.fields_found.indexOf(f) !== -1;
                    var icon = found ? '<i class="ti ti-check" style="font-size:11px"></i> ' : '';
                    if (found) {
                        html += '<span class="bp-field-tag bp-field-found bp-field-clickable" data-field="' + f + '" data-source="' + _bpEsc(sd.source || '') + '">'
                            + icon + _bpEsc(_bpFieldLabels[f]) + '</span>';
                    } else {
                        html += '<span class="bp-field-tag bp-field-missing">' + _bpEsc(_bpFieldLabels[f]) + '</span>';
                    }
                });
            } else {
                html += '<span class="bp-field-tag bp-field-missing">' + _i18n.noMatches + '</span>';
            }

            html += '</div></div>';
        });

        container.innerHTML = html;
        var bulkData = _bulkResultData[itemId];
        var candidates = (bulkData && bulkData.all_candidates) || [];
        container.addEventListener('click', function(e) {
            var tag = e.target.closest('.bp-field-clickable');
            if (!tag) return;

            var fieldKey = tag.dataset.field;
            var sourceName = tag.dataset.source;
            if (!fieldKey || !sourceName) return;

            var candidate = null;
            for (var i = 0; i < candidates.length; i++) {
                var c = candidates[i];
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
                    'Tillgangliga:', candidates.map(function(c) { return c.source; }));
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

    function toggleProgressDetail(itemId, icon) {
        var detail = document.getElementById('bp-detail-' + itemId);
        if (!detail) return;
        var expanded = detail.classList.toggle('expanded');
        if (icon) icon.classList.toggle('open', expanded);
        if (expanded) _renderSourceDetail(itemId);
    }

    /* -------------------------------------------------------------------- */
    /* Bulk result comparison modal                                          */
    /* -------------------------------------------------------------------- */
    var _brmItemId = null;
    var _bulkResultData = {};
    var _brmOverrides = {};

    function _brmEsc(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function _brmToggleSyn(el) {
        var td = el.parentNode;
        var preview = td.querySelector('.brm-syn-preview');
        var full = td.querySelector('.brm-syn-full');
        if (!preview || !full) return;
        var showingFull = full.style.display !== 'none';
        if (showingFull) {
            full.style.display = 'none';
            preview.style.display = '';
            el.textContent = 'Visa hela';
        } else {
            full.style.display = '';
            preview.style.display = 'none';
            el.textContent = 'Visa mindre';
        }
    }
    function _brmClassLabel(c) {
        return {
            'auto_apply':    _i18n.brmSavedAuto,
            'review_needed': _i18n.brmReviewRec,
            'no_match':      _i18n.brmNoSecure,
            'skipped':       _i18n.batchSkippedLabel,
            'source_error':  _i18n.batchSourceErrorLabel
        }[c] || c;
    }

    function openBulkResultModal(itemId) {
        _brmItemId = itemId;
        _brmOverrides = {};
        document.getElementById('bulkResultModal').style.display = 'flex';
        document.getElementById('brmFeedback').style.display = 'none';

        var data = _bulkResultData[itemId];
        var infoEl = document.getElementById('brmAutoApplyInfo');
        var saveBtn = document.getElementById('brmSaveBtn');
        if (infoEl) infoEl.style.display = 'none';
        if (saveBtn) saveBtn.style.display = '';

        if (!data) {
            document.getElementById('brmTitle').textContent = _i18n.brmNoResult;
            document.getElementById('brmMeta').textContent = '';
            document.getElementById('brmBody').innerHTML =
                '<tr><td colspan="4">' + _i18n.noCachedResultRow + '</td></tr>';
            return;
        }

        var isAutoApply = data.classification === 'auto_apply';

        document.getElementById('brmTitle').textContent = isAutoApply
            ? _i18n.brmAutoAdded
            : (data.title || _i18n.bookHeader);
        var metaParts = [];
        if (isAutoApply && data.title) metaParts.push(data.title);
        if (data.source) metaParts.push(_i18n.sourceShort + ' ' + data.source);
        if (data.score !== null && data.score !== undefined) {
            metaParts.push(_i18n.scoreShort + ' ' + Math.round(data.score));
        }
        metaParts.push(_brmClassLabel(data.classification));
        document.getElementById('brmMeta').textContent = metaParts.join(' · ');

        if (isAutoApply) {
            if (saveBtn) saveBtn.style.display = 'none';
            var details = data.apply_details || {};
            var added = details.fields_added || [];
            var replaced = details.fields_replaced || [];
            var skipped = details.fields_skipped || [];
            var lines = [];
            if (added.length === 0 && replaced.length === 0 && skipped.length === 0) {
                lines.push(_i18n.noChangesAlreadyAll);
            } else {
                lines.push(_i18n.keptOnlyEmpty);
                if (replaced.length) {
                    var qNotes = data.quality_notes || {};
                    var noted = [];
                    replaced.forEach(function(f) {
                        if (qNotes[f]) {
                            noted.push(_applyFieldLabel(f) + ' ' + _i18n.brmReplaced + ' ' + qNotes[f] + '.');
                        }
                    });
                    if (noted.length) lines = lines.concat(noted);
                    else lines.push(_i18n.replacedNFields.replace('{count}', replaced.length));
                }
            }
            if (infoEl) {
                infoEl.style.display = 'block';
                infoEl.innerHTML = lines.map(function(l) { return _brmEsc(l); }).join('<br>');
            }
        }

        // Cover compare row — current (DB) vs. fetched (external URL)
        var beforeCoverPath = (data.before && data.before.cover_path) || '';
        var fetchedCoverUrl = (data.candidate && data.candidate.cover_url) || '';
        var emptyBox =
            '<div style="width:80px; height:110px; background:var(--bg-tertiary); '
            + 'border-radius:4px; display:flex; align-items:center; justify-content:center; '
            + 'color:var(--text-tertiary); font-size:12px;">';
        var coverHtml = '<div style="display:flex; gap:20px; margin-bottom:16px; align-items:flex-start;">';
        coverHtml += '<div style="text-align:center;">'
            + '<div style="font-size:12px; color:var(--text-secondary); margin-bottom:4px;">' + _i18n.brmCurrent + '</div>';
        if (beforeCoverPath) {
            coverHtml += '<img src="/cover/' + itemId
                + '" style="max-height:120px; border-radius:4px; '
                + 'border:0.5px solid var(--border-light);" alt="' + _i18n.brmCurrentCover + '">';
        } else {
            coverHtml += emptyBox + _i18n.brmMissingParen + '</div>';
        }
        coverHtml += '</div>';
        coverHtml += '<div style="text-align:center;">'
            + '<div style="font-size:12px; color:var(--text-secondary); margin-bottom:4px;">' + _i18n.fetchedLabel + '</div>';
        if (fetchedCoverUrl) {
            coverHtml += '<img src="' + _brmEsc(fetchedCoverUrl)
                + '" style="max-height:120px; border-radius:4px; '
                + 'border:0.5px solid var(--border-light);" alt="' + _i18n.brmFetchedCover + '">';
        } else {
            coverHtml += emptyBox + _i18n.brmNoneParen + '</div>';
        }
        coverHtml += '</div>';
        coverHtml += '</div>';

        var brmBody = document.getElementById('brmBody');
        var coverDiv = document.getElementById('brmCoverCompare');
        if (!coverDiv) {
            coverDiv = document.createElement('div');
            coverDiv.id = 'brmCoverCompare';
            brmBody.parentElement.parentElement.insertBefore(
                coverDiv, brmBody.parentElement);
        }
        coverDiv.innerHTML = coverHtml;

        var fields = [
            { key: 'title',          label: _i18n.batchFieldTitle },
            { key: 'author',         label: _i18n.batchFieldAuthor },
            { key: 'series',         label: _i18n.batchFieldSeries },
            { key: 'series_index',   label: _i18n.batchFieldPart },
            { key: 'isbn',           label: 'ISBN' },
            { key: 'publisher',      label: _i18n.batchFieldPublisher },
            { key: 'language',       label: _i18n.batchFieldLanguage },
            { key: 'genres',         label: _i18n.batchFieldGenre },
            { key: 'published_date', label: _i18n.batchFieldPublicationDate },
            { key: 'description',    label: _i18n.batchFieldSynopsis }
        ];

        var before = data.before;
        var after = data.candidate;
        var fieldConfidence = data.field_confidence || {};
        // Only show low-confidence flags for review_needed candidates;
        // auto_apply already has its own per-field colour scheme.
        var showConfidence = data.classification === 'review_needed';
        var tbody = document.getElementById('brmBody');
        tbody.innerHTML = '';

        fields.forEach(function(f) {
            var b = (before[f.key] || '').toString().trim();
            var a = (after[f.key] || '').toString().trim();
            if (f.key === 'published_date') { b = _cleanDate(b); a = _cleanDate(a); }
            var changed = b !== a && a !== '';
            var checkable = a !== '' && b !== a;
            var isSynopsis = f.key === 'description';
            var lowConfidence = showConfidence && fieldConfidence[f.key] === 'low';

            var tr = document.createElement('tr');
            tr.dataset.field = f.key;
            tr.classList.add('brm-field-row');
            if (changed) tr.classList.add('brm-changed');
            if (lowConfidence) tr.classList.add('brm-confidence-low');
            tr.addEventListener('click', function(e) {
                // Don't toggle when interacting with checkbox / synopsis links etc.
                if (e.target.closest('input, a, .brm-expand-toggle')) return;
                _brmToggleFieldSources(tr, f.key);
            });

            var checkHtml = '';
            if (checkable) {
                checkHtml = '<span class="brm-arrow" title="' + _i18n.useFetchedValue + '">→</span>'
                    + '<input type="checkbox" class="brm-check" data-field="'
                    + f.key + '" title="' + _i18n.useFetchedValue + '" checked>';
            }

            function _cellContent(text) {
                if (!text) return _brmEsc('(tomt)');
                if (isSynopsis && text.length > 200) {
                    var preview = _brmEsc(text.substring(0, 200)) + '…';
                    var full = _brmEsc(text);
                    return '<span class="brm-syn-preview">' + preview + '</span>'
                        + '<span class="brm-syn-full" style="display:none;">' + full + '</span>'
                        + '<br><span class="brm-expand-toggle" onclick="_brmToggleSyn(this)">Visa hela</span>';
                }
                return _brmEsc(text);
            }

            var fieldCellCls = 'brm-td-field';
            var currentCellCls = 'brm-td-current' + (b ? '' : ' brm-empty');
            var fetchedCellCls = 'brm-td-fetched' + (a ? '' : ' brm-empty');

            var fetchedHtml = _cellContent(a);
            var note = (data.quality_notes || {})[f.key];
            if (note) {
                fetchedHtml += '<br><small class="brm-quality-note">⬆ '
                    + _brmEsc(note) + '</small>';
            }

            var labelHtml = '<span class="expand-hint">▸</span>'
                + (lowConfidence ? '<span class="brm-confidence-icon" title="' + _i18n.lowConfidence + '">⚠</span>' : '')
                + '<strong>' + _brmEsc(f.label) + '</strong>';
            tr.innerHTML =
                '<td class="' + fieldCellCls + '">' + labelHtml + '</td>' +
                '<td class="' + currentCellCls + '">' + _cellContent(b) + '</td>' +
                '<td class="brm-td-pick">' + checkHtml + '</td>' +
                '<td class="' + fetchedCellCls + '">' + fetchedHtml + '</td>';
            tbody.appendChild(tr);
        });

        if (isAutoApply) {
            var formatCount = (data.item_ids || [itemId]).length;
            document.getElementById('brmMeta').textContent +=
                ' — Sparat till ' + formatCount + ' format.';
            var details2 = data.apply_details || {};
            var addedSet = {};
            (details2.fields_added || []).forEach(function(f) { addedSet[f] = 1; });
            var replacedSet = {};
            (details2.fields_replaced || []).forEach(function(f) { replacedSet[f] = 1; });
            var skippedSet = {};
            (details2.fields_skipped || []).forEach(function(f) { skippedSet[f] = 1; });

            tbody.querySelectorAll('tr').forEach(function(tr) {
                var key = tr.dataset.field;
                var pickCell = tr.querySelector('.brm-td-pick');
                if (!pickCell) return;
                if (addedSet[key]) {
                    tr.classList.add('brm-aa-added');
                    pickCell.innerHTML = '<span class="brm-aa-badge added">Nytt</span>';
                } else if (replacedSet[key]) {
                    tr.classList.add('brm-aa-replaced');
                    pickCell.innerHTML = '<span class="brm-aa-badge replaced">Ersatt</span>';
                } else if (skippedSet[key]) {
                    tr.classList.add('brm-aa-skipped');
                    pickCell.innerHTML = '<span class="brm-aa-badge skipped">' + _i18n.kept + '</span>';
                } else {
                    pickCell.innerHTML = '';
                }
            });
        }
    }

    function closeBulkResultModal() {
        document.getElementById('bulkResultModal').style.display = 'none';
        _brmItemId = null;
        _brmOverrides = {};
        var coverDiv = document.getElementById('brmCoverCompare');
        if (coverDiv) coverDiv.innerHTML = '';
    }

    function _brmCellPreview(text, fieldKey) {
        if (!text) return _brmEsc('(tomt)');
        if (fieldKey === 'description' && text.length > 200) {
            return '<span class="brm-syn-preview">' + _brmEsc(text.substring(0, 200)) + '…</span>'
                + '<span class="brm-syn-full" style="display:none;">' + _brmEsc(text) + '</span>'
                + '<br><span class="brm-expand-toggle" onclick="_brmToggleSyn(this)">Visa hela</span>';
        }
        return _brmEsc(text);
    }

    function _brmToggleFieldSources(row, fieldKey) {
        var existing = row.nextElementSibling;
        if (existing && existing.classList.contains('brm-field-sources')) {
            existing.remove();
            row.classList.remove('brm-expanded');
            return;
        }
        // Collapse any other open source panel first.
        document.querySelectorAll('#brmBody tr.brm-field-sources').forEach(function(r) {
            var prev = r.previousElementSibling;
            if (prev) prev.classList.remove('brm-expanded');
            r.remove();
        });

        var data = _bulkResultData[_brmItemId];
        var candidates = (data && data.all_candidates) || [];
        var currentValue = (_brmOverrides[fieldKey] !== undefined)
            ? _brmOverrides[fieldKey]
            : ((data && data.candidate && data.candidate[fieldKey]) || '');

        var detail = document.createElement('tr');
        detail.className = 'brm-field-sources';
        var td = document.createElement('td');
        td.colSpan = 4;
        td.style.padding = '0';

        var wrap = document.createElement('div');
        wrap.className = 'field-sources-wrap';
        var label = document.createElement('div');
        label.className = 'field-sources-label';
        label.textContent = _i18n.chooseSource;
        wrap.appendChild(label);

        var rendered = 0;
        candidates.forEach(function(c, i) {
            var value = (c[fieldKey] || '').toString();
            if (!value) return;
            rendered += 1;

            var opt = document.createElement('div');
            opt.className = 'source-option';
            opt.dataset.field = fieldKey;
            opt.dataset.value = value;
            if (value === currentValue) opt.classList.add('source-option-selected');

            var head = document.createElement('div');
            head.innerHTML =
                '<span class="source-option-source">' + _brmEsc(c.source || (_i18n.sourceWord + ' ' + (i + 1))) + '</span>'
                + '<span class="source-option-score">' + _i18n.scoreWord + ' ' + (c.score != null ? c.score : '–') + '</span>';
            opt.appendChild(head);

            var body = document.createElement('div');
            body.className = 'source-option-value';
            if (fieldKey === 'description' && value.length > 200) {
                var shortSpan = document.createElement('span');
                shortSpan.textContent = value.substring(0, 200) + '… ';
                var fullSpan = document.createElement('span');
                fullSpan.style.display = 'none';
                fullSpan.textContent = value;
                var toggle = document.createElement('a');
                toggle.href = '#';
                toggle.className = 'synopsis-toggle';
                toggle.textContent = 'Visa mer';
                toggle.addEventListener('click', function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    shortSpan.style.display = 'none';
                    toggle.style.display = 'none';
                    fullSpan.style.display = 'inline';
                });
                body.appendChild(shortSpan);
                body.appendChild(toggle);
                body.appendChild(fullSpan);
            } else {
                body.textContent = value;
            }
            opt.appendChild(body);

            opt.addEventListener('click', function(ev) {
                ev.stopPropagation();
                _brmSelectSourceValue(fieldKey, opt, value);
            });
            wrap.appendChild(opt);
        });

        if (rendered === 0) {
            var empty = document.createElement('div');
            empty.className = 'source-option-empty';
            empty.textContent = _i18n.noSourcesForField;
            wrap.appendChild(empty);
        }

        td.appendChild(wrap);
        detail.appendChild(td);
        row.parentNode.insertBefore(detail, row.nextSibling);
        row.classList.add('brm-expanded');
    }

    function _brmSelectSourceValue(fieldKey, optEl, value) {
        // Mark this option as selected within its panel.
        var wrap = optEl.parentNode;
        wrap.querySelectorAll('.source-option').forEach(function(o) {
            o.classList.remove('source-option-selected');
        });
        optEl.classList.add('source-option-selected');

        // Update the "Fetched" cell in the field row above the source panel.
        var detailRow = optEl.closest('tr.brm-field-sources');
        var fieldRow = detailRow ? detailRow.previousElementSibling : null;
        if (fieldRow) {
            var fetchedCell = fieldRow.querySelector('td.brm-td-fetched');
            if (fetchedCell) {
                fetchedCell.classList.remove('brm-empty');
                fetchedCell.innerHTML = _brmCellPreview(value, fieldKey);
            }
            // Auto-check the field's "use this" checkbox.
            var cb = fieldRow.querySelector('.brm-check');
            if (cb) cb.checked = true;
            fieldRow.classList.add('brm-changed');
        }

        _brmOverrides[fieldKey] = value;
    }

    function saveBulkResult() {
        var itemId = _brmItemId;
        if (!itemId) return;

        var checked = document.querySelectorAll('.brm-check:checked');
        var fb = document.getElementById('brmFeedback');
        if (checked.length === 0) {
            fb.style.display = 'block';
            fb.className = 'modal-feedback modal-feedback-error';
            fb.textContent = _i18n.chooseFieldToUpdate;
            return;
        }

        var data = _bulkResultData[itemId];
        if (!data) {
            fb.style.display = 'block';
            fb.className = 'modal-feedback modal-feedback-error';
            fb.textContent = _i18n.noCachedResult;
            return;
        }

        var fields = [];
        checked.forEach(function(cb) { fields.push(cb.dataset.field); });

        var before = data.before;
        var candidate = data.candidate;
        var payload = {
            title:          before.title || '',
            author:         before.author || '',
            series:         before.series || '',
            series_index:   before.series_index || '',
            isbn:           before.isbn || '',
            publisher:      before.publisher || '',
            language:       before.language || '',
            genres:         before.genres || '',
            published_date: _cleanDate(before.published_date || ''),
            description:    before.description || ''
        };
        fields.forEach(function(f) {
            if (!(f in payload)) return;
            // Per-field override from the source picker takes precedence over
            // the auto-picked best candidate value.
            if (Object.prototype.hasOwnProperty.call(_brmOverrides, f)) {
                payload[f] = _brmOverrides[f];
            } else {
                payload[f] = candidate[f] || '';
            }
        });
        if (payload.published_date) payload.published_date = _cleanDate(payload.published_date);

        var allIds = data.item_ids || [itemId];
        var completed = 0;
        var errors = 0;

        fb.style.display = 'block';
        fb.className = 'modal-feedback modal-feedback-info';
        fb.textContent = 'Sparar till ' + allIds.length + ' format…';

        allIds.forEach(function(id) {
            fetch('/metadata/' + id + '/save-json', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
                .then(function(r) { return r.json(); })
                .then(function(result) {
                    if (!result.ok) errors++;
                    completed++;
                    if (completed === allIds.length) {
                        _onBulkSaveComplete(itemId, allIds, fields, errors, fb);
                    }
                })
                .catch(function() {
                    errors++;
                    completed++;
                    if (completed === allIds.length) {
                        _onBulkSaveComplete(itemId, allIds, fields, errors, fb);
                    }
                });
        });
    }

    function _onBulkSaveComplete(itemId, allIds, fields, errors, fb) {
        if (errors === 0) {
            fb.className = 'modal-feedback modal-feedback-success';
            fb.textContent = _i18n.savedFieldsBooks.replace('{fields}', fields.length).replace('{books}', allIds.length);
            var resultCell = document.getElementById('bp-result-' + itemId);
            if (resultCell) resultCell.innerHTML = '<span class="bp-ok">✓ Sparad</span>';
            setTimeout(closeBulkResultModal, 1200);
        } else {
            fb.className = 'modal-feedback modal-feedback-error';
            fb.textContent = errors + ' av ' + allIds.length + ' format kunde inte sparas.';
        }
    }

    document.getElementById('bulkResultModal').addEventListener('click', function(e) {
        if (e.target === this) closeBulkResultModal();
    });


    /* ------------------------------------------------------------------ */
    /* Publish all entry points on window                                   */
    /* ------------------------------------------------------------------ */
    window._bpEsc = _bpEsc;
    window._renderSourceDetail = _renderSourceDetail;
    window.toggleProgressDetail = toggleProgressDetail;
    window._brmEsc = _brmEsc;
    window._brmToggleSyn = _brmToggleSyn;
    window._brmClassLabel = _brmClassLabel;
    window.openBulkResultModal = openBulkResultModal;
    window.closeBulkResultModal = closeBulkResultModal;
    window._brmCellPreview = _brmCellPreview;
    window._brmToggleFieldSources = _brmToggleFieldSources;
    window._brmSelectSourceValue = _brmSelectSourceValue;
    window.saveBulkResult = saveBulkResult;
    window._onBulkSaveComplete = _onBulkSaveComplete;
})(window, document);
