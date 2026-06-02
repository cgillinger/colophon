/* ------------------------------------------------------------------ *
 * batch.js — Batch operations (wizard + review + search + delete)
 *
 * Owns the entire "Batch operations" flow: the multi-step wizard
 * (fields → search → review → done), the SSE-driven batch search,
 * the AI search variant, batch delete, plus three review sub-views
 * (text-field table, text-field card, synopsis/cover/summary).
 *
 * Reads i18n strings from window.__colophonConfig.i18n (batchStep*,
 * batchField*, batchReviewLabel etc. — added to the bridge for this
 * extraction).
 *
 * Reads from window.* (set by other modules):
 *   _grouped — owned by filters-sort-paging.js
 *   _i18n    — same shape as elsewhere; sourced from the bridge
 *
 * Exposes generic helpers on window for book-modal.js and
 * bulk-result-modal.js to consume:
 *   _esc, _cleanDate, _applyFieldLabel, _resultLabel, _resultTooltip
 *
 * Exposes onclick / cross-module entry points on window. Every
 * top-level `function X()` here is mirrored to window.X for
 * uniformity — see the trailing publish block.
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    /* ------------------------------------------------------------------ */
    /* Batch wizard — state and step navigation                           */
    /* ------------------------------------------------------------------ */
    var _batchWizard = {
        step: 1,
        selectedFields: [],
        selectedItemIds: [],
        searchCache: {},
        reviewQueue: [],
        reviewIndex: 0,
        results: { saved: 0, skipped: 0, noMatch: 0, fieldCounts: {} }
    };

    var _BATCH_TEXT_FIELDS = [
        'title', 'author', 'series', 'isbn',
        'publisher', 'language', 'genres', 'published_date'
    ];

    var _batchSSESource = null;

    /* --- Fetch-depth chooser (Snabb / Normal / Djup → fast / more / deep) ---
     * Passed as ?mode= on the batch bulk/stream; the backend resolves the saved
     * default (METADATA_FETCH_MODE) when absent. Same control as the single-book
     * modal, so depth selection is consistent whether you enrich one or a hundred. */
    function _batchDefaultMode() {
        return (window.__colophonConfig && window.__colophonConfig.fetchMode) || 'more';
    }
    var _batchFetchModeSel = _batchDefaultMode();
    function _setBatchFetchMode(mode) {
        var box = document.getElementById('batchFetchMode');
        if (!box) return;
        box.querySelectorAll('.fetch-mode-btn').forEach(function (b) {
            var on = b.getAttribute('data-mode') === mode;
            b.classList.toggle('active', on);
            if (on) _batchFetchModeSel = mode;
        });
    }
    function _initBatchFetchMode() {
        var box = document.getElementById('batchFetchMode');
        if (!box) return;
        if (!box._wired) {
            box._wired = true;
            box.querySelectorAll('.fetch-mode-btn').forEach(function (b) {
                b.addEventListener('click', function () {
                    _setBatchFetchMode(b.getAttribute('data-mode'));
                });
            });
        }
        _setBatchFetchMode(_batchDefaultMode());
    }

    function _resetBatchWizardState() {
        _batchWizard.step = 1;
        _batchWizard.selectedFields = [];
        _batchWizard.selectedItemIds = [];
        _batchWizard.searchCache = {};
        _batchWizard.reviewQueue = [];
        _batchWizard.reviewIndex = 0;
        _batchWizard.results = { saved: 0, skipped: 0, noMatch: 0, fieldCounts: {} };
    }

    var _STEP_LABELS = ['', _i18n.batchStep1, _i18n.batchStep2, _i18n.batchStep3, _i18n.batchStep4];

    function _renderWizardSteps() {
        var indicator = document.getElementById('batchWizardSteps');
        if (!indicator) return;
        var currentStep = _batchWizard.step;
        var parts = [];
        for (var i = 1; i <= 4; i++) {
            if (i > 1) parts.push('<span class="separator">→</span>');
            var label = _STEP_LABELS[i];
            if (i < currentStep) {
                parts.push('<a class="batch-step-link completed step-' + i + '" href="#" onclick="event.preventDefault();_batchGoToStep(' + i + ')">' + label + '</a>');
            } else if (i === currentStep) {
                parts.push('<span class="batch-step-link active step-' + i + '">' + label + '</span>');
            } else {
                parts.push('<span class="batch-step-link step-' + i + '">' + label + '</span>');
            }
        }
        indicator.innerHTML = parts.join('');
    }

    function _batchGoToStep(step) {
        if (step >= _batchWizard.step) return;
        if (step === 3) {
            _batchWizard.reviewIndex = 0;
            _batchSetStep(3);
            var container = document.getElementById('batchReviewContainer');
            if (container) _batchRenderTextFieldReview(container);
        } else if (step === 1) {
            _batchSetStep(1);
        } else if (step === 2) {
            _batchSetStep(2);
        }
    }

    function _batchSetStep(step) {
        _batchWizard.step = step;
        for (var i = 1; i <= 4; i++) {
            var el = document.getElementById('batchStep' + i);
            if (el) el.style.display = (i === step) ? '' : 'none';
        }
        _renderWizardSteps();
        _batchUpdateSubtitle();
        if (step === 4) {
            var sc = document.getElementById('batchSummaryContainer');
            if (sc) _batchRenderSummary(sc);
        }
    }

    function _batchUpdateSubtitle() {
        var subtitle = document.getElementById('batchSubtitle');
        if (!subtitle) return;
        var bookCount = (_batchWizard.selectedItemIds || []).length;
        if (!bookCount) return;
        var bookText = window._pluralize(
            bookCount, 'nBookSelectedOne', 'nBooksSelectedMany'
        );
        var fields = _batchWizard.selectedFields || [];
        if (_batchWizard.step >= 2 && fields.length > 0) {
            var fieldLabels = fields.map(function(f) {
                return _applyFieldLabels[f] || f;
            });
            subtitle.textContent = bookText + ' · ' + fieldLabels.join(', ');
        } else {
            subtitle.textContent = bookText;
        }
    }

    function openBatchModal() {
        var checked = document.querySelectorAll('.book-checkbox:checked');
        if (checked.length === 0) return;

        _resetBatchWizardState();

        var itemIds = _getBatchItemIds();
        _batchWizard.selectedItemIds = itemIds.slice();

        var subtitle = '';
        var bookCount = itemIds.length;
        if (window._grouped) {
            var groupKeys = new Set();
            checked.forEach(function(cb) {
                var row = cb.closest('tr');
                if (row && row.dataset.groupKey) groupKeys.add(row.dataset.groupKey);
            });
            subtitle = window._pluralize(
                groupKeys.size, 'nGroupSelectedOne', 'nGroupsSelectedMany'
            );
        } else {
            subtitle = window._pluralize(
                bookCount, 'nBookSelectedOne', 'nBooksSelectedMany'
            );
        }

        document.getElementById('batchSubtitle').textContent = subtitle;
        var bookCountEl = document.getElementById('batchBookCount');
        if (bookCountEl) bookCountEl.textContent = bookCount;

        document.getElementById('batchModal').style.display = 'flex';
        _batchSetStep(1);
        _initBatchFetchMode();
    }

    function closeBatchModal() {
        document.getElementById('batchModal').style.display = 'none';
        _resetBatchWizardState();
        _batchSetStep(1);
    }

    document.getElementById('batchModal').addEventListener('click', function(e) {
        if (e.target === this) closeBatchModal();
    });

    function _batchModalVisible() {
        var el = document.getElementById('batchModal');
        return el && el.style.display === 'flex';
    }

    function toggleBwFields(checked) {
        document.querySelectorAll('.bw-field').forEach(function(cb) {
            cb.checked = checked;
        });
    }

    function batchWizardStartSearch() {
        var fields = Array.from(document.querySelectorAll('.bw-field:checked'))
            .map(function(cb) { return cb.value; });

        if (fields.length === 0) {
            alert(_i18n.chooseAtLeastOneField);
            return;
        }

        _batchWizard.selectedFields = fields;

        var queue = [];
        var hasTextField = fields.some(function(f) {
            return _BATCH_TEXT_FIELDS.indexOf(f) !== -1;
        });
        if (hasTextField) queue.push('textfields');
        if (fields.indexOf('description') !== -1) queue.push('synopsis');
        if (fields.indexOf('cover') !== -1) queue.push('cover');
        _batchWizard.reviewQueue = queue;
        _batchWizard.reviewIndex = 0;

        _batchSetStep(2);
        startBatchSearch();
    }

    var _TEXTFIELD_DISPLAY_ORDER = [
        'title', 'author', 'series', 'series_index',
        'isbn', 'publisher', 'language', 'genres', 'published_date'
    ];
    var _brtCellValues = {};
    var _brtCols = [];
    var _brtAltPanelData = {};
    var _brtSourceCandidates = {};

    function _isValidLanguageCode(code) {
        if (!code || typeof code !== 'string') return false;
        var c = code.trim().toLowerCase();
        return c.length >= 2 && c.length <= 3 && /^[a-z]+$/.test(c);
    }

    function _brtCellHtml(itemId, field, current, fetchedVal) {
        if (!fetchedVal) {
            return '<span class="brt-no-match">—</span>';
        } else if (fetchedVal === current) {
            return '<span class="brt-same">' + _esc(fetchedVal) + ' ✓</span>';
        } else {
            var newValHtml;
            if (field === 'language' && !_isValidLanguageCode(fetchedVal)) {
                newValHtml = '<span class="brt-new-value brt-invalid" id="brt-cell-' + itemId + '-' + field +
                    '" title="' + _i18n.invalidLanguageCode + '">⚠ ' + _esc(fetchedVal) + '</span>';
            } else {
                newValHtml = '<span class="brt-new-value" id="brt-cell-' + itemId + '-' + field + '">' +
                    _esc(fetchedVal) + '</span>';
            }
            return '<span class="brt-current">' + _esc(current || '(tomt)') + '</span>' +
                '<span class="brt-arrow">→</span>' + newValHtml;
        }
    }

    function _brtToggleExpandRow(tr) {
        var expandTr = tr.nextElementSibling;
        if (!expandTr || !expandTr.classList.contains('batch-review-expand')) return;
        var isExpanded = expandTr.style.display !== 'none';
        expandTr.style.display = isExpanded ? 'none' : '';
        tr.classList.toggle('expanded', !isExpanded);
    }

    function batchUseSource(itemId, idx) {
        var sources = _brtSourceCandidates[itemId];
        if (!sources || !sources[idx]) return;
        var c = sources[idx];
        if (!_brtCellValues[itemId]) _brtCellValues[itemId] = {};
        var before = (_batchWizard.searchCache[itemId] || {}).before || {};
        _brtCols.forEach(function(f) {
            var v = (c[f] != null) ? String(c[f]) : '';
            if (f === 'published_date') v = _cleanDate(v);
            if (!v) return;
            _brtCellValues[itemId][f] = v;
            var cur = (before[f] != null) ? String(before[f]) : '';
            if (f === 'published_date') cur = _cleanDate(cur);
            var td = document.querySelector('tr.batch-review-row[data-item-id="' + itemId + '"] td[data-field="' + f + '"]');
            if (td) td.innerHTML = _brtCellHtml(itemId, f, cur, v);
        });
        var expandTr = document.querySelector('tr.batch-review-expand[data-item-id="' + itemId + '"]');
        if (expandTr) {
            expandTr.querySelectorAll('.source-alt-row').forEach(function(row, i) {
                row.classList.toggle('selected', i === idx);
            });
        }
        var cb = document.querySelector('.brt-row-check[data-item-id="' + itemId + '"]');
        if (cb) cb.checked = true;
    }

    function _batchRenderReview() {
        var container = document.getElementById('batchReviewContainer');
        if (!container) return;
        var currentReview = _batchWizard.reviewQueue[_batchWizard.reviewIndex];
        if (!currentReview) { _batchSetStep(4); return; }
        if (currentReview === 'textfields') {
            _batchRenderTextFieldReview(container);
        } else if (currentReview === 'synopsis') {
            _batchRenderSynopsisReview(container);
        } else if (currentReview === 'cover') {
            _batchRenderCoverReview(container);
        } else {
            container.innerHTML = '<p>' + _i18n.reviewViewFor + ' ' + _esc(currentReview) + ' (' + _i18n.notImplemented + ')</p>';
        }
    }

    /* Legacy table-based renderer — preserved as fallback only. NOT called. */
    function _batchRenderTextFieldReview_TABLE(container) {
        var selectedFields = _batchWizard.selectedFields;

        _brtCols = [];
        _TEXTFIELD_DISPLAY_ORDER.forEach(function(f) {
            if (f === 'series_index') {
                if (selectedFields.indexOf('series') !== -1) _brtCols.push('series_index');
            } else {
                if (selectedFields.indexOf(f) !== -1) _brtCols.push(f);
            }
        });

        _brtCellValues = {};
        _brtAltPanelData = {};
        _brtSourceCandidates = {};

        var colLabels = _brtCols.map(function(f) {
            return '<th>' + _esc(_applyFieldLabels[f] || f) + '</th>';
        }).join('');

        var rows = [];
        _batchWizard.selectedItemIds.forEach(function(itemId) {
            var data = _batchWizard.searchCache[itemId];
            if (!data) return;
            var before = data.before || {};
            var candidate = data.candidate || {};
            var allCandidates = data.all_candidates || [];

            _brtCellValues[itemId] = {};
            var hasChange = false;

            var hasInvalidOnly = true;
            var tds = _brtCols.map(function(field) {
                var current = (before[field] != null) ? String(before[field]) : '';
                var fetched = (candidate[field] != null) ? String(candidate[field]) : '';
                if (field === 'published_date') { current = _cleanDate(current); fetched = _cleanDate(fetched); }
                _brtCellValues[itemId][field] = fetched || current;
                if (fetched && fetched !== current) {
                    hasChange = true;
                    var invalid = (field === 'language' && !_isValidLanguageCode(fetched));
                    if (!invalid) hasInvalidOnly = false;
                }
                return '<td data-field="' + field + '">' + _brtCellHtml(itemId, field, current, fetched) + '</td>';
            }).join('');
            if (!hasChange) hasInvalidOnly = false;

            // Build deduplicated source list (sources with ≥1 value for selected fields)
            var seenSrc = {};
            var srcList = [];
            var bestSrc = data.source || '';
            var bestHasVal = _brtCols.some(function(f) { return candidate[f] != null && String(candidate[f]); });
            if (bestHasVal) {
                seenSrc[bestSrc] = true;
                srcList.push(Object.assign({}, candidate, { source: bestSrc, score: data.score || 0 }));
            }
            allCandidates.forEach(function(c) {
                var src = c.source || '';
                if (seenSrc[src]) return;
                var hasVal = _brtCols.some(function(f) { return c[f] != null && String(c[f]); });
                if (!hasVal) return;
                seenSrc[src] = true;
                srcList.push(c);
            });
            _brtSourceCandidates[itemId] = srcList;
            var hasAlts = srcList.length > 1;

            var title = data.title || String(itemId);
            if (title.length > 35) title = title.substring(0, 35) + '…';
            var isChecked = (hasChange && !hasInvalidOnly) ? ' checked' : '';
            var expandArrow = hasAlts ? '<span class="expand-arrow">▶</span>' : '';
            var rowCls = 'batch-review-row' + (hasAlts ? ' has-alts' : '');
            var rowClick = hasAlts ? ' onclick="_brtToggleExpandRow(this)"' : '';

            rows.push(
                '<tr class="' + rowCls + '" data-item-id="' + itemId + '"' + rowClick + '>' +
                '<td><label style="display:flex;align-items:center;gap:4px;cursor:pointer;" onclick="event.stopPropagation();">' +
                expandArrow +
                '<input type="checkbox" class="brt-row-check" data-item-id="' + itemId + '"' + isChecked + ' onclick="event.stopPropagation();">' +
                '<span>' + _esc(title) + '</span></label></td>' +
                tds + '</tr>'
            );

            if (hasAlts) {
                var altRowsHtml = srcList.map(function(c, idx) {
                    var isFirst = (idx === 0);
                    var fieldsHtml = _brtCols.map(function(f) {
                        var v = (c[f] != null) ? String(c[f]) : '';
                        if (f === 'published_date') v = _cleanDate(v);
                        if (!v) return '';
                        return '<span class="source-alt-field"><span class="source-alt-field-label">' +
                            _esc(_applyFieldLabels[f] || f) + '</span>' + _esc(v) + '</span>';
                    }).filter(Boolean).join('');
                    return '<div class="source-alt-row' + (isFirst ? ' selected' : '') + '">' +
                        '<div class="source-alt-header">' +
                        '<span class="source-alt-name">' + _esc(c.source || _i18n.unknownSource) + '</span>' +
                        '<button class="source-alt-use" onclick="event.stopPropagation();batchUseSource(\'' + itemId + '\',' + idx + ')">' + _i18n.useSource + '</button>' +
                        '</div>' +
                        (fieldsHtml ? '<div class="source-alt-fields">' + fieldsHtml + '</div>' : '') +
                        '</div>';
                }).join('');
                rows.push(
                    '<tr class="batch-review-expand" data-item-id="' + itemId + '" style="display:none;">' +
                    '<td colspan="' + (_brtCols.length + 1) + '">' +
                    '<div class="source-alternatives">' + altRowsHtml + '</div>' +
                    '</td></tr>'
                );
            }
        });

        var fieldSummary = _brtCols.map(function(f) {
            return '<strong>' + _esc(_applyFieldLabels[f] || f) + '</strong>';
        }).join(' · ');

        var manyCols = _brtCols.length > 5;
        var tableCls = 'batch-review-table' + (manyCols ? ' brt-many-cols' : '');
        container.innerHTML =
            '<div class="batch-review-header">Granskar: ' + fieldSummary +
            ' <a href="#" class="batch-add-field" onclick="event.preventDefault();_batchShowAddField(this)">[' + _i18n.addField + ']</a></div>' +
            '<div style="font-size:11px; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.4px; margin-bottom:6px;">' +
            _i18n.currentArrowFetched +
            '</div>' +
            '<div class="batch-review-scroll" id="batchReviewScroll">' +
            '<table class="' + tableCls + '"><thead><tr><th>Bok</th>' + colLabels + '</tr></thead>' +
            '<tbody>' + rows.join('') + '</tbody>' +
            '</table></div>' +
            '<div style="margin-top:16px;display:flex;gap:8px;align-items:center;">' +
            '<button type="button" class="btn primary" onclick="_batchSaveTextFields()">' + _i18n.saveSelectedContinue + '</button>' +
            '<button type="button" class="btn ghost" onclick="_batchSkipReview()">' + _i18n.skip + '</button>' +
            '<button type="button" class="btn ghost" onclick="closeBatchModal()">Avbryt</button>' +
            '</div>';
        _brtUpdateScrollHint();
    }

    function _brtUpdateScrollHint() {
        var el = document.getElementById('batchReviewScroll');
        if (!el) return;
        function update() {
            var node = document.getElementById('batchReviewScroll');
            if (!node) {
                window.removeEventListener('resize', update);
                return;
            }
            if (node.scrollWidth > node.clientWidth + 4 &&
                node.scrollLeft + node.clientWidth < node.scrollWidth - 4) {
                node.classList.add('has-overflow');
            } else {
                node.classList.remove('has-overflow');
            }
        }
        update();
        el.addEventListener('scroll', update);
        if (!_brtScrollResizeBound) {
            window.addEventListener('resize', update);
            _brtScrollResizeBound = true;
        }
    }
    var _brtScrollResizeBound = false;

    function _brtToggleAltPanel(iconEl, itemId, field) {
        var cell = iconEl.closest('td');
        var existing = cell.querySelector('.brt-alt-panel');
        if (existing) { existing.remove(); return; }

        var data = _batchWizard.searchCache[itemId];
        if (!data) return;
        var candidate = data.candidate || {};
        var allCandidates = data.all_candidates || [];
        var bestVal = (candidate[field] != null) ? String(candidate[field]) : '';

        var alts = [];
        if (bestVal) alts.push({ value: bestVal, source: data.source || '', score: data.score || 0 });
        allCandidates.forEach(function(c) {
            var v = c[field];
            if (v != null && String(v) && String(v) !== bestVal) {
                alts.push({ value: String(v), source: c.source || '', score: c.score || 0 });
            }
        });

        var key = itemId + '-' + field;
        _brtAltPanelData[key] = alts;

        var selectedVal = (_brtCellValues[itemId] && _brtCellValues[itemId][field] != null)
            ? _brtCellValues[itemId][field] : bestVal;

        var panel = document.createElement('div');
        panel.className = 'brt-alt-panel';
        panel.innerHTML = alts.map(function(alt, i) {
            var isSel = alt.value === selectedVal;
            return '<div class="brt-alt-option' + (isSel ? ' selected' : '') + '" data-idx="' + i + '">' +
                '<span>' + _esc(alt.value) + '</span>' +
                '<span class="brt-alt-meta">' + _esc(alt.source) +
                ' (' + Math.round(alt.score) + 'p)' + (isSel ? ' ← vald' : '') + '</span>' +
                '</div>';
        }).join('');

        panel.addEventListener('click', function(e) {
            var opt = e.target.closest('.brt-alt-option');
            if (!opt) return;
            var idx = parseInt(opt.dataset.idx, 10);
            var alt = _brtAltPanelData[key][idx];
            if (!alt) return;
            if (!_brtCellValues[itemId]) _brtCellValues[itemId] = {};
            _brtCellValues[itemId][field] = alt.value;
            var display = document.getElementById('brt-cell-' + itemId + '-' + field);
            if (display) display.textContent = alt.value;
            panel.remove();
        });

        cell.appendChild(panel);
    }

    /* ============================================================ */
    /* Card-based text-field review (Step 3) — new implementation     */
    /* ============================================================ */
    var _BRC_SOURCE_COLORS = [
        { bg: '#EAF3DE', border: '#97C459', text: '#3B6D11' },
        { bg: '#FAEEDA', border: '#EF9F27', text: '#854F0B' },
        { bg: '#E6F1FB', border: '#85B7EB', text: '#0C447C' },
        { bg: '#FBEAF0', border: '#ED93B1', text: '#72243E' },
        { bg: '#EEEDFE', border: '#AFA9EC', text: '#3C3489' }
    ];

    // Per-item, per-field user choices: { itemId: { field: { value, sourceIdx, sourceName } } }
    var _brcFieldChoices = {};
    // Per-item rendered source list (deduplicated, value-bearing) for save/cherry-pick lookup.
    var _brcSourcesByItem = {};
    // Selected ordered field columns for the current render.
    var _brcCols = [];
    // Bound flag for the delegated container listener.
    var _brcDelegationBound = false;

    function _brcResolveCols(selectedFields) {
        var cols = [];
        _TEXTFIELD_DISPLAY_ORDER.forEach(function(f) {
            if (f === 'series_index') {
                if (selectedFields.indexOf('series') !== -1) cols.push('series_index');
            } else {
                if (selectedFields.indexOf(f) !== -1) cols.push(f);
            }
        });
        return cols;
    }

    function _brcFieldValue(obj, field) {
        var v = (obj && obj[field] != null) ? String(obj[field]) : '';
        if (field === 'published_date') v = _cleanDate(v);
        return v;
    }

    function _brcBuildSourceList(data, cols) {
        var candidate = data.candidate || {};
        var allCandidates = data.all_candidates || [];
        var bestSrc = data.source || '';
        var seen = {};
        var list = [];
        var bestHasVal = cols.some(function(f) { return _brcFieldValue(candidate, f); });
        if (bestHasVal && bestSrc) {
            seen[bestSrc] = true;
            list.push(Object.assign({}, candidate, { source: bestSrc, score: data.score || 0 }));
        }
        allCandidates.forEach(function(c) {
            var src = c.source || '';
            if (!src || seen[src]) return;
            var hasVal = cols.some(function(f) { return _brcFieldValue(c, f); });
            if (!hasVal) return;
            seen[src] = true;
            list.push(c);
        });
        return list;
    }

    function _brcRenderSourcePanel(itemId, sources, cols) {
        if (!sources.length) return '';
        var html = sources.map(function(c, idx) {
            var color = _BRC_SOURCE_COLORS[idx % _BRC_SOURCE_COLORS.length];
            var fieldsHtml = cols.map(function(f) {
                var v = _brcFieldValue(c, f);
                if (!v) return '';
                return '<div class="brc-sf" data-field="' + _esc(f) + '">' +
                    '<span class="brc-sf-label">' + _esc(_brcFieldLabels[f] || f) + '</span>' +
                    '<span class="brc-sf-value">' + _esc(v) + '</span>' +
                    '</div>';
            }).filter(Boolean).join('');
            if (!fieldsHtml) return '';
            return '<div class="brc-source" data-source-idx="' + idx + '" data-source-color-text="' +
                _esc(color.text) + '" data-source-color-bg="' + _esc(color.bg) +
                '" data-source-color-border="' + _esc(color.border) + '">' +
                '<div class="brc-src-header">' +
                '<span class="brc-src-name" style="color:' + color.text + '">' +
                _esc(c.source || _i18n.unknownSource) + '</span>' +
                '<button type="button" class="brc-src-useall">' + _i18n.useAll + '</button>' +
                '</div>' +
                '<div class="brc-src-fields">' + fieldsHtml + '</div>' +
                '</div>';
        }).filter(Boolean).join('');
        return html;
    }

    // Per-item, per-field diff rows from the server ({field: row}).
    var _brcDiffByItem = {};

    function _brcSourceChipHtml(sourceName, color) {
        if (!sourceName) return '';
        return '<span class="brc-from" style="color:' + color.text + '">' +
            _esc(sourceName) + '</span>';
    }

    /* Render one field row, driven by the server-side diff status.
     *   missing       — nothing fetched
     *   same          — fetched equals current
     *   new           — current empty, value found (applied by default)
     *   changed       — current differs (NOT applied by default; click to opt in)
     * `applied` overrides the visual state when the user has cherry-picked /
     * toggled a value. */
    function _brcRenderField(field, current, fetched, status, sourceName, sourceColor, applied) {
        var labelHtml = '<span class="brc-label">' + _esc(_brcFieldLabels[field] || field) + '</span>';
        if (status === 'missing' || (!fetched && !current)) {
            return '<div class="brc-field" data-field="' + _esc(field) + '" data-status="missing">' +
                '<div class="brc-marker brc-marker-none"></div>' + labelHtml +
                '<span class="brc-nomatch">' + _i18n.noMatches + '</span>' +
                '</div>';
        }
        if (status === 'same' || (!fetched || fetched === current)) {
            var shownVal = fetched || current;
            return '<div class="brc-field" data-field="' + _esc(field) + '" data-status="same">' +
                '<div class="brc-marker brc-marker-none"></div>' + labelHtml +
                '<span class="brc-same">' + _esc(shownVal) + ' ✓</span>' +
                '</div>';
        }
        var color = sourceColor || _BRC_SOURCE_COLORS[0];
        var invalid = (field === 'language' && !_isValidLanguageCode(fetched));
        // "changed" fields default to NOT applied (only "new" is auto-checked) —
        // render the opt-out state via the shared rejected renderer so the
        // existing click-to-restore toggle picks them up.
        if (!applied) {
            return _brcRejectedFieldHtml(field, current, fetched, sourceName, color);
        }
        var newCls = 'brc-new' + (invalid ? ' brc-invalid' : '');
        var newAttr = invalid ? ' title="' + _i18n.invalidLanguageCode + '"' : '';
        var newPrefix = invalid ? '⚠ ' : '';
        return '<div class="brc-field" data-field="' + _esc(field) + '" data-status="' + _esc(status) + '">' +
            '<div class="brc-marker brc-marker-changed" style="background:' + color.text + '"></div>' +
            labelHtml +
            '<span class="brc-cur">' + _esc(current || '(tomt)') + '</span>' +
            '<span class="brc-arrow" style="color:' + color.text + '">→</span>' +
            '<span class="' + newCls + '"' + newAttr + ' style="color:' + color.text + '">' +
            newPrefix + _esc(fetched) + '</span>' +
            _brcSourceChipHtml(sourceName, color) +
            '</div>';
    }

    function _brcDiffMap(data) {
        // Index the server diff rows by field for O(1) lookup.
        var map = {};
        (data.diff || []).forEach(function(row) {
            if (row && row.key) map[row.key] = row;
        });
        return map;
    }

    function _batchRenderTextFieldReview(container) {
        var selectedFields = _batchWizard.selectedFields;
        var cols = _brcResolveCols(selectedFields);
        _brcCols = cols;
        _brcFieldChoices = {};
        _brcSourcesByItem = {};
        _brcDiffByItem = {};

        var cards = [];
        _batchWizard.selectedItemIds.forEach(function(itemId) {
            var data = _batchWizard.searchCache[itemId];
            if (!data) return;
            var before = data.before || {};
            var candidate = data.candidate || {};
            var diff = _brcDiffMap(data);
            _brcDiffByItem[itemId] = diff;
            var provenance = data.provenance || {};

            var sources = _brcBuildSourceList(data, cols);
            _brcSourcesByItem[itemId] = sources;

            // Source colors keyed by source name (matches by index in source list).
            var srcColors = {};
            sources.forEach(function(c, idx) {
                srcColors[c.source || ''] = _BRC_SOURCE_COLORS[idx % _BRC_SOURCE_COLORS.length];
            });

            // Seed per-field choices so the diff's default-check decides what is
            // applied: only "new" (current empty) starts applied; "changed" and
            // language start rejected (opt-in), matching the single-book preview.
            _brcFieldChoices[itemId] = {};
            var appliedCount = 0;
            var fieldsHtml = cols.map(function(field) {
                var row = diff[field] || {};
                var status = row.status || '';
                var current = _brcFieldValue(before, field);
                var fetched = _brcFieldValue(candidate, field);
                if (!status) {
                    // Field not in server diff (e.g. added later) — infer.
                    if (!fetched) status = 'missing';
                    else if (fetched === current) status = 'same';
                    else if (!current) status = 'new';
                    else status = 'changed';
                }
                var sourceName = (fetched && (provenance[field] || data.source)) || '';
                var sourceColor = srcColors[sourceName] || _BRC_SOURCE_COLORS[0];
                var applied = false;
                if (status === 'new' || status === 'changed') {
                    applied = !!row.default_check;  // only "new" is pre-checked
                    if (applied) {
                        appliedCount++;
                    } else {
                        // Record as rejected so save skips it until opted in.
                        _brcFieldChoices[itemId][field] = {
                            value: current,
                            rejected: true,
                            originalFetched: fetched,
                            originalSourceName: sourceName,
                            originalColor: sourceColor
                        };
                    }
                }
                return _brcRenderField(field, current, fetched, status, sourceName, sourceColor, applied);
            }).join('');

            var changeCount = appliedCount;
            var noChanges = (changeCount === 0);
            var hasSources = sources.length > 0;
            var srcCount = sources.length;
            var srcToggleHtml = hasSources
                ? '<div class="brc-src-toggle"><i class="ti ti-chevron-down"></i> ' +
                    srcCount + ' ' + (srcCount === 1 ? _i18n.sourcesAvailable : _i18n.sourcesAvailablePlural) + '</div>'
                : '';
            var srcPanelHtml = hasSources
                ? '<div class="brc-src-panel" style="display:none;">' +
                    _brcRenderSourcePanel(itemId, sources, cols) + '</div>'
                : '';

            var title = data.title || String(itemId);
            var isChecked = !noChanges;
            var badgeCls = noChanges ? 'brc-badge brc-badge-ok' : 'brc-badge brc-badge-change';
            var badgeText = noChanges ? _i18n.noChanges : (changeCount === 1 ? _i18n.oneChange : _i18n.nChanges.replace('{count}', changeCount));
            var cardCls = 'brc' + (isChecked ? ' brc-checked' : '') + (noChanges ? ' brc-no-changes' : '');

            cards.push(
                '<div class="' + cardCls + '" data-item-id="' + _esc(String(itemId)) + '">' +
                    '<div class="brc-top">' +
                        '<input type="checkbox" class="brc-check" data-item-id="' + _esc(String(itemId)) + '"' +
                            (isChecked ? ' checked' : '') + ' />' +
                        '<span class="brc-title">' + _esc(title) + '</span>' +
                        '<span class="' + badgeCls + '">' + _esc(badgeText) + '</span>' +
                    '</div>' +
                    '<div class="brc-body">' + fieldsHtml + '</div>' +
                    srcToggleHtml +
                    srcPanelHtml +
                '</div>'
            );
        });

        var fieldSummary = cols.map(function(f) {
            return '<strong>' + _esc(_brcFieldLabels[f] || f) + '</strong>';
        }).join(' · ');

        container.innerHTML =
            '<div class="batch-review-header">Granskar: ' + fieldSummary +
            ' <a href="#" class="batch-add-field" onclick="event.preventDefault();_batchShowAddField(this)">[' + _i18n.addField + ']</a></div>' +
            '<div style="font-size:11px; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.4px; margin-bottom:10px;">' +
            _i18n.currentArrowFetched +
            '</div>' +
            '<div class="brc-list">' + cards.join('') + '</div>' +
            '<div style="margin-top:16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
            '<button type="button" class="btn primary" onclick="_batchSaveTextFields()">' + _i18n.saveSelectedContinue + '</button>' +
            '<button type="button" class="btn ghost" onclick="_batchSkipReview()">' + _i18n.skip + '</button>' +
            '<button type="button" class="btn ghost" onclick="closeBatchModal()">Avbryt</button>' +
            '</div>';

        _brcBindDelegation(container);
    }

    function _brcBindDelegation(container) {
        if (_brcDelegationBound) return;
        _brcDelegationBound = true;
        container.addEventListener('click', _brcOnClick);
    }

    function _brcOnClick(e) {
        // Checkbox toggle
        var check = e.target.closest('.brc-check');
        if (check) {
            var card = check.closest('.brc');
            if (card) card.classList.toggle('brc-checked', check.checked);
            return;
        }

        // Source panel toggle
        var toggle = e.target.closest('.brc-src-toggle');
        if (toggle) {
            var crd = toggle.closest('.brc');
            var panel = crd && crd.querySelector('.brc-src-panel');
            if (panel) {
                var isOpen = panel.style.display !== 'none';
                panel.style.display = isOpen ? 'none' : 'block';
                toggle.classList.toggle('open', !isOpen);
            }
            return;
        }

        // "Use all" — apply all fields from this source
        var useAll = e.target.closest('.brc-src-useall');
        if (useAll) {
            e.stopPropagation();
            var srcEl = useAll.closest('.brc-source');
            var cardEl = useAll.closest('.brc');
            if (srcEl && cardEl) _brcApplyAllFromSource(cardEl, srcEl);
            return;
        }

        // Cherry-pick a single field from a source
        var sf = e.target.closest('.brc-sf');
        if (sf) {
            var srcE = sf.closest('.brc-source');
            var cardE = sf.closest('.brc');
            if (srcE && cardE) _brcCherryPick(cardE, srcE, sf);
            return;
        }

        // Toggle field in card body (reject or restore)
        var fieldEl = e.target.closest('.brc-field');
        if (fieldEl && (fieldEl.querySelector('.brc-marker-changed') || fieldEl.dataset.rejected === '1')) {
            var cardEl = fieldEl.closest('.brc');
            if (cardEl) _brcToggleField(cardEl, fieldEl);
            return;
        }

        // Card header click — expand/collapse no-change cards
        var top = e.target.closest('.brc-top');
        if (top && !e.target.closest('.brc-check')) {
            var crd2 = top.closest('.brc');
            if (crd2) {
                if (crd2.classList.contains('brc-no-changes')) {
                    crd2.classList.toggle('brc-expanded');
                } else {
                    var cb = crd2.querySelector('.brc-check');
                    if (cb) {
                        cb.checked = !cb.checked;
                        crd2.classList.toggle('brc-checked', cb.checked);
                    }
                }
            }
        }
    }

    function _brcGetColor(srcEl) {
        return {
            text: srcEl.dataset.sourceColorText || _BRC_SOURCE_COLORS[0].text,
            bg: srcEl.dataset.sourceColorBg || _BRC_SOURCE_COLORS[0].bg,
            border: srcEl.dataset.sourceColorBorder || _BRC_SOURCE_COLORS[0].border
        };
    }

    function _brcUpdateCardField(cardEl, field, newValue, sourceName, color) {
        var fieldEl = cardEl.querySelector('.brc-body .brc-field[data-field="' + field + '"]');
        if (!fieldEl) return;
        var before = ((_batchWizard.searchCache[cardEl.dataset.itemId] || {}).before) || {};
        var current = _brcFieldValue(before, field);

        // Rebuild as a "changed" or "same" row depending on the new value.
        var labelLabel = _brcFieldLabels[field] || field;
        if (!newValue) {
            fieldEl.outerHTML = '<div class="brc-field" data-field="' + field + '">' +
                '<div class="brc-marker brc-marker-none"></div>' +
                '<span class="brc-label">' + _esc(labelLabel) + '</span>' +
                '<span class="brc-nomatch">' + _i18n.noMatches + '</span>' +
                '</div>';
            return;
        }
        if (newValue === current) {
            fieldEl.outerHTML = '<div class="brc-field" data-field="' + field + '">' +
                '<div class="brc-marker brc-marker-none"></div>' +
                '<span class="brc-label">' + _esc(labelLabel) + '</span>' +
                '<span class="brc-same">' + _esc(newValue) + ' ✓</span>' +
                '</div>';
            return;
        }
        var invalid = (field === 'language' && !_isValidLanguageCode(newValue));
        var newCls = 'brc-new' + (invalid ? ' brc-invalid' : '');
        var newAttr = invalid ? ' title="' + _i18n.invalidLanguageCode + '"' : '';
        var newPrefix = invalid ? '⚠ ' : '';
        fieldEl.outerHTML = '<div class="brc-field" data-field="' + field + '">' +
            '<div class="brc-marker brc-marker-changed" style="background:' + color.text + '"></div>' +
            '<span class="brc-label">' + _esc(labelLabel) + '</span>' +
            '<span class="brc-cur">' + _esc(current || '(tomt)') + '</span>' +
            '<span class="brc-arrow" style="color:' + color.text + '">→</span>' +
            '<span class="' + newCls + '"' + newAttr + ' style="color:' + color.text + '">' +
            newPrefix + _esc(newValue) + '</span>' +
            (sourceName ? '<span class="brc-from" style="color:' + color.text + '">' +
                _esc(sourceName) + '</span>' : '') +
            '</div>';
    }

    function _brcMarkPicked(cardEl, srcEl, sfEl, color) {
        // Clear .brc-sf-picked from all rows in this card matching the same field.
        var field = sfEl.dataset.field;
        var allSf = cardEl.querySelectorAll('.brc-source .brc-sf[data-field="' + field + '"]');
        allSf.forEach(function(el) {
            el.classList.remove('brc-sf-picked');
            el.style.background = '';
            el.style.border = '0.5px solid transparent';
            var val = el.querySelector('.brc-sf-value');
            if (val) {
                val.style.color = '';
                val.style.fontWeight = '';
            }
        });
        sfEl.classList.add('brc-sf-picked');
        sfEl.style.background = color.bg;
        sfEl.style.border = '0.5px solid ' + color.border;
        var valEl = sfEl.querySelector('.brc-sf-value');
        if (valEl) {
            valEl.style.color = color.text;
            valEl.style.fontWeight = '500';
        }
    }

    function _brcCherryPick(cardEl, srcEl, sfEl) {
        var itemId = cardEl.dataset.itemId;
        var field = sfEl.dataset.field;
        var sourceIdx = parseInt(srcEl.dataset.sourceIdx, 10);
        var sources = _brcSourcesByItem[itemId] || [];
        var srcObj = sources[sourceIdx];
        if (!srcObj) return;
        var value = _brcFieldValue(srcObj, field);
        if (!value) return;
        var sourceName = srcObj.source || '';
        var color = _brcGetColor(srcEl);

        if (!_brcFieldChoices[itemId]) _brcFieldChoices[itemId] = {};
        _brcFieldChoices[itemId][field] = { value: value, sourceIdx: sourceIdx, sourceName: sourceName };

        _brcUpdateCardField(cardEl, field, value, sourceName, color);
        _brcMarkPicked(cardEl, srcEl, sfEl, color);
        _brcUpdateBadge(cardEl);
    }

    function _brcApplyAllFromSource(cardEl, srcEl) {
        var itemId = cardEl.dataset.itemId;
        var sourceIdx = parseInt(srcEl.dataset.sourceIdx, 10);
        var sources = _brcSourcesByItem[itemId] || [];
        var srcObj = sources[sourceIdx];
        if (!srcObj) return;
        var sourceName = srcObj.source || '';
        var color = _brcGetColor(srcEl);
        if (!_brcFieldChoices[itemId]) _brcFieldChoices[itemId] = {};

        var sfRows = srcEl.querySelectorAll('.brc-sf');
        sfRows.forEach(function(sfEl) {
            var field = sfEl.dataset.field;
            var value = _brcFieldValue(srcObj, field);
            if (!value) return;
            if (_brcCols.indexOf(field) === -1) return;
            _brcFieldChoices[itemId][field] = { value: value, sourceIdx: sourceIdx, sourceName: sourceName };
            _brcUpdateCardField(cardEl, field, value, sourceName, color);
            _brcMarkPicked(cardEl, srcEl, sfEl, color);
        });
        _brcUpdateBadge(cardEl);
    }

    function _brcToggleField(cardEl, fieldEl) {
        var itemId = cardEl.dataset.itemId;
        var field = fieldEl.dataset.field;
        if (!itemId || !field) return;

        var data = _batchWizard.searchCache[itemId];
        if (!data) return;
        var before = data.before || {};
        var candidate = data.candidate || {};
        var current = _brcFieldValue(before, field);

        if (!_brcFieldChoices[itemId]) _brcFieldChoices[itemId] = {};
        var existing = _brcFieldChoices[itemId][field];

        if (existing && existing.rejected) {
            // RESTORE: remove rejection, re-apply the previously stored fetched value
            var restoreValue = existing.originalFetched;
            var restoreSource = existing.originalSourceName || '';
            var restoreColor = existing.originalColor || _BRC_SOURCE_COLORS[0];
            delete _brcFieldChoices[itemId][field];
            _brcUpdateCardField(cardEl, field, restoreValue, restoreSource, restoreColor);
        } else {
            // REJECT: store rejection with original fetched value for later restore
            var fetchedValue;
            var sourceName = '';
            var color = _BRC_SOURCE_COLORS[0];
            if (existing && existing.value) {
                // Cherry-picked value
                fetchedValue = existing.value;
                sourceName = existing.sourceName || '';
                var srcIdx = existing.sourceIdx;
                var srcEl2 = cardEl.querySelector('.brc-source[data-source-idx="' + srcIdx + '"]');
                if (srcEl2) color = _brcGetColor(srcEl2);
            } else {
                // Default candidate value
                fetchedValue = _brcFieldValue(candidate, field);
                sourceName = data.source || '';
                var firstSrc = cardEl.querySelector('.brc-source[data-source-idx="0"]');
                if (firstSrc) color = _brcGetColor(firstSrc);
            }

            _brcFieldChoices[itemId][field] = {
                value: current,
                rejected: true,
                originalFetched: fetchedValue,
                originalSourceName: sourceName,
                originalColor: color
            };

            _brcRenderRejectedField(cardEl, field, current, fetchedValue);
        }

        _brcUpdateBadge(cardEl);
    }

    function _brcRejectedFieldHtml(field, current, rejectedFetched, sourceName, color) {
        var label = _brcFieldLabels[field] || field;
        var chip = (sourceName && color) ? _brcSourceChipHtml(sourceName, color) : '';
        return '<div class="brc-field brc-field-rejected" data-field="' + _esc(field) + '" data-rejected="1" data-status="changed" title="' + _i18n.brcClickToApply + '">' +
                '<div class="brc-marker brc-marker-none"></div>' +
                '<span class="brc-label">' + _esc(label) + '</span>' +
                '<span class="brc-same">' + _esc(current || '(tomt)') + ' ✓</span>' +
                '<span class="brc-rejected-hint">(→ ' + _esc(rejectedFetched) + ')</span>' +
                chip +
            '</div>';
    }

    function _brcRenderRejectedField(cardEl, field, current, rejectedFetched) {
        var fieldEl = cardEl.querySelector('.brc-body .brc-field[data-field="' + field + '"]');
        if (!fieldEl) return;
        fieldEl.outerHTML = _brcRejectedFieldHtml(field, current, rejectedFetched);
    }

    function _brcUpdateBadge(cardEl) {
        var itemId = cardEl.dataset.itemId;
        var data = _batchWizard.searchCache[itemId];
        if (!data) return;
        var before = data.before || {};
        var candidate = data.candidate || {};
        var choices = _brcFieldChoices[itemId] || {};

        var count = 0;
        _brcCols.forEach(function(f) {
            var choice = choices[f];
            if (choice && choice.rejected) return;
            var current = _brcFieldValue(before, f);
            var fetched = (choice && choice.value) ? choice.value : _brcFieldValue(candidate, f);
            if (fetched && fetched !== current) {
                var invalid = (f === 'language' && !_isValidLanguageCode(fetched));
                if (!invalid) count++;
            }
        });

        var badge = cardEl.querySelector('.brc-badge');
        if (badge) {
            badge.textContent = count === 0 ? _i18n.noChanges : (count === 1 ? _i18n.oneChange : _i18n.nChanges.replace('{count}', count));
            badge.className = count === 0 ? 'brc-badge brc-badge-ok' : 'brc-badge brc-badge-change';
        }
    }

    function _batchSaveTextFields() {
        var container = document.getElementById('batchReviewContainer');
        if (!container) { _batchAdvanceReview(); return; }
        var checked = Array.from(container.querySelectorAll('.brc-check:checked'));
        if (checked.length === 0) { _batchAdvanceReview(); return; }

        var pending = checked.length;
        var savedCount = 0;

        function _onAllDone() {
            _batchWizard.results.saved += savedCount;
            _batchAdvanceReview();
        }

        checked.forEach(function(cb) {
            var itemId = cb.dataset.itemId;
            var data = _batchWizard.searchCache[itemId];
            if (!data) { pending--; if (pending === 0) _onAllDone(); return; }

            var candidate = data.candidate || {};
            var before = data.before || {};
            // Seed payload from current DB values so required fields (title) are present
            // and unselected fields are not cleared on save.
            var _ALL_FIELDS = ['title','author','series','series_index','isbn','publisher','language','genres','published_date','description'];
            var payload = {};
            _ALL_FIELDS.forEach(function(f) {
                var v = (before[f] != null) ? String(before[f]) : '';
                if (f === 'published_date') v = _cleanDate(v);
                if (v) payload[f] = v;
            });

            var changedFields = [];
            var choices = _brcFieldChoices[itemId] || {};
            _brcCols.forEach(function(field) {
                var choice = choices[field];
                if (choice && choice.rejected) return; // skip — user rejected this field
                var val;
                if (choice && choice.value != null) {
                    val = choice.value;
                } else if (candidate[field] != null) {
                    val = String(candidate[field]);
                } else {
                    val = null;
                }
                if (field === 'published_date' && val) val = _cleanDate(val);
                if (val == null || val === '') return;
                var prev = (before[field] != null) ? String(before[field]) : '';
                if (field === 'published_date') prev = _cleanDate(prev);
                payload[field] = val;
                if (String(val) !== prev) changedFields.push(field);
            });

            var allIds = data.item_ids || [itemId];
            var remaining = allIds.length;
            var ok = true;

            allIds.forEach(function(id) {
                fetch('/metadata/' + id + '/save-json', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(function(r) {
                    return r.json().catch(function() { return { ok: false, error: 'http_' + r.status }; });
                })
                .then(function(result) {
                    if (!result || !result.ok) ok = false;
                    remaining--;
                    if (remaining === 0) {
                        if (ok && changedFields.length > 0) {
                            savedCount++;
                            var fc = _batchWizard.results.fieldCounts;
                            changedFields.forEach(function(f) {
                                fc[f] = (fc[f] || 0) + 1;
                            });
                        }
                        pending--;
                        if (pending === 0) _onAllDone();
                    }
                })
                .catch(function() {
                    ok = false;
                    remaining--;
                    if (remaining === 0) { pending--; if (pending === 0) _onAllDone(); }
                });
            });
        });
    }

    function _batchRenderSynopsisReview(container) {
        var rows = [];
        _batchWizard.selectedItemIds.forEach(function(itemId) {
            var data = _batchWizard.searchCache[itemId];
            if (!data) return;
            var curDesc = (data.before && data.before.description) ? data.before.description : '';
            var fetchedDesc = (data.candidate && data.candidate.description) ? data.candidate.description : '';
            var curLen = curDesc.length;
            var fetchedLen = fetchedDesc.length;

            var flagHtml, isChecked;
            if (!fetchedLen) {
                flagHtml = '<span class="synopsis-flag-same">' + _i18n.noMatches + '</span>';
                isChecked = false;
            } else if (!curLen) {
                flagHtml = '<span class="synopsis-flag-new">Nytt</span>';
                isChecked = true;
            } else if (fetchedLen > curLen * 1.1) {
                var times = Math.round(fetchedLen / curLen);
                flagHtml = '<span class="synopsis-flag-longer">' + _i18n.timesLonger.replace('{times}', times) + '</span>';
                isChecked = true;
            } else if (fetchedLen < curLen * 0.9) {
                flagHtml = '<span class="synopsis-flag-shorter">⚠ Kortare</span>';
                isChecked = false;
            } else {
                flagHtml = '<span class="synopsis-flag-same">' + _i18n.emptyEquivalent + '</span>';
                isChecked = false;
            }

            var curDisplay = curLen ? curLen + ' tecken' : '(tomt)';
            var fetchedDisplay = fetchedLen ? fetchedLen + ' tecken' : '—';
            var title = data.title || String(itemId);
            if (title.length > 35) title = title.substring(0, 35) + '…';
            var checkedAttr = isChecked ? ' checked' : '';

            var curLabel = 'Nuvarande' + (curLen ? ' (' + curLen + ' tecken)' : '');
            var fetchedLabel = fetchedLen ? _i18n.fetchedWithChars.replace('{count}', fetchedLen) : _i18n.fetchedLabel;

            rows.push(
                '<tr class="bsyn-row" data-item-id="' + itemId + '">' +
                '<td onclick="event.stopPropagation();"><label style="display:flex;align-items:center;gap:6px;cursor:pointer;">' +
                '<input type="checkbox" class="bsyn-check" data-item-id="' + itemId + '"' + checkedAttr + '>' +
                '<span>' + _esc(title) + '</span></label></td>' +
                '<td>' + _esc(curDisplay) + '</td>' +
                '<td>' + _esc(fetchedDisplay) + '</td>' +
                '<td>' + flagHtml + '</td>' +
                '</tr>' +
                '<tr class="bsyn-expand-row" data-item-id="' + itemId + '" style="display:none;">' +
                '<td colspan="4">' +
                '<div class="synopsis-compare">' +
                '<div class="synopsis-col"><div class="synopsis-col-label">' + _esc(curLabel) + '</div>' +
                '<div class="synopsis-col-text">' + _esc(curDesc || '(ingen text)') + '</div></div>' +
                '<div class="synopsis-col"><div class="synopsis-col-label">' + _esc(fetchedLabel) + '</div>' +
                '<div class="synopsis-col-text synopsis-col-text-fetched">' + _esc(fetchedDesc || '(ingen text)') + '</div></div>' +
                '</div></td></tr>'
            );
        });

        container.innerHTML =
            '<div class="batch-review-header">Granskar: <strong>Synopsis</strong>' +
            ' <a href="#" class="batch-add-field" onclick="event.preventDefault();_batchShowAddField(this)">[' + _i18n.addField + ']</a></div>' +
            '<div style="overflow-x:auto;">' +
            '<table class="batch-review-table"><thead><tr>' +
            '<th>' + _i18n.bookHeader + '</th><th>' + _i18n.currentHeader + '</th><th>' + _i18n.fetchedHeader + '</th><th>' + _i18n.changeHeader + '</th>' +
            '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>' +
            '<div style="margin-top:16px;display:flex;gap:8px;align-items:center;">' +
            '<button type="button" class="btn primary" onclick="_batchSaveSynopsis()">' + _i18n.saveSelectedContinue + '</button>' +
            '<button type="button" class="btn ghost" onclick="_batchSkipReview()">' + _i18n.skip + '</button>' +
            '<button type="button" class="btn ghost" onclick="closeBatchModal()">Avbryt</button>' +
            '</div>';

        container.querySelectorAll('.bsyn-row').forEach(function(row) {
            row.addEventListener('click', function() {
                var itemId = row.dataset.itemId;
                var expandRow = container.querySelector('.bsyn-expand-row[data-item-id="' + itemId + '"]');
                if (expandRow) {
                    expandRow.style.display = expandRow.style.display === 'none' ? '' : 'none';
                }
            });
        });
    }

    function _batchSaveSynopsis() {
        var container = document.getElementById('batchReviewContainer');
        if (!container) { _batchAdvanceReview(); return; }
        var checked = Array.from(container.querySelectorAll('.bsyn-check:checked'));
        if (checked.length === 0) { _batchAdvanceReview(); return; }

        var pending = checked.length;
        var savedCount = 0;

        function _onAllDone() {
            _batchWizard.results.saved += savedCount;
            if (savedCount > 0) {
                var fc = _batchWizard.results.fieldCounts;
                fc.description = (fc.description || 0) + savedCount;
            }
            _batchAdvanceReview();
        }

        checked.forEach(function(cb) {
            var itemId = cb.dataset.itemId;
            var data = _batchWizard.searchCache[itemId];
            if (!data) { pending--; if (pending === 0) _onAllDone(); return; }

            var fetchedDesc = (data.candidate && data.candidate.description) ? data.candidate.description : '';
            if (!fetchedDesc) { pending--; if (pending === 0) _onAllDone(); return; }

            var payload = { description: fetchedDesc };
            var allIds = data.item_ids || [itemId];
            var remaining = allIds.length;
            var ok = true;

            allIds.forEach(function(id) {
                fetch('/metadata/' + id + '/save-json', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(function(r) { return r.json(); })
                .then(function(result) {
                    if (!result.ok) ok = false;
                    remaining--;
                    if (remaining === 0) {
                        if (ok) savedCount++;
                        pending--;
                        if (pending === 0) _onAllDone();
                    }
                })
                .catch(function() {
                    remaining--;
                    if (remaining === 0) { pending--; if (pending === 0) _onAllDone(); }
                });
            });
        });
    }

    function _batchRenderCoverReview(container) {
        var cards = [];
        var hiddenNoFetch = 0;
        _batchWizard.selectedItemIds.forEach(function(itemId) {
            var data = _batchWizard.searchCache[itemId];
            if (!data) return;

            var hasCoverBefore = data.has_cover_before || false;
            var coverUrlFetched = data.cover_url_fetched || null;
            var hasCoverFetched = data.has_cover_fetched || false;

            // Skip books where no new cover was fetched — nothing to review.
            if (!hasCoverFetched) { hiddenNoFetch++; return; }

            var isChecked = !hasCoverBefore;
            var checkAttrs = isChecked ? ' checked' : '';

            var currentHtml = hasCoverBefore
                ? '<img src="/cover/' + itemId + '" alt="" onerror="this.outerHTML=\'<div class=&quot;cover-placeholder&quot;>📖</div>\'">'
                : '<div class="cover-placeholder">📖</div>';

            var fetchedHtml = (hasCoverFetched && coverUrlFetched)
                ? '<img src="' + _esc(coverUrlFetched) + '" alt="" onerror="this.outerHTML=\'<div class=&quot;cover-placeholder&quot; style=&quot;font-size:13px&quot;>Fel</div>\'">'
                : '<div class="cover-placeholder" style="font-size:13px;">Ej funnet</div>';

            var title = data.title || String(itemId);
            if (title.length > 35) title = title.substring(0, 35) + '…';

            cards.push(
                '<div class="cover-review-card">' +
                '<div class="cover-pair">' +
                '<div class="cover-thumb">' + currentHtml + '<div class="cover-label">Nuvarande</div></div>' +
                '<div class="cover-arrow">→</div>' +
                '<div class="cover-thumb">' + fetchedHtml + '<div class="cover-label">' + _i18n.fetchedLabel + '</div></div>' +
                '</div>' +
                '<div class="cover-meta"><label>' +
                '<input type="checkbox" class="cover-check" data-item-id="' + itemId + '"' + checkAttrs + '>' +
                '<span>' + _esc(title) + '</span></label></div>' +
                '</div>'
            );
        });

        var hiddenNote = '';
        if (hiddenNoFetch > 0) {
            hiddenNote = '<div class="hint" style="font-size:12px; margin-bottom:8px;">' +
                hiddenNoFetch + ' ' + (hiddenNoFetch === 1 ? _i18n.bookSingular : _i18n.bookPlural) +
                ' ' + _i18n.coverWithoutFetched + '</div>';
        }
        var body = cards.length
            ? '<div class="cover-review-grid">' + cards.join('') + '</div>'
            : '<div class="hint" style="padding:16px 0;">' + _i18n.noNewCoverFound + '</div>';
        container.innerHTML =
            '<div class="batch-review-header">' + _i18n.reviewViewFor + ' <strong>' + _i18n.fetchedLabel + '</strong>' +
            ' <a href="#" class="batch-add-field" onclick="event.preventDefault();_batchShowAddField(this)">[' + _i18n.addField + ']</a></div>' +
            hiddenNote +
            body +
            '<div style="margin-top:16px;display:flex;gap:8px;align-items:center;">' +
            '<button type="button" class="btn primary" onclick="_batchSaveCover()">' + _i18n.saveSelectedContinue + '</button>' +
            '<button type="button" class="btn ghost" onclick="_batchSkipReview()">' + _i18n.skip + '</button>' +
            '<button type="button" class="btn ghost" onclick="closeBatchModal()">' + _i18n.close + '</button>' +
            '</div>';
    }

    function _batchSaveCover() {
        var container = document.getElementById('batchReviewContainer');
        if (!container) { _batchAdvanceReview(); return; }
        var checked = Array.from(container.querySelectorAll('.cover-check:checked'));
        if (checked.length === 0) { _batchAdvanceReview(); return; }

        var pending = checked.length;
        var savedCount = 0;

        function _onAllDone() {
            _batchWizard.results.saved += savedCount;
            if (savedCount > 0) {
                var fc = _batchWizard.results.fieldCounts;
                fc.cover = (fc.cover || 0) + savedCount;
            }
            _batchAdvanceReview();
        }

        checked.forEach(function(cb) {
            var itemId = cb.dataset.itemId;
            var data = _batchWizard.searchCache[itemId];
            if (!data || !data.cover_url_fetched) {
                pending--;
                if (pending === 0) _onAllDone();
                return;
            }
            var formData = new FormData();
            formData.append('cover_url', data.cover_url_fetched);

            fetch('/metadata/' + itemId + '/cover/apply', { method: 'POST', body: formData })
                .then(function(r) {
                    if (r.ok) savedCount++;
                    pending--;
                    if (pending === 0) _onAllDone();
                })
                .catch(function() {
                    pending--;
                    if (pending === 0) _onAllDone();
                });
        });
    }

    function _batchSkipReview() {
        _batchAdvanceReview();
    }

    function _batchAdvanceReview() {
        _batchWizard.reviewIndex++;
        if (_batchWizard.reviewIndex >= _batchWizard.reviewQueue.length) {
            _batchSetStep(4);
        } else {
            _batchRenderReview();
        }
    }

    var _BATCH_FIELD_LABELS = {
        title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor, series: _i18n.batchFieldSeries, series_index: _i18n.batchFieldPart,
        isbn: 'ISBN', publisher: _i18n.batchFieldPublisher, language: _i18n.batchFieldLanguage, genres: _i18n.batchFieldGenre,
        published_date: _i18n.batchFieldDate, description: _i18n.batchFieldSynopsis, cover: _i18n.batchFieldCover
    };
    var _BATCH_MISSING_FILTER = {
        author: 'author', series: 'series', isbn: 'isbn', publisher: 'publisher',
        genres: 'genres', published_date: 'published_date',
        description: 'description', cover: 'cover'
    };

    function _batchRenderSummary(container) {
        if (!container) return;
        var fc = _batchWizard.results.fieldCounts || {};
        var cache = _batchWizard.searchCache;
        var selectedFields = _batchWizard.selectedFields;

        var savedItems = [];
        Object.keys(fc).forEach(function(field) {
            var count = fc[field];
            if (count > 0) {
                var label = _BATCH_FIELD_LABELS[field] || field;
                savedItems.push(
                    '<div class="batch-summary-item"><span class="count">' + count + '</span>' +
                    '<span>' + _esc(label) + ' ' + _i18n.fieldUpdated + ' ' + count +
                    ' ' + (count === 1 ? _i18n.bookSingular : _i18n.bookPlural) + '</span></div>'
                );
            }
        });

        var remainingItems = [];
        selectedFields.forEach(function(field) {
            var filterKey = _BATCH_MISSING_FILTER[field];
            if (!filterKey) return;
            var count = 0;
            _batchWizard.selectedItemIds.forEach(function(itemId) {
                var data = cache[itemId];
                if (!data) return;
                var wasMissing = field === 'cover'
                    ? !data.has_cover_before
                    : !(data.before && data.before[field]);
                var noFetch = field === 'cover'
                    ? !data.has_cover_fetched
                    : !(data.candidate && data.candidate[field]);
                if (wasMissing && noFetch) count++;
            });
            if (count > 0) {
                var label = _BATCH_FIELD_LABELS[field] || field;
                var missingText = window._pluralize(
                    count,
                    'nBookMissingFieldOne',
                    'nBooksMissingFieldMany',
                    { field: _esc(label.toLowerCase()) }
                );
                remainingItems.push(
                    '<div class="batch-summary-item batch-summary-remaining">' +
                    '<span class="count">' + count + '</span>' +
                    '<span>' + missingText + '</span>' +
                    '<span class="batch-summary-link" onclick="_batchFilterMissing(\'' + filterKey + '\')">[' + _i18n.showShort + ']</span>' +
                    '</div>'
                );
            }
        });

        var totalUpdates = 0;
        Object.keys(fc).forEach(function(f) { totalUpdates += (fc[f] || 0); });
        var booksAffected = _batchWizard.results.saved || 0;
        var anyFieldsSaved = savedItems.length > 0;

        var html;
        if (anyFieldsSaved) {
            html = '<div style="text-align:center; padding:40px 0 20px;">' +
                   '<div style="font-size:48px; color:var(--accent-green);">✓</div>' +
                   '<h3 style="margin-top:12px; font-size:18px; font-weight:600;">' + _i18n.batchDone + '</h3>' +
                   '<p style="color:var(--text-secondary); margin-top:8px; font-size:13px;">' +
                   _i18n.nFieldsUpdated.replace('{fields}', totalUpdates).replace('{books}', booksAffected) +
                   '</p>' +
                   '</div>' +
                   '<div class="batch-summary-section" style="margin-top:0;"><h3>' + _i18n.batchSaved + '</h3>' + savedItems.join('') + '</div>';
        } else {
            html = '<div style="text-align:center; padding:40px 0 20px;">' +
                   '<div style="font-size:48px; color:var(--text-tertiary);">○</div>' +
                   '<h3 style="margin-top:12px; font-size:18px; font-weight:600;">' + _i18n.noFieldsUpdated + '</h3>' +
                   '<p style="color:var(--text-secondary); margin-top:8px; font-size:13px;">' +
                   _i18n.noFieldsUpdatedDetail +
                   '</p>' +
                   '</div>';
        }

        if (remainingItems.length > 0) {
            html += '<div class="batch-summary-section"><h3>' + _i18n.remaining + '</h3>' + remainingItems.join('') + '</div>';
        }

        html += '<div style="text-align:center; margin-top:20px;">' +
                '<button type="button" class="btn ghost" onclick="closeBatchModal()">' + _i18n.close + '</button>' +
                '</div>';
        container.innerHTML = html;
    }

    function _batchFilterMissing(fieldKey) {
        closeBatchModal();
        var filterSelect = document.getElementById('filterMissingField');
        if (filterSelect) {
            filterSelect.value = fieldKey;
            applyFilters();
        }
    }

    var _BATCH_ADD_FIELD_LIST = [
        { key: 'title',        label: _i18n.batchFieldTitle },
        { key: 'author',       label: _i18n.batchFieldAuthor },
        { key: 'series',       label: _i18n.batchFieldSeries },
        { key: 'isbn',         label: 'ISBN' },
        { key: 'publisher',    label: _i18n.batchFieldPublisher },
        { key: 'language',     label: _i18n.batchFieldLanguage },
        { key: 'genres',       label: _i18n.batchFieldGenre },
        { key: 'published_date', label: _i18n.batchFieldDate },
        { key: 'description',  label: _i18n.batchFieldSynopsis },
        { key: 'cover',        label: _i18n.batchFieldCover }
    ];

    function _batchShowAddField(anchor) {
        var existing = document.getElementById('batchAddFieldPopover');
        if (existing) { existing.remove(); return; }

        var pop = document.createElement('div');
        pop.id = 'batchAddFieldPopover';
        pop.className = 'batch-add-field-pop';

        var currentReview = _batchWizard.reviewQueue[_batchWizard.reviewIndex];
        var textKeys = ['title','author','series','isbn','publisher','language','genres','published_date'];

        _BATCH_ADD_FIELD_LIST.forEach(function(f) {
            var selected = _batchWizard.selectedFields.indexOf(f.key) !== -1;
            var canAdd = !selected && currentReview === 'textfields' && textKeys.indexOf(f.key) !== -1;

            var label = document.createElement('label');
            label.className = 'field-check';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = selected;
            cb.disabled = !canAdd;
            if (canAdd) {
                cb.addEventListener('change', function() {
                    if (this.checked) {
                        _batchWizard.selectedFields.push(f.key);
                        pop.remove();
                        _batchRenderReview();
                    }
                });
            }
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + f.label));
            pop.appendChild(label);
        });

        var header = anchor.closest('.batch-review-header');
        (header || anchor.parentNode).style.position = 'relative';
        pop.style.top = '22px';
        pop.style.left = 'auto';
        pop.style.right = '0';
        (header || anchor.parentNode).appendChild(pop);

        setTimeout(function() {
            function _outside(e) {
                if (!pop.contains(e.target) && e.target !== anchor) {
                    pop.remove();
                    document.removeEventListener('click', _outside);
                }
            }
            document.addEventListener('click', _outside);
        }, 0);
    }

    function _getBatchItemIds() {
        var checked = Array.from(document.querySelectorAll('.book-checkbox:checked'));
        var itemIds = [];
        if (window._grouped) {
            var checkedGroupKeys = new Set();
            checked.forEach(function(cb) {
                var row = cb.closest('tr');
                var key = row && row.dataset.groupKey ? row.dataset.groupKey : '';
                if (key) checkedGroupKeys.add(key);
                else itemIds.push(cb.value);
            });
            checkedGroupKeys.forEach(function(key) {
                document.querySelectorAll('tr[data-group-key="' + key + '"] .book-checkbox')
                    .forEach(function(cb) {
                        if (itemIds.indexOf(cb.value) === -1) itemIds.push(cb.value);
                    });
            });
        } else {
            itemIds = checked.map(function(cb) { return cb.value; });
        }
        return itemIds;
    }
    /* -------------------------------------------------------------------- */
    /* Batch modal: search, AI, delete                                       */
    /* -------------------------------------------------------------------- */
    function _esc(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _cleanDate(val) {
        if (!val || typeof val !== 'string') return val;
        if (val.length > 10 && val[4] === '-' && val[7] === '-') {
            return val.substring(0, 10);
        }
        return val;
    }

    var _applyFieldLabels = {
        title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor, description: _i18n.batchFieldSynopsis,
        isbn: 'ISBN', publisher: _i18n.batchFieldPublisher, series: _i18n.batchFieldSeries,
        series_index: _i18n.batchFieldPart, language: _i18n.batchFieldLanguage, genres: _i18n.batchFieldGenre,
        published_date: _i18n.batchFieldPublicationDate,
        cover: _i18n.batchFieldCover
    };
    function _applyFieldLabel(f) {
        return _applyFieldLabels[f] || f;
    }

    // Shorter labels for the narrow-card review layout (.brc-label is 100px wide).
    var _brcFieldLabels = {
        title: _i18n.batchFieldTitle, author: _i18n.batchFieldAuthor, description: _i18n.batchFieldSynopsis,
        isbn: 'ISBN', publisher: _i18n.batchFieldPublisher, series: _i18n.batchFieldSeries,
        series_index: _i18n.batchFieldPart, language: _i18n.batchFieldLanguage, genres: _i18n.batchFieldGenre,
        published_date: _i18n.batchFieldDate,
        cover: _i18n.batchFieldCover
    };

    function _resultLabel(d) {
        if (d.classification === 'auto_apply') {
            var details = d.apply_details || {};
            var added = details.fields_added || [];
            var replaced = details.fields_replaced || [];
            if (added.length === 0 && replaced.length === 0) {
                return '<span class="bp-skip">— ' + _i18n.noChanges + '</span>';
            }
            var parts = [];
            if (added.length > 0) parts.push(_i18n.addedNFields.replace('{count}', added.length));
            if (replaced.length > 0) parts.push(_i18n.batchReplacedCount.replace('{count}', replaced.length));
            var cls = replaced.length > 0 ? 'bp-warn' : 'bp-ok';
            return '<span class="' + cls + '">✓ ' + parts.join(', ') + '</span>';
        }
        var labels = {
            'review_needed': '<span class="bp-warn">' + _i18n.batchReviewLabel + '</span>',
            'no_match':      '<span class="bp-fail">' + _i18n.batchNoMatchLabel + '</span>',
            'skipped':       '<span class="bp-skip">' + _i18n.batchSkippedLabel + '</span>',
            'source_error':  '<span class="bp-fail">' + _i18n.batchSourceErrorLabel + '</span>'
        };
        return labels[d.classification] || _esc(d.classification || '');
    }

    function _resultTooltip(d) {
        if (d.classification !== 'auto_apply') return '';
        var details = d.apply_details || {};
        var added = details.fields_added || [];
        var replaced = details.fields_replaced || [];
        var skipped = details.fields_skipped || [];

        var lines = [];
        if (added.length) lines.push(_i18n.batchAdded + ' ' + added.map(_applyFieldLabel).join(', '));
        if (replaced.length) lines.push(_i18n.replacedBetterQuality + ' ' + replaced.map(_applyFieldLabel).join(', '));
        if (skipped.length) lines.push(_i18n.keptExisting + ' ' + skipped.map(_applyFieldLabel).join(', '));
        if (lines.length === 0) {
            lines.push(_i18n.bookHadAllMetadata);
        }
        return lines.join('\n');
    }

    function abortBatchSearch() {
        // Close SSE stream immediately on the client so UI stops blocking.
        if (_batchSSESource) {
            try { _batchSSESource.close(); } catch (e) {}
            _batchSSESource = null;
        }
        // Tell the backend to stop in the background.
        fetch('/metadata/abort', {method: 'POST'}).catch(function(){});

        var titleEl = document.getElementById('batchProgressTitle');
        if (titleEl) titleEl.textContent = _i18n.searchAborted;
        _hideBatchAbortBtn();

        // Show "Continue to review" if any books finished and were cached.
        if (Object.keys(_batchWizard.searchCache).length > 0) {
            var continueBtnA = document.getElementById('batchContinueBtn');
            if (!continueBtnA) {
                continueBtnA = document.createElement('button');
                continueBtnA.id = 'batchContinueBtn';
                continueBtnA.type = 'button';
                continueBtnA.className = 'btn primary';
                continueBtnA.style.marginTop = '16px';
                continueBtnA.textContent = _i18n.continueToReview;
                continueBtnA.onclick = function() { _batchSetStep(3); _batchRenderReview(); };
                document.getElementById('batchStep2').appendChild(continueBtnA);
            }
            continueBtnA.style.display = '';
        }
    }
    function _resetBatchAbortBtn() {
        var btn = document.getElementById('batchAbortBtn');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="ti ti-x"></i> ' + _i18n.batchAbortSearch;
            btn.style.display = '';
        }
    }
    function _hideBatchAbortBtn() {
        var btn = document.getElementById('batchAbortBtn');
        if (btn) btn.style.display = 'none';
    }

    function _showBatchTerminalButtons() {
        _hideBatchAbortBtn();
        var container = document.getElementById('batchStep2');

        if (Object.keys(_batchWizard.searchCache).length > 0) {
            var continueBtn = document.getElementById('batchContinueBtn');
            if (!continueBtn) {
                continueBtn = document.createElement('button');
                continueBtn.id = 'batchContinueBtn';
                continueBtn.type = 'button';
                continueBtn.className = 'btn primary';
                continueBtn.style.marginTop = '16px';
                continueBtn.textContent = _i18n.continueToReview;
                continueBtn.onclick = function() { _batchSetStep(3); _batchRenderReview(); };
                container.appendChild(continueBtn);
            }
            continueBtn.style.display = '';
        }

        var closeBtn = document.getElementById('batchCloseBtn');
        if (!closeBtn) {
            closeBtn = document.createElement('button');
            closeBtn.id = 'batchCloseBtn';
            closeBtn.type = 'button';
            closeBtn.className = 'btn ghost';
            closeBtn.style.marginTop = '16px';
            closeBtn.style.marginLeft = '8px';
            closeBtn.textContent = _i18n.close;
            closeBtn.onclick = function() { closeBatchModal(); };
            container.appendChild(closeBtn);
        }
        closeBtn.style.display = '';
    }

    function startBatchSearch() {
        if (!window.EventSource) { alert(_i18n.sseNotSupported); return; }

        var itemIds = (_batchWizard.selectedItemIds && _batchWizard.selectedItemIds.length)
            ? _batchWizard.selectedItemIds
            : _getBatchItemIds();
        if (itemIds.length === 0) { alert(_i18n.chooseAtLeastOneBook); return; }

        var maxItemsEl = document.getElementById('batchMaxItems');
        var maxItems = (maxItemsEl && maxItemsEl.value) || '25';

        var url = '/metadata/bulk/stream?item_ids=' + itemIds.join(',')
            + '&max_items=' + maxItems
            + '&mode=' + encodeURIComponent(_batchFetchModeSel);

        var body = document.getElementById('batchProgressBody');
        var summaryEl = document.getElementById('batchProgressSub');
        var titleEl = document.getElementById('batchProgressTitle');
        body.innerHTML = '';
        titleEl.textContent = _i18n.searchingMetadata;
        _resetBatchAbortBtn();
        var existingContinueBtn = document.getElementById('batchContinueBtn');
        if (existingContinueBtn) existingContinueBtn.style.display = 'none';
        var existingCloseBtn = document.getElementById('batchCloseBtn');
        if (existingCloseBtn) existingCloseBtn.style.display = 'none';

        var counts = { saved: 0, review: 0, done: 0 };
        var source = new EventSource(url);
        _batchSSESource = source;

        source.onmessage = function(e) {
            var d;
            try { d = JSON.parse(e.data); } catch(ex) { return; }

            if (d.type === 'group_sync' && d.fields_synced > 0) {
                var syncTr = document.createElement('tr');
                var nFmts = (d.details || []).length;
                syncTr.innerHTML =
                    '<td colspan="5" style="font-size:12px; color:var(--text-secondary); padding:4px 10px;">' +
                    _i18n.syncedFields.replace('{count}', d.fields_synced).replace('{formats}', nFmts) +
                    '</td>';
                body.appendChild(syncTr);

            } else if (d.type === 'book_start') {
                document.querySelectorAll('#batchProgressBody tr.bp-active').forEach(function(r) {
                    r.classList.remove('bp-active');
                });
                _sourceDetails[d.item_id] = [];
                var tr = document.createElement('tr');
                tr.id = 'bp-row-' + d.item_id;
                tr.className = 'bp-active';
                var title = d.title || '';
                if (title.length > 45) title = title.substring(0, 45) + '…';
                var fmtHtml = '';
                if (d.formats && d.formats.length > 0) {
                    fmtHtml = ' ' + d.formats.map(function(f) {
                        return '<span class="format-badge">' + _esc(f) + '</span>';
                    }).join(' ');
                }
                tr.innerHTML =
                    '<td>' + _esc(title) + fmtHtml + '</td>' +
                    '<td style="text-align:center;" id="bp-google-' + d.item_id + '"></td>' +
                    '<td style="text-align:center;" id="bp-calibre-' + d.item_id + '"></td>' +
                    '<td style="text-align:center;" id="bp-score-' + d.item_id + '"></td>' +
                    '<td style="text-align:center;" id="bp-result-' + d.item_id + '"></td>';
                body.appendChild(tr);
                var unit = d.total === 1 ? _i18n.bookSingular : _i18n.bookPlural;
                summaryEl.textContent = d.index + ' av ' + d.total + ' ' + unit + '…';

            } else if (d.type === 'progress') {
                var stageMap = { google_books: 'google', calibre: 'calibre' };
                var key = stageMap[d.stage];
                if (key) {
                    var cell = document.getElementById('bp-' + key + '-' + d.item_id);
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
                    if (!_sourceDetails[d.item_id]) _sourceDetails[d.item_id] = [];
                    d.source_details.forEach(function(sd) { _sourceDetails[d.item_id].push(sd); });
                    var detailEl = document.getElementById('bp-detail-' + d.item_id);
                    if (detailEl && detailEl.classList.contains('expanded')) _renderSourceDetail(d.item_id);
                }

            } else if (d.type === 'book_done') {
                var _cacheEntry = {
                    title: d.title || '',
                    before: d.before || {},
                    candidate: d.candidate || {},
                    provenance: d.provenance || {},
                    diff: d.diff || [],
                    classification: d.classification,
                    score: d.score,
                    source: d.source || '',
                    warnings: d.warnings || [],
                    quality_notes: d.quality_notes || {},
                    item_ids: d.item_ids || [d.item_id],
                    source_details: d.source_details || _sourceDetails[d.item_id] || [],
                    apply_details: d.apply_details || null,
                    field_confidence: d.field_confidence || {},
                    all_candidates: d.all_candidates || [],
                    has_cover_before: d.has_cover_before || false,
                    cover_url_fetched: d.cover_url_fetched || null,
                    has_cover_fetched: d.has_cover_fetched || false,
                };
                _bulkResultData[d.item_id] = _cacheEntry;
                _batchWizard.searchCache[d.item_id] = _cacheEntry;
                if (d.source_details && d.source_details.length > 0) {
                    _sourceDetails[d.item_id] = d.source_details;
                    var detailEl2 = document.getElementById('bp-detail-' + d.item_id);
                    if (detailEl2 && detailEl2.classList.contains('expanded')) _renderSourceDetail(d.item_id);
                }

                var tr = document.getElementById('bp-row-' + d.item_id);
                if (!tr) {
                    tr = document.createElement('tr');
                    tr.id = 'bp-row-' + d.item_id;
                    var title = d.title || '';
                    if (title.length > 45) title = title.substring(0, 45) + '…';
                    var fmtHtml = '';
                    if (d.formats && d.formats.length > 0) {
                        fmtHtml = ' ' + d.formats.map(function(f) {
                            return '<span class="format-badge">' + _esc(f) + '</span>';
                        }).join(' ');
                    }
                    tr.innerHTML =
                        '<td>' + _esc(title) + fmtHtml + '</td>' +
                        '<td style="text-align:center;" id="bp-google-' + d.item_id + '">—</td>' +
                        '<td style="text-align:center;" id="bp-calibre-' + d.item_id + '">—</td>' +
                        '<td style="text-align:center;" id="bp-score-' + d.item_id + '"></td>' +
                        '<td style="text-align:center;" id="bp-result-' + d.item_id + '"></td>';
                    body.appendChild(tr);
                }
                tr.classList.remove('bp-active');

                var gCell = document.getElementById('bp-google-' + d.item_id);
                if (gCell && !gCell.textContent.trim()) {
                    gCell.innerHTML = (d.google_ok === null || d.google_ok === undefined)
                        ? '—'
                        : (d.google_ok ? '<span class="bp-ok">✓ ' + (d.google_candidates || 0) + '</span>' : '<span class="bp-fail">✗</span>');
                }
                var cCell = document.getElementById('bp-calibre-' + d.item_id);
                if (cCell && !cCell.textContent.trim()) {
                    if (d.calibre_status === 'skipped') {
                        cCell.innerHTML = '<span class="bp-skip" title="' + _esc(d.fetch_mode || '') + '">–</span>';
                    } else {
                        cCell.innerHTML = (d.calibre_ok === null || d.calibre_ok === undefined)
                            ? '—'
                            : (d.calibre_ok ? '<span class="bp-ok">✓ ' + (d.calibre_candidates || 0) + '</span>' : '<span class="bp-fail">✗</span>');
                    }
                }

                var scoreCell = document.getElementById('bp-score-' + d.item_id);
                if (scoreCell) {
                    if (d.score !== null && d.score !== undefined
                            && d.classification !== 'skipped' && d.classification !== 'source_error') {
                        var s = Math.round(d.score);
                        var cls, tooltip;
                        if (s >= 90) { cls = 'bp-ok'; tooltip = 'Stark match – sparas automatiskt'; }
                        else if (s >= 70) { cls = 'bp-warn'; tooltip = _i18n.likelyMatch; }
                        else if (s >= 50) { cls = 'bp-uncertain'; tooltip = _i18n.uncertainMatch; }
                        else { cls = 'bp-fail'; tooltip = 'Svag match'; }
                        scoreCell.innerHTML = '<span class="' + cls + '" title="' + tooltip + '">' + s + '</span>';
                        var bpTr = document.getElementById('bp-row-' + d.item_id);
                        if (bpTr) {
                            var bpCls = s >= 90 ? 'bp-score-strong' : s >= 70 ? 'bp-score-likely' : 'bp-score-weak';
                            bpTr.classList.add(bpCls);
                        }
                    } else {
                        scoreCell.textContent = '—';
                    }
                }

                var resultCell = document.getElementById('bp-result-' + d.item_id);
                if (resultCell) {
                    if (d.classification === 'no_match') {
                        resultCell.innerHTML = '<span class="bp-fail" title="' + _i18n.noMatch + '">✗</span>';
                    } else if (d.classification === 'source_error') {
                        resultCell.innerHTML = '<span class="bp-fail" title="' + _i18n.sourceError + '">⚠</span>';
                    } else if (d.classification === 'skipped') {
                        resultCell.innerHTML = '<span class="bp-skip" title="Hoppad">—</span>';
                    } else {
                        var rs = Math.round(d.score || 0);
                        var rIcon, rCls, rTip;
                        if (rs >= 90)      { rIcon = '✓'; rCls = 'bp-ok';        rTip = 'Stark match (' + rs + 'p)'; }
                        else if (rs >= 70) { rIcon = '●'; rCls = 'bp-warn';      rTip = 'Trolig match (' + rs + 'p) — granskas i steg 3'; }
                        else if (rs >= 50) { rIcon = '⚠'; rCls = 'bp-uncertain'; rTip = _i18n.uncertainMatch + ' (' + rs + 'p)'; }
                        else               { rIcon = '—'; rCls = 'bp-skip';      rTip = 'Svag match (' + rs + 'p)'; }
                        var autoTip = _resultTooltip(d);
                        resultCell.innerHTML = '<span class="' + rCls + '" title="' + _esc(autoTip || rTip) + '">' + rIcon + '</span>';
                    }
                }

                counts.done += 1;
                if (d.classification === 'auto_apply') counts.saved += 1;
                if (d.classification === 'review_needed') counts.review += 1;
                var doneUnit = d.total === 1 ? _i18n.bookSingular : _i18n.bookPlural;
                summaryEl.textContent = counts.done + ' av ' + d.total + ' ' + doneUnit + ' klara'
                    + (counts.saved ? ' — ' + counts.saved + ' sparade' : '')
                    + (counts.review ? ', ' + counts.review + ' granskning' : '');

            } else if (d.type === 'done') {
                source.close();
                _batchSSESource = null;
                _hideBatchAbortBtn();
                titleEl.textContent = _i18n.searchDone;
                var s = d.summary || {};
                var parts = [];
                if (s.updated) parts.push(s.updated + ' sparade');
                if (s.review_needed) parts.push(s.review_needed + ' granskning');
                if (s.no_match) parts.push(_i18n.sNoMatch.replace('{count}', s.no_match));
                if (s.source_errors) parts.push(_i18n.sSourceError.replace('{count}', s.source_errors));
                if (s.skipped) parts.push(s.skipped + ' hoppade');
                summaryEl.textContent = parts.join(' · ') || 'Klar.';
                var continueBtn = document.getElementById('batchContinueBtn');
                if (!continueBtn) {
                    continueBtn = document.createElement('button');
                    continueBtn.id = 'batchContinueBtn';
                    continueBtn.type = 'button';
                    continueBtn.className = 'btn primary';
                    continueBtn.style.marginTop = '16px';
                    continueBtn.textContent = _i18n.continueToReview;
                    continueBtn.onclick = function() { _batchSetStep(3); _batchRenderReview(); };
                    document.getElementById('batchStep2').appendChild(continueBtn);
                }
                continueBtn.style.display = '';

            } else if (d.type === 'aborted') {
                source.close();
                _batchSSESource = null;
                var processed = d.processed || 0;
                titleEl.textContent = _i18n.searchAbortedWith + ' '
                    + window._pluralize(processed, 'nBookProcessedOne', 'nBooksProcessedMany');
                var s = d.summary || {};
                var parts = [];
                if (s.updated) parts.push(_i18n.nSaved.replace('{count}', s.updated));
                if (s.review_needed) parts.push(_i18n.nReviewNeeded.replace('{count}', s.review_needed));
                if (s.no_match) parts.push(_i18n.sNoMatch.replace('{count}', s.no_match));
                if (s.source_errors) parts.push(_i18n.sSourceError.replace('{count}', s.source_errors));
                summaryEl.textContent = parts.length
                    ? _i18n.searchAbortedSummary.replace('{parts}', parts.join(' · '))
                    : _i18n.searchAbortedNothing;
                _showBatchTerminalButtons();

            } else if (d.type === 'error') {
                source.close();
                _batchSSESource = null;
                titleEl.textContent = _i18n.scanError + ' ' + (d.message || _i18n.unknownError);
                _showBatchTerminalButtons();
            }
        };

        source.onerror = function() {
            source.close();
            _batchSSESource = null;
            titleEl.textContent = _i18n.connectionLost;
            _showBatchTerminalButtons();
        };
    }

    function startBatchAI() {
        var itemIds = _getBatchItemIds();
        if (itemIds.length === 0) { alert(_i18n.chooseAtLeastOneBook); return; }

        var overwrite = document.getElementById('batchOverwrite').checked ? '1' : '0';
        var maxItems = document.getElementById('batchMaxItems').value || '25';

        document.getElementById('batchActions').style.display = 'none';
        document.getElementById('batchProgressTitle').textContent = _i18n.runningAi;
        document.getElementById('batchProgressSub').textContent = _i18n.runningAiSub;
        document.getElementById('batchProgress').style.display = 'block';
        document.getElementById('batchProgressBody').innerHTML = '';
        document.getElementById('batchResult').style.display = 'none';

        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/metadata/bulk';
        function _addHidden(name, value) {
            var inp = document.createElement('input');
            inp.type = 'hidden';
            inp.name = name;
            inp.value = value;
            form.appendChild(inp);
        }
        _addHidden('action', 'ai');
        _addHidden('overwrite', overwrite);
        _addHidden('max_items', maxItems);
        itemIds.forEach(function(id) { _addHidden('item_ids', id); });
        document.body.appendChild(form);
        form.submit();
    }

    function confirmBatchDelete() {
        var itemIds = _getBatchItemIds();
        if (itemIds.length === 0) { alert(_i18n.chooseAtLeastOneBook); return; }

        var confirmEl = document.getElementById('batchResult');
        confirmEl.style.display = 'block';
        var confirmTitle = window._pluralize(
            itemIds.length, 'deleteBookConfirmOne', 'deleteBooksConfirmMany'
        );
        document.getElementById('batchResultSummary').innerHTML =
            '<strong>' + confirmTitle + '</strong>'
            + '<div style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;">'
            + '<button type="button" class="btn ghost" onclick="_executeBatchDelete(false)">' + _i18n.removeFromLibrary + '</button>'
            + '<button type="button" class="btn-danger" onclick="_executeBatchDelete(true)">' + _i18n.deletePermanentlyIncludeFile + '</button>'
            + '<button type="button" class="btn ghost" onclick="document.getElementById(\'batchResult\').style.display=\'none\'">' + _i18n.cancelLabel + '</button>'
            + '</div>';
    }

    function _executeBatchDelete(deleteFiles) {
        var itemIds = _getBatchItemIds().map(function(id) { return parseInt(id, 10); });
        if (deleteFiles) {
            var confirmText = prompt(
                _i18n.deleteEnterRADERA
            );
            if (confirmText !== 'RADERA') return;
        }

        document.getElementById('batchResultSummary').textContent = _i18n.deleting;

        fetch('/metadata/bulk/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_ids: itemIds, delete_files: deleteFiles })
        })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.ok) {
                    document.getElementById('batchResultSummary').textContent = _i18n.scanError + ' ' + (data.error || _i18n.unknownError);
                    return;
                }
                itemIds.forEach(function(id) {
                    var row = document.querySelector('tr[data-item-id="' + id + '"]');
                    if (row) row.remove();
                });
                renderGroupedView();
                updateSelectedCount();
                updateBatchBar();
                var msg = window._pluralize(
                    data.deleted, 'nBookDeletedOne', 'nBooksDeletedMany'
                );
                if (data.file_errors) {
                    msg += ' ' + window._pluralize(
                        data.file_errors,
                        'nFileCouldNotBeDeletedOne',
                        'nFilesCouldNotBeDeletedMany'
                    );
                }
                document.getElementById('batchResultSummary').textContent = msg;
                closeBatchModal();
            })
            .catch(function() {
                document.getElementById('batchResultSummary').textContent = _i18n.deletionFailed;
            });
    }

    /* -------------------------------------------------------------------- */
    /* Book modal                                                            */
    /* -------------------------------------------------------------------- */
    var _modalItemId = null;
    var _modalDirty = false;
    var _modalAllCandidates = [];
    var _coverUrlBase = window.__colophonConfig.urls.coverItemBase;
    var _modalSSESource = null;

    /* ------------------------------------------------------------------ *
     * Publish entry points on window — every top-level function is
     * mirrored so HTML onclick / cross-module calls resolve uniformly.
     * ------------------------------------------------------------------ */
    window._resetBatchWizardState = _resetBatchWizardState;
    window._renderWizardSteps = _renderWizardSteps;
    window._batchGoToStep = _batchGoToStep;
    window._batchSetStep = _batchSetStep;
    window._batchUpdateSubtitle = _batchUpdateSubtitle;
    window.openBatchModal = openBatchModal;
    window.closeBatchModal = closeBatchModal;
    window._batchModalVisible = _batchModalVisible;
    window.toggleBwFields = toggleBwFields;
    window.batchWizardStartSearch = batchWizardStartSearch;
    window._isValidLanguageCode = _isValidLanguageCode;
    window._brtCellHtml = _brtCellHtml;
    window._brtToggleExpandRow = _brtToggleExpandRow;
    window.batchUseSource = batchUseSource;
    window._batchRenderReview = _batchRenderReview;
    window._batchRenderTextFieldReview_TABLE = _batchRenderTextFieldReview_TABLE;
    window._brtUpdateScrollHint = _brtUpdateScrollHint;
    window._brtToggleAltPanel = _brtToggleAltPanel;
    window._brcResolveCols = _brcResolveCols;
    window._brcFieldValue = _brcFieldValue;
    window._brcBuildSourceList = _brcBuildSourceList;
    window._brcRenderSourcePanel = _brcRenderSourcePanel;
    window._brcRenderField = _brcRenderField;
    window._brcSourceChipHtml = _brcSourceChipHtml;
    window._brcDiffMap = _brcDiffMap;
    window._brcRejectedFieldHtml = _brcRejectedFieldHtml;
    window._batchRenderTextFieldReview = _batchRenderTextFieldReview;
    window._brcBindDelegation = _brcBindDelegation;
    window._brcOnClick = _brcOnClick;
    window._brcGetColor = _brcGetColor;
    window._brcUpdateCardField = _brcUpdateCardField;
    window._brcMarkPicked = _brcMarkPicked;
    window._brcCherryPick = _brcCherryPick;
    window._brcApplyAllFromSource = _brcApplyAllFromSource;
    window._brcToggleField = _brcToggleField;
    window._brcRenderRejectedField = _brcRenderRejectedField;
    window._brcUpdateBadge = _brcUpdateBadge;
    window._batchSaveTextFields = _batchSaveTextFields;
    window._batchRenderSynopsisReview = _batchRenderSynopsisReview;
    window._batchSaveSynopsis = _batchSaveSynopsis;
    window._batchRenderCoverReview = _batchRenderCoverReview;
    window._batchSaveCover = _batchSaveCover;
    window._batchSkipReview = _batchSkipReview;
    window._batchAdvanceReview = _batchAdvanceReview;
    window._batchRenderSummary = _batchRenderSummary;
    window._batchFilterMissing = _batchFilterMissing;
    window._batchShowAddField = _batchShowAddField;
    window._getBatchItemIds = _getBatchItemIds;
    window._esc = _esc;
    window._cleanDate = _cleanDate;
    window._applyFieldLabel = _applyFieldLabel;
    window._resultLabel = _resultLabel;
    window._resultTooltip = _resultTooltip;
    window.abortBatchSearch = abortBatchSearch;
    window._resetBatchAbortBtn = _resetBatchAbortBtn;
    window._hideBatchAbortBtn = _hideBatchAbortBtn;
    window._showBatchTerminalButtons = _showBatchTerminalButtons;
    window.startBatchSearch = startBatchSearch;
    window.startBatchAI = startBatchAI;
    window.confirmBatchDelete = confirmBatchDelete;
    window._executeBatchDelete = _executeBatchDelete;
})(window, document);
