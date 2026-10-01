"""
src/api/ui.py — Interactive Web Upload Interface.
Allows users to select and upload multiple images at once via a single file picker or drag-and-drop.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Visual Search — Multi-Image Upload</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem 1rem; display: flex; justify-content: center; }
    .container { max-width: 720px; width: 100%; background: #1e293b; border-radius: 12px; padding: 2rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #38bdf8; }
    p.subtitle { font-size: 0.875rem; color: #94a3b8; margin-bottom: 1.5rem; }
    .drop-zone { border: 2px dashed #38bdf8; border-radius: 8px; padding: 2.5rem 1.5rem; text-align: center; cursor: pointer; transition: background 0.2s; background: #0f172a80; }
    .drop-zone:hover, .drop-zone.dragover { background: #1e3a5f; }
    .drop-zone input { display: none; }
    .btn { background: #0284c7; color: white; border: none; border-radius: 6px; padding: 0.75rem 1.5rem; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s; width: 100%; margin-top: 1.5rem; }
    .btn:hover { background: #0369a1; }
    .btn:disabled { background: #475569; cursor: not-allowed; }
    .form-group { margin-top: 1rem; }
    label { display: block; font-size: 0.875rem; font-weight: 500; margin-bottom: 0.4rem; color: #cbd5e1; }
    input[type="text"] { width: 100%; padding: 0.6rem 0.8rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: white; font-size: 0.95rem; }
    .checkbox-group { display: flex; align-items: center; gap: 0.5rem; margin-top: 1rem; font-size: 0.875rem; }
    .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 0.75rem; margin-top: 1.25rem; max-height: 260px; overflow-y: auto; padding: 0.5rem; background: #0f172a; border-radius: 6px; }
    .preview-card { position: relative; border-radius: 6px; overflow: hidden; height: 100px; background: #334155; }
    .preview-card img { width: 100%; height: 100%; object-fit: cover; }
    .progress-bar { width: 100%; height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 1rem; display: none; }
    .progress-fill { height: 100%; background: #38bdf8; width: 0%; transition: width 0.2s; }
    .result-box { margin-top: 1.5rem; padding: 1rem; background: #0f172a; border-radius: 6px; font-family: monospace; font-size: 0.85rem; display: none; white-space: pre-wrap; word-break: break-all; max-height: 250px; overflow-y: auto; border: 1px solid #334155; }
    .badge { display: inline-block; background: #0369a1; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; margin-top: 0.5rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Multi-Image Visual Indexer</h1>
    <p class="subtitle">Select or drop multiple pictures simultaneously to index into local FAISS vector stores.</p>

    <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
      <svg width="48" height="48" fill="none" stroke="#38bdf8" stroke-width="2" viewBox="0 0 24 24" style="margin: 0 auto 0.5rem auto; display: block;"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
      <strong>Click to browse</strong> or drag & drop multiple images
      <div id="fileCount" class="badge" style="display:none">0 files selected</div>
      <input type="file" id="fileInput" multiple accept="image/*" onchange="handleFiles(this.files)">
    </div>

    <div class="preview-grid" id="previewGrid" style="display:none"></div>

    <div class="form-group">
      <label for="folderInput">Category / Folder Name</label>
      <input type="text" id="folderInput" value="general" placeholder="e.g. vacation, wedding, products">
    </div>

    <div class="form-group">
      <label for="cldInput">Cloudinary URL (Optional — defaults to .env)</label>
      <input type="password" id="cldInput" placeholder="cloudinary://api_key:api_secret@cloud_name">
    </div>

    <div class="checkbox-group">
      <input type="checkbox" id="detectFaces" checked>
      <label for="detectFaces" style="margin-bottom:0">Detect & Index Faces (ArcFace + AdaFace)</label>
    </div>

    <div class="checkbox-group">
      <input type="checkbox" id="asyncMode">
      <label for="asyncMode" style="margin-bottom:0">Async Queue Mode (Background processing)</label>
    </div>

    <div class="progress-bar" id="progressBar">
      <div class="progress-fill" id="progressFill"></div>
    </div>

    <button class="btn" id="uploadBtn" onclick="uploadImages()" disabled>Upload Images</button>

    <div class="result-box" id="resultBox"></div>
  </div>

  <script>
    let selectedFiles = [];
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const previewGrid = document.getElementById('previewGrid');
    const fileCount = document.getElementById('fileCount');
    const uploadBtn = document.getElementById('uploadBtn');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
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
      selectedFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
      fileCount.textContent = `${selectedFiles.length} images selected`;
      fileCount.style.display = 'inline-block';
      uploadBtn.disabled = selectedFiles.length === 0;
      uploadBtn.textContent = `Upload ${selectedFiles.length} Images`;

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
      const detectFaces = document.getElementById('detectFaces').checked;
      const asyncMode = document.getElementById('asyncMode').checked;

      uploadBtn.disabled = true;
      uploadBtn.textContent = 'Uploading & Indexing...';
      progressBar.style.display = 'block';
      progressFill.style.width = '30%';
      resultBox.style.display = 'none';

      const formData = new FormData();
      formData.append('folder_name', folder);
      formData.append('detect_faces', detectFaces);

      const cld = document.getElementById('cldInput').value.trim();
      if (cld) {
        formData.append('cloudinary_url', cld);
        localStorage.setItem('cld_url', cld);
      }

      selectedFiles.forEach(f => {
        formData.append('files', f);
      });

      const url = asyncMode ? '/api/upload?async=true' : '/api/upload';

      try {
        progressFill.style.width = '60%';
        const response = await fetch(url, {
          method: 'POST',
          body: formData,
        });

        progressFill.style.width = '100%';
        resultBox.style.display = 'block';

        if (response.ok && data.job_id) {
          uploadBtn.textContent = 'AI Processing in Background...';
          resultBox.textContent = `Upload successful! Job ID: ${data.job_id}\nPolling background AI processing & FAISS indexing...\n\nUploaded URLs:\n${(data.urls || []).join('\n')}`;

          const interval = setInterval(async () => {
            try {
              const pollRes = await fetch(`/api/jobs/${data.job_id}`);
              const pollData = await pollRes.json();
              progressFill.style.width = `${pollData.progress_pct || 30}%`;
              resultBox.textContent = `Job ID: ${data.job_id}\nStatus: ${pollData.status.toUpperCase()} (${pollData.progress_pct || 0}%)\nStage: ${pollData.current_stage || 'processing'}\n\n--- Real-Time Execution Logs ---\n${(pollData.logs || []).join('\n')}\n\n--- Result ---\n${JSON.stringify(pollData.result || data.urls || {}, null, 2)}`;

              if (pollData.status === 'completed' || pollData.status === 'failed') {
                clearInterval(interval);
                uploadBtn.textContent = pollData.status === 'completed' ? 'Processing Complete!' : 'Processing Failed';
                setTimeout(() => {
                  uploadBtn.disabled = selectedFiles.length === 0;
                  uploadBtn.textContent = `Upload ${selectedFiles.length} Images`;
                }, 3000);
              }
            } catch (e) {
              clearInterval(interval);
            }
          }, 1000);
        } else if (response.ok) {
          resultBox.textContent = JSON.stringify(data, null, 2);
          uploadBtn.textContent = 'Upload Complete!';
          setTimeout(() => {
            uploadBtn.disabled = selectedFiles.length === 0;
            uploadBtn.textContent = `Upload ${selectedFiles.length} Images`;
          }, 3000);
        } else {
          resultBox.textContent = JSON.stringify(data, null, 2);
          uploadBtn.textContent = 'Upload Failed';
          setTimeout(() => {
            uploadBtn.disabled = selectedFiles.length === 0;
            uploadBtn.textContent = `Upload ${selectedFiles.length} Images`;
          }, 3000);
        }
      } catch (err) {
        resultBox.style.display = 'block';
        resultBox.textContent = 'Network error: ' + err.message;
        uploadBtn.textContent = 'Error';
      }
    }
    // Hydrate saved Cloudinary URL from previous sessions
    const savedCld = localStorage.getItem('cld_url');
    if (savedCld) document.getElementById('cldInput').value = savedCld;
  </script>
</body>
</html>
"""

@router.get("/upload-ui", response_class=HTMLResponse, summary="Interactive Multi-Image Upload UI")
@router.get("/ui", response_class=HTMLResponse, summary="Interactive Multi-Image Upload UI")
async def upload_ui():
    """Serves an intuitive HTML upload interface allowing single-dialog multi-image selection."""
    return HTMLResponse(content=HTML_PAGE)
