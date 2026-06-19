// Admin Panel JavaScript
// API Configuration
const API_BASE_URL = 'http://localhost:5000/api';

// Cache of protocol id -> protocol object, populated by loadProtocolsForCheckboxes
let protocolsCache = {};

// ==================== INITIALIZATION ====================

// Load data when page loads
window.addEventListener('DOMContentLoaded', () => {
    // Show main content immediately (no authentication needed for local-only admin)
    document.getElementById('main-content').classList.remove('hidden');
    loadInitialData().then(() => handleDeepLink());
});

function handleDeepLink() {
    // Handle hash-based tab switching: admin.html#experiments
    const hash = window.location.hash.substring(1);
    if (hash && !window.location.search) {
        const tabBtn = document.querySelector(`.tab:nth-child(${hash === 'experiments' ? 1 : hash === 'protocols' ? 2 : hash === 'reports' ? 3 : 0})`);
        if (tabBtn) switchTab(hash, tabBtn);
        return;
    }

    // Handle edit deep-links: admin.html?edit=experiment&id=3
    const params = new URLSearchParams(window.location.search);
    const editType = params.get('edit');
    const editId = params.get('id');
    const editName = params.get('name');

    if (editType === 'experiment' && editId) {
        const tabBtn = document.querySelector('.tab:nth-child(1)');
        if (tabBtn) switchTab('experiments', tabBtn);
        editExperiment(parseInt(editId));
    } else if (editType === 'protocol' && editId) {
        const tabBtn = document.querySelector('.tab:nth-child(2)');
        if (tabBtn) switchTab('protocols', tabBtn);
        editProtocol(parseInt(editId));
    } else if (editType === 'report' && editName) {
        const tabBtn = document.querySelector('.tab:nth-child(3)');
        if (tabBtn) switchTab('reports', tabBtn);
        // Find the report by matching the name in the list
        const items = document.querySelectorAll('#reports-list .list-item');
        items.forEach(item => {
            const title = item.querySelector('.list-item-title');
            if (title) {
                const filename = title.textContent.trim();
                editReport(filename);
            }
        });
    }
}

// ==================== UTILITY FUNCTIONS ====================

function showAlert(message, type = 'info') {
    const alert = document.getElementById('main-alert');
    alert.textContent = message;
    alert.className = `alert ${type} show`;
    setTimeout(() => alert.classList.remove('show'), 5000);
}

