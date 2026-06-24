// Edit overlay - injected by Flask for local editing
(function() {
    'use strict';

    document.body.classList.add('eln-editing');

    // --- Toolbar ---
    const toolbar = document.createElement('div');
    toolbar.className = 'eln-toolbar';
    toolbar.innerHTML = `
        <span class="eln-toolbar-label">Lab Notebook</span>
        <button class="eln-toolbar-btn publish" id="eln-publish-btn">Publish</button>
        <button class="eln-toolbar-btn" id="eln-export-btn">Export catalog</button>
    `;
    document.body.appendChild(toolbar);

    // --- Toast helper ---
    function showToast(message, type) {
        let toast = document.querySelector('.eln-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'eln-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'eln-toast ' + type;
        // Force reflow then show
        void toast.offsetWidth;
        toast.classList.add('show');
        clearTimeout(toast._timeout);
        toast._timeout = setTimeout(function() {
            toast.classList.remove('show');
        }, 5000);
    }

    // --- Publish ---
    document.getElementById('eln-publish-btn').addEventListener('click', function() {
        var btn = this;
        if (btn.disabled) return;
        btn.disabled = true;
        btn.textContent = 'Publishing...';
        showToast('Regenerating catalog and pushing to git...', 'info');

        fetch('/api/publish', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                showToast(data.message || 'Published successfully!', 'success');
            } else {
                showToast('Error: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(function(err) {
            showToast('Network error: ' + err.message, 'error');
        })
        .finally(function() {
            btn.disabled = false;
            btn.textContent = 'Publish';
        });
    });

    // --- Export (catalog or a single item): choose folder → preview → confirm → start ---
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        }).then(function(r) { return r.json(); });
    }

    function runExport(mode, id, label) {
        showToast('Choosing destination…', 'info');
        fetch('/api/sdgl/backup/choose-folder', {method: 'POST'})
            .then(function(r) { return r.json(); })
            .then(function(folder) {
                var dest = folder && folder.path;
                if (!dest) { showToast('Export cancelled.', 'info'); return; }
                return postJSON('/api/export/preview', {mode: mode, id: id, dest: dest})
                    .then(function(p) {
                        if (p.error) { showToast('Error: ' + p.error, 'error'); return; }
                        var kb = Math.round(p.bytes / 1024);
                        var msg = 'Export ' + label + ': ' + p.files + ' files (' + kb + ' KB) to ' + dest + '.';
                        if (p.dest_nonempty) { msg += '\nThe destination already contains files — overwrite?'; }
                        msg += '\n\nProceed?';
                        if (!window.confirm(msg)) { showToast('Export cancelled.', 'info'); return; }
                        showToast('Exporting ' + label + '…', 'info');
                        return postJSON('/api/export/start', {mode: mode, id: id, dest: dest})
                            .then(function(d) {
                                if (d.error) { showToast('Error: ' + d.error, 'error'); return; }
                                var done = 'Exported ' + d.files + ' files to ' + dest;
                                if (d.missing && d.missing.length) {
                                    done += ' (' + d.missing.length + ' missing asset(s) skipped)';
                                }
                                showToast(done, 'success');
                            });
                    });
            })
            .catch(function(err) { showToast('Network error: ' + err.message, 'error'); });
    }

    var exportBtn = document.getElementById('eln-export-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', function() {
            runExport('all', '', 'catalog');
        });
    }

    // --- Edit/Add buttons per page ---
    var page = location.pathname.split('/').pop() || 'sdgl.html';

    // Inject an "+ Add …" button into the page header (.header is present on
    // every catalogue page). Opens the matching inline form modal.
    function addPageAddButton(label, onClick) {
        var header = document.querySelector('.header');
        if (!header) return;
        var btn = document.createElement('button');
        btn.className = 'eln-add-btn';
        btn.textContent = label;
        btn.addEventListener('click', onClick);
        header.appendChild(btn);
    }

    // Encode a report identifier ("dir/file.md") as a URL path, segment by
    // segment, so slashes survive but spaces/specials are escaped.
    function encodeReportPath(filename) {
        return filename.split('/').map(encodeURIComponent).join('/');
    }

    // Replace a report card's body with a historical version's content,
    // read-only. The historical blob comes from git via the server, so this only
    // works in the live server view; on the static export the fetch fails and the
    // card is left untouched (graceful degradation).
    function showReportVersion(card, filename, sha) {
        fetch('/api/reports/' + encodeReportPath(filename) + '?version=' + encodeURIComponent(sha))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var content = card.querySelector('.report-content');
                if (!content) return;
                var pre = document.createElement('pre');
                pre.className = 'eln-version-pre';
                pre.textContent = data.content || '';
                content.innerHTML = '';
                content.appendChild(pre);
            })
            .catch(function() { /* server/git unavailable → leave card untouched */ });
    }

    if (page === 'experiments.html') {
        // Edit opens the inline modal instead of navigating to the old admin page.
        var rows = document.querySelectorAll('#experiments-table tbody tr');
        rows.forEach(function(row) {
            var id = row.getAttribute('data-id');
            if (!id) return;
            var td = document.createElement('td');
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '#';
            a.textContent = 'Edit';
            a.addEventListener('click', function(e) {
                e.preventDefault();
                window.elnForms.openExperimentForm(id);
            });
            td.appendChild(a);
            row.appendChild(td);
        });
        var headerRow = document.querySelector('#experiments-table thead tr');
        if (headerRow) {
            var th = document.createElement('th');
            th.textContent = '';
            th.style.cursor = 'default';
            headerRow.appendChild(th);
        }
        addPageAddButton('+ Add experiment', function() {
            window.elnForms.openExperimentForm();
        });
    }

    if (page === 'protocols.html') {
        // Add Edit button to each protocol group header
        var groups = document.querySelectorAll('.protocol-group');
        groups.forEach(function(group) {
            var id = group.id;
            if (!id) return;
            var header = group.querySelector('.protocol-header');
            if (!header) return;
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '#';
            a.textContent = 'Edit';
            a.style.marginLeft = '1rem';
            a.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.elnForms.openProtocolForm(id);
            });
            header.appendChild(a);

            var ex = document.createElement('a');
            ex.className = 'eln-edit-btn';
            ex.textContent = 'Export';
            ex.href = '#';
            ex.style.marginLeft = '0.5rem';
            ex.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                runExport('protocol', id, 'protocol');
            });
            header.appendChild(ex);
        });
        addPageAddButton('+ Add protocol', function() {
            window.elnForms.openProtocolForm();
        });
    }

    if (page === 'reports.html') {
        // Edit opens the inline modal; a git-backed version selector is added per
        // card. No Add button — reports are autogenerated from experiments.
        var cards = document.querySelectorAll('.report-card');
        cards.forEach(function(card) {
            var src = card.getAttribute('data-report-src');
            // The edit/version API keys reports by their path relative to reports/
            // (e.g. "foo/foo.md"). data-report-src is "reports/<relpath>", so
            // strip that one prefix.
            var filename = src ? src.replace(/^reports\//, '') : null;
            if (filename) {
                var a = document.createElement('a');
                a.className = 'eln-edit-btn';
                a.href = '#';
                a.textContent = 'Edit';
                a.style.float = 'right';
                a.addEventListener('click', function(e) {
                    e.preventDefault();
                    window.elnForms.openReportEditor(filename);
                });
                card.insertBefore(a, card.firstChild);
            }

            if (src) {
                var ex = document.createElement('a');
                ex.className = 'eln-edit-btn';
                ex.textContent = 'Export';
                ex.href = '#';
                ex.style.float = 'right';
                ex.style.marginRight = '0.5rem';
                ex.addEventListener('click', function(e) {
                    e.preventDefault();
                    runExport('report', src, 'report');
                });
                card.insertBefore(ex, card.firstChild);
            }

            if (filename) addVersionSelector(card, filename);
        });
    }

    // Fetch a report's git history and, if it has any, add a version indicator
    // and a dropdown to the card header. Selecting a version shows it read-only.
    function addVersionSelector(card, filename) {
        fetch('/api/reports/' + encodeReportPath(filename) + '/versions')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var versions = (data && data.versions) || [];
                if (versions.length === 0) return; // unpublished / not in git
                var wrap = document.createElement('span');
                wrap.className = 'eln-version';
                var label = document.createElement('span');
                label.className = 'eln-version-label';
                label.textContent = 'Published v' + versions.length + ' · ' + versions[0].date.slice(0, 10);
                var sel = document.createElement('select');
                sel.className = 'eln-version-select';
                versions.forEach(function(v, i) {
                    var opt = document.createElement('option');
                    opt.value = v.sha;
                    opt.textContent = 'v' + (versions.length - i) + ' · ' + v.date.slice(0, 10) + ' · ' + v.subject;
                    sel.appendChild(opt);
                });
                sel.addEventListener('click', function(e) { e.stopPropagation(); });
                sel.addEventListener('change', function() { showReportVersion(card, filename, sel.value); });
                wrap.appendChild(label);
                wrap.appendChild(sel);
                var header = card.querySelector('.report-header') || card;
                header.appendChild(wrap);
            })
            .catch(function() { /* git/server unavailable → no selector */ });
    }

    if (page === 'documents.html') {
        // Documents render as report-cards with data-report-src="documents/<rel>".
        // Edit opens the inline modal; a page-level Add creates a new document.
        var docCards = document.querySelectorAll('.report-card');
        docCards.forEach(function(card) {
            var src = card.getAttribute('data-report-src');
            var filename = src ? src.replace(/^documents\//, '') : null;
            if (!filename) return;
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '#';
            a.textContent = 'Edit';
            a.style.float = 'right';
            a.addEventListener('click', function(e) {
                e.preventDefault();
                window.elnForms.openDocumentForm(filename);
            });
            card.insertBefore(a, card.firstChild);
        });
        addPageAddButton('+ Add document', function() {
            window.elnForms.openDocumentForm();
        });
    }

    if (page === 'presentations.html') {
        // Add an Export button to each presentation row.
        var prows = document.querySelectorAll('tr[data-pres-dir]');
        prows.forEach(function(row) {
            var dir = row.getAttribute('data-pres-dir');
            var td = document.createElement('td');
            var ex = document.createElement('a');
            ex.className = 'eln-edit-btn';
            ex.textContent = 'Export';
            ex.href = '#';
            ex.addEventListener('click', function(e) {
                e.preventDefault();
                runExport('presentation', dir, 'presentation');
            });
            td.appendChild(ex);
            row.appendChild(td);
        });
    }
})();
