import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load environment variables from .env if present
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
  if (typeof process.loadEnvFile === 'function') {
    try {
      process.loadEnvFile(envPath);
    } catch (_) {}
  } else {
    const envContent = fs.readFileSync(envPath, 'utf8');
    for (const line of envContent.split('\n')) {
      const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
      if (match) {
        const key = match[1];
        let val = (match[2] || '').trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1);
        }
        if (!process.env[key]) process.env[key] = val;
      }
    }
  }
}

const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const BACKEND_URL = process.env.BACKEND_URL || process.env.VITE_API_URL || 'http://127.0.0.1:7860';

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.ts': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
};

const server = http.createServer((req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host}`);
  let pathname = decodeURIComponent(parsedUrl.pathname);

  // Handle API proxy to FastAPI if path starts with /api/
  if (pathname.startsWith('/api/')) {
    const backendTarget = new URL(pathname + parsedUrl.search, BACKEND_URL);
    const proxyReq = http.request(
      backendTarget,
      {
        method: req.method,
        headers: {
          ...req.headers,
          host: backendTarget.host,
        },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );

    proxyReq.on('error', () => {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          error: 'Backend unreachable',
          detail: `Could not connect to FastAPI at ${BACKEND_URL}. Ensure backend is running.`,
        })
      );
    });

    req.pipe(proxyReq);
    return;
  }

  // Normalize static file path
  let filePath = path.join(__dirname, pathname === '/' ? 'index.html' : pathname);

  // If path doesn't have an extension and is not a directory, try appending .html or fallback to index.html
  if (!fs.existsSync(filePath)) {
    if (fs.existsSync(filePath + '.html')) {
      filePath = filePath + '.html';
    } else if (fs.existsSync(path.join(filePath, 'index.html'))) {
      filePath = path.join(filePath, 'index.html');
    } else {
      // SPA Fallback for non-asset routes
      if (!path.extname(pathname)) {
        filePath = path.join(__dirname, 'index.html');
      }
    }
  }

  fs.stat(filePath, (err, stats) => {
    if (err || !stats.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(`404 Not Found: ${pathname}`);
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    res.writeHead(200, {
      'Content-Type': contentType,
      'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0',
      'Pragma': 'no-cache',
      'Expires': '0',
      'Access-Control-Allow-Origin': '*',
    });

    fs.createReadStream(filePath).pipe(res);
  });
});

let currentPort = Number(PORT);

server.on('listening', () => {
  const address = server.address();
  const actualPort = typeof address === 'object' && address ? address.port : currentPort;
  console.log(`\nVelunara Studio Dev Server running at:`);
  console.log(`   -> Local:   http://localhost:${actualPort}/`);
  console.log(`   -> Network: http://${HOST}:${actualPort}/`);
  console.log(`   -> Backend: ${BACKEND_URL}/api\n`);
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.warn(`Port ${currentPort} is occupied, trying port ${currentPort + 1}...`);
    currentPort += 1;
    startServer(currentPort);
  } else {
    console.error('Server error:', err);
  }
});

function startServer(port) {
  if (HOST === '0.0.0.0' || HOST === '::') {
    server.listen(port, '::');
  } else {
    server.listen(port, HOST);
  }
}

startServer(currentPort);