function switchTab(tabName, clickedTab) {
    // Update tab buttons
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    // Use clickedTab if provided, otherwise fall back to event.target
    const target = clickedTab || (typeof event !== 'undefined' ? event.target : null);
    if (target) target.classList.add('active');

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

// ==================== LOAD INITIAL DATA ====================

async function loadInitialData() {
    await Promise.all([
        loadExperiments(),
        loadProtocols(),
        loadReports(),
        loadProtocolsForCheckboxes(),
        loadTagSuggestions()
    ]);
    updateStats();
}

function updateStats() {
    const expCount = document.getElementById('experiments-list').children.length;
    const protoCount = document.getElementById('protocols-list').children.length;
    const reportCount = document.getElementById('reports-list').children.length;

    document.getElementById('stat-experiments').textContent = expCount;
    document.getElementById('stat-protocols').textContent = protoCount;
    document.getElementById('stat-reports').textContent = reportCount;
}

// ==================== EXPERIMENTS ====================

async function loadExperiments() {
    const loading = document.getElementById('exp-loading');
    const listDiv = document.getElementById('experiments-list');

    loading.classList.add('show');
    listDiv.innerHTML = '';

    try {
        const response = await fetch(`${API_BASE_URL}/experiments`);
        const experiments = await response.json();

        if (experiments.length === 0) {
            listDiv.innerHTML = '<p style="color: #666; text-align: center; padding: 2rem;">No experiments found</p>';
        } else {
            experiments.forEach(exp => {
                const item = createExperimentListItem(exp);
                listDiv.appendChild(item);
            });

            // Populate autocomplete datalists
            populateDatalistsFromExperiments(experiments);
        }
    } catch (error) {
        showAlert('Error loading experiments: ' + error.message, 'error');
    } finally {
        loading.classList.remove('show');
    }
}

// Title -> existing 5-letter code, so a known title locks its code field.
// codesByTitle and its inverse titlesByCode let the two identity fields fill
// each other: a known title suggests its code, a known code suggests its title.
let codesByTitle = {};
let titlesByCode = {};

function populateDatalistsFromExperiments(experiments) {
    // Get unique values for each field
    const expTypes = new Set();
    const cellTypes = new Set();
    const microscopes = new Set();

    codesByTitle = {};
    titlesByCode = {};
    experiments.forEach(exp => {
        if (exp.experiment_type) expTypes.add(exp.experiment_type);
        if (exp.experiment_type && exp.code) {
            codesByTitle[exp.experiment_type] = exp.code;
            titlesByCode[exp.code] = exp.experiment_type;
        }
        if (exp.cell_types) splitCellTypes(exp.cell_types).forEach(ct => cellTypes.add(ct));
        if (exp.microscope) microscopes.add(exp.microscope);
    });
    suggestCodeForTitle();

    // Populate datalists
    const expTypesList = document.getElementById('exp-types-list');
    const cellTypesList = document.getElementById('cell-types-list');
    const microscopesList = document.getElementById('microscopes-list');

    expTypesList.innerHTML = Array.from(expTypes).sort().map(v => `<option value="${v}">`).join('');
    cellTypesList.innerHTML = Array.from(cellTypes).sort().map(v => `<option value="${v}">`).join('');
    microscopesList.innerHTML = Array.from(microscopes).sort().map(v => `<option value="${v}">`).join('');
}

function createExperimentListItem(exp) {
    const div = document.createElement('div');
    div.className = 'list-item';
    div.dataset.cellTypes = (exp.cell_types || '').toLowerCase();
    div.dataset.type = (exp.experiment_type || '').toLowerCase();

    const protocol = exp.protocols && exp.protocols.length > 0
        ? exp.protocols.map(p => `${p.name} v${p.version}`).join(', ')
        : 'No protocol';
    const commentsPreview = exp.comments ? exp.comments.substring(0, 100) + (exp.comments.length > 100 ? '...' : '') : '';
    const excludedBadge = exp.excluded ? '<span class="badge excluded" style="margin-left:0.5rem;">Excluded</span>' : '';

    div.innerHTML = `
        <div class="list-item-content">
            <div class="list-item-title">${exp.experiment_id ? `<span style="font-family:ui-monospace,monospace;color:#2b5878;">${exp.experiment_id}</span> ` : ''}${exp.experiment_type || 'Experiment'}${excludedBadge}</div>
            <div class="list-item-meta">Cell Types: ${exp.cell_types || 'N/A'} | Microscope: ${exp.microscope || 'N/A'} | ${exp.live_or_fixed || 'N/A'}</div>
            <div class="list-item-meta">Protocol: ${protocol}</div>
            ${commentsPreview ? `<div class="list-item-meta" style="margin-top: 0.5rem; font-style: italic;">${commentsPreview}</div>` : ''}
        </div>
        <div class="list-item-actions">
            <button class="button btn-small" onclick="editExperiment(${exp.id})">Edit</button>
            <button class="button btn-small" onclick="copyExperiment(${exp.id})">Copy</button>
            <button class="button danger btn-small" onclick="deleteExperiment(${exp.id}, '${exp.experiment_id || ('#' + exp.id)}')">Delete</button>
        </div>
    `;

    return div;
}

function filterExperiments() {
    const searchTerm = document.getElementById('exp-search').value.toLowerCase();
    const items = document.querySelectorAll('#experiments-list .list-item');

    items.forEach(item => {
        const cellTypes = item.dataset.cellTypes;
        const type = item.dataset.type;

        if (cellTypes.includes(searchTerm) || type.includes(searchTerm)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
}

// ---- Tag chip input ----

let currentTags = [];

async function loadTagSuggestions() {
    try {
        const response = await fetch(`${API_BASE_URL}/tags`);
        const tags = await response.json();
        const datalist = document.getElementById('tags-list');
        if (datalist && Array.isArray(tags)) {
            datalist.innerHTML = tags.map(name => `<option value="${name}"></option>`).join('');
        }
    } catch (error) {
        // Suggestions are optional; ignore load failures.
    }
}

function renderTagChips() {
    const container = document.getElementById('exp-tags');
    const input = document.getElementById('exp-tag-input');
    if (!container || !input) return;
    // Remove existing chips, keep the input.
    container.querySelectorAll('.tag-chip').forEach(chip => chip.remove());
    currentTags.forEach((name, index) => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '×';
        remove.setAttribute('aria-label', `Remove tag ${name}`);
        remove.addEventListener('click', () => removeTag(index));
        chip.appendChild(remove);
        container.insertBefore(chip, input);
    });
}

function addTag(name) {
    const value = (name || '').trim();
    if (!value) return;
    if (!currentTags.some(tag => tag.toLowerCase() === value.toLowerCase())) {
        currentTags.push(value);
        renderTagChips();
    }
}

function removeTag(index) {
    currentTags.splice(index, 1);
    renderTagChips();
}

function setExperimentTags(tags) {
    currentTags = Array.isArray(tags) ? [...tags] : [];
    renderTagChips();
}

// --- Cell types: chip input mirroring the tags input ---
// Stored in the DB as a single comma-separated string; split into chips here.
let currentCellTypes = [];

function splitCellTypes(value) {
    return (value || '')
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
}

function renderCellTypeChips() {
    const container = document.getElementById('exp-cell-types');
    const input = document.getElementById('exp-cell-type-input');
    if (!container || !input) return;
    container.querySelectorAll('.tag-chip').forEach(chip => chip.remove());
    currentCellTypes.forEach((name, index) => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '×';
        remove.setAttribute('aria-label', `Remove cell type ${name}`);
        remove.addEventListener('click', () => removeCellType(index));
        chip.appendChild(remove);
        container.insertBefore(chip, input);
    });
}

function addCellType(name) {
    const value = (name || '').trim();
    if (!value) return;
    if (!currentCellTypes.some(ct => ct.toLowerCase() === value.toLowerCase())) {
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

// Collect the microscopy channel rows from the form into an array of objects.
// Empty rows are kept here (the API drops blanks) so order stays stable.
function getChannelsFromForm() {
    const rows = document.querySelectorAll('#exp-channels .channel-row');
    return Array.from(rows).map((row, idx) => {
        const label = row.dataset.label;
        const targetEl = row.querySelector('.channel-target');
        const modalityEl = row.querySelector('.channel-modality');
        return {
            channel_order: idx + 1,
            channel_label: label,
            target: targetEl ? targetEl.value.trim() : '',
            modality: modalityEl ? modalityEl.value : ''
        };
    });
}

// Populate the channel rows from a saved experiment's channels (matched by label).
function setChannelsInForm(channels) {
    document.querySelectorAll('#exp-channels .channel-target').forEach(el => { el.value = ''; });
    document.querySelectorAll('#exp-channels .channel-modality').forEach(el => { el.value = ''; });
    (channels || []).forEach(ch => {
        const row = document.querySelector(`#exp-channels .channel-row[data-label="${ch.channel_label}"]`);
        if (!row) return;
        const targetEl = row.querySelector('.channel-target');
        const modalityEl = row.querySelector('.channel-modality');
        if (targetEl && ch.target) targetEl.value = ch.target;
        if (modalityEl && ch.modality) modalityEl.value = ch.modality;
    });
}

// The code is a property of the title. Auto-fill the known code as an editable
// suggestion; changing it renames the title's ID for every repetition.
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

// Inverse of suggestCodeForTitle: a fully typed, known code fills in its title.
// Only fills on an exact match and never overwrites a non-empty title that the
// user is actively editing, so it can't fight manual entry.
function suggestTitleForCode() {
    const titleEl = document.getElementById('exp-type');
    const codeEl = document.getElementById('exp-code');
    const hintEl = document.getElementById('exp-code-hint');
    if (!titleEl || !codeEl) return;
    const code = codeEl.value.trim().toUpperCase();
    const known = titlesByCode[code];
    const currentTitle = titleEl.value.trim();
    // Fill only when the title is blank or still free text (not yet an established
    // title). Never overwrite an already-known title — typing another title's code
    // there is a deliberate clash, left for save-time validation, not auto-resolved.
    if (known && known !== currentTitle && (!currentTitle || !codesByTitle[currentTitle])) {
        titleEl.value = known;
        if (hintEl) hintEl.textContent = `Code ${code} belongs to "${known}".`;
    }
}

function populateExperimentForm(exp) {
    setExperimentTags(exp.tags || []);
    setChannelsInForm(exp.channels || []);
    document.getElementById('exp-type').value = exp.experiment_type || '';
    document.getElementById('exp-code').value = exp.code || '';
    // Use experiment_id (CODE-NN or CODE-XNN) to populate repetition field
    if (exp.experiment_id && exp.code) {
        // Extract the repetition part from experiment_id (e.g., "COV2D-X03" -> "X03", "COV2D-03" -> "03")
        const idPart = exp.experiment_id.substring(exp.code.length + 1);
        document.getElementById('exp-rep').value = idPart;
    } else {
        document.getElementById('exp-rep').value = (exp.repetition != null ? exp.repetition : '');
    }
    suggestCodeForTitle();
    setExperimentCellTypes(exp.cell_types || '');
    document.getElementById('exp-microscope').value = exp.microscope || '';
    document.getElementById('exp-live-fixed').value = exp.live_or_fixed || '';
    document.getElementById('exp-thumbnail').value = exp.thumbnail_path || '';
    document.getElementById('exp-comments').value = exp.comments || '';

    // Uncheck all protocol checkboxes first
    document.querySelectorAll('#exp-protocols input[type="checkbox"]').forEach(cb => cb.checked = false);

    // Check the protocols associated with this experiment
    if (exp.protocol_ids && Array.isArray(exp.protocol_ids)) {
        exp.protocol_ids.forEach(protocolId => {
            const checkbox = document.getElementById(`protocol-${protocolId}`);
            if (checkbox) checkbox.checked = true;
        });
    }
}

async function editExperiment(id) {
    try {
        const response = await fetch(`${API_BASE_URL}/experiments/${id}`);
        const exp = await response.json();

        document.getElementById('exp-id').value = exp.id;
        populateExperimentForm(exp);

        // Scroll to form
        document.getElementById('experiment-form').scrollIntoView({behavior: 'smooth'});
        showAlert('Editing ' + (exp.experiment_id || exp.experiment_type || 'experiment'), 'info');
    } catch (error) {
        showAlert('Error loading experiment: ' + error.message, 'error');
    }
}

async function copyExperiment(id) {
    try {
        const response = await fetch(`${API_BASE_URL}/experiments/${id}`);
        const exp = await response.json();

        // Leave exp-id empty so saving creates a NEW experiment from this template
        document.getElementById('exp-id').value = '';
        populateExperimentForm(exp);
        // A copy is a new repetition: clear the number so it defaults to next free.
        document.getElementById('exp-rep').value = '';

        // Scroll to form
        document.getElementById('experiment-form').scrollIntoView({behavior: 'smooth'});
        showAlert('Copied ' + (exp.experiment_id || exp.experiment_type || 'experiment') + ' as a new template — adjust and save to create a new entry', 'info');
    } catch (error) {
        showAlert('Error copying experiment: ' + error.message, 'error');
    }
}

async function deleteExperiment(id, name) {
    if (!confirm(`Are you sure you want to delete experiment "${name}"?`)) return;

    try {
        const response = await fetch(`${API_BASE_URL}/experiments/${id}`, {
            method: 'DELETE',        });

        const data = await response.json();

        if (data.success) {
            showAlert('Experiment deleted successfully', 'success');
            await loadExperiments();
            updateStats();
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showAlert('Error deleting experiment: ' + error.message, 'error');
    }
}

function resetExperimentForm() {
    document.getElementById('experiment-form').reset();
    document.getElementById('exp-id').value = '';
    document.getElementById('exp-code').value = '';
    document.getElementById('exp-rep').value = '';
    suggestCodeForTitle();
    // Uncheck all protocol checkboxes
    document.querySelectorAll('#exp-protocols input[type="checkbox"]').forEach(cb => cb.checked = false);
    // Clear tag chips
    setExperimentTags([]);
    // Clear cell-type chips
    setExperimentCellTypes('');
}

// Handle experiment form submission
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('experiment-form');
    if (form) {
        // Title drives the code field: lock to the stored code for a known
        // title, or open it for a new 5-letter code.
        const titleInput = document.getElementById('exp-type');
        if (titleInput) {
            titleInput.addEventListener('input', suggestCodeForTitle);
            titleInput.addEventListener('change', suggestCodeForTitle);
        }

        // Code field drives the title in reverse: a known code fills its title.
        // Programmatic `.value = …` doesn't fire input/change, so this can't loop
        // with suggestCodeForTitle above.
        const codeInput = document.getElementById('exp-code');
        if (codeInput) {
            codeInput.addEventListener('input', suggestTitleForCode);
            codeInput.addEventListener('change', suggestTitleForCode);
        }

        // Tag chip input: Enter or comma commits the typed tag.
        const tagInput = document.getElementById('exp-tag-input');
        if (tagInput) {
            tagInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    addTag(tagInput.value);
                    tagInput.value = '';
                } else if (e.key === 'Backspace' && !tagInput.value && currentTags.length) {
                    removeTag(currentTags.length - 1);
                }
            });
            tagInput.addEventListener('blur', () => {
                addTag(tagInput.value);
                tagInput.value = '';
            });
        }

        // Cell-type chip input: Enter or comma commits the typed cell type.
        const cellTypeInput = document.getElementById('exp-cell-type-input');
        if (cellTypeInput) {
            cellTypeInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    addCellType(cellTypeInput.value);
                    cellTypeInput.value = '';
                } else if (e.key === 'Backspace' && !cellTypeInput.value && currentCellTypes.length) {
                    removeCellType(currentCellTypes.length - 1);
                }
            });
            cellTypeInput.addEventListener('blur', () => {
                addCellType(cellTypeInput.value);
                cellTypeInput.value = '';
            });
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const id = document.getElementById('exp-id').value;

            // Commit any tag still in the input before saving.
            const tagInputEl = document.getElementById('exp-tag-input');
            if (tagInputEl && tagInputEl.value.trim()) {
                addTag(tagInputEl.value);
                tagInputEl.value = '';
            }

            // Commit any cell type still in the input before saving.
            const cellTypeInputEl = document.getElementById('exp-cell-type-input');
            if (cellTypeInputEl && cellTypeInputEl.value.trim()) {
                addCellType(cellTypeInputEl.value);
                cellTypeInputEl.value = '';
            }

            // Collect selected protocol IDs
            const selectedProtocols = Array.from(document.querySelectorAll('#exp-protocols input[type="checkbox"]:checked'))
                .map(cb => parseInt(cb.value));

            const repValue = document.getElementById('exp-rep').value.trim();
            const data = {
                experiment_type: document.getElementById('exp-type').value,
                code: document.getElementById('exp-code').value.trim().toUpperCase(),
                repetition: repValue === '' ? null : repValue,
                cell_types: currentCellTypes.join(', '),
                microscope: document.getElementById('exp-microscope').value,
                live_or_fixed: document.getElementById('exp-live-fixed').value,
                protocol_ids: selectedProtocols,
                tags: [...currentTags],
                channels: getChannelsFromForm(),
                thumbnail_path: document.getElementById('exp-thumbnail').value,
                comments: document.getElementById('exp-comments').value
            };

            try {
                const url = id ? `${API_BASE_URL}/experiments/${id}` : `${API_BASE_URL}/experiments`;
                const method = id ? 'PUT' : 'POST';

                const response = await fetch(url, {
                    method,
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (result.success) {
                    showAlert(id ? 'Experiment updated successfully' : 'Experiment created successfully', 'success');
                    resetExperimentForm();
                    await loadExperiments();
                    updateStats();
                } else {
                    showAlert('Error: ' + result.error, 'error');
                }
            } catch (error) {
                showAlert('Error saving experiment: ' + error.message, 'error');
            }
        });
    }
});

