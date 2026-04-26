import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { Send, Square, RotateCcw, Zap, Play, Sun, Moon } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'

interface ChatPanelProps {
    output: string
    status: 'idle' | 'generating' | 'done' | 'error'
    compactLogs?: boolean
    onGenerate: (prompt: string) => void
    onResume: () => void
    onStop: () => void
    onReset: () => void
    provider: string
    model: string
    apiKey: string
    onProviderChange: (p: string, m: string, k: string) => void
    availableProviders: Array<{ id: string, name: string, models: string[] }>
    showPreview: boolean
    setShowPreview: (s: boolean) => void
    showLogs: boolean
    setShowLogs: (s: boolean) => void
}

const FALLBACK_PROVIDERS = [
    { id: 'groq', name: 'Groq', models: ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile'] },
    { id: 'anthropic', name: 'Claude', models: ['claude-3-5-haiku-latest', 'claude-3-5-sonnet-latest'] },
    { id: 'openai', name: 'OpenAI', models: ['gpt-4o-mini', 'gpt-4o'] },
    { id: 'openrouter', name: 'OpenRouter', models: ['meta-llama/llama-3.3-70b-instruct', 'anthropic/claude-3.5-sonnet'] },
    { id: 'deepseek', name: 'DeepSeek API', models: ['deepseek-chat', 'deepseek-reasoner'] },
    { id: 'scraper', name: 'Scraper (self-hosted)', models: ['claude-scraper', 'chatgpt-scraper', 'deepseek', 'gemini-scraper'] },
]

const selectStyle: React.CSSProperties = {
    padding: '6px 10px',
    background: 'var(--color-surface2)',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    color: 'var(--color-text)',
    fontSize: 12,
    outline: 'none',
    cursor: 'pointer',
    flex: 1,
}

const toggleButtonStyle: React.CSSProperties = {
    background: 'transparent',
    border: '1px solid var(--color-border)',
    borderRadius: 12,
    padding: '4px 10px',
    fontSize: 11,
    cursor: 'pointer',
    fontWeight: 500,
    transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
}

type OutputBlock =
    | { type: 'status'; text: string; tone: OutputTone }
    | { type: 'heading'; text: string; level: 1 | 2 | 3 }
    | { type: 'plan'; title: string; items: Array<{ status: 'todo' | 'done'; text: string }> }
    | { type: 'code'; title?: string; lang?: string; content: string }
    | { type: 'text'; text: string }

type OutputTone = 'progress' | 'success' | 'error' | 'agent' | 'warning'

interface PlanningUnit {
    status: string
    name: string
    stage: string
    files: string
}

interface ExecutionPlanSummary {
    status?: string
    productType?: string
    appKind?: string
    summary?: string
    features?: string
    pages?: string
    apiResources?: string
    units: PlanningUnit[]
}

const STATUS_PREFIXES = [
    '📦', '🔨', '🛠️', '🧹', '🎨', '📋', '📝', '🔍', '⚙️', '🚀', '🔄', '📁',
    '✅', '⚠️', '❌', '🤖', 'ℹ️', '⏳', '💭'
]

function normalizeOutput(raw: string) {
    return raw
        .replace(/\r\n/g, '\n')
        .replace(/([^\n])(\/\/ FILE:\s)/g, '$1\n$2')
        .replace(/([^\n])(###\s)/g, '$1\n$2')
        .replace(/([^\n])((?:📦|🔨|🛠️|🧹|🎨|📋|📝|🔍|⚙️|🚀|🔄|📁|✅|⚠️|❌|🤖|ℹ️|⏳))/g, '$1\n$2')
}

function isStatusLine(line: string) {
    const trimmed = line.trim()
    return STATUS_PREFIXES.some(prefix => trimmed.startsWith(prefix)) || trimmed.includes('Rate limit reached')
}

function getStatusTone(line: string): OutputTone {
    if (line.includes('❌')) return 'error'
    if (line.includes('⚠️') || line.includes('Rate limit reached')) return 'warning'
    if (line.includes('✅') || line.startsWith('✓') || line.includes('📁 Fixed:')) return 'success'
    if (line.includes('🤖')) return 'agent'
    return 'progress'
}

function inferCodeLang(title?: string, fallback?: string) {
    if (fallback) return fallback
    if (!title) return 'text'
    if (title.endsWith('.tsx')) return 'tsx'
    if (title.endsWith('.ts')) return 'ts'
    if (title.endsWith('.jsx')) return 'jsx'
    if (title.endsWith('.js')) return 'js'
    if (title.endsWith('.json')) return 'json'
    if (title.endsWith('.md')) return 'md'
    if (title.endsWith('.py')) return 'python'
    return 'text'
}

function looksLikeCodeLine(line: string) {
    const trimmed = line.trim()
    if (!trimmed) return false
    const isIndentedProperty = /^[A-Za-z-]+\s*:\s*.+;?$/.test(trimmed) && /^[\t ]+/.test(line)

    return (
        /[{};]/.test(trimmed) ||
        /^<\/?[A-Za-z][\w:-]*(\s|>|\/>)/.test(trimmed) ||
        /^[@.#][\w-].*\{$/.test(trimmed) ||
        isIndentedProperty ||
        /^(import|export|from|const|let|var|function|class|interface|type|return|await|if|else|for|while|try|catch)\b/.test(trimmed) ||
        /^(npm|pnpm|yarn|git|cd|node|python|pip)\b/.test(trimmed)
    )
}

function inferLooseCodeLang(lines: string[]) {
    const sample = lines.filter(line => line.trim()).slice(0, 8).join('\n')
    if (/<\/?[A-Za-z][\w:-]*(\s|>|\/>)/.test(sample)) return 'html'
    if (/^[\s]*[@.#][\w-].*\{$/m.test(sample) || /^[\t ]+[A-Za-z-]+\s*:\s*.+;?$/m.test(sample)) return 'css'
    if (/^\s*[{[]/.test(sample) && /"\s*:/.test(sample)) return 'json'
    if (/\b(interface|type|import|export)\b/.test(sample)) return 'ts'
    if (/\b(const|let|var|function)\b/.test(sample)) return 'js'
    return 'text'
}

function extractAfterColon(line: string) {
    const idx = line.indexOf(':')
    return idx >= 0 ? line.slice(idx + 1).trim() : ''
}

function parseExecutionPlanSummary(output: string): ExecutionPlanSummary | null {
    const lines = normalizeOutput(output)
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)

    const startIdx = lines.findIndex(line => line === 'EXECUTION PLAN' || line.startsWith('EXECUTION PLAN STATUS'))
    if (startIdx === -1) {
        return null
    }

    const summary: ExecutionPlanSummary = { units: [] }
    let inUnits = false

    for (let i = startIdx; i < lines.length; i += 1) {
        const line = lines[i]

        if (line === 'EXECUTION PLAN') continue
        if (/^EXECUTION PLAN STATUS/i.test(line)) {
            summary.status = line.replace(/^EXECUTION PLAN STATUS/i, '').trim()
            continue
        }
        if (/^Product Type:/i.test(line)) {
            summary.productType = extractAfterColon(line)
            continue
        }
        if (/^App Kind:/i.test(line)) {
            summary.appKind = extractAfterColon(line)
            continue
        }
        if (/^Summary:/i.test(line)) {
            summary.summary = extractAfterColon(line)
            continue
        }
        if (/^Features:/i.test(line)) {
            summary.features = extractAfterColon(line)
            continue
        }
        if (/^Pages:/i.test(line)) {
            summary.pages = extractAfterColon(line)
            continue
        }
        if (/^API Resources:/i.test(line)) {
            summary.apiResources = extractAfterColon(line)
            continue
        }
        if (line === 'UNITS') {
            inUnits = true
            continue
        }

        if (inUnits) {
            const unitMatch = line.match(/^(PENDING|DONE|IN_PROGRESS)\s+([^\[]+)\s+\[([^\]]+)\]\s*::\s*(.+)$/i)
            if (unitMatch) {
                summary.units.push({
                    status: unitMatch[1].toUpperCase(),
                    name: unitMatch[2].trim(),
                    stage: unitMatch[3].trim(),
                    files: unitMatch[4].trim(),
                })
                continue
            }
            if (line.startsWith('depends_on:')) {
                continue
            }
            if (/^(🤖|⚙️|🔍|🛠️|⏳|✅|❌|📁)/.test(line)) {
                break
            }
        }
    }

    const hasData =
        Boolean(summary.status)
        || Boolean(summary.productType)
        || Boolean(summary.summary)
        || summary.units.length > 0

    return hasData ? summary : null
}

function shouldKeepCompactStatus(text: string) {
    const keepPatterns = [
        'Starting build',
        'plan prepared',
        'Loaded prepared execution plan',
        'Resume state restored',
        'Style:',
        'Fonts:',
        'UUPM',
        'workflow context built',
        'Key resolution',
        'Restoring prepared design system',
        'Using execution plan',
        'Planned',
        'Preparing with',
        'Building scoped architectural context',
        'Scoping complete',
        'Stage-aware',
        'System prompt built',
        'Calling provider',
        'Executing write_batch',
        'Batch write rejected',
        'BATCH WRITE ERROR',
        'Phase gate blocked progress',
        'Partial batch',
        'Partial write after contract filtering',
        'Filtered files queued for retry',
        'Missing files this turn',
        'Retrying',
        'This same batch-write rejection',
        'kept repeating',
        'fallback',
        'Self-Heal',
        'Executing write_batch',
        'File written:',
        'Executing execute_command',
        'Progress:',
        'Iteration',
        'Running',
        'Linter',
        'Validator',
        'FATAL',
        'ERROR',
        'cancelled',
    ]

    return keepPatterns.some(pattern => text.toLowerCase().includes(pattern.toLowerCase()))
}

function shouldKeepCompactText(text: string) {
    const lines = String(text || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)

    if (!lines.length) return false

    const errorMarkers = [
        'BLUEPRINT_NOT_ENFORCED',
        'BLUEPRINT_SCOPE_FAILURE',
        'IMPORT_SITE_ERROR',
        'BLUEPRINT_EXPORT_MISMATCH',
        'SCHEMA_SYNC_ERROR',
        'API_RESPONSE_ENVELOPE_MISMATCH',
        'THEME_CONTRACT_ERROR',
        'TAILWIND_RUNTIME_MISSING',
        'styling contract validation failed',
        'pre-write syntax validation failed',
        'blueprint execution validation failed',
        'write_batch validation failed',
    ]

    return lines.some((line) => {
        const lower = line.toLowerCase()
        if (line.startsWith('✨')) {
            return true
        }
        if (line.startsWith('- ')) {
            return errorMarkers.some((marker) => lower.includes(marker.toLowerCase()))
        }
        return errorMarkers.some((marker) => lower.includes(marker.toLowerCase()))
    })
}

function isPlanningMetaLine(line: string) {
    const trimmed = line.trim()
    return /^Style:/i.test(trimmed) || /^Fonts:/i.test(trimmed)
}

function parseOutputBlocks(output: string): OutputBlock[] {
    const normalized = normalizeOutput(output)
    const lines = normalized.split('\n')
    const blocks: OutputBlock[] = []
    let i = 0

    const pushText = (text: string) => {
        if (!text.trim()) return
        blocks.push({ type: 'text', text: text.replace(/\n{3,}/g, '\n\n') })
    }

    while (i < lines.length) {
        const line = lines[i]
        const trimmed = line.trim()

        if (!trimmed) {
            i += 1
            continue
        }

        if (trimmed.startsWith('```')) {
            const lang = trimmed.slice(3).trim() || 'text'
            i += 1
            const codeLines: string[] = []
            while (i < lines.length && !lines[i].trim().startsWith('```')) {
                codeLines.push(lines[i])
                i += 1
            }
            if (i < lines.length) i += 1
            blocks.push({
                type: 'code',
                lang,
                content: codeLines.join('\n').replace(/\n+$/, ''),
            })
            continue
        }

        if (trimmed.startsWith('// FILE:')) {
            const title = trimmed.replace('// FILE:', '').trim()
            i += 1
            const codeLines: string[] = []
            while (i < lines.length) {
                const current = lines[i]
                const currentTrimmed = current.trim()
                if (
                    currentTrimmed.startsWith('// FILE:') ||
                    currentTrimmed.startsWith('```') ||
                    currentTrimmed.startsWith('### ') ||
                    isStatusLine(currentTrimmed) ||
                    currentTrimmed.startsWith('✓ ')
                ) {
                    break
                }
                codeLines.push(current)
                i += 1
            }
            blocks.push({
                type: 'code',
                title,
                lang: inferCodeLang(title),
                content: codeLines.join('\n').replace(/\n+$/, ''),
            })
            continue
        }

        if (looksLikeCodeLine(line)) {
            const codeLines: string[] = [line]
            let j = i + 1
            let codeLikeCount = 1

            while (j < lines.length) {
                const current = lines[j]
                const currentTrimmed = current.trim()
                if (
                    currentTrimmed.startsWith('```') ||
                    currentTrimmed.startsWith('// FILE:') ||
                    currentTrimmed.startsWith('### ') ||
                    isStatusLine(currentTrimmed) ||
                    currentTrimmed.startsWith('✓ ')
                ) {
                    break
                }

                if (!currentTrimmed) {
                    codeLines.push(current)
                    j += 1
                    continue
                }

                if (!looksLikeCodeLine(current)) {
                    break
                }

                codeLikeCount += 1
                codeLines.push(current)
                j += 1
            }

            if (codeLikeCount >= 2 || /[{};]/.test(line)) {
                blocks.push({
                    type: 'code',
                    lang: inferLooseCodeLang(codeLines),
                    content: codeLines.join('\n').replace(/\n+$/, ''),
                })
                i = j
                continue
            }
        }

        if (trimmed.startsWith('### TODO LIST')) {
            const items: Array<{ status: 'todo' | 'done'; text: string }> = []
            const title = trimmed.replace(/^###\s*/, '')
            i += 1
            while (i < lines.length) {
                const currentTrimmed = lines[i].trim()
                if (!currentTrimmed) {
                    i += 1
                    continue
                }
                if (currentTrimmed.startsWith('DONE:')) {
                    items.push({ status: 'done', text: currentTrimmed.slice(5).trim() })
                    i += 1
                    continue
                }
                if (currentTrimmed.startsWith('TODO:')) {
                    items.push({ status: 'todo', text: currentTrimmed.slice(5).trim() })
                    i += 1
                    continue
                }
                break
            }
            blocks.push({ type: 'plan', title, items })
            continue
        }

        const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/)
        if (headingMatch) {
            blocks.push({
                type: 'heading',
                level: Math.min(headingMatch[1].length, 3) as 1 | 2 | 3,
                text: headingMatch[2].trim(),
            })
            i += 1
            continue
        }

        if (/^[─-]{2}\s*STEP\s+/i.test(trimmed)) {
            blocks.push({
                type: 'heading',
                level: 2,
                text: trimmed,
            })
            i += 1
            continue
        }

        if (isStatusLine(trimmed) || trimmed.startsWith('✓ ') || shouldKeepCompactStatus(trimmed)) {
            blocks.push({
                type: 'status',
                text: trimmed,
                tone: getStatusTone(trimmed),
            })
            i += 1
            continue
        }

        if (isPlanningMetaLine(trimmed)) {
            blocks.push({
                type: 'status',
                text: trimmed,
                tone: 'progress',
            })
            i += 1
            continue
        }

        const textLines: string[] = [line]
        i += 1
        while (i < lines.length) {
            const currentTrimmed = lines[i].trim()
            if (
                !currentTrimmed ||
                currentTrimmed.startsWith('```') ||
                currentTrimmed.startsWith('// FILE:') ||
                currentTrimmed.startsWith('### ') ||
                isStatusLine(currentTrimmed) ||
                currentTrimmed.startsWith('✓ ')
            ) {
                break
            }
            textLines.push(lines[i])
            i += 1
        }
        pushText(textLines.join('\n'))
    }

    return blocks
}

export default function ChatPanel({
    output, status, compactLogs = false, onGenerate, onResume, onStop, onReset,
    provider, model, apiKey, onProviderChange,
    availableProviders,
    showPreview, setShowPreview, showLogs, setShowLogs
}: ChatPanelProps) {
    const { theme, toggleTheme } = useTheme()
    const [prompt, setPrompt] = useState('')
    const [isInputFocused, setIsInputFocused] = useState(false)
    const outputRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const hasVisibleOutput = output.trim().length > 0
    const hasInput = prompt.trim().length > 0
    const shouldCenterInput = !hasVisibleOutput && !isInputFocused && !hasInput && status !== 'generating'

    const providerOptions = availableProviders.length ? availableProviders : FALLBACK_PROVIDERS
    const currentProvider = providerOptions.find(p => p.id === provider) || providerOptions[0]
    const outputBlocks = hasVisibleOutput ? parseOutputBlocks(output) : []
    const executionPlan = hasVisibleOutput ? parseExecutionPlanSummary(output) : null
    const compactBlocks = compactLogs
        ? outputBlocks.filter((block) => {
            if (block.type === 'status') return shouldKeepCompactStatus(block.text)
            if (block.type === 'plan') return true
            if (block.type === 'text') return shouldKeepCompactText(block.text)
            return false
        })
        : outputBlocks

    useEffect(() => {
        if (outputRef.current) {
            outputRef.current.scrollTop = outputRef.current.scrollHeight
        }
    }, [output])

    const handleSubmit = () => {
        if (!prompt.trim() || status === 'generating') return
        onGenerate(prompt.trim())
    }

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            handleSubmit()
        }
    }

    const examples = [
        'Build a modern SaaS dashboard with charts and analytics',
        'Create an e-commerce store with product catalog',
        'Build a portfolio website for a designer',
        'Create a blog platform with categories',
    ]

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            background: 'var(--color-surface)',
        }}>
            {/* Header */}
            <div style={{
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
            }}>
                <div style={{ fontWeight: 600, fontSize: 18, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center' }}>
                    WAGI <span style={{ fontSize: 13, color: 'var(--color-text-muted)', opacity: 0.5, marginLeft: 4 }}>platform</span>
                </div>
                <div style={{ display: 'flex', gap: 6, flex: 1, justifyContent: 'flex-end', opacity: 0.5 }}>
                    <button
                        onClick={() => setShowPreview(!showPreview)}
                        style={{ ...toggleButtonStyle, color: showPreview ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
                        title="Toggle Preview"
                    >
                        Preview
                    </button>
                    <button
                        onClick={toggleTheme}
                        style={{ ...toggleButtonStyle, color: 'var(--color-text-muted)' }}
                        title="Toggle Theme"
                    >
                        {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                    </button>
                    <button
                        onClick={() => setShowLogs(!showLogs)}
                        style={{ ...toggleButtonStyle, color: showLogs ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
                        title="Toggle Logs"
                    >
                        Logs
                    </button>
                    <select
                        value={provider}
                        onChange={e => {
                            const p = providerOptions.find(x => x.id === e.target.value) || providerOptions[0]
                            onProviderChange(p.id, p.models[0], apiKey)
                        }}
                        style={{ ...selectStyle, maxWidth: 120, background: 'transparent', border: 'none' }}
                    >
                        {providerOptions.map(p => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                    </select>
                    <select
                        value={model}
                        onChange={e => onProviderChange(provider, e.target.value, apiKey)}
                        style={{ ...selectStyle, maxWidth: 120, background: 'transparent', border: 'none' }}
                        disabled={!currentProvider || currentProvider.models.length === 0}
                    >
                        {(currentProvider?.models || []).map(m => (
                            <option key={m} value={m}>{m}</option>
                        ))}
                    </select>
                </div>
                {status !== 'idle' && (
                    <button
                        onClick={onReset}
                        style={{
                            background: 'transparent', border: 'none', color: 'var(--color-text-muted)',
                            cursor: 'pointer', padding: 4, display: 'flex'
                        }}
                        title="Reset Chat"
                    >
                        <RotateCcw size={16} />
                    </button>
                )}
            </div>

            {/* Output area */}
            <div
                ref={outputRef}
                style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: '16px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    lineHeight: 1.7,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: 'var(--color-text)',
                }}
            >
                <div style={{
                    maxWidth: 720,
                    margin: '0 auto',
                    width: '100%',
                }}>
                    {(hasVisibleOutput || status === 'generating') ? (
                        <span className={status === 'generating' ? '' : 'animate-fadeIn'}>
                            {hasVisibleOutput ? (
                                <>
                                    {compactLogs && executionPlan && (
                                        <div style={{
                                            background: 'linear-gradient(180deg, rgba(99,102,241,0.10), rgba(99,102,241,0.04))',
                                            border: '1px solid rgba(99,102,241,0.25)',
                                            borderRadius: 14,
                                            padding: 14,
                                            margin: '6px 0 12px 0',
                                        }}>
                                            <div style={{
                                                fontSize: 12,
                                                fontWeight: 800,
                                                letterSpacing: '0.05em',
                                                textTransform: 'uppercase',
                                                color: 'var(--color-primary)',
                                                marginBottom: 10,
                                            }}>
                                                Planning Mode
                                            </div>
                                            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                                                {executionPlan.status && (
                                                    <span style={{
                                                        fontSize: 11,
                                                        padding: '4px 8px',
                                                        borderRadius: 999,
                                                        background: 'var(--color-surface2)',
                                                        border: '1px solid var(--color-border)',
                                                    }}>
                                                        {executionPlan.status}
                                                    </span>
                                                )}
                                                {executionPlan.productType && (
                                                    <span style={{
                                                        fontSize: 11,
                                                        padding: '4px 8px',
                                                        borderRadius: 999,
                                                        background: 'var(--color-surface2)',
                                                        border: '1px solid var(--color-border)',
                                                    }}>
                                                        Product: {executionPlan.productType}
                                                    </span>
                                                )}
                                                {executionPlan.appKind && (
                                                    <span style={{
                                                        fontSize: 11,
                                                        padding: '4px 8px',
                                                        borderRadius: 999,
                                                        background: 'var(--color-surface2)',
                                                        border: '1px solid var(--color-border)',
                                                    }}>
                                                        App: {executionPlan.appKind}
                                                    </span>
                                                )}
                                                {executionPlan.units.length > 0 && (
                                                    <span style={{
                                                        fontSize: 11,
                                                        padding: '4px 8px',
                                                        borderRadius: 999,
                                                        background: 'rgba(16,185,129,0.1)',
                                                        border: '1px solid rgba(16,185,129,0.25)',
                                                        color: 'var(--color-success)',
                                                    }}>
                                                        Units: {executionPlan.units.length}
                                                    </span>
                                                )}
                                            </div>
                                            {executionPlan.summary && (
                                                <div style={{
                                                    fontSize: 12,
                                                    color: 'var(--color-text-muted)',
                                                    lineHeight: 1.6,
                                                    marginBottom: 10,
                                                }}>
                                                    {executionPlan.summary}
                                                </div>
                                            )}
                                            {executionPlan.units.length > 0 && (
                                                <div style={{
                                                    display: 'grid',
                                                    gap: 6,
                                                    maxHeight: 160,
                                                    overflowY: 'auto',
                                                    paddingRight: 2,
                                                }}>
                                                    {executionPlan.units.slice(0, 12).map((unit, idx) => (
                                                        <div key={`${unit.name}-${idx}`} style={{
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            gap: 8,
                                                            background: 'var(--color-surface2)',
                                                            border: '1px solid var(--color-border)',
                                                            borderRadius: 8,
                                                            padding: '6px 8px',
                                                            fontSize: 11,
                                                        }}>
                                                            <span style={{
                                                                minWidth: 64,
                                                                textAlign: 'center',
                                                                borderRadius: 999,
                                                                padding: '2px 8px',
                                                                background: unit.status === 'DONE'
                                                                    ? 'rgba(16,185,129,0.12)'
                                                                    : 'rgba(245,158,11,0.12)',
                                                                color: unit.status === 'DONE' ? 'var(--color-success)' : '#d97706',
                                                                fontWeight: 700,
                                                            }}>
                                                                {unit.status}
                                                            </span>
                                                            <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{unit.name}</span>
                                                            <span style={{ color: 'var(--color-text-muted)' }}>[{unit.stage}]</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {compactLogs && (
                                        <div style={{
                                            fontSize: 11,
                                            color: 'var(--color-text-muted)',
                                            marginBottom: 10,
                                            padding: '6px 10px',
                                            borderRadius: 8,
                                            background: 'var(--color-surface2)',
                                            border: '1px solid var(--color-border)',
                                        }}>
                                            Streaming code is shown in Monaco editor. Chat shows progress only.
                                        </div>
                                    )}

                                    {compactBlocks.map((block, i) => {
                                        if (block.type === 'status') {
                                            const toneStyles: Record<OutputTone, React.CSSProperties> = {
                                                progress: {
                                                    background: 'var(--color-surface2)',
                                                    color: 'var(--color-text)',
                                                    border: '1px solid var(--color-border)',
                                                },
                                                success: {
                                                    background: 'rgba(16,185,129,0.1)',
                                                    color: 'var(--color-success)',
                                                    border: '1px solid rgba(16,185,129,0.2)',
                                                },
                                                error: {
                                                    background: 'rgba(239,68,68,0.1)',
                                                    color: 'var(--color-error)',
                                                    border: '1px solid rgba(239,68,68,0.2)',
                                                },
                                                warning: {
                                                    background: 'rgba(245,158,11,0.12)',
                                                    color: '#d97706',
                                                    border: '1px solid rgba(245,158,11,0.2)',
                                                },
                                                agent: {
                                                    background: 'var(--color-surface2)',
                                                    color: 'var(--color-text-muted)',
                                                    border: '1px solid var(--color-border)',
                                                    fontStyle: 'italic',
                                                },
                                            }

                                            return (
                                                <div key={i} style={{
                                                    ...toneStyles[block.tone],
                                                    padding: '6px 12px',
                                                    borderRadius: 8,
                                                    fontSize: 12,
                                                    margin: '4px 0',
                                                    fontFamily: 'var(--font-mono)',
                                                }}>
                                                    {block.text}
                                                </div>
                                            )
                                        }

                                        if (block.type === 'heading') {
                                            const fontSize = block.level === 1 ? 20 : block.level === 2 ? 16 : 14
                                            return (
                                                <div key={i} style={{
                                                    marginTop: i === 0 ? 0 : 18,
                                                    marginBottom: 8,
                                                    fontWeight: 700,
                                                    fontSize,
                                                    color: 'var(--color-text)',
                                                    letterSpacing: block.level === 3 ? '0.02em' : undefined,
                                                    textTransform: block.level === 3 ? 'uppercase' : undefined,
                                                }}>
                                                    {block.text}
                                                </div>
                                            )
                                        }

                                        if (block.type === 'plan') {
                                            return (
                                                <div key={i} style={{
                                                    background: 'var(--color-surface2)',
                                                    border: '1px solid var(--color-border)',
                                                    borderRadius: 14,
                                                    padding: 14,
                                                    margin: '10px 0',
                                                }}>
                                                    <div style={{
                                                        fontWeight: 700,
                                                        fontSize: 13,
                                                        marginBottom: 10,
                                                        color: 'var(--color-text)',
                                                        textTransform: 'uppercase',
                                                        letterSpacing: '0.04em',
                                                    }}>
                                                        {block.title}
                                                    </div>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                        {block.items.map((item, itemIndex) => (
                                                            <div key={itemIndex} style={{
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                gap: 10,
                                                                padding: '6px 8px',
                                                                background: 'rgba(255,255,255,0.02)',
                                                                borderRadius: 8,
                                                            }}>
                                                                <span style={{
                                                                    minWidth: 44,
                                                                    textAlign: 'center',
                                                                    borderRadius: 999,
                                                                    padding: '2px 8px',
                                                                    fontSize: 10,
                                                                    fontWeight: 700,
                                                                    letterSpacing: '0.05em',
                                                                    color: item.status === 'done' ? 'var(--color-success)' : '#d97706',
                                                                    background: item.status === 'done'
                                                                        ? 'rgba(16,185,129,0.12)'
                                                                        : 'rgba(245,158,11,0.12)',
                                                                }}>
                                                                    {item.status === 'done' ? 'DONE' : 'TODO'}
                                                                </span>
                                                                <code style={{
                                                                    fontFamily: 'var(--font-mono)',
                                                                    color: 'var(--color-text)',
                                                                    fontSize: 12,
                                                                }}>
                                                                    {item.text}
                                                                </code>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )
                                        }

                                        if (block.type === 'code') {
                                            if (compactLogs) {
                                                return null
                                            }

                                            return (
                                                <div key={i} style={{
                                                    background: '#0f1117',
                                                    border: '1px solid rgba(148,163,184,0.18)',
                                                    borderRadius: 14,
                                                    overflow: 'hidden',
                                                    margin: '10px 0',
                                                }}>
                                                    <div style={{
                                                        display: 'flex',
                                                        justifyContent: 'space-between',
                                                        alignItems: 'center',
                                                        gap: 12,
                                                        padding: '10px 12px',
                                                        borderBottom: '1px solid rgba(148,163,184,0.12)',
                                                        background: 'rgba(255,255,255,0.03)',
                                                    }}>
                                                        <span style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: 12,
                                                            color: '#e2e8f0',
                                                            wordBreak: 'break-all',
                                                        }}>
                                                            {block.title || 'Code Block'}
                                                        </span>
                                                        <span style={{
                                                            fontSize: 10,
                                                            textTransform: 'uppercase',
                                                            letterSpacing: '0.06em',
                                                            color: '#94a3b8',
                                                        }}>
                                                            {inferCodeLang(block.title, block.lang)}
                                                        </span>
                                                    </div>
                                                    <pre style={{
                                                        margin: 0,
                                                        padding: '14px 16px',
                                                        overflowX: 'auto',
                                                        fontSize: 12,
                                                        lineHeight: 1.6,
                                                        color: '#e2e8f0',
                                                        whiteSpace: 'pre-wrap',
                                                        wordBreak: 'break-word',
                                                    }}>
                                                        <code>{block.content}</code>
                                                    </pre>
                                                </div>
                                            )
                                        }

                                        return (
                                            <div key={i} style={{
                                                whiteSpace: 'pre-wrap',
                                                margin: '8px 0',
                                                color: 'var(--color-text)',
                                            }}>
                                                {block.text}
                                            </div>
                                        )
                                    })}
                                </>
                            ) : (
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: '10px 16px',
                                    background: 'var(--color-surface2)',
                                    borderRadius: 16,
                                    border: '1px solid var(--color-border)',
                                    width: 'fit-content'
                                }}>
                                    <div style={{ display: 'flex', gap: 4 }}>
                                        <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%' }} />
                                        <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.2s' }} />
                                        <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.4s' }} />
                                    </div>
                                    <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-muted)' }}>
                                        Starting build and connecting to logs...
                                    </span>
                                </div>
                            )}

                            {status === 'generating' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
                                    {/* Sub-tokens / Typing Cursor */}
                                    <span style={{
                                        display: 'inline-block',
                                        width: 8,
                                        height: 15,
                                        background: 'var(--color-primary)',
                                        borderRadius: 2,
                                        marginLeft: 4,
                                        verticalAlign: 'middle',
                                        animation: 'blink 0.8s infinite step-start'
                                    }} />

                                    {/* Thinking Bubble */}
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 10,
                                        padding: '10px 16px',
                                        background: 'var(--color-surface2)',
                                        borderRadius: 16,
                                        border: '1px solid var(--color-border)',
                                        width: 'fit-content',
                                        animation: 'pulse 2s infinite ease-in-out'
                                    }}>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%' }} />
                                            <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.2s' }} />
                                            <div className="dot-pulse" style={{ width: 4, height: 4, background: 'var(--color-primary)', borderRadius: '50%', animationDelay: '0.4s' }} />
                                        </div>
                                        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-muted)' }}>
                                            WAGI is thinking...
                                        </span>
                                    </div>
                                </div>
                            )}
                        </span>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 30, marginTop: '15vh' }}>
                            <h2 style={{ fontSize: 24, fontWeight: 600, color: 'var(--color-text)' }}>What can I uniquely help with?</h2>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 400 }}>
                                {examples.map((ex, i) => (
                                    <button
                                        key={i}
                                        onClick={() => setPrompt(ex)}
                                        className="btn btn-ghost"
                                        style={{ padding: '12px 16px', fontSize: 13, borderRadius: 20 }}
                                    >
                                        {ex}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Input area */}
            <div
                style={{
                    padding: '0 16px 16px',
                    background: 'var(--color-surface)',
                    display: 'flex',
                    justifyContent: 'center',
                    transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                    marginTop: shouldCenterInput ? 'auto' : 0,
                    marginBottom: shouldCenterInput ? 'auto' : 0,
                }}
            >
                <div style={{
                    display: 'flex',
                    alignItems: 'flex-end',
                    gap: 8,
                    background: 'var(--color-surface2)',
                    borderRadius: 24,
                    padding: '10px 12px',
                    position: 'relative',
                    maxWidth: 720,
                    width: '100%',
                }}>
                    <textarea
                        ref={textareaRef}
                        id="prompt-input"
                        value={prompt}
                        onChange={e => {
                            setPrompt(e.target.value);
                            setIsInputFocused(true);
                        }}
                        onFocus={() => setIsInputFocused(true)}
                        onBlur={() => setIsInputFocused(false)}
                        onKeyDown={handleKeyDown}
                        placeholder="Message WAGI..."
                        disabled={status === 'generating'}
                        rows={1}
                        style={{
                            flex: 1,
                            padding: '6px 0',
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--color-text)',
                            fontFamily: 'var(--font-sans)',
                            fontSize: 15,
                            resize: 'none',
                            outline: 'none',
                            lineHeight: 1.5,
                            minHeight: 24,
                            maxHeight: 120,
                        }}
                    />
                    {status !== 'generating' && output && (
                        <button
                            onClick={onResume}
                            title="Resume Generation"
                            className="btn btn-ghost"
                            style={{
                                padding: 8,
                                display: 'flex',
                                alignItems: 'center',
                                color: 'var(--color-text-muted)',
                            }}
                        >
                            <Play size={18} />
                        </button>
                    )}
                    <button
                        id={status === 'generating' ? 'stop-btn' : 'generate-btn'}
                        onClick={status === 'generating' ? onStop : handleSubmit}
                        disabled={!prompt.trim() && status !== 'generating'}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: 36,
                            height: 36,
                            borderRadius: 12,
                            border: 'none',
                            background: status === 'generating'
                                ? 'rgba(239,68,68,0.1)'
                                : prompt.trim()
                                    ? 'var(--color-text)'
                                    : 'var(--color-surface)',
                            color: status === 'generating'
                                ? 'var(--color-error)'
                                : prompt.trim()
                                    ? 'var(--color-bg)'
                                    : 'var(--color-text-muted)',
                            cursor: (prompt.trim() || status === 'generating') ? 'pointer' : 'not-allowed',
                            transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                            flexShrink: 0,
                        }}
                    >
                        {status === 'generating' ? <Square size={14} fill="currentColor" /> : <Send size={16} />}
                    </button>
                </div>
            </div>
            <div style={{ color: 'var(--color-text-muted)', fontSize: 11, paddingBottom: 8, textAlign: 'center', background: 'var(--color-surface)' }}>
                WAGI platform can make mistakes. Check important info.
            </div>
        </div>
    )
}
