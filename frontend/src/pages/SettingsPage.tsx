import { useState, useEffect } from 'react'
import { Save, TestTube, Plus, X, Settings2, Key, Server, Zap, ShieldCheck } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ProviderKeys {
    groq: string[]
    anthropic: string[]
    openai: string[]
    openrouter: string[]
    deepseek: string[]
}

interface TestResult {
    status: 'ok' | 'error' | 'testing' | null
    message: string
}

const PROVIDER_META = [
    {
        id: 'auto',
        name: 'Auto-Routing',
        tag: 'Recommended',
        color: '#10b981',
        description: 'Tries Groq → Scraper → Anthropic automatically.',
        keyEnv: null,
    },
    {
        id: 'groq',
        name: 'Groq Cloud',
        tag: 'Fast',
        color: '#f59e0b',
        description: 'Ultra-fast Llama 3 models via Groq API.',
        keyEnv: 'GROQ_API_KEY',
    },
    {
        id: 'anthropic',
        name: 'Anthropic',
        tag: 'Intelligence',
        color: '#ececec',
        description: 'Claude 3.5 Sonnet & Haiku models.',
        keyEnv: 'ANTHROPIC_API_KEY',
    },
    {
        id: 'openai',
        name: 'OpenAI',
        tag: 'Classic',
        color: '#10a37f',
        description: 'GPT-4o and GPT-4o-mini models.',
        keyEnv: 'OPENAI_API_KEY',
    },
    {
        id: 'openrouter',
        name: 'OpenRouter',
        tag: 'Router',
        color: '#60a5fa',
        description: 'Hosted routing across multiple upstream model providers.',
        keyEnv: 'OPENROUTER_API_KEY',
    },
    {
        id: 'deepseek',
        name: 'DeepSeek',
        tag: 'Reasoning',
        color: '#1d4ed8',
        description: 'Powerful DeepSeek chat and reasoner API models.',
        keyEnv: 'DEEPSEEK_API_KEY',
    },
    {
        id: 'scraper',
        name: 'Local Scraper',
        tag: 'Cost-zero',
        color: '#6366f1',
        description: 'Your self-hosted browser gateway.',
        keyEnv: null,
    },
]

function MultiKeyInput({
    label, keys, onChange,
}: {
    label: string
    keys: string[]
    onChange: (keys: string[]) => void
}) {
    const updateKey = (i: number, val: string) => {
        const updated = [...keys]
        updated[i] = val
        onChange(updated)
    }
    const addKey = () => onChange([...keys, ''])
    const removeKey = (i: number) => onChange(keys.filter((_, idx) => idx !== i))

    return (
        <div style={{ marginBottom: 24 }}>
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                <Key size={14} /> {label}
            </label>
            {keys.map((k, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                    <input
                        type="password"
                        value={k}
                        placeholder={`••••••••••••••••••••••••`}
                        onChange={e => updateKey(i, e.target.value)}
                        style={inputStyle}
                    />
                    {keys.length > 1 && (
                        <button
                            onClick={() => removeKey(i)}
                            style={{ ...iconBtnStyle, color: 'var(--color-error)', border: 'none' }}
                            title="Remove key"
                        >
                            <X size={16} />
                        </button>
                    )}
                </div>
            ))}
            <button onClick={addKey} style={addBtnStyle}>
                <Plus size={14} /> Add fallback key
            </button>
        </div>
    )
}

function ProviderCard({
    meta, selected, onClick,
}: {
    meta: typeof PROVIDER_META[0]
    selected: boolean
    onClick: () => void
}) {
    return (
        <div
            onClick={onClick}
            style={{
                padding: '16px',
                borderRadius: 12,
                border: selected ? `1px solid var(--color-primary)` : '1px solid var(--color-border)',
                background: selected ? 'var(--color-surface2)' : 'transparent',
                cursor: 'pointer',
                transition: 'var(--transition)',
                marginBottom: 10,
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: meta.color, flexShrink: 0,
                    boxShadow: selected ? `0 0 10px ${meta.color}` : 'none'
                }} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>{meta.name}</span>
                <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 20,
                    background: 'var(--color-border)', color: 'var(--color-text-muted)', fontWeight: 700,
                    marginLeft: 'auto'
                }}>
                    {meta.tag}
                </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 8 }}>
                {meta.description}
            </div>
        </div>
    )
}

