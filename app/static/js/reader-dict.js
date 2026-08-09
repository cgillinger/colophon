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
// Longer than this and the selection is a stray select-all, not a passage
// someone means to quote. Roughly a page of text.
var MAX_PASSAGE = 4000;
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
    var eyebrow = sheet.querySelector('.rd-eyebrow');
    var quoteEl = document.getElementById('rdQuote');
    var actionsEl = document.getElementById('rdActions');
    var copyBtn = document.getElementById('rdCopyBtn');
    var copyCiteBtn = document.getElementById('rdCopyCiteBtn');
    var gripBtn = document.getElementById('rdGrip');

    var DICT_EYEBROW = eyebrow ? eyebrow.textContent : '';
    var STR = {
        passage: i18n.rdPassage || 'Selected text',
        copied: i18n.rdCopied || 'Copied.',
        copyFailed: i18n.rdCopyFailed || 'Could not copy. Use your browser’s own copy instead.',
    };

    var current = null;          // { word, sentence }
    var selectedText = '';       // what the copy actions act on
    var placementPinned = false; // the user moved it; leave it alone until close
    var seq = 0;                 // stale-response guard
    var downloading = false;
    var openedAt = 0;

    function isOpen() { return !sheet.hidden; }
    function open() { sheet.hidden = false; openedAt = Date.now(); }

    // --- Where the sheet sits ---------------------------------------------
    // It is not modal: you are meant to keep looking at the passage it is
    // about. Anchored to the bottom it lands on exactly the text you just
    // selected whenever that text is low on the page. So put it at the end the
    // selection is *not* at, and let the grip override when the guess is wrong.

    function placeAwayFrom(doc, sel) {
        if (placementPinned) return;
        var mid = selectionMidpoint(doc, sel);
        if (mid == null) return;
        sheet.classList.toggle('rd-top', mid > window.innerHeight / 2);
    }

    // The selection lives inside the book's iframe, so its rectangle is in the
    // iframe's coordinates — the frame's own offset has to be added to compare
    // it against the window.
    function selectionMidpoint(doc, sel) {
        try {
            var rect = sel.getRangeAt(0).getBoundingClientRect();
            if (!rect || (!rect.height && !rect.top)) return null;
            var frame = doc.defaultView && doc.defaultView.frameElement;
            var offset = frame ? frame.getBoundingClientRect().top : 0;
            return offset + rect.top + rect.height / 2;
        } catch (e) { return null; }
    }

    function togglePlacement() {
        sheet.classList.toggle('rd-top');
        // Honour the override for as long as this sheet is open, then forget
        // it — a pinned position would fight the next selection at the other
        // end of the page.
        placementPinned = true;
    }
    function close() {
        sheet.hidden = true;
        current = null;
        selectedText = '';
        placementPinned = false;
        if (actionsEl) actionsEl.hidden = true;
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
        // Passage mode is the exception, not the default: every lookup starts
        // from the dictionary layout and opts in. The copy actions are NOT
        // reset here — resetBody runs again when a lookup returns, and they
        // apply to whatever is selected either way. close() clears them.
        if (quoteEl) { quoteEl.hidden = true; quoteEl.textContent = ''; }
        if (eyebrow) eyebrow.textContent = DICT_EYEBROW;
    }

    function showStatus(msg, busy) {
        statusEl.textContent = msg;
        statusEl.classList.toggle('rd-busy', !!busy);
        statusEl.hidden = false;
    }

    function renderEntry(container, match, clamp) {
        var entry = document.createElement('div');
        entry.className = 'rd-entry';
        var body = document.createElement('div');
        if (match.type === 'h') body.innerHTML = sanitizeEntryHtml(match.text);
        else {
            body.classList.add('rd-pre');
            body.textContent = match.text.trim();
        }
        entry.appendChild(body);
        container.appendChild(entry);
        if (!clamp) return;
        // Collapse long entries (GCIDE definitions can be essay-length) and
        // only offer the toggle when something is actually clipped.
        body.classList.add('rd-clip');
        requestAnimationFrame(function () {
            if (body.scrollHeight <= body.clientHeight + 4) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'rd-more';
            btn.textContent = i18n.dictShowMore || 'Show more';
            btn.addEventListener('click', function () {
                var open = entry.classList.toggle('rd-open');
                btn.textContent = open ? (i18n.dictShowLess || 'Show less')
                                       : (i18n.dictShowMore || 'Show more');
            });
            entry.appendChild(btn);
        });
    }

    function renderMatches(data) {
        var any = false;
        (data.matches || []).forEach(function (m) {
            if (m.kind === 'translation') {
                renderEntry(transEl, m, false);
                transRow.hidden = false;
            } else {
                renderEntry(defsEl, m, true);
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
        // Copy applies to a single word too — the sheet is already open on it,
        // and reaching past it for the browser's own menu would be silly.
        if (actionsEl) actionsEl.hidden = false;
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

    // --- Passage mode ------------------------------------------------------
    // A multi-word selection has nothing to look up, and until now it did
    // nothing at all: the sheet only ever opened for a single word. The
    // browser's own selection menu can copy the raw text, but it doesn't know
    // it is holding a book — so what Colophon adds is the passage *with its
    // source*, which is what you actually want when quoting one.

    function showPassage(text) {
        seq += 1;                 // cancel any dictionary request in flight
        resetBody();
        selectedText = text;
        if (eyebrow) eyebrow.textContent = STR.passage;
        if (wordEl) wordEl.textContent = '';
        if (quoteEl) { quoteEl.textContent = text; quoteEl.hidden = false; }
        if (actionsEl) actionsEl.hidden = false;
        // "Explain in this sentence" is a word-level idea; a passage already
        // is its own context.
        aiBtn.hidden = true;
        open();
    }

    function citation() {
        var parts = [];
        if (cfg.bookTitle) parts.push(cfg.bookTitle);
        if (cfg.bookAuthor) parts.push(cfg.bookAuthor);
        return parts.join(' — ');
    }

    function copyText(withSource) {
        if (!selectedText) return;
        var payload = selectedText;
        if (withSource) {
            var source = citation();
            payload = '”' + selectedText + '”' + (source ? '\n— ' + source : '');
        }
        writeToClipboard(payload).then(function (ok) {
            showStatus(ok ? STR.copied : STR.copyFailed, false);
        });
    }

    // navigator.clipboard needs a secure context, which the reader has over
    // Tailscale but not on a plain LAN http:// address. Fall back to the old
    // execCommand path there rather than failing on the machines most likely
    // to be used at home.
    function writeToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text)
                .then(function () { return true; })
                .catch(function () { return legacyCopy(text); });
        }
        return Promise.resolve(legacyCopy(text));
    }

    function legacyCopy(text) {
        try {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.cssText = 'position:fixed;top:-1000px;opacity:0;';
            document.body.appendChild(ta);
            ta.select();
            var ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return ok;
        } catch (e) { return false; }
    }

    // --- Selection wiring inside the book iframe --------------------------
    function checkSelection(doc) {
        var sel = doc.getSelection && doc.getSelection();
        if (!sel || sel.isCollapsed) return;
        var text = sel.toString().replace(/\s+/g, ' ').trim();
        if (!text) return;
        // Decide the position before opening, so the sheet never appears over
        // the selection and then jumps.
        placeAwayFrom(doc, sel);
        if (WORD_RE.test(text)) {
            selectedText = text;
            lookup(text, sentenceAround(sel, text));
            return;
        }
        if (text.length > MAX_PASSAGE) return;   // a runaway select-all
        showPassage(text);
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
    if (gripBtn) gripBtn.addEventListener('click', togglePlacement);
    if (copyBtn) copyBtn.addEventListener('click', function () { copyText(false); });
    if (copyCiteBtn) copyCiteBtn.addEventListener('click', function () { copyText(true); });

    return { isOpen: isOpen, close: close };
}
