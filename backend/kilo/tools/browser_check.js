const { chromium } = require('playwright');

/**
 * Validates the frontend runtime using a headless browser.
 * Captures console errors, checks for blank pages, and detects basic UI features.
 */
async function runBrowserCheck() {
    const result = {
        status: 'success',
        blank_page: false,
        root_empty: false,
        console_errors: [],
        runtime_errors: [],
        network_errors: [],
        ui: {
            hasNavbar: false,
            hasLogin: false,
            hasComments: false,
            hasContent: false
        },
        dom_snapshot: ''  // Filled after page load for semantic analysis
    };

    let browser;
    try {
        browser = await chromium.launch({ headless: true });
        const page = await browser.newPage();

        // Capture console errors
        page.on('console', msg => {
            if (msg.type() === 'error') {
                result.console_errors.push(msg.text());
            }
        });

        // Capture unhandled page errors (e.g. React crashes)
        page.on('pageerror', err => {
            result.runtime_errors.push(err.message);
        });

        // Capture network failures
        page.on('requestfailed', request => {
            result.network_errors.push(`${request.url()} - ${request.failure().errorText}`);
        });

        // Capture HTTP error responses like 404/500. These are especially
        // important for API calls because they don't trigger requestfailed.
        page.on('response', response => {
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

        // Give a short grace period for animations/renders
        await page.waitForTimeout(1000);

        // Evaluate the page state
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

        // Capture full DOM snapshot for semantic analysis (capped for safety)
        try {
            const fullHtml = await page.content();
            result.dom_snapshot = fullHtml.slice(0, 8000);
        } catch (snapErr) {
            // Non-fatal: semantic layer will simply not run
            result.dom_snapshot = '';
        }

        // Check for "Error" in DOM text if root is not entirely empty
        if (!result.root_empty) {
            const bodyText = await page.evaluate(() => document.body.innerText);
            // Basic heuristic for unhandled react error overlays
            if (bodyText.includes('Unhandled Rejection') || (bodyText.includes('Error:') && bodyText.includes('at '))) {
                result.runtime_errors.push("Detected Error stack trace in DOM.");
            }
        }

        if (
            result.root_empty ||
            result.blank_page ||
            result.console_errors.length > 0 ||
            result.runtime_errors.length > 0 ||
            result.network_errors.length > 0
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

    // Strictly output JSON to stdout
    console.log(JSON.stringify(result));
}

runBrowserCheck();