export default function SettingsPage({ onClose }: { onClose?: () => void }) {
    const [tab, setTab] = useState<'providers' | 'keys'>('providers')
    const [selectedProvider, setSelectedProvider] = useState('groq')
    const [keys, setKeys] = useState<ProviderKeys>({ groq: [''], anthropic: [''], openai: [''], openrouter: [''], deepseek: [''] })
    const [scraperUrl, setScraperUrl] = useState('http://localhost:5300')
    const [scraperKey, setScraperKey] = useState('your-secret-key-1')
    const [saved, setSaved] = useState(false)
    const [testResults, setTestResults] = useState<Record<string, TestResult>>({})
    const [visibleProviderIds, setVisibleProviderIds] = useState<string[]>([])

    useEffect(() => {
        try {
            const raw = localStorage.getItem('llm_keys')
            if (raw) {
                const data = JSON.parse(raw)
                setKeys({
                    groq: data.groq_keys?.length ? data.groq_keys : [''],
                    anthropic: data.anthropic_keys?.length ? data.anthropic_keys : [''],
                    openai: data.openai_keys?.length ? data.openai_keys : [''],
                    openrouter: data.openrouter_keys?.length ? data.openrouter_keys : [''],
                    deepseek: data.deepseek_keys?.length ? data.deepseek_keys : [''],
                })
                if (data.scraper_url) setScraperUrl(data.scraper_url)
                if (data.scraper_key) setScraperKey(data.scraper_key)
            }
        } catch { }
    }, [])

    useEffect(() => {
        fetch('/api/providers')
            .then(res => res.json())
            .then(data => {
                const ids = Array.isArray(data.providers) ? data.providers.map((provider: any) => provider.id) : []
                setVisibleProviderIds(ids)
            })
            .catch(() => setVisibleProviderIds([]))
    }, [])

    const visibleProviders = PROVIDER_META.filter((meta) => (
        meta.id === 'auto' || visibleProviderIds.length === 0 || visibleProviderIds.includes(meta.id)
    ))

    useEffect(() => {
        if (visibleProviders.length && !visibleProviders.some((meta) => meta.id === selectedProvider)) {
            setSelectedProvider(visibleProviders[0].id)
        }
    }, [selectedProvider, visibleProviders])

    const handleSave = async () => {
        const payload = {
            groq_keys: keys.groq.filter(k => k.trim()),
            anthropic_keys: keys.anthropic.filter(k => k.trim()),
            openai_keys: keys.openai.filter(k => k.trim()),
            openrouter_keys: keys.openrouter.filter(k => k.trim()),
            deepseek_keys: keys.deepseek.filter(k => k.trim()),
            scraper_url: scraperUrl,
            scraper_key: scraperKey,
        }
        try {
            await fetch('/api/settings/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
        } catch { }
        localStorage.setItem('llm_keys', JSON.stringify(payload))
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
    }

    const handleTest = async (providerId: string) => {
        setTestResults(r => ({ ...r, [providerId]: { status: 'testing', message: 'Verifying...' } }))
        try {
            const firstKey = providerId === 'groq' ? keys.groq[0]
                : providerId === 'anthropic' ? keys.anthropic[0]
                    : providerId === 'openai' ? keys.openai[0]
                        : providerId === 'openrouter' ? keys.openrouter[0]
                            : providerId === 'deepseek' ? keys.deepseek[0]
                                : ''
            const body: any = {
                provider: providerId === 'auto' ? 'groq' : providerId,
                api_key: firstKey || '',
                model: providerId === 'groq' ? 'llama-3.3-70b-versatile'
                    : providerId === 'anthropic' ? 'claude-3-5-haiku-latest'
                        : providerId === 'openai' ? 'gpt-4o-mini'
                            : providerId === 'openrouter' ? 'anthropic/claude-3.5-sonnet'
                                : providerId === 'deepseek' ? 'deepseek-chat'
                                    : 'deepseek',
            }
            if (providerId === 'scraper') {
                body.provider = 'scraper'
                body.scraper_url = scraperUrl
                body.api_key = scraperKey
            }
            const res = await fetch('/api/providers/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            const data = await res.json()
            setTestResults(r => ({
                ...r,
                [providerId]: {
                    status: data.status === 'ok' ? 'ok' : 'error',
                    message: data.status === 'ok'
                        ? `Connected Successfully`
                        : `${data.error?.slice(0, 80) || 'Auth Failed'}`,
                },
            }))
        } catch (e: any) {
            setTestResults(r => ({
                ...r,
                [providerId]: { status: 'error', message: `Engine error: ${e.message}` },
            }))
        }
    }

    return (
        <div style={{
            position: 'fixed', inset: 0,
            background: 'var(--color-bg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
        }}>
            <div style={{
                width: 680, height: '90vh',
                background: 'var(--color-bg)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
            }}>
                {/* Header */}
                <div style={{
                    padding: '24px 32px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--color-surface2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Settings2 size={18} />
                        </div>
                        <div>
                            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Settings</h2>
                            <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Configure your WAGI engine and API models</p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', padding: 8 }}
                    >
                        <X size={20} />
                    </button>
                </div>

                {/* Tabs */}
                <div style={{ display: 'flex', padding: '0 32px', gap: 8, marginBottom: 20 }}>
                    {[
                        { id: 'providers', label: 'Models & Engine', icon: <Zap size={14} /> },
                        { id: 'keys', label: 'Security & Keys', icon: <ShieldCheck size={14} /> },
                    ].map(t => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id as any)}
                            style={{
                                padding: '8px 16px',
                                background: tab === t.id ? 'var(--color-surface2)' : 'transparent',
                                border: 'none',
                                borderRadius: 10,
                                color: tab === t.id ? 'var(--color-text)' : 'var(--color-text-muted)',
                                cursor: 'pointer',
                                fontSize: 13,
                                fontWeight: 600,
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                transition: 'var(--transition)'
                            }}
                        >
                            {t.icon} {t.label}
                        </button>
                    ))}
                </div>

                {/* Body */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '0 32px 32px' }}>
                    {tab === 'providers' && (
                        <div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                                {visibleProviders.map(meta => (
                                    <ProviderCard
                                        key={meta.id}
                                        meta={meta}
                                        selected={selectedProvider === meta.id}
                                        onClick={() => setSelectedProvider(meta.id)}
                                    />
                                ))}
                            </div>

                            <div style={{ marginTop: 24, padding: 20, borderRadius: 12, background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
                                <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <TestTube size={14} /> Connection Tester
                                </h3>
                                <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 16 }}>
                                    WAGI will attempt a real handshake with the selected model to verify your configuration.
                                </p>
                                <button
                                    onClick={() => handleTest(selectedProvider)}
                                    disabled={testResults[selectedProvider]?.status === 'testing'}
                                    style={{
                                        padding: '10px 20px', borderRadius: 10,
                                        background: 'var(--color-text)',
                                        border: 'none',
                                        color: '#000', cursor: 'pointer', fontSize: 13,
                                        fontWeight: 600,
                                        opacity: testResults[selectedProvider]?.status === 'testing' ? 0.6 : 1,
                                    }}
                                >
                                    {testResults[selectedProvider]?.status === 'testing' ? 'Testing...' : 'Test Selected Engine'}
                                </button>
                                {testResults[selectedProvider]?.status && testResults[selectedProvider]?.status !== 'testing' && (
                                    <div style={{
                                        marginTop: 12, padding: 12, borderRadius: 8,
                                        fontSize: 12, background: 'var(--color-surface2)',
                                        color: testResults[selectedProvider].status === 'ok' ? 'var(--color-success)' : 'var(--color-error)',
                                        border: `1px solid ${testResults[selectedProvider].status === 'ok' ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}`
                                    }}>
                                        {testResults[selectedProvider].message}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {tab === 'keys' && (
                        <div style={{ maxWidth: 500 }}>
                            <MultiKeyInput label="Groq API Keys" keys={keys.groq} onChange={v => setKeys(k => ({ ...k, groq: v }))} />
                            <MultiKeyInput label="Anthropic API Keys" keys={keys.anthropic} onChange={v => setKeys(k => ({ ...k, anthropic: v }))} />
                            <MultiKeyInput label="OpenAI API Keys" keys={keys.openai} onChange={v => setKeys(k => ({ ...k, openai: v }))} />
                            <MultiKeyInput label="OpenRouter API Keys" keys={keys.openrouter} onChange={v => setKeys(k => ({ ...k, openrouter: v }))} />
                            <MultiKeyInput label="DeepSeek API Keys" keys={keys.deepseek} onChange={v => setKeys(k => ({ ...k, deepseek: v }))} />

                            <div style={{ marginTop: 32, padding: 24, borderRadius: 12, background: 'var(--color-surface2)' }}>
                                <label style={{ fontSize: 13, fontWeight: 700, display: 'block', marginBottom: 16 }}>
                                    <Server size={14} style={{ display: 'inline', marginRight: 8, verticalAlign: 'middle' }} />
                                    Scraper Gateway
                                </label>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    <input value={scraperUrl} onChange={e => setScraperUrl(e.target.value)} placeholder="URL" style={inputStyle} />
                                    <input type="password" value={scraperKey} onChange={e => setScraperKey(e.target.value)} placeholder="Secret Key" style={inputStyle} />
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div style={{
                    padding: '24px 32px',
                    borderTop: '1px solid var(--color-border)',
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: 12,
                }}>
                    {onClose && (
                        <button onClick={onClose} style={{ padding: '10px 20px', borderRadius: 10, background: 'transparent', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 13, fontWeight: 500 }}>
                            Cancel
                        </button>
                    )}
                    <button
                        onClick={handleSave}
                        style={{
                            padding: '10px 24px', borderRadius: 10,
                            background: saved ? 'var(--color-success)' : 'var(--color-text)',
                            border: 'none', color: '#000', cursor: 'pointer',
                            fontSize: 13, fontWeight: 700,
                            transition: 'var(--transition)',
                        }}
                    >
                        {saved ? 'Saved ✓' : 'Save Changes'}
                    </button>
                </div>
            </div>
        </div>
    )
}

const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '12px 16px',
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 10,
    color: 'var(--color-text)',
    fontSize: 13,
    fontFamily: 'var(--font-mono)',
    outline: 'none',
}

const iconBtnStyle: React.CSSProperties = {
    background: 'none',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    cursor: 'pointer',
    padding: '8px',
    display: 'flex',
    alignItems: 'center',
    transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
}

const addBtnStyle: React.CSSProperties = {
    background: 'transparent',
    border: '1px dashed var(--color-border)',
    borderRadius: 10,
    color: 'var(--color-text-muted)',
    cursor: 'pointer',
    fontSize: 12,
    padding: '10px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    justifyContent: 'center',
    transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
}
