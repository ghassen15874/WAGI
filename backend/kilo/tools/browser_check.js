const { chromium } = require('playwright');

function parseJsonEnv(name, fallback) {
    const raw = String(process.env[name] || '').trim();
    if (!raw) return fallback;
    try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
    } catch (_) {}
    return fallback;
}

function normalizeRoutePath(path) {
    const raw = String(path || '').trim();
    if (!raw) return '';
    if (raw.startsWith('http://') || raw.startsWith('https://')) {
        try {
            const u = new URL(raw);
            return `${u.pathname}${u.search || ''}${u.hash || ''}`;
        } catch (_) {
            return '';
        }
    }
    if (!raw.startsWith('/')) return '';
    return raw;
}

function shouldTreatAsInternalRoute(path) {
    const normalized = normalizeRoutePath(path);
    if (!normalized) return false;
    if (normalized.startsWith('/api')) return false;
    if (normalized.startsWith('/#')) return false;
    return true;
}

/**
 * Validates the frontend runtime using a headless browser.
 * Captures console/runtime/network errors and runs smoke checks:
 * - root route + linked routes
 * - key API endpoints
 * - theme toggle interaction
 */
async function runBrowserCheck() {
    const requiredRoutes = parseJsonEnv('REQUIRED_ROUTES_JSON', ['/'])
        .map(normalizeRoutePath)
        .filter(shouldTreatAsInternalRoute);
    const requiredApi = parseJsonEnv('REQUIRED_API_JSON', ['/api/health'])
        .map((item) => String(item || '').trim())
        .filter((item) => item.startsWith('/api/'));
    const requireThemeToggle = ['1', 'true', 'yes', 'on'].includes(
        String(process.env.REQUIRE_THEME_TOGGLE || '').trim().toLowerCase()
    );
    const themeStorageKey = String(process.env.THEME_STORAGE_KEY || 'theme').trim() || 'theme';

    const result = {
        status: 'success',
        blank_page: false,
        root_empty: false,
        console_errors: [],
        runtime_errors: [],
        network_errors: [],
        errors: [],
        ui: {
            hasNavbar: false,
            hasLogin: false,
            hasComments: false,
            hasContent: false
        },
        smoke: {
            checked_routes: [],
            linked_routes: [],
            route_errors: [],
            api_errors: [],
            theme_errors: []
        },
        dom_snapshot: ''
    };

    let browser;
    try {
        browser = await chromium.launch({ headless: true });
        const page = await browser.newPage();

        page.on('console', (msg) => {
            if (msg.type() === 'error') {
                result.console_errors.push(msg.text());
            }
        });

        page.on('pageerror', (err) => {
            result.runtime_errors.push(err.message);
        });

        page.on('requestfailed', (request) => {
            result.network_errors.push(`${request.url()} - ${request.failure().errorText}`);
        });

        page.on('response', (response) => {
            const status = response.status();
            if (status >= 400) {
                result.network_errors.push(`HTTP ${status} ${response.url()}`);
            }
        });

        const configuredPort = String(process.env.FRONTEND_PREVIEW_PORT || '3000');
        const configuredUrl = process.env.FRONTEND_PREVIEW_URL
            ? String(process.env.FRONTEND_PREVIEW_URL).trim()
            : '';
        const candidateUrls = [
            configuredUrl,
            `http://127.0.0.1:${configuredPort}`,
            `http://localhost:${configuredPort}`,
            'http://127.0.0.1:3000',
            'http://localhost:3000',
            'http://127.0.0.1:5173',
            'http://localhost:5173',
        ].filter(Boolean);

        let lastNavError = null;
        let resolvedUrl = null;
        for (const url of candidateUrls) {
            try {
                await page.goto(url, { waitUntil: 'networkidle', timeout: 8000 });
                resolvedUrl = url;
                break;
            } catch (navErr) {
                lastNavError = navErr;
            }
        }

        if (!resolvedUrl) {
            throw lastNavError || new Error('Unable to reach preview server');
        }

        const baseOrigin = new URL(resolvedUrl).origin;
        await page.waitForTimeout(800);

        const domState = await page.evaluate(() => {
            const rootHtml = document.getElementById('root')?.innerHTML || '';
            const bodyText = document.body.innerText || '';
            return {
                rootEmpty: rootHtml.trim() === '',
                bodyLength: bodyText.length,
                hasNavbar: !!document.querySelector('nav') || !!document.querySelector('header'),
                hasLogin: !!document.querySelector('input[type="password"]'),
                hasComments: !!document.querySelector('.comment') || !!document.querySelector('textarea'),
                hasContent: bodyText.length > 50
            };
        });

        result.root_empty = domState.rootEmpty;
        result.blank_page = domState.bodyLength < 50;
        result.ui.hasNavbar = domState.hasNavbar;
        result.ui.hasLogin = domState.hasLogin;
        result.ui.hasComments = domState.hasComments;
        result.ui.hasContent = domState.hasContent;

        try {
            const fullHtml = await page.content();
            result.dom_snapshot = fullHtml.slice(0, 12000);
        } catch (_) {
            result.dom_snapshot = '';
        }

        const linkedRoutes = await page.evaluate(() => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            const normalized = links
                .map((link) => link.getAttribute('href') || '')
                .map((href) => String(href || '').trim())
                .filter(Boolean)
                .map((href) => {
                    if (href.startsWith('http://') || href.startsWith('https://')) {
                        try {
                            const url = new URL(href);
                            return url.pathname || '/';
                        } catch (_) {
                            return '';
                        }
                    }
                    return href;
                })
                .map((href) => href.split('#')[0])
                .map((href) => href.split('?')[0])
                .filter((href) => href.startsWith('/'))
                .filter((href) => !href.startsWith('/api'))
                .filter((href) => href !== '/');

            const deduped = [];
            const seen = new Set();
            for (const route of normalized) {
                if (!route || seen.has(route)) continue;
                seen.add(route);
                deduped.push(route);
            }
            return deduped.slice(0, 5);
        });
        result.smoke.linked_routes = linkedRoutes;

        const routeCandidates = [];
        const seenRouteCandidates = new Set();
        for (const route of [...requiredRoutes, ...linkedRoutes]) {
            const normalized = normalizeRoutePath(route);
            if (!shouldTreatAsInternalRoute(normalized)) continue;
            if (seenRouteCandidates.has(normalized)) continue;
            seenRouteCandidates.add(normalized);
            routeCandidates.push(normalized);
        }
        if (routeCandidates.length === 0) {
            routeCandidates.push('/');
        }

        for (const route of routeCandidates) {
            const targetUrl = new URL(route, baseOrigin).toString();
            try {
                const response = await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 8000 });
                await page.waitForTimeout(400);
                const routeState = await page.evaluate(() => {
                    const rootHtml = document.getElementById('root')?.innerHTML || '';
                    const bodyText = String(document.body?.innerText || '').trim();
                    return {
                        rootEmpty: rootHtml.trim() === '',
                        bodyLength: bodyText.length
                    };
                });
                result.smoke.checked_routes.push(route);
                if ((response && response.status() >= 400) || routeState.rootEmpty || routeState.bodyLength < 40) {
                    result.smoke.route_errors.push(
                        `Route '${route}' did not render correctly (status=${response ? response.status() : 'n/a'}, body=${routeState.bodyLength}).`
                    );
                }
            } catch (routeErr) {
                result.smoke.route_errors.push(`Route '${route}' navigation failed: ${routeErr.message}`);
            }
        }

        for (const apiPath of requiredApi) {
            const apiUrl = new URL(apiPath, baseOrigin).toString();
            try {
                const apiResponse = await page.request.get(apiUrl, { timeout: 8000 });
                if (!apiResponse || apiResponse.status() >= 400) {
                    result.smoke.api_errors.push(
                        `API '${apiPath}' returned status ${apiResponse ? apiResponse.status() : 'n/a'}.`
                    );
                }
            } catch (apiErr) {
                result.smoke.api_errors.push(`API '${apiPath}' request failed: ${apiErr.message}`);
            }
        }

        if (requireThemeToggle) {
            try {
                await page.goto(new URL('/', baseOrigin).toString(), { waitUntil: 'networkidle', timeout: 8000 });
                await page.waitForTimeout(300);

                const themeState = await page.evaluate(async (storageKey) => {
                    const root = document.documentElement;
                    const beforeClass = String(root.className || '');
                    const beforeThemeAttr = String(root.getAttribute('data-theme') || '');
                    const beforeStorage = localStorage.getItem(storageKey);

                    const candidates = Array.from(
                        document.querySelectorAll(
                            'button,[role="button"],input[type="checkbox"],label,[data-theme-toggle],[aria-label],[title]'
                        )
                    );
                    const toggle = candidates.find((node) => {
                        const text = [
                            String(node.getAttribute('aria-label') || ''),
                            String(node.getAttribute('title') || ''),
                            String(node.textContent || ''),
                            String(node.className || ''),
                            String(node.getAttribute('data-theme-toggle') || '')
                        ].join(' ').toLowerCase();
                        return /theme|dark|light|mode/.test(text);
                    });

                    if (!toggle) {
                        return {
                            toggleFound: false,
                            classChanged: false,
                            storageChanged: false,
                            hasStoredValue: false
                        };
                    }

                    toggle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    if (toggle instanceof HTMLInputElement && toggle.type === 'checkbox') {
                        toggle.checked = !toggle.checked;
                        toggle.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    await new Promise((resolve) => setTimeout(resolve, 350));

                    const afterClass = String(root.className || '');
                    const afterThemeAttr = String(root.getAttribute('data-theme') || '');
                    const afterStorage = localStorage.getItem(storageKey);

                    return {
                        toggleFound: true,
                        classChanged: beforeClass !== afterClass || beforeThemeAttr !== afterThemeAttr,
                        storageChanged: beforeStorage !== afterStorage,
                        hasStoredValue: !!String(afterStorage || '').trim()
                    };
                }, themeStorageKey);

                if (!themeState.toggleFound) {
                    result.smoke.theme_errors.push('Theme toggle control was not found in the UI.');
                } else {
                    if (!themeState.classChanged) {
                        result.smoke.theme_errors.push('Theme toggle did not update document.documentElement theme state.');
                    }
                    if (!themeState.storageChanged || !themeState.hasStoredValue) {
                        result.smoke.theme_errors.push(
                            `Theme toggle did not persist preference to localStorage key '${themeStorageKey}'.`
                        );
                    }
                }
            } catch (themeErr) {
                result.smoke.theme_errors.push(`Theme smoke check failed: ${themeErr.message}`);
            }
        }

        if (!result.root_empty) {
            const bodyText = await page.evaluate(() => document.body.innerText);
            if (
                bodyText.includes('Unhandled Rejection') ||
                (bodyText.includes('Error:') && bodyText.includes('at '))
            ) {
                result.runtime_errors.push('Detected Error stack trace in DOM.');
            }
        }

        const smokeErrors = [
            ...result.smoke.route_errors,
            ...result.smoke.api_errors,
            ...result.smoke.theme_errors
        ];
        if (smokeErrors.length > 0) {
            result.errors.push(...smokeErrors);
        }

        if (
            result.root_empty ||
            result.blank_page ||
            result.console_errors.length > 0 ||
            result.runtime_errors.length > 0 ||
            result.network_errors.length > 0 ||
            result.errors.length > 0
        ) {
            result.status = 'error';
        }
    } catch (err) {
        result.status = 'error';
        result.runtime_errors.push(`Playwright execution failed: ${err.message}`);
    } finally {
        if (browser) {
            await browser.close();
        }
    }

    console.log(JSON.stringify(result));
}

runBrowserCheck();
