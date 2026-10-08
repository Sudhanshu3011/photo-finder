"""
src/api/ui.py — Interactive Web Upload Interface.
Allows users to select and upload up to 50 images at once via a single file picker or drag-and-drop,
automatically triggering batch ingestion and AI vector processing into FAISS.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Visual Search — Multi-Image Batch Upload & Indexer</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem 1rem; display: flex; justify-content: center; }
    .container { max-width: 760px; width: 100%; background: #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #38bdf8; display: flex; align-items: center; justify-content: space-between; }
    .badge-limit { background: #0369a1; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 999px; color: white; }
    p.subtitle { font-size: 0.875rem; color: #94a3b8; margin-bottom: 1.5rem; }
    .drop-zone { border: 2px dashed #38bdf8; border-radius: 8px; padding: 2.2rem 1.5rem; text-align: center; cursor: pointer; transition: background 0.2s; background: #0f172a80; }
    .drop-zone:hover, .drop-zone.dragover { background: #1e3a5f; }
    .drop-zone input { display: none; }
    .btn { background: #0284c7; color: white; border: none; border-radius: 6px; padding: 0.8rem 1.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s; width: 100%; margin-top: 1.5rem; }
    .btn:hover { background: #0369a1; }
    .btn:disabled { background: #475569; cursor: not-allowed; }
    .form-group { margin-top: 1rem; }
    label { display: block; font-size: 0.875rem; font-weight: 500; margin-bottom: 0.4rem; color: #cbd5e1; }
    input[type="text"], input[type="password"] { width: 100%; padding: 0.65rem 0.8rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: white; font-size: 0.95rem; }
    .checkbox-group { display: flex; align-items: center; gap: 0.5rem; margin-top: 1rem; font-size: 0.875rem; color: #e2e8f0; }
    .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 0.6rem; margin-top: 1.25rem; max-height: 240px; overflow-y: auto; padding: 0.5rem; background: #0f172a; border-radius: 6px; border: 1px solid #334155; }
    .preview-card { position: relative; border-radius: 6px; overflow: hidden; height: 90px; background: #334155; }
    .preview-card img { width: 100%; height: 100%; object-fit: cover; }
    .progress-bar { width: 100%; height: 10px; background: #334155; border-radius: 5px; overflow: hidden; margin-top: 1rem; display: none; }
    .progress-fill { height: 100%; background: #38bdf8; width: 0%; transition: width 0.3s; }
    .status-text { font-size: 0.85rem; color: #38bdf8; margin-top: 0.5rem; text-align: center; font-weight: 500; }
    .result-box { margin-top: 1.5rem; padding: 1rem; background: #0f172a; border-radius: 6px; font-family: monospace; font-size: 0.85rem; display: none; white-space: pre-wrap; word-break: break-all; max-height: 250px; overflow-y: auto; border: 1px solid #334155; }
    .alert-banner { display: none; margin-top: 1rem; padding: 0.75rem; border-radius: 6px; background: #f59e0b20; border: 1px solid #f59e0b; color: #fde68a; font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>
      <span>Batch Photo Uploader & Indexer</span>
      <span class="badge-limit">Max 50 Photos / Batch</span>
    </h1>
    <p class="subtitle">Select or drop up to 50 photos to upload to Cloudinary and index into FAISS vector stores.</p>

    <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
      <svg width="42" height="42" fill="none" stroke="#38bdf8" stroke-width="2" viewBox="0 0 24 24" style="margin: 0 auto 0.5rem auto; display: block;"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
      <strong>Click to browse</strong> or drag & drop up to 50 images
      <div id="fileCount" class="badge-limit" style="display:none; margin-top:0.5rem">0 files selected</div>
      <input type="file" id="fileInput" multiple accept="image/*" onchange="handleFiles(this.files)">
    </div>

    <div id="alertBanner" class="alert-banner"></div>
    <div class="preview-grid" id="previewGrid" style="display:none"></div>

    <div class="form-group">
      <label for="jwtInput">JWT Access Token (Required for authenticated API access)</label>
      <input type="password" id="jwtInput" placeholder="Paste your Bearer token or obtain from /api/auth/login">
    </div>

    <div class="form-group">
      <label for="folderInput">Cloudinary Target Folder / Album</label>
      <input type="text" id="folderInput" value="general" placeholder="e.g. wedding_2026, vacation, portraits">
    </div>

    <div class="form-group">
      <label for="cldInput">Cloudinary URL (Optional — auto-fetched from user profile if omitted)</label>
      <input type="password" id="cldInput" placeholder="cloudinary://api_key:api_secret@cloud_name">
    </div>

    <div class="checkbox-group">
      <input type="checkbox" id="autoProcess" checked>
      <label for="autoProcess">Automatically trigger AI inference & FAISS indexing after upload</label>
    </div>

    <div class="progress-bar" id="progressBar">
      <div class="progress-fill" id="progressFill"></div>
    </div>
    <div id="statusText" class="status-text"></div>

    <button class="btn" id="uploadBtn" onclick="uploadImages()" disabled>Select Images (Max 50)</button>

    <div class="result-box" id="resultBox"></div>
  </div>

  <script>
    const MAX_FILES = 50;
    let selectedFiles = [];
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const previewGrid = document.getElementById('previewGrid');
    const fileCount = document.getElementById('fileCount');
    const alertBanner = document.getElementById('alertBanner');
    const uploadBtn = document.getElementById('uploadBtn');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const statusText = document.getElementById('statusText');
    const resultBox = document.getElementById('resultBox');

    ['dragenter', 'dragover'].forEach(e => {
      dropZone.addEventListener(e, (evt) => { evt.preventDefault(); dropZone.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(e => {
      dropZone.addEventListener(e, (evt) => { evt.preventDefault(); dropZone.classList.remove('dragover'); });
    });
    dropZone.addEventListener('drop', (evt) => {
      handleFiles(evt.dataTransfer.files);
    });

    function handleFiles(files) {
      if (!files || files.length === 0) return;
      alertBanner.style.display = 'none';

      let incoming = Array.from(files).filter(f => f.type.startsWith('image/'));
      if (incoming.length > MAX_FILES) {
        alertBanner.textContent = `Warning: You selected ${incoming.length} photos. Only the first ${MAX_FILES} photos will be processed in this batch.`;
        alertBanner.style.display = 'block';
        incoming = incoming.slice(0, MAX_FILES);
      }

      selectedFiles = incoming;
      fileCount.textContent = `${selectedFiles.length} / ${MAX_FILES} images selected`;
      fileCount.style.display = 'inline-block';
      uploadBtn.disabled = selectedFiles.length === 0;
      uploadBtn.textContent = `Upload & Index ${selectedFiles.length} Images`;

      previewGrid.innerHTML = '';
      if (selectedFiles.length > 0) {
        previewGrid.style.display = 'grid';
        selectedFiles.forEach(file => {
          const card = document.createElement('div');
          card.className = 'preview-card';
          const img = document.createElement('img');
          img.src = URL.createObjectURL(file);
          card.appendChild(img);
          previewGrid.appendChild(card);
        });
      } else {
        previewGrid.style.display = 'none';
      }
    }

    async function uploadImages() {
      if (selectedFiles.length === 0) return;

      const folder = document.getElementById('folderInput').value.trim() || 'general';
      const autoProcess = document.getElementById('autoProcess').checked;
      const cld = document.getElementById('cldInput').value.trim();
      const jwt = document.getElementById('jwtInput').value.trim();

      if (jwt) localStorage.setItem('jwt_token', jwt);
      const reqHeaders = {};
      if (jwt) {
        reqHeaders['Authorization'] = jwt.startsWith('Bearer ') ? jwt : `Bearer ${jwt}`;
      }

      uploadBtn.disabled = true;
      uploadBtn.textContent = `Uploading ${selectedFiles.length} images...`;
      progressBar.style.display = 'block';
      progressFill.style.width = '20%';
      statusText.textContent = `Step 1/2: Uploading ${selectedFiles.length} images to folder '${folder}'...`;
      resultBox.style.display = 'none';

      const formData = new FormData();
      formData.append('folder_name', folder);
      if (cld) {
        formData.append('cloudinary_url', cld);
        localStorage.setItem('cld_url', cld);
      }

      selectedFiles.forEach(f => {
        formData.append('files', f);
      });

      try {
        const response = await fetch('/api/upload/batch', {
          method: 'POST',
          headers: reqHeaders,
          body: formData,
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || 'Upload failed');
        }

        progressFill.style.width = '50%';
        const items = data.items || [];
        const successItems = items.filter(i => i.status === 'success');

        if (!autoProcess || successItems.length === 0) {
          progressFill.style.width = '100%';
          statusText.textContent = `Upload complete! ${successItems.length} photos stored.`;
          resultBox.style.display = 'block';
          resultBox.textContent = JSON.stringify(data, null, 2);
          uploadBtn.textContent = 'Upload Finished';
          return;
        }

        // Step 2: Auto-trigger AI processing per image into FAISS
        statusText.textContent = `Step 2/2: Running AI feature extraction & FAISS indexing (0 / ${successItems.length})...`;
        uploadBtn.textContent = 'AI Indexing in Progress...';
        
        let processedCount = 0;
        const processResults = [];

        for (const item of successItems) {
          try {
            const pRes = await fetch(`/api/process/image/${item.image_id}`, {
              method: 'POST',
              headers: reqHeaders,
            });
            const pData = await pRes.json();
            processResults.push(pData);
          } catch (e) {
            processResults.push({ image_id: item.image_id, status: 'error', error: e.message });
          }
          processedCount++;
          const pct = Math.round(50 + (processedCount / successItems.length) * 50);
          progressFill.style.width = `${pct}%`;
          statusText.textContent = `Step 2/2: Running AI indexing (${processedCount} / ${successItems.length})...`;
        }

        progressFill.style.width = '100%';
        statusText.textContent = `All ${processedCount} photos indexed into FAISS folder '${folder}'! Ready for search.`;
        uploadBtn.textContent = 'Complete! Upload Another Batch';
        uploadBtn.disabled = false;

        resultBox.style.display = 'block';
        resultBox.textContent = JSON.stringify({
          batch_summary: {
            total_uploaded: data.total,
            successful: data.successful,
            folder: folder,
            indexed_in_faiss: processedCount
          },
          processed_items: processResults
        }, null, 2);

      } catch (err) {
        progressFill.style.width = '0%';
        statusText.textContent = 'Error: ' + err.message;
        uploadBtn.textContent = 'Upload Failed';
        uploadBtn.disabled = false;
        resultBox.style.display = 'block';
        resultBox.textContent = err.message;
      }
    }

    const savedCld = localStorage.getItem('cld_url');
    if (savedCld) document.getElementById('cldInput').value = savedCld;
    const savedJwt = localStorage.getItem('jwt_token');
    if (savedJwt) document.getElementById('jwtInput').value = savedJwt;

  </script>
</body>
</html>
"""

@router.get("/ui", response_class=HTMLResponse, summary="Interactive Multi-Image Upload UI")
async def upload_ui():
    """Serves an intuitive HTML upload interface allowing single-dialog multi-image selection up to 50 photos."""
    return HTMLResponse(content=HTML_PAGE)
