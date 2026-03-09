"""Stealth-script construction isolated from browser lifecycle concerns."""

from __future__ import annotations

from curlwright.runtime import ensure_supported_python

ensure_supported_python()


def chrome_major_version(user_agent: str) -> str:
    """Extract the Chrome major version from the configured user agent."""
    marker = "Chrome/"
    if marker not in user_agent:
        return "124"
    version = user_agent.split(marker, 1)[1].split(".", 1)[0]
    return version or "124"


def build_browser_init_script(user_agent: str) -> str:
    """Build the native anti-detection script injected into every page."""
    chrome_major = chrome_major_version(user_agent)
    return f"""
            // Override navigator.webdriver - delete rather than set false for better evasion
            delete Object.getPrototypeOf(navigator).webdriver;
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined,
                configurable: true,
            }});

            Object.defineProperty(navigator, 'platform', {{
                get: () => 'Win32',
            }});

            Object.defineProperty(navigator, 'maxTouchPoints', {{
                get: () => 0,
            }});

            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => 8,
            }});

            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => 8,
            }});

            Object.defineProperty(navigator, 'vendor', {{
                get: () => 'Google Inc.',
            }});

            Object.defineProperty(navigator, 'pdfViewerEnabled', {{
                get: () => true,
            }});

            window.chrome = {{
                runtime: {{
                    connect: function() {{}},
                    sendMessage: function() {{}},
                    onMessage: {{ addListener: function() {{}} }},
                    onConnect: {{ addListener: function() {{}} }},
                    id: undefined,
                }},
                app: {{
                    isInstalled: false,
                    InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
                    RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }},
                    getDetails: function() {{ return null; }},
                    getIsInstalled: function() {{ return false; }},
                }},
                csi: function() {{ return {{}}; }},
                loadTimes: function() {{
                    return {{
                        commitLoadTime: Date.now() / 1000 - Math.random() * 2,
                        connectionInfo: 'h2',
                        finishDocumentLoadTime: Date.now() / 1000 - Math.random(),
                        finishLoadTime: Date.now() / 1000 - Math.random() * 0.5,
                        firstPaintAfterLoadTime: 0,
                        firstPaintTime: Date.now() / 1000 - Math.random() * 1.5,
                        navigationType: 'Other',
                        npnNegotiatedProtocol: 'h2',
                        requestTime: Date.now() / 1000 - Math.random() * 3,
                        startLoadTime: Date.now() / 1000 - Math.random() * 2.5,
                        wasAlternateProtocolAvailable: false,
                        wasFetchedViaSpdy: true,
                        wasNpnNegotiated: true,
                    }};
                }},
            }};

            Object.defineProperty(navigator, 'userAgentData', {{
                get: () => ({{
                    brands: [
                        {{ brand: 'Chromium', version: '{chrome_major}' }},
                        {{ brand: 'Google Chrome', version: '{chrome_major}' }},
                        {{ brand: 'Not-A.Brand', version: '8' }},
                    ],
                    mobile: false,
                    platform: 'Windows',
                    getHighEntropyValues: async (hints) => ({{
                        architecture: 'x86',
                        bitness: '64',
                        brands: [
                            {{ brand: 'Chromium', version: '{chrome_major}' }},
                            {{ brand: 'Google Chrome', version: '{chrome_major}' }},
                            {{ brand: 'Not-A.Brand', version: '8' }},
                        ],
                        fullVersionList: [
                            {{ brand: 'Chromium', version: '{chrome_major}.0.6998.89' }},
                            {{ brand: 'Google Chrome', version: '{chrome_major}.0.6998.89' }},
                            {{ brand: 'Not-A.Brand', version: '8.0.0.0' }},
                        ],
                        mobile: false,
                        model: '',
                        platform: 'Windows',
                        platformVersion: '15.0.0',
                        uaFullVersion: '{chrome_major}.0.6998.89',
                        wow64: false,
                    }}),
                    toJSON: function() {{
                        return {{
                            brands: this.brands,
                            mobile: this.mobile,
                            platform: this.platform,
                        }};
                    }},
                }}),
            }});

            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => {{
                if (parameters.name === 'notifications') {{
                    return Promise.resolve({{ state: Notification.permission, onchange: null }});
                }}
                return originalQuery.call(navigator.permissions, parameters);
            }};

            const mockPlugins = {{
                0: {{
                    name: 'PDF Viewer',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 2,
                    0: {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
                    1: {{ type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
                }},
                1: {{
                    name: 'Chrome PDF Viewer',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 2,
                    0: {{ type: 'application/pdf', suffixes: 'pdf', description: '' }},
                    1: {{ type: 'text/pdf', suffixes: 'pdf', description: '' }},
                }},
                2: {{
                    name: 'Chromium PDF Viewer',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 2,
                    0: {{ type: 'application/pdf', suffixes: 'pdf', description: '' }},
                    1: {{ type: 'text/pdf', suffixes: 'pdf', description: '' }},
                }},
                3: {{
                    name: 'Microsoft Edge PDF Viewer',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 2,
                    0: {{ type: 'application/pdf', suffixes: 'pdf', description: '' }},
                    1: {{ type: 'text/pdf', suffixes: 'pdf', description: '' }},
                }},
                4: {{
                    name: 'WebKit built-in PDF',
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 2,
                    0: {{ type: 'application/pdf', suffixes: 'pdf', description: '' }},
                    1: {{ type: 'text/pdf', suffixes: 'pdf', description: '' }},
                }},
                length: 5,
                item: function(index) {{ return this[index]; }},
                namedItem: function(name) {{
                    for (let i = 0; i < this.length; i++) {{
                        if (this[i].name === name) return this[i];
                    }}
                    return null;
                }},
                refresh: function() {{}},
            }};
            Object.defineProperty(navigator, 'plugins', {{
                get: () => mockPlugins,
            }});

            const mockMimeTypes = {{
                0: {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: mockPlugins[0] }},
                1: {{ type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: mockPlugins[0] }},
                length: 2,
                item: function(index) {{ return this[index]; }},
                namedItem: function(name) {{
                    for (let i = 0; i < this.length; i++) {{
                        if (this[i].type === name) return this[i];
                    }}
                    return null;
                }},
            }};
            Object.defineProperty(navigator, 'mimeTypes', {{
                get: () => mockMimeTypes,
            }});

            Object.defineProperty(navigator, 'languages', {{
                get: () => ['en-US', 'en'],
            }});

            Object.defineProperty(window, 'outerWidth', {{
                get: () => window.innerWidth,
            }});

            Object.defineProperty(window, 'outerHeight', {{
                get: () => window.innerHeight + 85,
            }});

            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return 'Google Inc. (NVIDIA)';
                if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter.call(this, parameter);
            }};

            if (window.WebGL2RenderingContext) {{
                const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
                    if (parameter === 37445) return 'Google Inc. (NVIDIA)';
                    if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                    return getParameter2.call(this, parameter);
                }};
            }}

            if (window.Notification) {{
                Object.defineProperty(Notification, 'permission', {{
                    get: () => 'default',
                }});
            }}

            const originalFunction = Function.prototype.toString;
            Function.prototype.toString = function() {{
                if (this === window.chrome.loadTimes || this === window.chrome.csi) {{
                    return 'function loadTimes() {{ [native code] }}';
                }}
                return originalFunction.call(this);
            }};
        """
