// ================= GLOBAL STATE =================
let connectionMode = 'demo'; // 'demo' or 'real'
let authStatus = { credentials_exist: false, token_active: false };
let scanPollInterval = null;
let deletePollInterval = null;

// Duplicate finder state
let scanResults = null; // Stores API results
let selectedDupeIds = new Set(); // File IDs checked for deletion

// Selective deleter state
let selectiveResults = null;
let selectedSelectiveIds = new Set();
let selectedSelectiveMimeCategories = new Set();

// ================= INITIALIZATION =================
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initDeduplicator();
  initSelectiveDeleter();
  initDialogs();
  
  // Refresh Lucide Icons once page is structured
  lucide.createIcons();
  checkConnectionStatus();
});

// ================= SYSTEM CONNECTION STATUS =================
async function checkConnectionStatus() {
  const statusDot = document.getElementById('sidebar-indicator-dot');
  const statusText = document.getElementById('sidebar-status-text');

  try {
    const response = await fetch('/api/auth/status');
    const data = await response.json();
    authStatus = data;
    
    statusDot.className = 'status-indicator-dot';
    
    if (data.mode === 'real') {
      connectionMode = 'real';
      if (data.token_active) {
        statusDot.classList.add('online');
        statusText.textContent = 'Google Connected';
      } else {
        statusDot.classList.add('offline');
        statusText.textContent = 'Account Link Required';
      }
    } else {
      connectionMode = 'demo';
      statusDot.classList.add('demo');
      statusText.textContent = 'Demo Mode Active';
    }
    
    // Update settings view dynamically if settings is loaded
    renderSettingsView();
  } catch (err) {
    statusDot.className = 'status-indicator-dot offline';
    statusText.textContent = 'Connection Error';
    console.error('Error fetching connection status:', err);
  }
}

// ================= SIDEBAR NAVIGATION =================
function initNavigation() {
  const navDedup = document.getElementById('nav-dedup');
  const navSelective = document.getElementById('nav-selective');
  const navSettings = document.getElementById('nav-settings');
  
  const viewTitle = document.getElementById('view-title');
  
  const paneDedup = document.getElementById('view-dedup-content');
  const paneSelective = document.getElementById('view-selective-content');
  const paneSettings = document.getElementById('view-settings-content');

  const navItems = [navDedup, navSelective, navSettings];
  const paneItems = [paneDedup, paneSelective, paneSettings];

  function switchView(activeNav, activePane, titleText) {
    navItems.forEach(item => item.classList.remove('active'));
    paneItems.forEach(pane => pane.classList.add('hidden'));
    
    activeNav.classList.add('active');
    activePane.classList.remove('hidden');
    viewTitle.textContent = titleText;
    
    lucide.createIcons();
  }

  navDedup.addEventListener('click', () => {
    switchView(navDedup, paneDedup, 'Duplicate Finder');
  });

  navSelective.addEventListener('click', () => {
    switchView(navSelective, paneSelective, 'Selective Deleter');
  });

  navSettings.addEventListener('click', () => {
    switchView(navSettings, paneSettings, 'Settings & Status');
    renderSettingsView();
  });

  const btnSidebarSettings = document.getElementById('btn-sidebar-settings');
  if (btnSidebarSettings) {
    btnSidebarSettings.addEventListener('click', () => {
      switchView(navSettings, paneSettings, 'Settings & Status');
      renderSettingsView();
    });
  }
}

