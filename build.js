const fs = require('fs');
const path = require('path');

console.log('[BUILD] Building Freelancer Command Center PWA...');

const rootDir = __dirname;
const publicDir = path.join(rootDir, 'public');

if (!fs.existsSync(publicDir)) {
  fs.mkdirSync(publicDir, { recursive: true });
}

// 1. Sync index.html -> public/index.html
const indexHtml = fs.readFileSync(path.join(rootDir, 'index.html'), 'utf-8');
fs.writeFileSync(path.join(publicDir, 'index.html'), indexHtml, 'utf-8');
console.log('✓ Synced index.html to public/index.html');

// 2. Sync manifest.json -> public/manifest.json
const manifestPath = path.join(rootDir, 'manifest.json');
let manifest = {
  name: "Homelab OS Command Center",
  short_name: "Homelab OS",
  description: "24/7 Hardware Freelance & Telemetry Command Center",
  start_url: "/",
  display: "standalone",
  background_color: "#000000",
  theme_color: "#000000",
  orientation: "portrait-primary",
  icons: [
    { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
    { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
    { src: "/icon.svg", sizes: "any", type: "image/svg+xml" }
  ]
};

if (fs.existsSync(manifestPath)) {
  manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
}
manifest.display = "standalone";
manifest.theme_color = "#000000";
manifest.background_color = "#000000";

fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
fs.writeFileSync(path.join(publicDir, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf-8');
console.log('✓ Verified & synced manifest.json (display: standalone, theme_color: #000000)');

// 3. Verify zero homework remnants in build
if (indexHtml.toLowerCase().includes('homework')) {
  console.error('❌ Build failed: found homework reference in index.html');
  process.exit(1);
}
console.log('✓ Verified 0 homework references');

console.log('[BUILD] Build complete. Ready for Vercel deployment.');
