// Edit overlay - injected by Flask for local editing
(function() {
    'use strict';

    document.body.classList.add('eln-editing');

    // --- Toolbar ---
    const toolbar = document.createElement('div');
    toolbar.className = 'eln-toolbar';
    toolbar.innerHTML = `
        <span class="eln-toolbar-label">Lab Notebook</span>
        <a class="eln-toolbar-btn add" href="/admin.html#experiments">+ Experiment</a>
        <a class="eln-toolbar-btn add" href="/admin.html#protocols">+ Protocol</a>
        <a class="eln-toolbar-btn add" href="/admin.html#reports">+ Report</a>
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

    // --- Edit buttons per page ---
    var page = location.pathname.split('/').pop() || 'sdgl.html';

    if (page === 'experiments.html') {
        // Add Edit button to each experiment row
        var rows = document.querySelectorAll('#experiments-table tbody tr');
        rows.forEach(function(row) {
            var id = row.getAttribute('data-id');
            if (!id) return;
            var td = document.createElement('td');
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '/admin.html?edit=experiment&id=' + id;
            a.textContent = 'Edit';
            td.appendChild(a);
            row.appendChild(td);
        });
        // Add header for the edit column
        var headerRow = document.querySelector('#experiments-table thead tr');
        if (headerRow) {
            var th = document.createElement('th');
            th.textContent = '';
            th.style.cursor = 'default';
            headerRow.appendChild(th);
        }
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
            a.href = '/admin.html?edit=protocol&id=' + id;
            a.textContent = 'Edit';
            a.style.marginLeft = '1rem';
            a.onclick = function(e) { e.stopPropagation(); };
            header.appendChild(a);
        });
    }

    if (page === 'reports.html') {
        // Add Edit button to each report card
        var cards = document.querySelectorAll('.report-card');
        cards.forEach(function(card) {
            // Extract filename from the report title (h1)
            var h1 = card.querySelector('.report-content h1');
            if (!h1) return;
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '/admin.html?edit=report&name=' + encodeURIComponent(h1.textContent.trim());
            a.textContent = 'Edit';
            a.style.float = 'right';
            card.insertBefore(a, card.firstChild);

            var src = card.getAttribute('data-report-src');
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