// ==================== PROTOCOLS ====================

async function loadProtocols() {
    const loading = document.getElementById('proto-loading');
    const listDiv = document.getElementById('protocols-list');

    loading.classList.add('show');
    listDiv.innerHTML = '';

    try {
        const response = await fetch(`${API_BASE_URL}/protocols?all=true`);
        const protocols = await response.json();

        if (protocols.length === 0) {
            listDiv.innerHTML = '<p style="color: #666; text-align: center; padding: 2rem;">No protocols found</p>';
        } else {
            // Group by name
            const grouped = {};
            protocols.forEach(proto => {
                if (!grouped[proto.name]) grouped[proto.name] = [];
                grouped[proto.name].push(proto);
            });

            Object.entries(grouped).forEach(([name, versions]) => {
                const item = createProtocolListItem(name, versions);
                listDiv.appendChild(item);
            });
        }
    } catch (error) {
        showAlert('Error loading protocols: ' + error.message, 'error');
    } finally {
        loading.classList.remove('show');
    }
}

async function loadProtocolsForCheckboxes() {
    try {
        const response = await fetch(`${API_BASE_URL}/protocols`);
        const protocols = await response.json();

        // Populate cache for use in experiment list display
        protocolsCache = {};
        protocols.forEach(p => { protocolsCache[p.id] = p; });

        const container = document.getElementById('exp-protocols');
        container.innerHTML = '';

        if (protocols.length === 0) {
            container.innerHTML = '<p style="color: #999; text-align: center; padding: 1rem;">No protocols available</p>';
            return;
        }

        protocols.forEach(proto => {
            const item = document.createElement('div');
            item.className = 'protocol-checkbox-item';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `protocol-${proto.id}`;
            checkbox.value = proto.id;
            checkbox.name = 'protocols';

            const label = document.createElement('label');
            label.htmlFor = `protocol-${proto.id}`;
            label.textContent = `${proto.name} v${proto.version}`;

            item.appendChild(checkbox);
            item.appendChild(label);
            container.appendChild(item);
        });
    } catch (error) {
        console.error('Error loading protocols:', error);
    }
}

