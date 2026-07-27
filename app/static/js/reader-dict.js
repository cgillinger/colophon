// Colophon – e-book metadata manager
//
// Dictionary lookup for the in-browser reader (see
// docs/reader-dictionary-lookup.md). Select a single word inside the book →
// a bottom sheet shows an English definition + Swedish translation from the
// server-side lookup endpoint, with an optional AI "explain in this sentence"
// call. First lookup in a language triggers a one-time dictionary download.
//
// ES module, wired from reader.js after the foliate view is created. All
// selection listening happens inside the book iframe documents, which foliate
// hands us via its per-section 'load' events.

var WORD_RE = /^[\p{L}\p{M}'’ʼ-]{2,64}$/u;
var SENTENCE_CAP = 400;

function debounce(fn, ms) {
    var t = null;
    return function () {
        if (t) clearTimeout(t);
        t = setTimeout(fn, ms);
    };
}

// Strip anything active from dictionary HTML entries ('h' type) before
// injection: the files come from pinned sources, but they're still foreign
// content — scripts, event handlers and javascript: URLs all go.
function sanitizeEntryHtml(html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script, style, link, iframe, object, embed, img')
        .forEach(function (el) { el.remove(); });
    doc.querySelectorAll('*').forEach(function (el) {
        Array.prototype.slice.call(el.attributes).forEach(function (attr) {
            var name = attr.name.toLowerCase();
            if (name.indexOf('on') === 0) el.removeAttribute(attr.name);
            else if ((name === 'href' || name === 'src')
                && /^\s*javascript:/i.test(attr.value)) el.removeAttribute(attr.name);
        });
    });
    return doc.body.innerHTML;
}

// The sentence the word sits in, clipped from its block's text — context for
// the AI prompt, never shown verbatim to any dictionary.
function sentenceAround(sel, word) {
    var node = sel.anchorNode;
    if (!node) return '';
    var el = node.nodeType === 3 ? node.parentElement : node;
    var block = (el && el.closest && el.closest('p, li, blockquote, dd, td, div, h1, h2, h3')) || el;
    if (!block) return '';
    var text = (block.textContent || '').replace(/\s+/g, ' ').trim();
    var idx = text.indexOf(word);
    if (idx < 0) return text.slice(0, SENTENCE_CAP);
    var start = idx, end = idx + word.length;
    while (start > 0 && !/[.!?…]/.test(text[start - 1]) && idx - start < SENTENCE_CAP / 2) start--;
    while (end < text.length && !/[.!?…]/.test(text[end]) && end - idx < SENTENCE_CAP / 2) end++;
    if (end < text.length) end++;   // keep the closing punctuation
    return text.slice(start, end).trim();
}

export function initDictLookup(opts) {
    var view = opts.view;
    var cfg = opts.cfg || {};
    var i18n = cfg.i18n || {};

    var sheet = document.getElementById('readerDictSheet');
    if (!sheet || !view) return null;

    var wordEl = document.getElementById('rdWord');
    var statusEl = document.getElementById('rdStatus');
    var defsEl = document.getElementById('rdDefs');
    var transRow = document.getElementById('rdTransRow');
    var transEl = document.getElementById('rdTrans');
    var aiBtn = document.getElementById('rdAiBtn');
    var aiBox = document.getElementById('rdAiBox');
    var aiText = document.getElementById('rdAiText');
    var closeBtn = document.getElementById('rdClose');

    var current = null;          // { word, sentence }
    var seq = 0;                 // stale-response guard
    var downloading = false;
    var openedAt = 0;

    function isOpen() { return !sheet.hidden; }
    function open() { sheet.hidden = false; openedAt = Date.now(); }
    function close() {
        sheet.hidden = true;
        current = null;
        seq++;
    }

    function resetBody() {
        statusEl.hidden = true;
        statusEl.textContent = '';
        statusEl.classList.remove('rd-busy');
        defsEl.hidden = true;
        defsEl.innerHTML = '';
        transRow.hidden = true;
        transEl.innerHTML = '';
        aiBox.hidden = true;
        aiText.textContent = '';
        aiBtn.hidden = !cfg.aiConfigured;
        aiBtn.disabled = false;
    }

    function showStatus(msg, busy) {
        statusEl.textContent = msg;
        statusEl.classList.toggle('rd-busy', !!busy);
        statusEl.hidden = false;
    }

    function renderEntry(container, match) {
        var div = document.createElement('div');
        div.className = 'rd-entry';
        if (match.type === 'h') div.innerHTML = sanitizeEntryHtml(match.text);
        else {
            div.classList.add('rd-pre');
            div.textContent = match.text.trim();
        }
        container.appendChild(div);
    }

    function renderMatches(data) {
        var any = false;
        (data.matches || []).forEach(function (m) {
            if (m.kind === 'translation') {
                renderEntry(transEl, m);
                transRow.hidden = false;
            } else {
                renderEntry(defsEl, m);
                defsEl.hidden = false;
            }
            any = true;
        });
        if (!any) {
            showStatus(cfg.aiConfigured
                ? (i18n.dictMiss || 'No entry found — try the AI explanation.')
                : (i18n.dictMissNoAi || 'No entry found.'));
        }
    }

    function startDownload(data, myseq) {
        if (downloading) return;
        downloading = true;
        var label = (i18n.dictDownloading || 'Downloading dictionaries ({mb} MB, one-time)…')
            .replace('{mb}', data.download_mb);
        showStatus(label, true);
        fetch(cfg.dictDownloadUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: data.language })
        }).then(function (r) { return r.json(); }).then(function (res) {
            downloading = false;
            if (myseq !== seq || !current) return;
            if (res && res.ok) lookup(current.word, current.sentence);
            else showStatus(i18n.dictDownloadFailed || 'Dictionary download failed — see the server log.');
        }).catch(function () {
            downloading = false;
            if (myseq !== seq) return;
            showStatus(i18n.dictDownloadFailed || 'Dictionary download failed — see the server log.');
        });
    }

    function lookup(word, sentence) {
        current = { word: word, sentence: sentence };
        var myseq = ++seq;
        wordEl.textContent = word;
        resetBody();
        showStatus(i18n.dictLoading || 'Looking up…', true);
        open();

        var url = cfg.dictLookupUrl
            + '?word=' + encodeURIComponent(word)
            + '&lang=' + encodeURIComponent(cfg.bookLanguage || '');
        fetch(url).then(function (r) { return r.json(); }).then(function (data) {
            if (myseq !== seq) return;
            resetBody();
            if (data.status === 'ok') renderMatches(data);
            else if (data.status === 'needs_download') startDownload(data, myseq);
            else if (data.status === 'unsupported_language') {
                showStatus(cfg.aiConfigured
                    ? (i18n.dictNoLanguage || 'No dictionary for this language yet — the AI explanation still works.')
                    : (i18n.dictNoLanguageNoAi || 'No dictionary for this language yet.'));
            } else showStatus(i18n.dictError || 'Lookup failed.');
        }).catch(function () {
            if (myseq !== seq) return;
            resetBody();
            showStatus(i18n.dictError || 'Lookup failed.');
        });
    }

    function explain() {
        if (!current) return;
        aiBtn.disabled = true;
        aiBox.hidden = false;
        aiText.textContent = i18n.dictAiThinking || 'Thinking…';
        fetch(cfg.dictExplainUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: current.word, sentence: current.sentence })
        }).then(function (r) { return r.json(); }).then(function (res) {
            aiBtn.disabled = false;
            if (res && res.ok) aiText.textContent = res.explanation;
            else aiText.textContent = i18n.dictAiFailed || 'AI explanation failed.';
        }).catch(function () {
            aiBtn.disabled = false;
            aiText.textContent = i18n.dictAiFailed || 'AI explanation failed.';
        });
    }

    // --- Selection wiring inside the book iframe --------------------------
    function checkSelection(doc) {
        var sel = doc.getSelection && doc.getSelection();
        if (!sel || sel.isCollapsed) return;
        var text = sel.toString().trim();
        if (!WORD_RE.test(text)) return;
        lookup(text, sentenceAround(sel, text));
    }

    function wireDoc(doc) {
        if (!doc || doc.__colophonDictWired) return;
        doc.__colophonDictWired = true;
        var deferred = debounce(function () { checkSelection(doc); }, 350);
        // pointerup covers mouse selection; the debounced selectionchange
        // covers touch handles (iOS fires pointerup before the selection
        // settles) and keyboard selection.
        doc.addEventListener('pointerup', deferred);
        doc.addEventListener('selectionchange', deferred);
    }

    view.addEventListener('load', function (e) {
        var detail = e.detail || {};
        if (detail.doc) wireDoc(detail.doc);
    });
    // A page turn means the reader moved on — take the sheet with it. The
    // grace period keeps the anchoring scroll that can accompany a selection
    // near a page edge from closing the sheet it just opened.
    view.addEventListener('relocate', function () {
        if (isOpen() && Date.now() - openedAt > 800) close();
    });

    if (closeBtn) closeBtn.addEventListener('click', close);
    if (aiBtn) aiBtn.addEventListener('click', explain);

    return { isOpen: isOpen, close: close };
}
