STEALTH_JS = r"""
// 1. إخفاء webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
delete Object.getPrototypeOf(navigator).webdriver;

// 2. اللغات والمنصة
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });

// 3. Plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ];
        plugins.refresh = () => {};
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (n) => plugins.find(p => p.name === n);
        return plugins;
    }
});

// 4. MimeTypes
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
        const mimes = [
            { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        ];
        mimes.item = (i) => mimes[i];
        mimes.namedItem = (n) => mimes.find(m => m.type === n);
        return mimes;
    }
});

// 5. WebGL
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.
