import { useEffect, useMemo, useRef, useState } from 'react'
import { WebContainer } from '@webcontainer/api'
import { ExternalLink, Loader2, RefreshCw } from 'lucide-react'

interface WebContainerPreviewProps {
    files: Record<string, string>
    sessionId: string | null
    generationStatus: 'idle' | 'generating' | 'done' | 'error'
    allowHostPreview?: boolean
}

type PreviewMode = 'host' | 'webcontainer'
type PreviewStatus =
    | 'idle'
    | 'checking-host'
    | 'host-running'
    | 'booting'
    | 'mounting'
    | 'installing'
    | 'starting'
    | 'running'
    | 'error'

const HOST_PREVIEW_URL = 'http://localhost:3000'
const HOST_PROBE_TIMEOUT_MS = 12000

export default function WebContainerPreview({
    files,
    sessionId,
    generationStatus,
    allowHostPreview = false,
}: WebContainerPreviewProps) {
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const wcRef = useRef<WebContainer | null>(null)
    const hasStartedWebContainerRef = useRef(false)

    const [mode, setMode] = useState<PreviewMode>('host')
    const [status, setStatus] = useState<PreviewStatus>('idle')
    const [statusMsg, setStatusMsg] = useState(generationStatus === 'generating' ? 'Initializing preview...' : 'Waiting for generated project...')
    const [iframeUrl, setIframeUrl] = useState(HOST_PREVIEW_URL)
    const [error, setError] = useState('')

    const fileCount = useMemo(() => Object.keys(files).length, [files])

    useEffect(() => {
        setMode('host')
        setStatus(generationStatus === 'idle' || !allowHostPreview ? 'idle' : 'checking-host')
        setStatusMsg(
            generationStatus === 'idle'
                ? 'Waiting for generated project...'
                : allowHostPreview
                    ? 'Checking host preview...'
                    : 'Preview paused for this chat. Click Run Project to start live preview.'
        )
        setIframeUrl(allowHostPreview ? HOST_PREVIEW_URL : '')
        setError('')
        hasStartedWebContainerRef.current = false
    }, [sessionId, generationStatus, allowHostPreview])

    useEffect(() => {
        let cancelled = false

        if (generationStatus === 'idle') {
            setMode('host')
            setStatus('idle')
            setStatusMsg('Waiting for generated project...')
            setIframeUrl(HOST_PREVIEW_URL)
            return () => {
                cancelled = true
            }
        }

        if (!allowHostPreview) {
            setMode('host')
            setStatus('idle')
            setStatusMsg('Preview paused for this chat. Click Run Project to start live preview.')
            setIframeUrl('')
            return () => {
                cancelled = true
            }
        }

        async function probeHostPreview() {
            setMode('host')
            setStatus('checking-host')
            setStatusMsg('Checking host preview...')
            setIframeUrl(HOST_PREVIEW_URL)

            const deadline = Date.now() + HOST_PROBE_TIMEOUT_MS
            while (!cancelled && Date.now() < deadline) {
                const ok = await canReachHostPreview(HOST_PREVIEW_URL)
                if (ok) {
                    if (cancelled) return
                    setMode('host')
                    setStatus('host-running')
                    setStatusMsg('Host preview running ✓')
                    return
                }
                await delay(1000)
            }

            if (!cancelled) {
                await ensureWebContainerFallback()
            }
        }

        probeHostPreview()

        return () => {
            cancelled = true
        }
    }, [generationStatus, sessionId, fileCount, allowHostPreview])

    useEffect(() => {
        if (
            mode === 'webcontainer'
            && wcRef.current
            && generationStatus === 'done'
            && fileCount > 0
            && (status === 'booting' || status === 'idle')
        ) {
            runProjectInWebContainer(wcRef.current, files)
        }
    }, [mode, generationStatus, fileCount, files, status])

    async function ensureWebContainerFallback() {
        if (hasStartedWebContainerRef.current) {
            return
        }
        hasStartedWebContainerRef.current = true
        setMode('webcontainer')

        try {
            let wc = wcRef.current
            if (!wc) {
                setStatus('booting')
                setStatusMsg('Host preview unavailable. Booting WebContainer fallback...')
                wc = await WebContainer.boot()
                wcRef.current = wc
                wc.on('server-ready', (_port, url) => {
                    setIframeUrl(url)
                    if (iframeRef.current) iframeRef.current.src = url
                    setStatus('running')
                    setStatusMsg('WebContainer fallback running ✓')
                })
                wc.on('error', (err: any) => {
                    setError(err?.message || 'WebContainer error')
                    setStatus('error')
                })
            }

            if (!fileCount || generationStatus !== 'done') {
                setStatus('booting')
                setStatusMsg('Waiting for generated files before starting WebContainer...')
                return
            }

            await runProjectInWebContainer(wc, files)
        } catch (e: any) {
            setError(
                e?.message?.includes('SharedArrayBuffer')
                    ? 'WebContainer fallback needs cross-origin isolation. Set VITE_ENABLE_CROSS_ORIGIN_ISOLATION=true if you want fallback mode.'
                    : (e?.message || 'Preview failed')
            )
            setStatus('error')
        }
    }

    async function runProjectInWebContainer(wc: WebContainer, projectFiles: Record<string, string>) {
        try {
            setStatus('mounting')
            setStatusMsg('Mounting project files into WebContainer...')

            const wcFiles: Record<string, any> = {}
            for (const [path, content] of Object.entries(projectFiles)) {
                const parts = path.split('/')
                let node: Record<string, any> = wcFiles
                for (let i = 0; i < parts.length - 1; i += 1) {
                    if (!node[parts[i]]) node[parts[i]] = { directory: {} }
                    node = node[parts[i]].directory
                }
                node[parts[parts.length - 1]] = { file: { contents: content } }
            }
            await wc.mount(wcFiles)

            setStatus('installing')
            setStatusMsg('Installing dependencies in WebContainer...')
            const installProc = await wc.spawn('npm', ['install'])
            const installExit = await installProc.exit
            if (installExit !== 0) {
                throw new Error('npm install failed in WebContainer')
            }

            setStatus('starting')
            setStatusMsg('Starting dev server in WebContainer...')
            await wc.spawn('npm', ['run', 'dev'])
        } catch (e: any) {
            setError(e?.message || 'WebContainer fallback failed')
            setStatus('error')
        }
    }

    const statusColors: Record<PreviewStatus, string> = {
        idle: '#64748b',
        'checking-host': '#f59e0b',
        'host-running': '#10b981',
        booting: '#6366f1',
        mounting: '#6366f1',
        installing: '#6366f1',
        starting: '#6366f1',
        running: '#10b981',
        error: '#ef4444',
    }

    const isLoading = ['checking-host', 'booting', 'mounting', 'installing', 'starting'].includes(status)
    const canRefresh = status === 'host-running' || status === 'running'

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--color-bg)' }}>
            <div
                style={{
                    padding: '8px 16px',
                    borderBottom: '1px solid var(--color-border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    background: 'var(--color-surface)',
                    minHeight: 40,
                }}
            >
                <div
                    style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: statusColors[status],
                        flexShrink: 0,
                    }}
                    className={status === 'host-running' || status === 'running' ? '' : 'animate-pulse'}
                />
                <span style={{ color: 'var(--color-text-muted)', fontSize: 12, flex: 1 }}>
                    {statusMsg}
                    {isLoading && (
                        <Loader2
                            size={12}
                            style={{
                                display: 'inline-block',
                                marginLeft: 6,
                                verticalAlign: 'middle',
                                animation: 'spin 1s linear infinite',
                            }}
                        />
                    )}
                </span>
                <span
                    style={{
                        fontSize: 11,
                        color: mode === 'host' ? 'var(--color-primary)' : 'var(--color-text-muted)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 999,
                        padding: '2px 8px',
                    }}
                >
                    {mode === 'host' ? 'iframe default' : 'webcontainer fallback'}
                </span>
                {iframeUrl && (
                    <a
                        href={iframeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                            color: 'var(--color-text-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                            fontSize: 12,
                            textDecoration: 'none',
                        }}
                    >
                        <ExternalLink size={12} />
                        Open
                    </a>
                )}
                {canRefresh && (
                    <button
                        onClick={() => {
                            if (iframeRef.current && iframeUrl) {
                                iframeRef.current.src = iframeUrl
                            }
                        }}
                        className="btn btn-text"
                        style={{ padding: 4, display: 'flex', alignItems: 'center' }}
                        title="Refresh"
                    >
                        <RefreshCw size={12} />
                    </button>
                )}
            </div>

            <div style={{ flex: 1, position: 'relative' }}>
                {status === 'error' ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: '100%',
                            gap: 16,
                            padding: 32,
                            textAlign: 'center',
                        }}
                    >
                        <div style={{ color: '#ef4444', fontSize: 40 }}>⚠️</div>
                        <div style={{ color: '#ef4444', fontWeight: 600 }}>Preview Error</div>
                        <div
                            style={{
                                color: 'var(--color-text-muted)',
                                fontSize: 12,
                                fontFamily: 'var(--font-mono)',
                                background: 'var(--color-surface2)',
                                padding: 12,
                                borderRadius: 8,
                                maxWidth: 460,
                            }}
                        >
                            {error}
                        </div>
                    </div>
                ) : status === 'idle' ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            height: '100%',
                            gap: 16,
                            color: 'var(--color-text-muted)',
                            background: 'var(--color-surface)',
                            padding: 32,
                        }}
                    >
                        <div 
                            style={{ 
                                fontSize: 48, 
                                opacity: 0.6,
                                background: 'var(--color-surface2)',
                                padding: 24,
                                borderRadius: 16,
                            }}
                        >
                            {generationStatus === 'generating' ? '⚙️' : '🖥️'}
                        </div>
                        <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-text)' }}>
                            {generationStatus === 'generating' ? 'Starting build...' : 'Live Preview'}
                        </div>
                        <div style={{ fontSize: 12, textAlign: 'center', maxWidth: 300, lineHeight: 1.6 }}>
                            {generationStatus === 'generating' 
                                ? 'The AI is generating your project. The preview will appear automatically once the build is ready.'
                                : 'The preview will appear here once generation starts. Start building to see your app come to life!'}
                        </div>
                        {generationStatus === 'generating' && (
                            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                                <div className="dot-pulse" style={{ width: 6, height: 6, background: 'var(--color-primary)', borderRadius: '50%' }} />
                                <div className="dot-pulse" style={{ width: 6, height: 6, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.2s' }} />
                                <div className="dot-pulse" style={{ width: 6, height: 6, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.4s' }} />
                            </div>
                        )}
                    </div>
                ) : (
                    <>
                        <iframe
                            ref={iframeRef}
                            id="preview-iframe"
                            title="Live Preview"
                            src={iframeUrl}
                            style={{
                                width: '100%',
                                height: '100%',
                                border: 'none',
                                background: 'white',
                                opacity: status === 'host-running' || status === 'running' ? 1 : 0.35,
                                transition: 'opacity 0.3s ease',
                            }}
                            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                        />
                        {isLoading && (
                            <div
                                style={{
                                    position: 'absolute',
                                    inset: 0,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: 16,
                                    background: 'rgba(10,10,15,0.7)',
                                    backdropFilter: 'blur(4px)',
                                }}
                            >
                                <Loader2
                                    size={32}
                                    color="var(--color-primary)"
                                    style={{ animation: 'spin 1s linear infinite' }}
                                />
                                <div style={{ color: 'var(--color-text)', fontWeight: 500 }}>
                                    {statusMsg}
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

function delay(ms: number) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms)
    })
}

async function canReachHostPreview(url: string) {
    try {
        await fetch(url, {
            method: 'GET',
            mode: 'no-cors',
            cache: 'no-store',
        })
        return true
    } catch {
        return false
    }
}
