import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const distDir = path.join(__dirname, 'dist');
const srcDir = path.join(__dirname, 'src');

console.log('Building Elementum Frontend for production...');

// Ensure clean dist directory
if (fs.existsSync(distDir)) {
  fs.rmSync(distDir, { recursive: true, force: true });
}
fs.mkdirSync(distDir, { recursive: true });

// Recursive copy helper
function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    if (!fs.existsSync(dest)) {
      fs.mkdirSync(dest, { recursive: true });
    }
    const entries = fs.readdirSync(src);
    for (const entry of entries) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
  } else {
    fs.copyFileSync(src, dest);
  }
}

// 1. Copy index.html
if (fs.existsSync(path.join(__dirname, 'index.html'))) {
  fs.copyFileSync(path.join(__dirname, 'index.html'), path.join(distDir, 'index.html'));
  console.log(' [OK] Copied index.html -> dist/index.html');
}

// 2. Copy src directory
if (fs.existsSync(srcDir)) {
  copyRecursive(srcDir, path.join(distDir, 'src'));
  console.log(' [OK] Copied src assets -> dist/src/');
}

// 3. Create production preview server helper or meta
const buildMeta = {
  name: 'velunara-web',
  version: '2.0.0',
  buildTime: new Date().toISOString(),
  environment: 'production',
};

fs.writeFileSync(path.join(distDir, 'build.json'), JSON.stringify(buildMeta, null, 2));

console.log('\nBuild complete! Production output ready in frontend/dist/\n');

