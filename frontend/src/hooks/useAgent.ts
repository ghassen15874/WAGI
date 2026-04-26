import { useState, useCallback, useRef } from 'react'

const PROJECT_LOG_TAIL_CHARS = 12000

interface AgentState {
    status: 'idle' | 'generating' | 'done' | 'error'
    output: string
    sessionId: string | null
    files: Record<string, string>
    fileList: string[]
}

interface GenerateOptions {
    prompt: string
    provider: string
    model: string
    apiKey: string
    scraperUrl?: string
    projectId?: string
    resume?: boolean
}

export function useAgent() {
    const [state, setState] = useState<AgentState>({
        status: 'idle',
        output: '',
        sessionId: null,
        files: {},
        fileList: [],
    })
    const generateAbortRef = useRef<AbortController | null>(null)
    const logAbortRef = useRef<AbortController | null>(null)
    const stopRequestedRef = useRef(false)
    const activeSessionIdRef = useRef<string | null>(null)
    const loadRequestRef = useRef(0)

    const appendOutputLine = useCallback((line: string) => {
        setState(s => ({
            ...s,
            output: s.output.includes(line)
                ? s.output
                : `${s.output}${s.output.endsWith('\n') || !s.output ? '' : '\n'}${line}\n`
        }))
    }, [])

    const followLogs = useCallback(async (projectId: string, abortSignal: AbortSignal, fromEnd = false) => {
        try {
            const params = new URLSearchParams()
            if (fromEnd) params.set('from_end', 'true')

            const res = await fetch(`/api/generate/${projectId}/logs${params.toString() ? `?${params.toString()}` : ''}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                signal: abortSignal
            })

            if (!res.ok) throw new Error(`Logs stream failed: ${res.status}`)

            const reader = res.body!.getReader()
            const decoder = new TextDecoder()

            let buffer = ''
            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''

                for (const line of lines) {
                    const trimmed = line.trim()
                    if (!trimmed.startsWith('data:')) continue
                    try {
                        const parsed = JSON.parse(trimmed.slice(5).trim())
                        if (parsed.type === 'token') {
                            setState(s => ({ ...s, status: 'generating', output: s.output + parsed.content }))
                        } else if (parsed.type === 'info') {
                            setState(s => ({
                                ...s,
                                status: 'generating',
                                output: s.output.includes(parsed.content)
                                    ? s.output
                                    : s.output + `${parsed.content}\n`
                            }))
                        } else if (parsed.type === 'files') {
                            setState(s => ({
                                ...s,
                                status: 'done',
                                sessionId: parsed.session_id,
                                files: parsed.files,
                                fileList: Object.keys(parsed.files)
                            }))
                        } else if (parsed.type === 'error') {
                            throw new Error(parsed.message)
                        } else if (parsed.type === 'done') {
                            setState(s => ({ ...s, status: 'done' }))
                        }
                    } catch (e) { }
                }
            }
        } catch (e: any) {
            if (e.name !== 'AbortError') {
                setState(s => ({ ...s, status: 'error', output: s.output + `\n❌ Log Error: ${e.message}` }))
            }
        }
    }, [])

    const generate = useCallback(async (opts: GenerateOptions) => {
        generateAbortRef.current?.abort()
        logAbortRef.current?.abort()
        generateAbortRef.current = new AbortController()
        logAbortRef.current = null
        stopRequestedRef.current = false

        setState(s => ({
            ...s,
            status: 'generating',
            output: opts.resume
                ? `${s.output}${s.output.endsWith('\n') || !s.output ? '' : '\n'}▶ Resuming build from existing files...\n`
                : '🚀 Starting build...\n',
            sessionId: opts.projectId || s.sessionId
        }))

        try {
            const finalApiKey = opts.apiKey;
            const accessToken = localStorage.getItem('access_token') || ''

            const payload: any = {
                message: opts.prompt, // Updated for ChatRequest
                provider: opts.provider,
                model: opts.model,
                scraper_url: opts.scraperUrl || '',
                projectId: opts.projectId || '',
                resume: Boolean(opts.resume),
            }

            const trimmedApiKey = (finalApiKey || '').trim()
            if (!accessToken && trimmedApiKey) {
                payload.api_key = finalApiKey
            }

            const res = await fetch('/api/chat', { // Updated to hit Decision Layer
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`
                },
                body: JSON.stringify(payload),
                signal: generateAbortRef.current.signal,
            })

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
                throw new Error(err.detail || `HTTP ${res.status}`)
            }

            // Check if response is stream (chat) or json (generation fallback)
            const contentType = res.headers.get('content-type') || ''
            if (contentType.includes('text/event-stream')) {
                // Handle chat stream directly
                setState(s => ({ ...s, status: 'generating' }))
                const reader = res.body!.getReader()
                const decoder = new TextDecoder()
                let buffer = ''
                let isFirstToken = true;

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        const trimmed = line.trim()
                        if (!trimmed.startsWith('data:')) continue
                        try {
                            const parsed = JSON.parse(trimmed.slice(5).trim())
                            if (parsed.type === 'token') {
                                let content = parsed.content;
                                if (isFirstToken && content.trim() !== '') {
                                    content = '\n\n✨ ' + content;
                                    isFirstToken = false;
                                }
                                setState(s => ({ ...s, output: s.output + content }))
                            } else if (parsed.type === 'done') {
                                setState(s => ({ ...s, status: 'done' }))
                            } else if (parsed.type === 'error') {
                                throw new Error(parsed.message)
                            }
                        } catch (e) { }
                    }
                }
                return
            }

            // Fallback: This is a generation task JSON response
            const data = await res.json()
            const sessionId = data.session_id
            activeSessionIdRef.current = sessionId
            setState(s => ({ ...s, sessionId }))

            if (stopRequestedRef.current) {
                try {
                    await fetch(`/api/generate/${sessionId}/cancel`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                    })
                } catch (cancelError) {
                    console.error('Failed to cancel build after session start', cancelError)
                }

                setState(s => ({
                    ...s,
                    status: 'idle',
                    sessionId,
                    output: s.output.includes('🛑 Build cancelled.')
                        ? s.output
                        : `${s.output}${s.output.endsWith('\n') || !s.output ? '' : '\n'}🛑 Build cancelled.\n`
                }))
                return
            }

            // Start following logs
            logAbortRef.current = new AbortController()
            await followLogs(sessionId, logAbortRef.current.signal, Boolean(opts.resume))

        } catch (e: any) {
            if (e.name !== 'AbortError') {
                setState(s => ({
                    ...s,
                    status: 'error',
                    output: s.output + `\n❌ Error: ${e.message}`,
                }))
            }
        }
    }, [followLogs])

    const reconnect = useCallback(async (projectId: string) => {
        generateAbortRef.current?.abort()
        logAbortRef.current?.abort()
        logAbortRef.current = new AbortController()
        stopRequestedRef.current = false
        activeSessionIdRef.current = projectId

        setState(s => ({
            ...s,
            status: 'generating',
            sessionId: projectId,
            output: s.output || '🔄 Reconnecting to build logs...\n'
        }))
        await followLogs(projectId, logAbortRef.current.signal)
    }, [followLogs])

    const resumeGeneration = useCallback(async (opts: Omit<GenerateOptions, 'resume'>) => {
        await generate({
            ...opts,
            resume: true,
        })
    }, [generate])

    const stop = useCallback(async () => {
        stopRequestedRef.current = true
        const activeSessionId = activeSessionIdRef.current || state.sessionId

        if (!activeSessionId) {
            appendOutputLine('🛑 Stop requested. Waiting for build session...')
            return
        }

        try {
            await fetch(`/api/generate/${activeSessionId}/cancel`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
            })
        } catch (e) {
            console.error('Failed to cancel build', e)
        } finally {
            logAbortRef.current?.abort()
            generateAbortRef.current?.abort()
            activeSessionIdRef.current = activeSessionId
            setState(s => ({
                ...s,
                status: 'idle',
                sessionId: activeSessionId,
                output: s.output.includes('🛑 Build cancelled.')
                    ? s.output
                    : `${s.output}${s.output.endsWith('\n') || !s.output ? '' : '\n'}🛑 Build cancelled.\n`
            }))
        }
    }, [appendOutputLine, state.sessionId])

    const reset = useCallback(() => {
        loadRequestRef.current += 1
        stopRequestedRef.current = false
        generateAbortRef.current?.abort()
        logAbortRef.current?.abort()
        activeSessionIdRef.current = null
        setState({ status: 'idle', output: '', sessionId: null, files: {}, fileList: [] })
    }, [])

    const loadProject = useCallback(async (projectId: string, token: string) => {
        loadRequestRef.current += 1
        const requestId = loadRequestRef.current

        generateAbortRef.current?.abort()
        logAbortRef.current?.abort()
        stopRequestedRef.current = false
        activeSessionIdRef.current = projectId

        setState(s => ({
            ...s,
            status: 'done',
            output: '',
            sessionId: projectId,
            files: {},
            fileList: [],
        }))

        try {
            const [filesRes, logTailRes] = await Promise.all([
                fetch(`/api/projects/${projectId}/files`, {
                    headers: { Authorization: `Bearer ${token}` },
                }),
                fetch(`/api/projects/${projectId}/log-tail?chars=${PROJECT_LOG_TAIL_CHARS}`, {
                    headers: { Authorization: `Bearer ${token}` },
                }),
            ])

            const filesData = filesRes.ok ? await filesRes.json() : { files: {} }
            const logTailData = logTailRes.ok ? await logTailRes.json() : { content: '' }
            const boundedOutput = String(logTailData?.content || '').slice(-PROJECT_LOG_TAIL_CHARS)

            if (requestId !== loadRequestRef.current) {
                return
            }

            setState(s => ({
                ...s,
                status: 'done',
                sessionId: projectId,
                files: filesData.files || {},
                fileList: Object.keys(filesData.files || {}),
                output: boundedOutput,
            }))
        } catch (e) {
            if (requestId === loadRequestRef.current) {
                console.error('Failed to load project snapshot', e)
            }
        }
    }, [])

    return { state, generate, stop, reset, loadProject, reconnect, resumeGeneration }
}
