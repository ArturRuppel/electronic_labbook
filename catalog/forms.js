// Inline create/edit forms, injected into a <dialog> modal by edit-overlay.js.
// Ported from the old admin.js/admin.html: same form logic, but same-origin API,
// listeners instead of inline onclick, and "save → regenerate catalog → reload"
// so the viewer reflects edits immediately (no separate admin page).
(function () {
    'use strict';

    const API = '/api';
    const forms = (window.elnForms = window.elnForms || {});

    // ---- module state (shared by the experiment form) ----------------------
    let currentTags = [];
    let currentCellTypes = [];
    let codesByTitle = {};
    let titlesByCode = {};

    // ---- modal shell -------------------------------------------------------
    let dlg = null;
    function modal() {
        if (dlg) return dlg;
        dlg = document.createElement('dialog');
        dlg.className = 'eln-form-modal';
        dlg.innerHTML =
            '<form method="dialog" class="eln-form-modal-close-row">' +
            '<button value="cancel" class="eln-form-modal-close" aria-label="Close">&times;</button>' +
            '</form><div class="eln-form-modal-body"></div>';
        document.body.appendChild(dlg);
        return dlg;
    }
    function openModal(innerHTML) {
        const m = modal();
        const body = m.querySelector('.eln-form-modal-body');
        body.innerHTML = innerHTML;
        if (!m.open) m.showModal();
        return body;
    }
    function closeModal() {
        if (dlg && dlg.open) dlg.close();
    }
    forms._openModal = openModal;
    forms._closeModal = closeModal;

    // After a successful save: rebuild the static catalog so the view reflects
    // the edit, then reload. Mirrors what Publish does, but without committing.
    function afterSave() {
        return fetch(API + '/regenerate', { method: 'POST' })
            .then(function () { window.location.reload(); });
    }

    function postJSON(url, method, body) {
        return fetch(API + url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function (r) {
            return r.json().then(function (j) { return { ok: r.ok, body: j }; });
        });
    }

    // ---- autocomplete + identity maps --------------------------------------

    // Datalists, populated from the server's distinct-value endpoint so
    // suggestions reflect the whole database (and collapse fungible channels).
    async function loadFieldValues() {
        const targets = {
            experiment_type: 'exp-types-list',
            cell_types: 'cell-types-list',
            microscope: 'microscopes-list',
            channel_target: 'channel-targets-list',
        };
        try {
            const response = await fetch(API + '/field-values');
            const values = await response.json();
            Object.entries(targets).forEach(function (entry) {
                const datalist = document.getElementById(entry[1]);
                if (!datalist) return;
                const options = Array.isArray(values[entry[0]]) ? values[entry[0]] : [];
                datalist.innerHTML = options.map(function (v) {
                    return '<option value="' + v + '"></option>';
                }).join('');
            });
        } catch (error) {
            // Suggestions are optional; ignore load failures.
        }
    }

    async function loadTagSuggestions() {
        try {
            const response = await fetch(API + '/tags');
            const tags = await response.json();
            const datalist = document.getElementById('tags-list');
            if (datalist && Array.isArray(tags)) {
                datalist.innerHTML = tags.map(function (name) {
                    return '<option value="' + name + '"></option>';
                }).join('');
            }
        } catch (error) {
            // Suggestions are optional; ignore load failures.
        }
    }

    // Build the title<->code maps from all experiments so the two identity
    // fields can fill each other (a known title suggests its code and vice versa).
    async function loadIdentityMaps() {
        codesByTitle = {};
        titlesByCode = {};
        try {
            const response = await fetch(API + '/experiments');
            const experiments = await response.json();
            experiments.forEach(function (exp) {
                if (exp.experiment_type && exp.code) {
                    codesByTitle[exp.experiment_type] = exp.code;
                    titlesByCode[exp.code] = exp.experiment_type;
                }
            });
        } catch (error) {
            // Identity hints are optional.
        }
    }

    async function loadProtocolsForCheckboxes() {
        try {
            const response = await fetch(API + '/protocols');
            const protocols = await response.json();
            const container = document.getElementById('exp-protocols');
            if (!container) return;
            container.innerHTML = '';
            if (protocols.length === 0) {
                container.innerHTML = '<p style="color:#999;text-align:center;padding:1rem;">No protocols available</p>';
                return;
            }
            protocols.forEach(function (proto) {
                const item = document.createElement('div');
                item.className = 'protocol-checkbox-item';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = 'protocol-' + proto.id;
                checkbox.value = proto.id;
                checkbox.name = 'protocols';
                const label = document.createElement('label');
                label.htmlFor = 'protocol-' + proto.id;
                label.textContent = proto.name + ' v' + proto.version;
                item.appendChild(checkbox);
                item.appendChild(label);
                container.appendChild(item);
            });
        } catch (error) {
            console.error('Error loading protocols:', error);
        }
    }

    // ---- tag chips ---------------------------------------------------------

    function renderTagChips() {
        const container = document.getElementById('exp-tags');
        const input = document.getElementById('exp-tag-input');
        if (!container || !input) return;
        container.querySelectorAll('.tag-chip').forEach(function (chip) { chip.remove(); });
        currentTags.forEach(function (name, index) {
            const chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = name;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = '×';
            remove.setAttribute('aria-label', 'Remove tag ' + name);
            remove.addEventListener('click', function () { removeTag(index); });
            chip.appendChild(remove);
            container.insertBefore(chip, input);
        });
    }
    function addTag(name) {
        const value = (name || '').trim();
        if (!value) return;
        if (!currentTags.some(function (t) { return t.toLowerCase() === value.toLowerCase(); })) {
            currentTags.push(value);
            renderTagChips();
        }
    }
    function removeTag(index) {
        currentTags.splice(index, 1);
        renderTagChips();
    }
    function setExperimentTags(tags) {
        currentTags = Array.isArray(tags) ? tags.slice() : [];
        renderTagChips();
    }

    // ---- cell-type chips (stored as a comma-separated string) --------------

    function splitCellTypes(value) {
        return (value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    }
    function renderCellTypeChips() {
        const container = document.getElementById('exp-cell-types');
        const input = document.getElementById('exp-cell-type-input');
        if (!container || !input) return;
        container.querySelectorAll('.tag-chip').forEach(function (chip) { chip.remove(); });
        currentCellTypes.forEach(function (name, index) {
            const chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = name;
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = '×';
            remove.setAttribute('aria-label', 'Remove cell type ' + name);
            remove.addEventListener('click', function () { removeCellType(index); });
            chip.appendChild(remove);
            container.insertBefore(chip, input);
        });
    }
    function addCellType(name) {
        const value = (name || '').trim();
        if (!value) return;
        if (!currentCellTypes.some(function (ct) { return ct.toLowerCase() === value.toLowerCase(); })) {
            currentCellTypes.push(value);
            renderCellTypeChips();
        }
    }
    function removeCellType(index) {
        currentCellTypes.splice(index, 1);
        renderCellTypeChips();
    }
    function setExperimentCellTypes(value) {
        currentCellTypes = splitCellTypes(value);
        renderCellTypeChips();
    }

    // ---- microscopy channels ----------------------------------------------

    function getChannelsFromForm() {
        const rows = document.querySelectorAll('#exp-channels .channel-row');
        return Array.from(rows).map(function (row, idx) {
            const targetEl = row.querySelector('.channel-target');
            const modalityEl = row.querySelector('.channel-modality');
            return {
                channel_order: idx + 1,
                channel_label: row.dataset.label,
                target: targetEl ? targetEl.value.trim() : '',
                modality: modalityEl ? modalityEl.value : '',
            };
        });
    }
    function setChannelsInForm(channels) {
        document.querySelectorAll('#exp-channels .channel-target').forEach(function (el) { el.value = ''; });
        document.querySelectorAll('#exp-channels .channel-modality').forEach(function (el) { el.value = ''; });
        (channels || []).forEach(function (ch) {
            const row = document.querySelector('#exp-channels .channel-row[data-label="' + ch.channel_label + '"]');
            if (!row) return;
            const targetEl = row.querySelector('.channel-target');
            const modalityEl = row.querySelector('.channel-modality');
            if (targetEl && ch.target) targetEl.value = ch.target;
            if (modalityEl && ch.modality) modalityEl.value = ch.modality;
        });
    }

    // ---- title <-> code identity fields ------------------------------------

    function suggestCodeForTitle() {
        const titleEl = document.getElementById('exp-type');
        const codeEl = document.getElementById('exp-code');
        const hintEl = document.getElementById('exp-code-hint');
        if (!titleEl || !codeEl) return;
        codeEl.readOnly = false;
        codeEl.style.background = '';
        const known = codesByTitle[titleEl.value.trim()];
        if (known) {
            codeEl.value = known;
            if (hintEl) hintEl.textContent = 'Editable — changing this code renames the ID for every repetition of this title.';
        } else if (hintEl) {
            hintEl.textContent = 'New title — set a unique 5-character code (letters or digits).';
        }
    }
    function suggestTitleForCode() {
        const titleEl = document.getElementById('exp-type');
        const codeEl = document.getElementById('exp-code');
        const hintEl = document.getElementById('exp-code-hint');
        if (!titleEl || !codeEl) return;
        const code = codeEl.value.trim().toUpperCase();
        const known = titlesByCode[code];
        const currentTitle = titleEl.value.trim();
        if (known && known !== currentTitle && (!currentTitle || !codesByTitle[currentTitle])) {
            titleEl.value = known;
            if (hintEl) hintEl.textContent = 'Code ' + code + ' belongs to "' + known + '".';
        }
    }

    function populateExperimentForm(exp) {
        setExperimentTags(exp.tags || []);
        setChannelsInForm(exp.channels || []);
        document.getElementById('exp-type').value = exp.experiment_type || '';
        document.getElementById('exp-code').value = exp.code || '';
        if (exp.experiment_id && exp.code) {
            // "COV2D-X03" -> "X03", "COV2D-03" -> "03"
            document.getElementById('exp-rep').value = exp.experiment_id.substring(exp.code.length + 1);
        } else {
            document.getElementById('exp-rep').value = (exp.repetition != null ? exp.repetition : '');
        }
        suggestCodeForTitle();
        setExperimentCellTypes(exp.cell_types || '');
        document.getElementById('exp-microscope').value = exp.microscope || '';
        document.getElementById('exp-live-fixed').value = exp.live_or_fixed || '';
        document.getElementById('exp-thumbnail').value = exp.thumbnail_path || '';
        document.getElementById('exp-comments').value = exp.comments || '';
        document.querySelectorAll('#exp-protocols input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
        if (exp.protocol_ids && Array.isArray(exp.protocol_ids)) {
            exp.protocol_ids.forEach(function (protocolId) {
                const checkbox = document.getElementById('protocol-' + protocolId);
                if (checkbox) checkbox.checked = true;
            });
        }
    }

    // ---- experiment form ---------------------------------------------------

    const EXPERIMENT_FORM_HTML =
        '<h2 id="exp-form-title">Add experiment</h2>' +
        '<form id="experiment-form">' +
        '<input type="hidden" id="exp-id" />' +
        '<datalist id="exp-types-list"></datalist>' +
        '<datalist id="cell-types-list"></datalist>' +
        '<datalist id="microscopes-list"></datalist>' +
        '<datalist id="channel-targets-list"></datalist>' +
        '<datalist id="tags-list"></datalist>' +
        '<datalist id="live-fixed-list"><option value="Live"><option value="Fixed"><option value="Both"></datalist>' +
        '<div class="form-section"><h3 class="form-section-title">Details</h3><div class="form-grid">' +
        '<div class="form-group"><label for="exp-type">Title *</label>' +
        '<input type="text" id="exp-type" list="exp-types-list" placeholder="e.g., spheroid imaging" required /></div>' +
        '<div class="form-group"><label for="exp-code">Code</label>' +
        '<input type="text" id="exp-code" maxlength="5" placeholder="5 chars, e.g. SPHIM or TFM01" autocomplete="off" pattern="[A-Za-z0-9]{5}" style="text-transform:uppercase" />' +
        '<small id="exp-code-hint" style="color:#6a7884;">Auto-filled for known titles; set a new 5-character code for a new title.</small></div>' +
        '<div class="form-group"><label for="exp-rep">Repetition</label>' +
        '<input type="text" id="exp-rep" maxlength="3" placeholder="e.g., 1, 03, X3, x03" pattern="[A-Za-z0-9]{1,3}" />' +
        '<small style="color:#6a7884;">Optional X prefix marks excluded (X3, x03). Leave empty for next free.</small></div>' +
        '<div class="form-group"><label for="exp-microscope">Microscope</label>' +
        '<input type="text" id="exp-microscope" list="microscopes-list" placeholder="e.g., Nikon TiE2 Spinning Disk CSU" /></div>' +
        '<div class="form-group"><label for="exp-live-fixed">Live or Fixed</label>' +
        '<input type="text" id="exp-live-fixed" list="live-fixed-list" placeholder="Live, Fixed, or Both" /></div>' +
        '<div class="form-group"><label for="exp-thumbnail">Thumbnail Path</label>' +
        '<input type="text" id="exp-thumbnail" placeholder="/path/to/thumbnail.png" /></div>' +
        '</div></div>' +
        '<div class="form-section"><h3 class="form-section-title">Cell Types &amp; Tags</h3><div class="form-grid">' +
        '<div class="form-group"><label for="exp-cell-type-input">Cell Types</label>' +
        '<div class="tag-input" id="exp-cell-types"><input type="text" id="exp-cell-type-input" list="cell-types-list" placeholder="Type a cell type and press Enter" autocomplete="off" /></div></div>' +
        '<div class="form-group"><label for="exp-tag-input">Tags</label>' +
        '<div class="tag-input" id="exp-tags"><input type="text" id="exp-tag-input" list="tags-list" placeholder="Type a tag and press Enter" autocomplete="off" /></div></div>' +
        '</div></div>' +
        '<div class="form-section"><h3 class="form-section-title">Protocols</h3><div id="exp-protocols" class="protocol-checkboxes"></div></div>' +
        '<div class="form-section"><h3 class="form-section-title">Microscopy Channels</h3><div id="exp-channels" class="channel-rows">' +
        '<div class="channel-row" data-label="Blue" data-type="fluorescence"><span class="channel-name">Blue</span><input type="text" class="channel-target" list="channel-targets-list" placeholder="target / marker (e.g. DAPI) — leave empty if unused" /></div>' +
        '<div class="channel-row" data-label="Green" data-type="fluorescence"><span class="channel-name">Green</span><input type="text" class="channel-target" list="channel-targets-list" placeholder="target / marker (e.g. F-actin) — leave empty if unused" /></div>' +
        '<div class="channel-row" data-label="Red" data-type="fluorescence"><span class="channel-name">Red</span><input type="text" class="channel-target" list="channel-targets-list" placeholder="target / marker (e.g. vinculin) — leave empty if unused" /></div>' +
        '<div class="channel-row" data-label="Far-red" data-type="fluorescence"><span class="channel-name">Far-red</span><input type="text" class="channel-target" list="channel-targets-list" placeholder="target / marker — leave empty if unused" /></div>' +
        '<div class="channel-row" data-label="Brightfield" data-type="brightfield"><span class="channel-name">Brightfield</span><select class="channel-modality"><option value="">— not used —</option><option value="Standard">Standard</option><option value="Phase contrast">Phase contrast</option><option value="DIC">DIC</option></select></div>' +
        '</div></div>' +
        '<div class="form-section"><h3 class="form-section-title">Comments / Notes</h3>' +
        '<textarea id="exp-comments" aria-label="Comments / Notes" placeholder="Experiment details, observations, notes..."></textarea></div>' +
        '<div class="button-group"><button type="submit" class="button">Save Experiment</button>' +
        '<button type="button" class="button secondary" data-eln-cancel>Cancel</button></div>' +
        '</form>';

    function wireExperimentInputs() {
        const titleInput = document.getElementById('exp-type');
        if (titleInput) {
            titleInput.addEventListener('input', suggestCodeForTitle);
            titleInput.addEventListener('change', suggestCodeForTitle);
        }
        const codeInput = document.getElementById('exp-code');
        if (codeInput) {
            codeInput.addEventListener('input', suggestTitleForCode);
            codeInput.addEventListener('change', suggestTitleForCode);
        }
        const tagInput = document.getElementById('exp-tag-input');
        if (tagInput) {
            tagInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    addTag(tagInput.value);
                    tagInput.value = '';
                } else if (e.key === 'Backspace' && !tagInput.value && currentTags.length) {
                    removeTag(currentTags.length - 1);
                }
            });
            tagInput.addEventListener('blur', function () { addTag(tagInput.value); tagInput.value = ''; });
        }
        const cellTypeInput = document.getElementById('exp-cell-type-input');
        if (cellTypeInput) {
            cellTypeInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    addCellType(cellTypeInput.value);
                    cellTypeInput.value = '';
                } else if (e.key === 'Backspace' && !cellTypeInput.value && currentCellTypes.length) {
                    removeCellType(currentCellTypes.length - 1);
                }
            });
            cellTypeInput.addEventListener('blur', function () { addCellType(cellTypeInput.value); cellTypeInput.value = ''; });
        }
    }

    function collectExperimentPayload() {
        // Commit any chip still sitting in an input before reading values.
        const tagInputEl = document.getElementById('exp-tag-input');
        if (tagInputEl && tagInputEl.value.trim()) { addTag(tagInputEl.value); tagInputEl.value = ''; }
        const cellTypeInputEl = document.getElementById('exp-cell-type-input');
        if (cellTypeInputEl && cellTypeInputEl.value.trim()) { addCellType(cellTypeInputEl.value); cellTypeInputEl.value = ''; }

        const selectedProtocols = Array.from(
            document.querySelectorAll('#exp-protocols input[type="checkbox"]:checked')
        ).map(function (cb) { return parseInt(cb.value, 10); });
        const repValue = document.getElementById('exp-rep').value.trim();
        return {
            experiment_type: document.getElementById('exp-type').value,
            code: document.getElementById('exp-code').value.trim().toUpperCase(),
            repetition: repValue === '' ? null : repValue,
            cell_types: currentCellTypes.join(', '),
            microscope: document.getElementById('exp-microscope').value,
            live_or_fixed: document.getElementById('exp-live-fixed').value,
            protocol_ids: selectedProtocols,
            tags: currentTags.slice(),
            channels: getChannelsFromForm(),
            thumbnail_path: document.getElementById('exp-thumbnail').value,
            comments: document.getElementById('exp-comments').value,
        };
    }

    forms.openExperimentForm = async function (id) {
        const body = openModal(EXPERIMENT_FORM_HTML);
        body.querySelector('#exp-form-title').textContent = id ? 'Edit experiment' : 'Add experiment';
        currentTags = [];
        currentCellTypes = [];
        await Promise.all([loadFieldValues(), loadTagSuggestions(), loadIdentityMaps(), loadProtocolsForCheckboxes()]);
        wireExperimentInputs();
        renderTagChips();
        renderCellTypeChips();
        if (id) {
            const resp = await fetch(API + '/experiments/' + id);
            populateExperimentForm(await resp.json());
        } else {
            suggestCodeForTitle();
        }
        wireCancel(body);
        body.querySelector('#experiment-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = collectExperimentPayload();
            const method = id ? 'PUT' : 'POST';
            const url = id ? '/experiments/' + id : '/experiments';
            const res = await postJSON(url, method, payload);
            if (!res.ok || res.body.error) { alert((res.body && res.body.error) || 'Save failed'); return; }
            closeModal();
            await afterSave();
        });
    };

    // ---- protocol form -----------------------------------------------------

    const PROTOCOL_FORM_HTML =
        '<h2 id="proto-form-title">Add protocol</h2>' +
        '<form id="protocol-form"><input type="hidden" id="proto-id" /><div class="form-grid">' +
        '<div class="form-group"><label for="proto-name">Protocol Name *</label>' +
        '<input type="text" id="proto-name" required placeholder="e.g., Spheroid Culture Protocol" /></div>' +
        '<div class="form-group"><label for="proto-version">Version *</label>' +
        '<input type="text" id="proto-version" required placeholder="e.g., 1.0, 2.1" /></div>' +
        '<div class="form-group full-width"><label for="proto-description">Description</label>' +
        '<textarea id="proto-description" placeholder="Brief description of the protocol..."></textarea></div>' +
        '<div class="form-group full-width"><label for="proto-content">Protocol Content (Markdown) *</label>' +
        '<textarea id="proto-content" class="large" required placeholder="# Protocol Steps"></textarea></div>' +
        '<div class="form-group full-width"><label for="proto-file-path">File Path (optional)</label>' +
        '<input type="text" id="proto-file-path" placeholder="/path/to/protocol.md" /></div>' +
        '</div><div class="button-group"><button type="submit" class="button">Save Protocol</button>' +
        '<button type="button" class="button secondary" data-eln-cancel>Cancel</button></div></form>';

    forms.openProtocolForm = async function (id) {
        const body = openModal(PROTOCOL_FORM_HTML);
        body.querySelector('#proto-form-title').textContent = id ? 'Edit protocol' : 'Add protocol';
        if (id) {
            const resp = await fetch(API + '/protocols/' + id);
            const proto = await resp.json();
            body.querySelector('#proto-id').value = proto.id;
            body.querySelector('#proto-name').value = proto.name || '';
            body.querySelector('#proto-version').value = proto.version || '';
            body.querySelector('#proto-description').value = proto.description || '';
            body.querySelector('#proto-content').value = proto.content || '';
            body.querySelector('#proto-file-path').value = proto.file_path || '';
        }
        wireCancel(body);
        body.querySelector('#protocol-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = {
                name: body.querySelector('#proto-name').value,
                version: body.querySelector('#proto-version').value,
                description: body.querySelector('#proto-description').value,
                content: body.querySelector('#proto-content').value,
                file_path: body.querySelector('#proto-file-path').value,
            };
            const method = id ? 'PUT' : 'POST';
            const url = id ? '/protocols/' + id : '/protocols';
            const res = await postJSON(url, method, payload);
            if (!res.ok || res.body.error) { alert((res.body && res.body.error) || 'Save failed'); return; }
            closeModal();
            await afterSave();
        });
    };

    // ---- report / document editor ------------------------------------------
    // Reports are edit-only; documents also support create (a new .md file).
    // Both share one renderer: markdown reports use a single textarea, notebooks
    // expose one textarea per markdown cell (code cells/outputs stay untouched).

    function reportEditorMarkup(opts) {
        const filenameField = opts && opts.withFilename
            ? '<div class="form-group full-width"><label for="doc-filename">Filename (e.g. note/note.md)</label>' +
              '<input type="text" id="doc-filename" placeholder="folder/name.md" required /></div>'
            : '';
        return '<h2>' + (opts && opts.title ? opts.title : 'Edit') + '</h2>' +
            '<form id="report-form"><div class="form-grid">' +
            filenameField +
            '<div class="form-group full-width" id="report-content-group"><label for="report-content">Content (Markdown)</label>' +
            '<textarea id="report-content" class="large"></textarea></div>' +
            '<div class="form-group full-width hidden" id="report-notebook-group"><label>Notebook Text Cells</label>' +
            '<small style="color:#666;display:block;margin-bottom:0.5rem;">Editing the markdown cells only. Code cells and outputs are not shown and will not change.</small>' +
            '<div id="report-notebook-cells"></div></div>' +
            '</div><div class="button-group"><button type="submit" class="button">Save</button>' +
            '<button type="button" class="button secondary" data-eln-cancel>Cancel</button></div></form>';
    }

    // Render loaded content into the editor; returns the content type so the
    // submit handler knows whether to send {content} or {cells}.
    function renderLoadedEditor(body, data) {
        const contentGroup = body.querySelector('#report-content-group');
        const contentArea = body.querySelector('#report-content');
        const nbGroup = body.querySelector('#report-notebook-group');
        const nbCells = body.querySelector('#report-notebook-cells');
        if (data.type === 'notebook') {
            contentGroup.classList.add('hidden');
            contentArea.required = false;
            nbGroup.classList.remove('hidden');
            nbCells.innerHTML = '';
            (data.cells || []).forEach(function (cell) {
                const wrap = document.createElement('div');
                wrap.className = 'form-group';
                wrap.style.marginBottom = '1rem';
                const label = document.createElement('label');
                label.textContent = 'Cell ' + cell.index;
                const ta = document.createElement('textarea');
                ta.className = 'large';
                ta.dataset.cellIndex = cell.index;
                ta.value = cell.source;
                wrap.appendChild(label);
                wrap.appendChild(ta);
                nbCells.appendChild(wrap);
            });
        } else {
            nbGroup.classList.add('hidden');
            contentGroup.classList.remove('hidden');
            contentArea.required = true;
            contentArea.value = data.content || '';
        }
        return data.type;
    }

    function collectEditorPayload(body, type) {
        if (type === 'notebook') {
            const cells = Array.from(body.querySelectorAll('#report-notebook-cells textarea')).map(function (ta) {
                return { index: parseInt(ta.dataset.cellIndex, 10), source: ta.value };
            });
            return { cells: cells };
        }
        return { content: body.querySelector('#report-content').value };
    }

    forms.openReportEditor = async function (filename) {
        const body = openModal(reportEditorMarkup({ title: 'Edit report' }));
        const resp = await fetch(API + '/reports/' + encodeURIComponent(filename));
        const data = await resp.json();
        if (!resp.ok) { alert(data.error || 'Could not load report'); closeModal(); return; }
        const type = renderLoadedEditor(body, data);
        wireCancel(body);
        body.querySelector('#report-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const res = await postJSON('/reports/' + encodeURIComponent(filename), 'PUT', collectEditorPayload(body, type));
            if (!res.ok || res.body.error) { alert((res.body && res.body.error) || 'Save failed'); return; }
            closeModal();
            await afterSave();
        });
    };

    forms.openDocumentForm = async function (path) {
        const isCreate = !path;
        const body = openModal(reportEditorMarkup({
            title: isCreate ? 'Add document' : 'Edit document',
            withFilename: isCreate,
        }));
        let type = 'markdown';
        if (isCreate) {
            // New document: a plain markdown textarea, required.
            body.querySelector('#report-content').required = true;
        } else {
            const resp = await fetch(API + '/documents/' + encodeURIComponent(path));
            const data = await resp.json();
            if (!resp.ok) { alert(data.error || 'Could not load document'); closeModal(); return; }
            type = renderLoadedEditor(body, data);
        }
        wireCancel(body);
        body.querySelector('#report-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            let res;
            if (isCreate) {
                res = await postJSON('/documents', 'POST', {
                    filename: body.querySelector('#doc-filename').value.trim(),
                    content: body.querySelector('#report-content').value,
                });
            } else {
                res = await postJSON('/documents/' + encodeURIComponent(path), 'PUT', collectEditorPayload(body, type));
            }
            if (!res.ok || res.body.error) { alert((res.body && res.body.error) || 'Save failed'); return; }
            closeModal();
            await afterSave();
        });
    };

    // ---- poster form -------------------------------------------------------
    // A poster is a title + an SVG already sitting in the data repo's posters/
    // folder. The form picks both: a free-text title and a dropdown of the SVG
    // files present. Saving writes the index and regenerates the page.

    const POSTER_FORM_HTML =
        '<h2>Add poster</h2>' +
        '<form id="poster-form"><div class="form-grid">' +
        '<div class="form-group full-width"><label for="poster-title">Title *</label>' +
        '<input type="text" id="poster-title" required placeholder="e.g., EMBO workshop — cytoskeleton" /></div>' +
        '<div class="form-group full-width"><label for="poster-file">SVG file *</label>' +
        '<select id="poster-file" required></select>' +
        '<small id="poster-file-hint" style="color:#6a7884;">Files in the data repo\'s <code>posters/</code> folder.</small></div>' +
        '</div><div class="button-group"><button type="submit" class="button">Save Poster</button>' +
        '<button type="button" class="button secondary" data-eln-cancel>Cancel</button></div></form>';

    forms.openPosterForm = async function () {
        const body = openModal(POSTER_FORM_HTML);
        const select = body.querySelector('#poster-file');
        const hint = body.querySelector('#poster-file-hint');
        let files = [];
        try {
            const resp = await fetch(API + '/posters');
            const data = await resp.json();
            files = (data && data.files) || [];
        } catch (e) { /* leave files empty → handled below */ }
        if (files.length === 0) {
            select.innerHTML = '<option value="">— no SVGs in posters/ —</option>';
            select.disabled = true;
            hint.textContent = 'Drop an .svg into the data repo\'s posters/ folder, then reopen this form.';
        } else {
            select.innerHTML = files.map(function (f) {
                return '<option value="' + f + '">' + f + '</option>';
            }).join('');
        }
        wireCancel(body);
        body.querySelector('#poster-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const res = await postJSON('/posters', 'POST', {
                title: body.querySelector('#poster-title').value.trim(),
                file: select.value,
            });
            if (!res.ok || res.body.error) { alert((res.body && res.body.error) || 'Save failed'); return; }
            closeModal();
            await afterSave();
        });
    };

    // ---- shared: cancel button closes the modal ----------------------------
    function wireCancel(body) {
        const cancel = body.querySelector('[data-eln-cancel]');
        if (cancel) cancel.addEventListener('click', function () { closeModal(); });
    }
})();