// ================= VIEW: DEDUPLICATOR STAGE =================
function initDeduplicator() {
  const btnStartScan = document.getElementById('btn-start-scan');
  const dedupSetupCard = document.getElementById('dedup-setup-card');
  const scanProgressCard = document.getElementById('scan-progress-card');
  const dedupResultsPanel = document.getElementById('dedup-results-panel');
  const btnExportCsv = document.getElementById('btn-export-csv');
  const dedupSearchInput = document.getElementById('dedup-search-input');
  
  const btnSelectAll = document.getElementById('btn-select-all-dupes');
  const btnDeselectAll = document.getElementById('btn-deselect-all-dupes');

  btnStartScan.addEventListener('click', async () => {
    dedupSetupCard.classList.add('hidden');
    dedupResultsPanel.classList.add('hidden');
    scanProgressCard.classList.remove('hidden');
    
    const includeShared = document.getElementById('dedup-shared-drives').checked;
    const strictName = document.getElementById('dedup-strict-name').checked;

    try {
      const response = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          include_shared: includeShared,
          strict_name: strictName
        })
      });
      
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to start scan');
      }

      // Start status polling
      scanPollInterval = setInterval(pollScanStatus, 500);
    } catch (err) {
      showToast(`Error starting scan: ${err.message}`);
      dedupSetupCard.classList.remove('hidden');
      scanProgressCard.classList.add('hidden');
    }
  });

  const btnRescanDedup = document.getElementById('btn-rescan-dedup');
  if (btnRescanDedup) {
    btnRescanDedup.addEventListener('click', () => {
      btnStartScan.click();
    });
  }

  // Export CSV
  btnExportCsv.addEventListener('click', () => {
    if (!scanResults || !scanResults.duplicates) return;
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Group,Action,File Name,Folder Path,Size (Bytes),MD5 Checksum,Created Time,File ID,WebView Link\r\n";
    
    scanResults.duplicates.forEach((group, index) => {
      group.copies.forEach(copy => {
        const action = selectedDupeIds.has(copy.id) ? "DELETE" : "KEEP";
        const row = [
          index + 1,
          action,
          `"${copy.name.replace(/"/g, '""')}"`,
          `"${copy.path.replace(/"/g, '""')}"`,
          copy.size,
          copy.md5,
          copy.createdTime,
          copy.id,
          `"${copy.webViewLink}"`
        ].join(",");
        csvContent += row + "\r\n";
      });
    });
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `gdrive_cleaner_report_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });

  // Search filter
  dedupSearchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    const accordionGroups = document.querySelectorAll('.accordion-group');
    
    accordionGroups.forEach(group => {
      const name = group.getAttribute('data-name').toLowerCase();
      if (name.includes(query)) {
        group.classList.remove('hidden');
      } else {
        group.classList.add('hidden');
      }
    });
  });

  // Group Selection Actions
  btnSelectAll.addEventListener('click', () => {
    if (!scanResults || !scanResults.duplicates) return;
    scanResults.duplicates.forEach(group => {
      group.copies.forEach(copy => {
        if (!copy.isKeeper) {
          selectedDupeIds.add(copy.id);
        }
      });
    });
    updateDupeCheckboxesAndLabels();
  });

  btnDeselectAll.addEventListener('click', () => {
    selectedDupeIds.clear();
    updateDupeCheckboxesAndLabels();
  });
}

// Poll scanning progress
async function pollScanStatus() {
  const progressBar = document.getElementById('scan-progress-bar');
  const fileStat = document.getElementById('scan-stat-files');
  const folderStat = document.getElementById('scan-stat-folders');
  const scanProgressCard = document.getElementById('scan-progress-card');
  const dedupResultsPanel = document.getElementById('dedup-results-panel');
  const resultsTitle = document.getElementById('results-summary-title');
  const resultsDesc = document.getElementById('results-summary-desc');

  try {
    const response = await fetch('/api/scan/status');
    const data = await response.json();

    if (data.status === 'scanning') {
      const progress = data.progress;
      fileStat.textContent = `Scanned: ${progress.scanned_count.toLocaleString()} files`;
      folderStat.textContent = `Cached: ${progress.folders_cached.toLocaleString()} folders`;
      
      // Calculate a pseudo progress based on file/page numbers (up to 95% until completed)
      let percent = Math.min(95, (progress.page_num * 25));
      progressBar.style.width = `${percent}%`;
    } 
    else if (data.status === 'completed') {
      clearInterval(scanPollInterval);
      progressBar.style.width = '100%';
      
      setTimeout(() => {
        scanProgressCard.classList.add('hidden');
        dedupResultsPanel.classList.remove('hidden');
        
        scanResults = data.results;
        
        // Populate initial selection sets
        selectedDupeIds.clear();
        let groupCount = 0;
        let duplicateCount = 0;
        
        if (scanResults.duplicates) {
          groupCount = scanResults.duplicates.length;
          scanResults.duplicates.forEach(group => {
            group.copies.forEach(copy => {
              if (!copy.isKeeper) {
                selectedDupeIds.add(copy.id);
                duplicateCount++;
              }
            });
          });
        }
        
        resultsTitle.textContent = 'Scan Completed';
        resultsDesc.textContent = `We found ${duplicateCount} duplicate copies across ${groupCount} unique file groups.`;
        
        renderDuplicatesList();
        updateDupeCheckboxesAndLabels();
      }, 500);
    } 
    else if (data.status === 'error') {
      clearInterval(scanPollInterval);
      showToast(`Scan failed: ${data.error}`);
      document.getElementById('dedup-setup-card').classList.remove('hidden');
      scanProgressCard.classList.add('hidden');
    }
  } catch (err) {
    console.error('Error polling scan status:', err);
  }
}

// Render duplicate file rows
function renderDuplicatesList() {
  const container = document.getElementById('duplicate-groups-list');
  container.innerHTML = '';
  
  if (!scanResults || !scanResults.duplicates || scanResults.duplicates.length === 0) {
    container.innerHTML = '<div class="glass-panel p-md text-center text-secondary">No duplicate files found. Your Drive is clean!</div>';
    return;
  }

  scanResults.duplicates.forEach((group, index) => {
    const groupElement = document.createElement('div');
    groupElement.className = 'glass-panel accordion-group card';
    groupElement.setAttribute('data-name', group.name);
    

    const copiesCount = group.copies.length;
    const deletableCount = copiesCount - 1;

    // Header HTML
    groupElement.innerHTML = `
      <button class="accordion-header" id="header-group-${index}">
        <i data-lucide="chevron-right" class="accordion-chevron"></i>
        <div class="group-info-row">
          <span class="group-name">${group.name}</span>
          <div class="group-meta">
            <span class="group-badge">${copiesCount} copies</span>
            <span>Size: ${formatBytes(group.size)}</span>
            <span class="text-muted">MD5: ${group.md5.slice(0, 8)}</span>
          </div>
        </div>
      </button>
      <div class="accordion-content">
        <ul class="accordion-file-list" id="file-list-group-${index}">
        </ul>
      </div>
    `;

    container.appendChild(groupElement);
    
    // File list rendering
    const listContainer = document.getElementById(`file-list-group-${index}`);
    group.copies.forEach(copy => {
      const fileLi = document.createElement('li');
      fileLi.className = 'file-row-item';
      
      const isChecked = selectedDupeIds.has(copy.id) ? 'checked' : '';
      const checkboxHtml = copy.isKeeper 
        ? '<div style="width:20px;"></div>' 
        : `
          <label class="checkbox-container">
            <input type="checkbox" class="dupe-file-checkbox" data-file-id="${copy.id}" ${isChecked}>
            <span class="checkmark"></span>
          </label>
        `;
        
      const statusTagClass = copy.isKeeper ? 'tag-keep' : 'tag-delete';
      const statusTagText = copy.isKeeper ? 'Keeper' : 'Delete';
      
      fileLi.innerHTML = `
        <div>${checkboxHtml}</div>
        <div class="file-path">${copy.path}</div>
        <div>${formatBytes(copy.size)}</div>
        <div class="file-created">${copy.createdTime.substring(0, 16).replace('T', ' ')}</div>
        <div>
          <span class="file-status-tag ${statusTagClass}" id="tag-${copy.id}">${statusTagText}</span>
        </div>
        <div>
          <a href="${copy.webViewLink}" target="_blank" class="file-link" title="Open file in Drive">
            <i data-lucide="external-link" style="width:16px;height:16px;"></i>
          </a>
        </div>
      `;
      
      listContainer.appendChild(fileLi);
    });

    // Toggle accordion interaction
    const headerBtn = document.getElementById(`header-group-${index}`);
    headerBtn.addEventListener('click', () => {
      groupElement.classList.toggle('open');
    });
  });

  // Bind checkbox events
  document.querySelectorAll('.dupe-file-checkbox').forEach(checkbox => {
    checkbox.addEventListener('change', (e) => {
      const fid = e.target.getAttribute('data-file-id');
      const statusTag = document.getElementById(`tag-${fid}`);
      
      if (e.target.checked) {
        selectedDupeIds.add(fid);
        statusTag.textContent = 'Delete';
        statusTag.className = 'file-status-tag tag-delete';
      } else {
        selectedDupeIds.delete(fid);
        statusTag.textContent = 'Keep';
        statusTag.className = 'file-status-tag tag-keep';
      }
      recalculateSelectionSize();
    });
  });
  
  // Reload icons inside accordions
  lucide.createIcons();
}

function updateDupeCheckboxesAndLabels() {
  document.querySelectorAll('.dupe-file-checkbox').forEach(checkbox => {
    const fid = checkbox.getAttribute('data-file-id');
    const checked = selectedDupeIds.has(fid);
    checkbox.checked = checked;
    
    const statusTag = document.getElementById(`tag-${fid}`);
    if (statusTag) {
      if (checked) {
        statusTag.textContent = 'Delete';
        statusTag.className = 'file-status-tag tag-delete';
      } else {
        statusTag.textContent = 'Keep';
        statusTag.className = 'file-status-tag tag-keep';
      }
    }
  });
  recalculateSelectionSize();
}

function recalculateSelectionSize() {
  let totalBytes = 0;
  
  if (scanResults && scanResults.duplicates) {
    scanResults.duplicates.forEach(group => {
      group.copies.forEach(copy => {
        if (selectedDupeIds.has(copy.id)) {
          totalBytes += copy.size;
        }
      });
    });
  }

  const selectedSizeEl = document.getElementById('selected-reclaim-size');
  selectedSizeEl.textContent = formatBytes(totalBytes);
}

// ================= VIEW: SELECTIVE DELETER =================
function initSelectiveDeleter() {
  const mimePills = document.querySelectorAll('.mime-pill');
  const selectiveFilterForm = document.getElementById('selective-filter-form');
  const selectivePreviewPanel = document.getElementById('selective-preview-panel');
  const btnSelectiveSelectAll = document.getElementById('btn-selective-select-all');
  const btnSelectiveDeselectAll = document.getElementById('btn-selective-deselect-all');
  const headerSelectAll = document.getElementById('header-select-all-selective');

  // Pill Toggling
  mimePills.forEach(pill => {
    pill.addEventListener('click', () => {
      const category = pill.getAttribute('data-category');
      pill.classList.toggle('active');
      
      if (pill.classList.contains('active')) {
        selectedSelectiveMimeCategories.add(category);
      } else {
        selectedSelectiveMimeCategories.delete(category);
      }
    });
  });

  // Submit filters
  selectiveFilterForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const namesInput = document.getElementById('selective-names').value;
    const includeShared = document.getElementById('selective-shared-drives').checked;
    
    // Assemble MIME categories
    const categoriesArray = Array.from(selectedSelectiveMimeCategories);
    const categoriesString = categoriesArray.join(',');

    selectivePreviewPanel.classList.add('hidden');
    document.getElementById('selective-filter-card').classList.add('hidden');
    selectiveFilterForm.parentElement.classList.add('hidden');
    
    const selectiveProgressCard = document.getElementById('selective-progress-card');
    selectiveProgressCard.classList.remove('hidden');

    try {
      const response = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          names: namesInput || null,
          types: categoriesString || null,
          include_shared: includeShared
        })
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Search failed');
      }

      scanPollInterval = setInterval(pollSelectiveScanStatus, 500);
    } catch (err) {
      showToast(`Error scanning files: ${err.message}`);
      selectiveProgressCard.classList.add('hidden');
      document.getElementById('selective-filter-card').classList.remove('hidden');
      selectiveFilterForm.parentElement.classList.remove('hidden');
    }
  });

  const btnRescanSelective = document.getElementById('btn-rescan-selective');
  if (btnRescanSelective) {
    btnRescanSelective.addEventListener('click', () => {
      const btnPreviewSelective = document.getElementById('btn-preview-selective');
      if (btnPreviewSelective) {
        btnPreviewSelective.click();
      }
    });
  }

  // Select/Deselect shortcuts for table rows
  btnSelectiveSelectAll.addEventListener('click', () => {
    if (!selectiveResults || !selectiveResults.files) return;
    selectiveResults.files.forEach(f => selectedSelectiveIds.add(f.id));
    updateSelectiveCheckboxes();
  });

  btnSelectiveDeselectAll.addEventListener('click', () => {
    selectedSelectiveIds.clear();
    updateSelectiveCheckboxes();
  });

  headerSelectAll.addEventListener('change', (e) => {
    if (e.target.checked) {
      if (selectiveResults && selectiveResults.files) {
        selectiveResults.files.forEach(f => selectedSelectiveIds.add(f.id));
      }
    } else {
      selectedSelectiveIds.clear();
    }
    updateSelectiveCheckboxes();
  });
}

// Poll scanning progress for Selective Deleter
async function pollSelectiveScanStatus() {
  const progressBar = document.getElementById('selective-progress-bar');
  const fileStat = document.getElementById('selective-stat-files');
  const folderStat = document.getElementById('selective-stat-folders');
  const selectiveProgressCard = document.getElementById('selective-progress-card');
  const selectiveFilterCard = document.getElementById('selective-filter-card');
  const selectiveFilterForm = document.getElementById('selective-filter-form');
  const selectivePreviewPanel = document.getElementById('selective-preview-panel');
  const summaryTitle = document.getElementById('selective-summary-title');
  const summaryDesc = document.getElementById('selective-summary-desc');

  try {
    const response = await fetch('/api/scan/status');
    const data = await response.json();

    if (data.status === 'scanning') {
      const progress = data.progress;
      fileStat.textContent = `Scanned: ${progress.scanned_count.toLocaleString()} files`;
      folderStat.textContent = `Cached: ${progress.folders_cached.toLocaleString()} folders`;
      
      let percent = Math.min(95, (progress.page_num * 25));
      progressBar.style.width = `${percent}%`;
    } 
    else if (data.status === 'completed') {
      clearInterval(scanPollInterval);
      progressBar.style.width = '100%';
      
      setTimeout(() => {
        selectiveProgressCard.classList.add('hidden');
        selectiveFilterCard.classList.remove('hidden');
        selectiveFilterForm.parentElement.classList.remove('hidden');
        selectivePreviewPanel.classList.remove('hidden');
        
        selectiveResults = data.results;
        selectedSelectiveIds.clear();
        
        let totalCount = 0;
        let totalSize = 0;
        
        if (selectiveResults.files) {
          totalCount = selectiveResults.files.length;
          selectiveResults.files.forEach(f => {
            selectedSelectiveIds.add(f.id);
            totalSize += f.size;
          });
        }
        
        summaryTitle.textContent = 'Preview Matching Files';
        summaryDesc.textContent = `Found ${totalCount} files matching search criteria (${formatBytes(totalSize)} total).`;
        
        renderSelectivePreviewTable();
        updateSelectiveCheckboxes();
      }, 500);
    } 
    else if (data.status === 'error') {
      clearInterval(scanPollInterval);
      showToast(`Search failed: ${data.error}`);
      selectiveProgressCard.classList.add('hidden');
      selectiveFilterCard.classList.remove('hidden');
      selectiveFilterForm.parentElement.classList.remove('hidden');
    }
  } catch (err) {
    console.error('Error polling selective scan status:', err);
  }
}

// Render Table Rows for Selective Delete View
function renderSelectivePreviewTable() {
  const tbody = document.getElementById('selective-preview-tbody');
  tbody.innerHTML = '';
  
  if (!selectiveResults || !selectiveResults.files || selectiveResults.files.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-secondary">No files matched your filter criteria.</td></tr>';
    return;
  }

  selectiveResults.files.forEach(file => {
    const tr = document.createElement('tr');
    tr.id = `row-${file.id}`;
    
    tr.innerHTML = `
      <td>
        <input type="checkbox" class="selective-file-checkbox" data-file-id="${file.id}">
      </td>
      <td style="font-weight: 500;">${file.name}</td>
      <td class="file-path">${file.path}</td>
      <td>${formatBytes(file.size)}</td>
      <td class="text-secondary">${file.mimeType.split('/').pop()}</td>
      <td class="file-created">${file.createdTime.substring(0, 10)}</td>
    `;
    tbody.appendChild(tr);
  });

  // Bind individual checkbox clicks
  document.querySelectorAll('.selective-file-checkbox').forEach(checkbox => {
    checkbox.addEventListener('change', (e) => {
      const fid = e.target.getAttribute('data-file-id');
      if (e.target.checked) {
        selectedSelectiveIds.add(fid);
      } else {
        selectedSelectiveIds.delete(fid);
        document.getElementById('header-select-all-selective').checked = false;
      }
      recalculateSelectiveSelection();
    });
  });
}

function updateSelectiveCheckboxes() {
  document.querySelectorAll('.selective-file-checkbox').forEach(checkbox => {
    const fid = checkbox.getAttribute('data-file-id');
    checkbox.checked = selectedSelectiveIds.has(fid);
  });
  recalculateSelectiveSelection();
}

function recalculateSelectiveSelection() {
  let totalBytes = 0;
  let count = selectedSelectiveIds.size;
  
  if (selectiveResults && selectiveResults.files) {
    selectiveResults.files.forEach(f => {
      if (selectedSelectiveIds.has(f.id)) {
        totalBytes += f.size;
      }
    });
  }

  document.getElementById('selective-selected-size').textContent = formatBytes(totalBytes);
  document.getElementById('selective-selection-counter').textContent = `${count} files selected`;
  
  // Sync select all header state
  const headerCheckbox = document.getElementById('header-select-all-selective');
  if (selectiveResults && selectiveResults.files && selectiveResults.files.length > 0) {
    headerCheckbox.checked = (count === selectiveResults.files.length);
  } else {
    headerCheckbox.checked = false;
  }
}

// ================= VIEW: SETTINGS & STATUS =================
function renderSettingsView() {
  const box = document.getElementById('google-auth-config-box');
  const actions = document.getElementById('settings-auth-actions');
  const icon = document.getElementById('settings-auth-icon');
  const title = document.getElementById('settings-auth-title');
  const desc = document.getElementById('settings-auth-desc');

  actions.innerHTML = '';
  icon.className = 'status-indicator-icon';

  if (connectionMode === 'real') {
    if (authStatus.token_active) {
      icon.classList.add('online');
      title.textContent = 'Google API Connected';
      desc.textContent = 'Connected. You are authorized to scan and clean files in your actual Google Drive.';
      
      actions.innerHTML = `
        <button id="btn-settings-disconnect" class="btn btn-outline">Disconnect Google Account</button>
      `;
      
      document.getElementById('btn-settings-disconnect').addEventListener('click', handleDisconnectGoogle);
    } else {
      icon.classList.add('warning');
      title.textContent = 'Credentials Loaded - Authorization Required';
      desc.textContent = 'Google credentials.json found. Click below to authenticate this utility with your Google account via browser.';
      
      actions.innerHTML = `
        <button id="btn-settings-connect" class="btn btn-primary">Connect Google Account</button>
      `;
      
      document.getElementById('btn-settings-connect').addEventListener('click', handleConnectGoogle);
    }
  } else {
    icon.classList.add('offline');
    title.textContent = 'Demo Mode (No credentials.json)';
    desc.textContent = 'No credentials.json detected in the root folder. Running in a sandbox. Scan reports and deletions are simulated.';
    
    actions.innerHTML = `
      <span class="text-secondary" style="font-size:0.9rem;">To link your real account, add credentials.json to your directory as outlined in the setup guide.</span>
    `;
  }
  
  lucide.createIcons();
}

async function handleConnectGoogle() {
  const btn = document.getElementById('btn-settings-connect');
  btn.disabled = true;
  btn.textContent = 'Generating authorization link...';
  
  try {
    const response = await fetch('/api/auth/google-login', { method: 'POST' });
    if (!response.ok) throw new Error('Authentication flow failed to start.');
    
    const data = await response.json();
    if (data.auth_url) {
      window.open(data.auth_url, '_blank');
      btn.textContent = 'Waiting for Google Login...';
    } else {
      throw new Error('No authorization URL returned by server.');
    }
    
    // Poll the status every second until authenticated
    const statusPoll = setInterval(async () => {
      await checkConnectionStatus();
      if (authStatus.token_active) {
        clearInterval(statusPoll);
        renderSettingsView();
      }
    }, 1000);
    
  } catch (err) {
    showToast(`Failed to start authorization: ${err.message}`);
    btn.disabled = false;
    btn.textContent = 'Connect Google Account';
  }
}

async function handleDisconnectGoogle() {
  if (confirm('Disconnect from Google Account? This will delete local token.json.')) {
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST' });
      if (response.ok) {
        await checkConnectionStatus();
        renderSettingsView();
      }
    } catch (err) {
      showToast(`Error disconnecting: ${err.message}`);
    }
  }
}

// ================= DELETION CONFIRMATION & DIALOGS =================
function initDialogs() {
  const dialog = document.getElementById('confirm-delete-dialog');
  
  // Deduplicator action
  const btnOpenDeleteDialog = document.getElementById('btn-open-delete-dialog');
  
  // Selective deleter action
  const btnOpenSelectiveDeleteDialog = document.getElementById('btn-open-selective-delete-dialog');
  
  const btnCancel = document.getElementById('btn-dialog-cancel');
  const btnConfirm = document.getElementById('btn-dialog-confirm');
  
  let currentDeleteTarget = 'dedup'; // 'dedup' or 'selective'

  // Open Dialog from Deduplicator
  btnOpenDeleteDialog.addEventListener('click', () => {
    if (selectedDupeIds.size === 0) {
      showToast('Please select at least one duplicate file to delete.');
      return;
    }
    currentDeleteTarget = 'dedup';
    document.getElementById('confirm-dialog-msg').innerHTML = `
      You are about to delete <strong>${selectedDupeIds.size} files</strong>. Are you sure you want to proceed?
    `;
    
    // Only show Purge checkbox in Real Mode (Demo Mode skips real trashing anyways)
    const purgeContainer = document.getElementById('purge-option-container');
    if (connectionMode === 'real') {
      purgeContainer.classList.remove('hidden');
    } else {
      purgeContainer.classList.add('hidden');
    }
    
    document.getElementById('checkbox-purge-permanently').checked = false;
    dialog.showModal();
  });

  // Open Dialog from Selective Deleter
  btnOpenSelectiveDeleteDialog.addEventListener('click', () => {
    if (selectedSelectiveIds.size === 0) {
      showToast('Please select at least one file to delete.');
      return;
    }
    currentDeleteTarget = 'selective';
    document.getElementById('confirm-dialog-msg').innerHTML = `
      You are about to move <strong>${selectedSelectiveIds.size} files</strong> matching your filter to Google Drive Trash. Proceed?
    `;
    
    // Purging selectively can be irreversible
    const purgeContainer = document.getElementById('purge-option-container');
    if (connectionMode === 'real') {
      purgeContainer.classList.remove('hidden');
    } else {
      purgeContainer.classList.add('hidden');
    }
    
    document.getElementById('checkbox-purge-permanently').checked = false;
    dialog.showModal();
  });

  // Close Dialog Buttons
  btnCancel.addEventListener('click', () => {
    dialog.close();
  });

  // Execute Deletion
  btnConfirm.addEventListener('click', () => {
    dialog.close();
    
    const purgeCheck = document.getElementById('checkbox-purge-permanently').checked;
    const fileIds = currentDeleteTarget === 'dedup' 
      ? Array.from(selectedDupeIds) 
      : Array.from(selectedSelectiveIds);
      
    triggerDeletion(fileIds, purgeCheck);
  });

  // Fallback for browsers without closedby support (Safari)
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    dialog.addEventListener('click', (event) => {
      if (event.target !== dialog) return;

      const rect = dialog.getBoundingClientRect();
      const isDialogContent = (
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width
      );

      if (!isDialogContent) {
        dialog.close();
      }
    });
  }
}

// Trigger Deletion POST
async function triggerDeletion(fileIds, purge) {
  const overlay = document.getElementById('deletion-progress-overlay');
  overlay.classList.remove('hidden');
  
  document.getElementById('delete-progress-title').textContent = purge ? 'Permanently Purging...' : 'Moving to Trash...';
  document.getElementById('delete-progress-subtitle').textContent = 'Connecting to Drive API...';
  
  try {
    const response = await fetch('/api/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_ids: fileIds, purge: purge })
    });
    
    if (!response.ok) {
      const errData = await response.json();
      throw new Error(errData.detail || 'Failed to start deletion');
    }

    // Start Polling Deletion Progress
    deletePollInterval = setInterval(pollDeleteStatus, 500);
  } catch (err) {
    showToast(`Error: ${err.message}`);
    overlay.classList.add('hidden');
  }
}

async function pollDeleteStatus() {
  const progressBar = document.getElementById('delete-progress-bar');
  const countStat = document.getElementById('delete-stat-count');
  const sizeStat = document.getElementById('delete-stat-size');
  const overlay = document.getElementById('deletion-progress-overlay');

  try {
    const response = await fetch('/api/delete/status');
    const data = await response.json();

    if (data.status === 'deleting') {
      const progress = data.progress;
      countStat.textContent = `Deleted: ${progress.current}/${progress.total} files`;
      sizeStat.textContent = `Space Reclaimed: ${formatBytes(progress.actual_bytes)}`;
      
      let percent = Math.floor((progress.current / progress.total) * 100);
      progressBar.style.width = `${percent}%`;
    } 
    else if (data.status === 'completed') {
      clearInterval(deletePollInterval);
      progressBar.style.width = '100%';
      
      setTimeout(() => {
        overlay.classList.add('hidden');
        showToast('Cleanup completed successfully!');
        
        // Return to setup / reset layout
        resetAppWorkflowState();
      }, 500);
    } 
    else if (data.status === 'error') {
      clearInterval(deletePollInterval);
      showToast(`Deletion failed: ${data.error}`);
      overlay.classList.add('hidden');
    }
  } catch (err) {
    console.error('Error polling delete status:', err);
  }
}

// Reset after deletion completes
function resetAppWorkflowState() {
  // Clear lists
  scanResults = null;
  selectiveResults = null;
  selectedDupeIds.clear();
  selectedSelectiveIds.clear();

  // Reset Deduplicator view
  document.getElementById('dedup-setup-card').classList.remove('hidden');
  document.getElementById('scan-progress-card').classList.add('hidden');
  document.getElementById('dedup-results-panel').classList.add('hidden');
  document.getElementById('dedup-search-input').value = '';
  document.getElementById('dedup-shared-drives').checked = false;

  // Reset Selective view
  document.getElementById('selective-preview-panel').classList.add('hidden');
  document.getElementById('selective-names').value = '';
  document.getElementById('header-select-all-selective').checked = false;
  document.getElementById('selective-shared-drives').checked = false;
  document.querySelectorAll('.mime-pill').forEach(pill => pill.classList.remove('active'));
  selectedSelectiveMimeCategories.clear();
}

// ================= HELPERS =================
function formatBytes(bytes, decimals = 2) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}


// ================= TOAST NOTIFICATIONS =================
function showToast(message, type = 'error') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  if (message.includes('success')) {
      type = 'success';
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let iconName = 'info';
  if (type === 'error') iconName = 'alert-circle';
  if (type === 'success') iconName = 'check-circle';

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="toast-icon"></i>
    <div class="toast-message">${message}</div>
    <button class="toast-close"><i data-lucide="x" style="width:16px;height:16px;"></i></button>
  `;

  container.appendChild(toast);
  lucide.createIcons({ root: toast });

  const closeBtn = toast.querySelector('.toast-close');
  
  const hideToast = () => {
    toast.classList.add('toast-hiding');
    toast.addEventListener('animationend', () => {
      if (toast.parentElement) {
        toast.remove();
      }
    });
  };

  closeBtn.addEventListener('click', hideToast);
  setTimeout(hideToast, 5000); // Auto hide after 5 seconds
}
