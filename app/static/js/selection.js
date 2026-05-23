/* ------------------------------------------------------------------ *
 * selection.js — Row selection, the batch action bar, bulk delete
 *
 * Owns:
 *   - Per-row checkbox selection lifecycle (clear / select-all)
 *   - The "selected: N" label and the batch bar visibility
 *   - The grouped-mode parent→children checkbox mirroring (one click
 *     on a parent must mark every hidden format)
 *   - The bulk-delete flow + the Danger Zone reveal toggle
 *   - One delegated `change` listener on document for .book-checkbox
 *
 * Reads from window.* mirrored state:
 *   _grouped — owned by the (still inline) grouping section. It's a
 *   top-level `var` in the non-strict main inline script, so it lives
 *   on window automatically; this IIFE accesses it via window._grouped
 *   explicitly for clarity.
 *
 * Reads i18n strings from window.__colophonConfig.i18n:
 *   chooseAtLeastOneBook, confirmBulkDeleteHeader, confirmDeleteFiles,
 *   errorWithMsg, unknownError
 *
 * Note: the count labels keep their hard-coded Swedish wording
 * (' grupp', ' bok', ' valda', etc.) — preserving exact pre-refactor
 * behaviour. Pluralisation and proper i18n of these is out of scope.
 *
 * Exposes globals consumed by the template / other modules:
 *   clearSelection, toggleSelectAll, deselectAll, updateBatchBar,
 *   updateSelectedCount, _syncGroupChildrenFromParents,
 *   toggleDangerZone, confirmBulkDelete
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    /* ============================================================ *
     * Selection state + batch bar
     * ============================================================ */

    function _syncGroupChildrenFromParents() {
        // Mirror every group-parent's checkbox state onto its hidden
        // group-children so all formats follow the parent.
        if (!window._grouped) return;
        document.querySelectorAll('tr.group-parent[data-group-key]').forEach(function (parent) {
            var key = parent.dataset.groupKey;
            if (!key) return;
            var parentCb = parent.querySelector('.book-checkbox');
            if (!parentCb) return;
            document.querySelectorAll('tr.group-child[data-group-key="' + key + '"] .book-checkbox')
                .forEach(function (cb) { cb.checked = parentCb.checked; });
        });
    }
    window._syncGroupChildrenFromParents = _syncGroupChildrenFromParents;

    function clearSelection() {
        document.querySelectorAll('.book-checkbox').forEach(function (box) { box.checked = false; });
        updateSelectedCount();
        updateBatchBar();
    }
    window.clearSelection = clearSelection;

    function toggleSelectAll(master) {
        var rows = document.querySelectorAll('#bookTableBody tr');
        rows.forEach(function (row) {
            if (row.style.display !== 'none') {
                var cb = row.querySelector('input[type="checkbox"]');
                if (cb) cb.checked = master.checked;
            }
        });
        _syncGroupChildrenFromParents();
        updateSelectedCount();
        updateBatchBar();
    }
    window.toggleSelectAll = toggleSelectAll;

    function deselectAll() {
        clearSelection();
    }
    window.deselectAll = deselectAll;

    function updateBatchBar() {
        var checked = document.querySelectorAll('.book-checkbox:checked');
        var bar = document.getElementById('batchBar');
        var count = document.getElementById('batchBarCount');
        if (!bar) return;

        if (checked.length > 1) {
            bar.style.display = 'flex';
            if (window._grouped) {
                var groupKeys = new Set();
                checked.forEach(function (cb) {
                    var row = cb.closest('tr');
                    if (row && row.dataset.groupKey) groupKeys.add(row.dataset.groupKey);
                });
                count.textContent = groupKeys.size + ' grupp' + (groupKeys.size !== 1 ? 'er' : '') + ' valda';
            } else {
                count.textContent = checked.length + ' bok' + (checked.length !== 1 ? 'er' : '') + ' valda';
            }
        } else {
            bar.style.display = 'none';
        }
    }
    window.updateBatchBar = updateBatchBar;

    function updateSelectedCount() {
        var el = document.getElementById('selectedCount');
        if (!el) return;

        var checked = document.querySelectorAll('.book-checkbox:checked');

        if (!window._grouped) {
            el.textContent = checked.length + ' valda';
            return;
        }

        // Grouped mode: count distinct selected groups and total formats.
        // Items without a group_key count as standalone selections.
        var groupKeys = new Set();
        var soloItems = 0;
        checked.forEach(function (cb) {
            var row = cb.closest('tr');
            var key = row && row.dataset.groupKey ? row.dataset.groupKey : '';
            if (key) groupKeys.add(key);
            else soloItems += 1;
        });

        var totalFiles = soloItems;
        groupKeys.forEach(function (key) {
            totalFiles += document.querySelectorAll(
                'tr[data-group-key="' + key + '"] .book-checkbox'
            ).length;
        });

        var groupCount = groupKeys.size + soloItems;
        if (groupCount === 0) {
            el.textContent = '0 valda';
        } else {
            el.textContent =
                groupCount + ' grupp' + (groupCount !== 1 ? 'er' : '')
                + ' (' + totalFiles + ' fil' + (totalFiles !== 1 ? 'er' : '') + ') valda';
        }
    }
    window.updateSelectedCount = updateSelectedCount;

    /* Delegated change-listener: any .book-checkbox toggle re-syncs
       group children (if grouped) and updates the count + bar. */
    document.addEventListener('change', function (e) {
        if (!(e.target && e.target.classList && e.target.classList.contains('book-checkbox'))) {
            return;
        }
        // Uncheck select-all when any row checkbox changes
        var selectAll = document.getElementById('selectAllCheckbox');
        if (selectAll && !e.target.checked) selectAll.checked = false;
        // In grouped view, toggling the parent's checkbox should mirror to
        // every (hidden) child format so the SSE submit picks them all up.
        if (window._grouped) {
            var row = e.target.closest('tr');
            var key = row && row.dataset.groupKey ? row.dataset.groupKey : '';
            if (key && row.classList.contains('group-parent')) {
                document.querySelectorAll(
                    'tr.group-child[data-group-key="' + key + '"] .book-checkbox'
                ).forEach(function (cb) { cb.checked = e.target.checked; });
            }
        }
        updateSelectedCount();
        updateBatchBar();
    });

    /* ============================================================ *
     * Bulk delete (Danger Zone)
     * ============================================================ */

    function toggleDangerZone() {
        var show = document.getElementById('showDangerZone').checked;
        var el = document.getElementById('dangerZone');
        if (el) el.style.display = show ? '' : 'none';
    }
    window.toggleDangerZone = toggleDangerZone;

    function confirmBulkDelete() {
        var checked = Array.from(document.querySelectorAll('.book-checkbox:checked'));
        if (checked.length === 0) {
            alert(_i18n.chooseAtLeastOneBook);
            return;
        }

        if (!confirm(_i18n.confirmBulkDeleteHeader)) return;

        var deleteFiles = false;
        var confirmText = prompt(_i18n.confirmDeleteFiles);
        if (confirmText === 'DELETE' || confirmText === 'RADERA') deleteFiles = true;

        var itemIds = checked.map(function (cb) { return parseInt(cb.value, 10); });

        fetch('/metadata/bulk/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_ids: itemIds, delete_files: deleteFiles })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.ok) {
                    alert(_i18n.errorWithMsg.replace('{msg}', data.error || _i18n.unknownError));
                    return;
                }
                itemIds.forEach(function (id) {
                    var row = document.querySelector('tr[data-item-id="' + id + '"]');
                    if (row) row.remove();
                });
                if (typeof renderGroupedView === 'function') renderGroupedView();
                updateSelectedCount();
                var resultMsg = data.deleted + ' bok' + (data.deleted !== 1 ? 'er' : '') + ' raderade.';
                if (data.file_errors) resultMsg += ' ' + data.file_errors + ' filer kunde inte raderas.';
                alert(resultMsg);
            })
            .catch(function () { alert('Radering misslyckades.'); });
    }
    window.confirmBulkDelete = confirmBulkDelete;
})(window, document);
