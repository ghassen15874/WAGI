'use strict';

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const http = require('http');

/**
 * Production-grade backend runtime validator.
 *
 * Steps:
 *   1. Database seeding validation
 *   2. Smart server startup with stdout/stderr capture
 *   3. Log-based + TCP startup detection
 *   4. HTTP health-check (/, /api, /health)
 *   5. Structured error classification
 *   6. Graceful process teardown (SIGTERM → SIGKILL)
 *   7. Strict JSON output — never throws
 *
 * Output is backward-compatible with the previous structure:
 *   { status, crashed, errors[], stderr }
 * Extended fields:
 *   { server_started, port, health_check{reachable, status_code},
 *     errors[{type, message, raw}], logs{stdout, stderr} }
 */
async function runBackendValidation(targetDir) {
    const VALIDATION_PORT = String(process.env.BACKEND_VALIDATION_PORT || '3001');
    // ── Canonical result object (backward-compatible + extended) ──────
    const result = {
        status: 'success',
        crashed: false,
        server_started: false,
        port: null,
        health_check: {
            reachable: false,
            status_code: null
        },
        errors: [],        // now [{type, message, raw}] — legacy callers read .message
        logs: {
            stdout: '',
            stderr: ''
        },
        // Legacy field kept for backward compat (mirrors logs.stderr)
        get stderr() { return this.logs.stderr; },
        set stderr(v) { this.logs.stderr = v; }
    };

    // ── Helpers ───────────────────────────────────────────────────────

    /** Add a classified error. */
    function addError(type, message, raw = '') {
        result.status = 'error';
        result.errors.push({ type, message, raw: String(raw).slice(0, 500) });
    }

    /** Classify an error string into a structured type. */
    function classifyError(text) {
        if (/EADDRINUSE/i.test(text))
            return { type: 'PORT_ERROR', message: 'Port is already in use (EADDRINUSE)' };
        if (/ECONNREFUSED/i.test(text))
            return { type: 'PORT_ERROR', message: 'Connection refused — server not reachable' };
        if (/Cannot find module|MODULE_NOT_FOUND/i.test(text))
            return { type: 'DEPENDENCY_ERROR', message: 'Missing module dependency' };
        if (/SqliteError|SQLITE_|SQL error/i.test(text))
            return { type: 'DB_ERROR', message: 'Database/SQL error during startup' };
        if (/SyntaxError/i.test(text))
            return { type: 'RUNTIME_ERROR', message: 'JavaScript SyntaxError in server code' };
        if (/ReferenceError/i.test(text))
            return { type: 'RUNTIME_ERROR', message: 'ReferenceError — undefined variable in server code' };
        if (/UnhandledPromiseRejection|UnhandledPromiseRejectionWarning/i.test(text))
            return { type: 'RUNTIME_ERROR', message: 'Unhandled Promise Rejection during startup' };
        if (/TypeError/i.test(text))
            return { type: 'RUNTIME_ERROR', message: 'TypeError in server code' };
        return null;
    }

    /** Extract port number from a log line. */
    function extractPort(text) {
        const match = text.match(/(?:port|listening on|running on)[^\d]*(\d{4,5})/i)
            || text.match(/:(\d{4,5})/);
        if (match) {
            const p = parseInt(match[1], 10);
            if (p > 1024 && p < 65535) return p;
        }
        return null;
    }

    /** TCP probe — is the port open? */
    function isPortOpen(port, timeout = 2000) {
        return new Promise(resolve => {
            const socket = new net.Socket();
            let resolved = false;
            const done = (val) => { if (!resolved) { resolved = true; socket.destroy(); resolve(val); } };
            socket.setTimeout(timeout);
            socket.once('connect', () => done(true));
            socket.once('timeout', () => done(false));
            socket.once('error', () => done(false));
            socket.connect(port, '127.0.0.1');
        });
    }

    /** HTTP GET with a hard timeout. Returns { status_code } or null on failure. */
    function httpGet(url, timeout = 2000) {
        return new Promise(resolve => {
            let resolved = false;
            const done = (val) => { if (!resolved) { resolved = true; resolve(val); } };
            try {
                const req = http.get(url, { timeout }, (res) => {
                    res.resume(); // drain response
                    done({ status_code: res.statusCode });
                });
                req.on('error', () => done(null));
                req.on('timeout', () => { req.destroy(); done(null); });
                setTimeout(() => { req.destroy(); done(null); }, timeout + 500);
            } catch (_) {
                done(null);
            }
        });
    }

    /** Kill a process gracefully: SIGTERM then SIGKILL after 1 s. */
    function killProcess(proc) {
        if (!proc || proc.killed) return;
        try { proc.kill('SIGTERM'); } catch (_) { }
        setTimeout(() => {
            try { if (!proc.killed) proc.kill('SIGKILL'); } catch (_) { }
        }, 1000);
    }

    /** Emit the final JSON result (only call once). */
    function finish() {
        // Ensure legacy callers get a plain errors[] they can iterate
        // Make sure the result is serialisable (remove getter/setter)
        const out = {
            status: result.status,
            crashed: result.crashed,
            server_started: result.server_started,
            port: result.port,
            health_check: result.health_check,
            errors: result.errors,
            logs: result.logs,
            stderr: result.logs.stderr   // legacy compat
        };
        process.stdout.write(JSON.stringify(out) + '\n');
    }

    // ─────────────────────────────────────────────────────────────────
    // STEP 1 — DATABASE SEEDING
    // ─────────────────────────────────────────────────────────────────
    const seedPath = path.join(targetDir, 'server', 'db', 'seed.js');
    if (fs.existsSync(seedPath)) {
        try {
            execSync('node server/db/seed.js', {
                cwd: targetDir,
                stdio: 'pipe',
                timeout: 15000
            });
        } catch (err) {
            const raw = [
                err.stderr ? err.stderr.toString() : '',
                err.stdout ? err.stdout.toString() : '',
                err.message || ''
            ].join('\n');

            result.crashed = true;
            result.logs.stderr += raw;

            const classified = classifyError(raw);
            if (classified) {
                addError(classified.type, `Seed failed: ${classified.message}`, raw);
            } else {
                addError('DB_ERROR', 'Database seeding failed (schema mismatch or syntax error)', raw);
            }

            finish();
            return;
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // STEP 2 — SMART SERVER STARTUP
    // ─────────────────────────────────────────────────────────────────
    const STARTUP_TIMEOUT_MS = 8000;    // max wait for server to boot
    const STARTUP_SIGNALS = ['listening', 'server started', 'localhost', 'running on port', 'ready'];
    const START_CANDIDATES = [
        'npm run server',
        'node --import tsx server/index.ts',
        'npx tsx server/index.ts',
        './node_modules/.bin/tsx server/index.ts',
    ];

    let devProcess = null;
    let processExited = false;
    let exitCode = null;
    let detectedPort = null;

    try {
        devProcess = spawn('sh', ['-lc', START_CANDIDATES.join(' || ')], {
            cwd: targetDir,
            env: { ...process.env, FORCE_COLOR: '0', PORT: VALIDATION_PORT }
        });
    } catch (spawnErr) {
        addError('RUNTIME_ERROR', `Failed to spawn server process: ${spawnErr.message}`, spawnErr.message);
        finish();
        return;
    }

    devProcess.stdout.on('data', data => {
        const chunk = data.toString();
        result.logs.stdout += chunk;
        // Try to extract port from stdout in real time
        if (!detectedPort) detectedPort = extractPort(chunk);
    });

    devProcess.stderr.on('data', data => {
        const chunk = data.toString();
        result.logs.stderr += chunk;
        if (!detectedPort) detectedPort = extractPort(chunk);
    });

    devProcess.on('exit', (code) => {
        processExited = true;
        exitCode = code;
    });

    // ─────────────────────────────────────────────────────────────────
    // STEP 3 — DETECT REAL STARTUP (logs + TCP)
    // ─────────────────────────────────────────────────────────────────

    /** Poll until a startup signal appears in the logs or timeout. */
    async function waitForStartup() {
        const deadline = Date.now() + STARTUP_TIMEOUT_MS;
        while (Date.now() < deadline) {
            if (processExited) break; // crashed before signalling ready

            const combined = (result.logs.stdout + result.logs.stderr).toLowerCase();
            const signalled = STARTUP_SIGNALS.some(s => combined.includes(s));

            if (!detectedPort) {
                detectedPort = extractPort(result.logs.stdout + result.logs.stderr);
            }

            if (signalled && detectedPort) break; // best-case: signal + port known
            if (signalled) break;                 // signal seen, port check below

            await new Promise(r => setTimeout(r, 300));
        }
    }

    await waitForStartup();

    // If process already exited with non-zero → mark crashed
    if (processExited && exitCode !== 0) {
        result.crashed = true;
        addError('RUNTIME_ERROR', `Server crashed on boot with exit code ${exitCode}`,
            result.logs.stderr.slice(-800));
    }

    // TCP port verification
    const FALLBACK_PORTS = [3001, 3002, 5000, 8000, 8080];
    const portsToCheck = detectedPort
        ? [detectedPort, ...FALLBACK_PORTS.filter(p => p !== detectedPort)]
        : FALLBACK_PORTS;

    for (const p of portsToCheck) {
        const open = await isPortOpen(p);
        if (open) {
            result.server_started = true;
            result.port = p;
            break;
        }
        if (result.port) break; // already found
    }

    // If log-signalled but port not open (partial startup)
    if (!result.server_started) {
        if (!processExited) {
            // Process still alive but port not bound → likely still booting or silent fail
            addError('RUNTIME_ERROR', 'Server process is running but no open port detected', '');
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // STEP 4 — HTTP HEALTH CHECK
    // ─────────────────────────────────────────────────────────────────
    if (result.server_started && result.port) {
        const base = `http://127.0.0.1:${result.port}`;
        const endpoints = ['/api/health', '/', '/api', '/health'];

        for (const ep of endpoints) {
            const res = await httpGet(base + ep);
            if (res) {
                result.health_check.reachable = true;
                result.health_check.status_code = res.status_code;
                break; // first reachable endpoint is enough
            }
        }

        if (!result.health_check.reachable) {
            addError('PORT_ERROR',
                `Server port ${result.port} is open but HTTP requests are not answered`,
                `Tested: ${endpoints.join(', ')}`);
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // STEP 5 — DEEP ERROR CLASSIFICATION from captured stderr/stdout
    // ─────────────────────────────────────────────────────────────────
    const fullLog = result.logs.stdout + result.logs.stderr;

    const errorPatterns = [
        { pattern: /EADDRINUSE/, type: 'PORT_ERROR', message: 'Port is already in use (EADDRINUSE)' },
        { pattern: /ECONNREFUSED/, type: 'PORT_ERROR', message: 'Connection refused — server not reachable' },
        { pattern: /Cannot find module|MODULE_NOT_FOUND/, type: 'DEPENDENCY_ERROR', message: 'Missing module dependency' },
        { pattern: /SqliteError|SQLITE_|SQL error/i, type: 'DB_ERROR', message: 'Database/SQL error during startup' },
        { pattern: /SyntaxError/, type: 'RUNTIME_ERROR', message: 'SyntaxError in server code' },
        { pattern: /ReferenceError/, type: 'RUNTIME_ERROR', message: 'ReferenceError — undefined variable' },
        { pattern: /UnhandledPromiseRejection/, type: 'RUNTIME_ERROR', message: 'Unhandled Promise Rejection' },
        { pattern: /TypeError/, type: 'RUNTIME_ERROR', message: 'TypeError in server code' },
    ];

    // Avoid duplicating errors already added
    const existingMessages = new Set(result.errors.map(e => e.type));

    for (const { pattern, type, message } of errorPatterns) {
        if (pattern.test(fullLog) && !existingMessages.has(type)) {
            const matchLine = fullLog.split('\n').find(l => pattern.test(l)) || '';
            addError(type, message, matchLine.trim().slice(0, 300));
            existingMessages.add(type);
        }
    }

    // Mark crashed if any CRITICAL errors and server never started
    if (!result.server_started && result.errors.length > 0) {
        result.crashed = true;
    }

    // ─────────────────────────────────────────────────────────────────
    // STEP 6 — GRACEFUL PROCESS TEARDOWN
    // ─────────────────────────────────────────────────────────────────
    killProcess(devProcess);

    // ─────────────────────────────────────────────────────────────────
    // STEP 7 — OUTPUT
    // ─────────────────────────────────────────────────────────────────
    finish();
    // Allow async kill timers to resolve before hard exit
    setTimeout(() => process.exit(0), 1200);
}

// ── Entry point ───────────────────────────────────────────────────────
const targetDir = process.argv[2] || process.cwd();

runBackendValidation(targetDir).catch(err => {
    // Last-resort catch — must never surface as plain text
    process.stdout.write(JSON.stringify({
        status: 'error',
        crashed: true,
        server_started: false,
        port: null,
        health_check: { reachable: false, status_code: null },
        errors: [{ type: 'UNKNOWN', message: 'Validator itself threw an unexpected error', raw: String(err) }],
        logs: { stdout: '', stderr: String(err) },
        stderr: String(err)
    }) + '\n');
    process.exit(1);
});