function createProtocolListItem(name, versions) {
    const div = document.createElement('div');
    div.className = 'list-item';

    const latest = versions.find(v => v.is_latest);
    const versionsList = versions.map(v =>
        `v${v.version}${v.is_latest ? ' (latest)' : ''}`
    ).join(', ');

    div.innerHTML = `
        <div class="list-item-content">
            <div class="list-item-title">
                ${name}
                ${latest ? '<span class="badge latest">LATEST</span>' : ''}
            </div>
            <div class="list-item-meta">Versions: ${versionsList}</div>
            ${latest && latest.description ? `<div class="list-item-meta">${latest.description}</div>` : ''}
        </div>
        <div class="list-item-actions">
            ${latest ? `<button class="button btn-small" onclick="editProtocol(${latest.id})">Edit Latest</button>` : ''}
            <button class="button secondary btn-small" onclick="viewProtocolVersions('${name}', ${JSON.stringify(versions).replace(/"/g, '&quot;')})">View All</button>
        </div>
    `;

    return div;
}

function viewProtocolVersions(name, versions) {
    const versionsList = versions.map(v => `
        <tr>
            <td>v${v.version}${v.is_latest ? ' <span class="badge latest">LATEST</span>' : ''}</td>
            <td>${new Date(v.created_at).toLocaleDateString()}</td>
            <td>
                <button class="button btn-small" onclick="editProtocol(${v.id})">Edit</button>
                <button class="button danger btn-small" onclick="deleteProtocol(${v.id}, '${name}', 'v${v.version}')">Delete</button>
            </td>
        </tr>
    `).join('');

    const modal = document.createElement('div');
    modal.className = 'modal show';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">${name} - All Versions</div>
            <div class="modal-body">
                <table>
                    <thead>
                        <tr>
                            <th>Version</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${versionsList}
                    </tbody>
                </table>
            </div>
            <button class="button secondary" onclick="this.closest('.modal').remove()">Close</button>
        </div>
    `;

    document.body.appendChild(modal);
}

async function editProtocol(id) {
    try {
        const response = await fetch(`${API_BASE_URL}/protocols/${id}`);
        const proto = await response.json();

        document.getElementById('proto-id').value = proto.id;
        document.getElementById('proto-name').value = proto.name;
        document.getElementById('proto-version').value = proto.version;
        document.getElementById('proto-description').value = proto.description || '';
        document.getElementById('proto-content').value = proto.content || '';
        document.getElementById('proto-file-path').value = proto.file_path || '';

        // Switch to protocols tab
        switchTab('protocols');
        document.querySelector('.tab:nth-child(2)').click();

        // Scroll to form
        document.getElementById('protocol-form').scrollIntoView({behavior: 'smooth'});
        showAlert('Editing protocol: ' + proto.name + ' v' + proto.version, 'info');
    } catch (error) {
        showAlert('Error loading protocol: ' + error.message, 'error');
    }
}

async function deleteProtocol(id, name, version) {
    if (!confirm(`Are you sure you want to delete protocol "${name} ${version}"?`)) return;

    try {
        const response = await fetch(`${API_BASE_URL}/protocols/${id}`, {
            method: 'DELETE',        });

        const data = await response.json();

        if (data.success) {
            showAlert('Protocol deleted successfully', 'success');
            await loadProtocols();
            await loadProtocolsForDropdown();
            updateStats();
            // Close any open modals
            document.querySelectorAll('.modal').forEach(m => m.remove());
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showAlert('Error deleting protocol: ' + error.message, 'error');
    }
}

function resetProtocolForm() {
    document.getElementById('protocol-form').reset();
    document.getElementById('proto-id').value = '';
}

// Handle protocol form submission
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('protocol-form');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const id = document.getElementById('proto-id').value;
            const data = {
                name: document.getElementById('proto-name').value,
                version: document.getElementById('proto-version').value,
                description: document.getElementById('proto-description').value,
                content: document.getElementById('proto-content').value,
                file_path: document.getElementById('proto-file-path').value
            };

            try {
                const url = id ? `${API_BASE_URL}/protocols/${id}` : `${API_BASE_URL}/protocols`;
                const method = id ? 'PUT' : 'POST';

                const response = await fetch(url, {
                    method,
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (result.success) {
                    showAlert(id ? 'Protocol updated successfully' : 'Protocol created successfully', 'success');
                    resetProtocolForm();
                    await loadProtocols();
                    await loadProtocolsForDropdown();
                    updateStats();
                } else {
                    showAlert('Error: ' + result.error, 'error');
                }
            } catch (error) {
                showAlert('Error saving protocol: ' + error.message, 'error');
            }
        });
    }
});

// ==================== REPORTS ====================

async function loadReports() {
    const loading = document.getElementById('report-loading');
    const listDiv = document.getElementById('reports-list');

    loading.classList.add('show');
    listDiv.innerHTML = '';

    try {
        const response = await fetch(`${API_BASE_URL}/reports`);
        const reports = await response.json();

        if (reports.length === 0) {
            listDiv.innerHTML = '<p style="color: #666; text-align: center; padding: 2rem;">No reports found</p>';
        } else {
            reports.forEach(report => {
                const item = createReportListItem(report);
                listDiv.appendChild(item);
            });
        }
    } catch (error) {
        showAlert('Error loading reports: ' + error.message, 'error');
    } finally {
        loading.classList.remove('show');
    }
}

function createReportListItem(report) {
    const div = document.createElement('div');
    div.className = 'list-item';

    const date = new Date(report.modified).toLocaleString();

    div.innerHTML = `
        <div class="list-item-content">
            <div class="list-item-title">${report.filename}</div>
            <div class="list-item-meta">Last modified: ${date}</div>
            <div class="list-item-meta">Size: ${(report.size / 1024).toFixed(2)} KB</div>
        </div>
        <div class="list-item-actions">
            <button class="button btn-small" onclick="editReport('${report.filename}')">Edit</button>
            <button class="button danger btn-small" onclick="deleteReport('${report.filename}')">Delete</button>
        </div>
    `;

    return div;
}

async function editReport(filename) {
    try {
        const response = await fetch(`${API_BASE_URL}/reports/${filename}`);
        const report = await response.json();

        document.getElementById('report-filename').value = report.filename;
        document.getElementById('report-filename').readOnly = true;
        document.getElementById('report-content').value = report.content;

        // Switch to reports tab
        switchTab('reports');
        document.querySelector('.tab:nth-child(3)').click();

        // Scroll to form
        document.getElementById('report-form').scrollIntoView({behavior: 'smooth'});
        showAlert('Editing report: ' + filename, 'info');
    } catch (error) {
        showAlert('Error loading report: ' + error.message, 'error');
    }
}

async function deleteReport(filename) {
    if (!confirm(`Are you sure you want to delete report "${filename}"?`)) return;

    try {
        const response = await fetch(`${API_BASE_URL}/reports/${filename}`, {
            method: 'DELETE',        });

        const data = await response.json();

        if (data.success) {
            showAlert('Report deleted successfully', 'success');
            await loadReports();
            updateStats();
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showAlert('Error deleting report: ' + error.message, 'error');
    }
}

function resetReportForm() {
    document.getElementById('report-form').reset();
    document.getElementById('report-filename').readOnly = false;
}

// Handle report form submission
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('report-form');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const filename = document.getElementById('report-filename').value;
            const content = document.getElementById('report-content').value;
            const isEdit = document.getElementById('report-filename').readOnly;

            if (!filename.endsWith('.md')) {
                showAlert('Filename must end with .md', 'error');
                return;
            }

            const data = {
                filename,
                content
            };

            try {
                const url = isEdit
                    ? `${API_BASE_URL}/reports/${filename}`
                    : `${API_BASE_URL}/reports`;
                const method = isEdit ? 'PUT' : 'POST';

                const response = await fetch(url, {
                    method,
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (result.success) {
                    showAlert(isEdit ? 'Report updated successfully' : 'Report created successfully', 'success');
                    resetReportForm();
                    await loadReports();
                    updateStats();
                } else {
                    showAlert('Error: ' + result.error, 'error');
                }
            } catch (error) {
                showAlert('Error saving report: ' + error.message, 'error');
            }
        });
    }
});

// ==================== REGENERATE CATALOGS ====================

async function regenerateCatalogs() {
    if (!confirm('This will regenerate all catalog HTML files. Continue?')) return;

    showAlert('Regenerating catalogs...', 'info');

    try {
        const response = await fetch(`${API_BASE_URL}/regenerate`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (data.success) {
            showAlert('Catalogs regenerated successfully! Refresh the pages to see changes.', 'success');
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showAlert('Error regenerating catalogs: ' + error.message, 'error');
    }
}
