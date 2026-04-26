import { useEffect, useMemo, useState, useRef, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import Editor from "@monaco-editor/react";
import {
    Save, Sparkles, FileCode, Edit3, Palette, Check,
    ChevronDown, RefreshCw, Layers, Layout, Type, MousePointer2, Search,
    FileJson, FileText, File
} from "lucide-react";

interface LivePreviewWorkbenchProps {
    files: Record<string, string>;
    output: string;
    mode: "code" | "manual";
    generationStatus: "idle" | "generating" | "done" | "error";
    onChangeFile: (path: string, content: string) => void;
    onSaveFile: (path: string, content: string) => Promise<boolean>;
}

function CustomSearchSelect({
    value,
    options,
    onChange,
    placeholder
}: {
    value: string;
    options: string[];
    onChange: (val: string) => void;
    placeholder: string;
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState("");
    const containerRef = useRef<HTMLDivElement>(null);
    const [coords, setCoords] = useState({ top: 0, left: 0, width: 0 });

    useLayoutEffect(() => {
        if (isOpen && containerRef.current) {
            const rect = containerRef.current.getBoundingClientRect();
            setCoords({
                top: rect.bottom + window.scrollY,
                left: rect.left + window.scrollX,
                width: rect.width
            });
        }
    }, [isOpen]);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                // If the target is in the portal, don't close. 
                // But portals to document.body are outside. 
                // We'll trust the portal handles clicks or check event target.
                const portalNode = document.getElementById('workbench-dropdown-portal');
                if (portalNode && portalNode.contains(event.target as Node)) return;
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const filtered = options.filter(opt =>
        opt.toLowerCase().includes(search.toLowerCase())
    );

    const getFileIcon = (path: string) => {
        if (path.endsWith('.json')) return <FileJson size={14} />;
        if (path.endsWith('.css')) return <Palette size={14} />;
        if (path.endsWith('.tsx') || path.endsWith('.ts') || path.endsWith('.js')) return <FileCode size={14} />;
        if (path.endsWith('.html')) return <Layout size={14} />;
        if (path.endsWith('.md')) return <FileText size={14} />;
        return <File size={14} />;
    };

    const dropdownMenu = isOpen && (
        <div
            id="workbench-dropdown-portal"
            className="glass"
            style={{
                position: "absolute",
                top: coords.top + 8,
                left: coords.left,
                width: coords.width,
                zIndex: 10000,
                maxHeight: 320,
                overflow: "hidden",
                display: "flex",
                flexDirection: "column",
                borderRadius: 16,
                boxShadow: "var(--shadow-xl)",
                animation: "fadeIn 0.2s ease forwards",
                padding: 8,
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                backdropFilter: 'blur(16px)'
            }}
        >
            <div style={{ position: 'relative', marginBottom: 6 }}>
                <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', opacity: 0.3 }} />
                <input
                    autoFocus
                    placeholder="Search files..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Escape') setIsOpen(false);
                        if (e.key === 'Enter' && filtered.length > 0) {
                            onChange(filtered[0]);
                            setIsOpen(false);
                            setSearch("");
                        }
                    }}
                    style={{
                        width: '100%',
                        padding: '10px 12px 10px 36px',
                        background: 'var(--color-surface3)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 10,
                        fontSize: 13,
                        color: 'var(--color-text)',
                        outline: 'none'
                    }}
                />
            </div>

            <div style={{ overflowY: 'auto', flex: 1 }}>
                {filtered.length === 0 ? (
                    <div style={{ padding: '20px', textAlign: 'center', fontSize: 12, color: 'var(--color-text-muted)' }}>
                        No files found
                    </div>
                ) : (
                    filtered.map((opt) => (
                        <div
                            key={opt}
                            onClick={() => {
                                onChange(opt);
                                setIsOpen(false);
                                setSearch("");
                            }}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 10,
                                padding: '10px 12px',
                                borderRadius: 8,
                                fontSize: 13,
                                fontWeight: value === opt ? 700 : 500,
                                background: value === opt ? 'var(--color-accent-muted)' : 'transparent',
                                color: value === opt ? 'var(--color-accent)' : 'var(--color-text)',
                                cursor: 'pointer',
                            }}
                            onMouseEnter={(e) => {
                                if (value !== opt) e.currentTarget.style.background = 'var(--color-surface2)';
                            }}
                            onMouseLeave={(e) => {
                                if (value !== opt) e.currentTarget.style.background = 'transparent';
                            }}
                        >
                            <div style={{ opacity: 0.5 }}>{getFileIcon(opt)}</div>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{opt}</span>
                            {value === opt && <Check size={14} style={{ marginLeft: 'auto' }} />}
                        </div>
                    ))
                )}
            </div>
        </div>
    );

    return (
        <div ref={containerRef} style={{ position: "relative", width: "100%", maxWidth: 300 }}>
            <div
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    padding: "10px 16px",
                    background: "var(--color-surface2)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 12,
                    cursor: "pointer",
                    fontSize: 14,
                    fontWeight: 500,
                    transition: "all var(--transition)",
                }}
                onMouseEnter={(e) => e.currentTarget.style.borderColor = "var(--color-accent-muted)"}
                onMouseLeave={(e) => !isOpen && (e.currentTarget.style.borderColor = "var(--color-border)")}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, overflow: 'hidden' }}>
                    <div style={{ opacity: 0.5, flexShrink: 0 }}>{getFileIcon(value)}</div>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {value || placeholder}
                    </span>
                </div>
                <ChevronDown size={16} style={{ transition: 'transform 0.2s', transform: isOpen ? 'rotate(180deg)' : 'none', opacity: 0.5 }} />
            </div>

            {isOpen && createPortal(dropdownMenu, document.body)}
        </div>
    );
}

type PaletteKey =
    | "primary"
    | "secondary"
    | "accent"
    | "background"
    | "foreground"
    | "muted"
    | "card"
    | "border";

type PaletteValues = Record<PaletteKey, string>;

const PALETTE_VAR_MAP: Record<PaletteKey, string> = {
    primary: "--color-primary",
    secondary: "--color-secondary",
    accent: "--color-accent",
    background: "--color-background",
    foreground: "--color-foreground",
    muted: "--color-muted",
    card: "--color-card",
    border: "--color-border",
};

const DEFAULT_PALETTE: PaletteValues = {
    primary: "#334155",
    secondary: "#475569",
    accent: "#059669",
    background: "#f8fafc",
    foreground: "#0f172a",
    muted: "#cbd5e1",
    card: "#ffffff",
    border: "#e2e8f0",
};

function escapeRegExp(value: string) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractHexColor(value: string) {
    const match = value.match(/#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/);
    return match ? match[0] : null;
}

function detectPalette(files: Record<string, string>): PaletteValues {
    const entries = Object.entries(files).sort(([a], [b]) => {
        const rank = (path: string) => {
            if (path.endsWith("variables.css")) return 0;
            if (path.endsWith(".css")) return 1;
            return 2;
        };
        return rank(a) - rank(b);
    });

    const nextPalette: PaletteValues = { ...DEFAULT_PALETTE };
    const remainingKeys = new Set<PaletteKey>(Object.keys(PALETTE_VAR_MAP) as PaletteKey[]);

    for (const [, content] of entries) {
        if (!remainingKeys.size) break;
        for (const key of Array.from(remainingKeys)) {
            const cssVar = PALETTE_VAR_MAP[key];
            const regex = new RegExp(`${escapeRegExp(cssVar)}\\s*:\\s*([^;]+);`, "i");
            const match = content.match(regex);
            if (!match) continue;
            const hex = extractHexColor(match[1]);
            if (hex) {
                nextPalette[key] = hex;
                remainingKeys.delete(key);
            }
        }
    }

    return nextPalette;
}

function applyPaletteVariables(content: string, palette: PaletteValues) {
    let next = content;
    for (const key of Object.keys(PALETTE_VAR_MAP) as PaletteKey[]) {
        const cssVar = PALETTE_VAR_MAP[key];
        const value = palette[key];
        const regex = new RegExp(`(${escapeRegExp(cssVar)}\\s*:\\s*)[^;]+;`, "gi");
        next = next.replace(regex, `$1${value};`);
    }
    return next;
}

function decodeEscapedContent(value: string) {
    return value
        .replace(/\\r/g, "\r")
        .replace(/\\n/g, "\n")
        .replace(/\\t/g, "\t")
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, "\\");
}

function extractStreamedFilesFromOutput(output: string): Record<string, string> {
    const map: Record<string, string> = {};
    const text = String(output || "");

    const jsonPairRegex = /"path"\s*:\s*"((?:\\.|[^"\\])*)"\s*,\s*"content"\s*:\s*"((?:\\.|[^"\\])*)"/g;
    let pairMatch: RegExpExecArray | null = jsonPairRegex.exec(text);
    while (pairMatch) {
        const path = decodeEscapedContent(pairMatch[1]);
        const content = decodeEscapedContent(pairMatch[2]);
        if (path) {
            map[path] = content;
        }
        pairMatch = jsonPairRegex.exec(text);
    }

    const fileSectionRegex = /\/\/ FILE:\s*([^\n]+)\n([\s\S]*?)(?=\n\/\/ FILE:|\n📁 Fixed:|\n(?:✅|❌|⚠️|ℹ️|🤖|🛠️|⚙️|🚀|🔍|⏳)|$)/g;
    let sectionMatch: RegExpExecArray | null = fileSectionRegex.exec(text);
    while (sectionMatch) {
        const path = sectionMatch[1].trim();
        const content = sectionMatch[2].replace(/\n+$/, "");
        if (path && content) {
            map[path] = content;
        }
        sectionMatch = fileSectionRegex.exec(text);
    }

    return map;
}

export default function LivePreviewWorkbench({
    files,
    output,
    mode,
    generationStatus,
    onChangeFile,
    onSaveFile,
}: LivePreviewWorkbenchProps) {
    const streamedFiles = useMemo(() => extractStreamedFilesFromOutput(output), [output]);
    const allFiles = useMemo(() => ({ ...streamedFiles, ...files }), [streamedFiles, files]);
    const filePaths = useMemo(() => Object.keys(allFiles).sort(), [allFiles]);
    const detectedPalette = useMemo(() => detectPalette(allFiles), [allFiles]);
    const fileListFingerprint = useMemo(() => filePaths.join("|"), [filePaths]);
    const [selectedFile, setSelectedFile] = useState<string>("");
    const [manualTargetFile, setManualTargetFile] = useState<string>("");
    const [isSaving, setIsSaving] = useState(false);
    const [saveMessage, setSaveMessage] = useState("");

    const [manualPrimaryColor, setManualPrimaryColor] = useState(DEFAULT_PALETTE.primary);
    const [manualSecondaryColor, setManualSecondaryColor] = useState(DEFAULT_PALETTE.secondary);
    const [manualAccentColor, setManualAccentColor] = useState(DEFAULT_PALETTE.accent);
    const [manualBackgroundColor, setManualBackgroundColor] = useState(DEFAULT_PALETTE.background);
    const [manualForegroundColor, setManualForegroundColor] = useState(DEFAULT_PALETTE.foreground);
    const [manualMutedColor, setManualMutedColor] = useState(DEFAULT_PALETTE.muted);
    const [manualCardColor, setManualCardColor] = useState(DEFAULT_PALETTE.card);
    const [manualBorderColor, setManualBorderColor] = useState(DEFAULT_PALETTE.border);
    const [manualTitle, setManualTitle] = useState("");
    const [manualButtonText, setManualButtonText] = useState("");
    const [manualFindText, setManualFindText] = useState("");
    const [manualReplaceText, setManualReplaceText] = useState("");

    useEffect(() => {
        if (!filePaths.length) {
            setSelectedFile("");
            setManualTargetFile("");
            return;
        }
        if (!selectedFile || !filePaths.includes(selectedFile)) {
            setSelectedFile(filePaths[0]);
        }
        if (!manualTargetFile || !filePaths.includes(manualTargetFile)) {
            setManualTargetFile(filePaths[0]);
        }
    }, [filePaths, selectedFile, manualTargetFile]);

    useEffect(() => {
        setManualPrimaryColor(detectedPalette.primary);
        setManualSecondaryColor(detectedPalette.secondary);
        setManualAccentColor(detectedPalette.accent);
        setManualBackgroundColor(detectedPalette.background);
        setManualForegroundColor(detectedPalette.foreground);
        setManualMutedColor(detectedPalette.muted);
        setManualCardColor(detectedPalette.card);
        setManualBorderColor(detectedPalette.border);
    }, [fileListFingerprint, detectedPalette]);

    const currentCode = selectedFile ? allFiles[selectedFile] || "" : "";

    const currentPalette: PaletteValues = {
        primary: manualPrimaryColor,
        secondary: manualSecondaryColor,
        accent: manualAccentColor,
        background: manualBackgroundColor,
        foreground: manualForegroundColor,
        muted: manualMutedColor,
        card: manualCardColor,
        border: manualBorderColor,
    };

    const applyManualEdit = async () => {
        if (!manualTargetFile) return;
        setIsSaving(true);
        setSaveMessage(`Applying and saving to ${manualTargetFile}...`);

        const source = allFiles[manualTargetFile] || "";
        let next = applyPaletteVariables(source, currentPalette);

        if (manualPrimaryColor.trim()) {
            if (/--color-primary\s*:\s*[^;]+;/i.test(next)) {
                next = next.replace(/(--color-primary\s*:\s*)[^;]+;/i, `$1${manualPrimaryColor};`);
            } else if (/#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b/.test(next)) {
                next = next.replace(/#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b/, manualPrimaryColor);
            }
        }

        if (manualTitle.trim()) {
            next = next.replace(
                /(<h1\b[^>]*>)([\s\S]*?)(<\/h1>)/i,
                (_match, start, _content, end) => `${start}${manualTitle}${end}`
            );
        }

        if (manualButtonText.trim()) {
            next = next.replace(
                /(<button\b[^>]*>)([\s\S]*?)(<\/button>)/i,
                (_match, start, _content, end) => `${start}${manualButtonText}${end}`
            );
        }

        if (manualFindText.trim()) {
            const findPattern = new RegExp(escapeRegExp(manualFindText), "g");
            next = next.replace(findPattern, manualReplaceText);
        }

        onChangeFile(manualTargetFile, next);
        const ok = await onSaveFile(manualTargetFile, next);
        setIsSaving(false);
        setSaveMessage(ok ? `Successfully applied and saved to ${manualTargetFile}.` : `Applied locally but failed to save to ${manualTargetFile}.`);
    };

    const applyPaletteToAllFiles = async () => {
        const replacementPairs = (Object.keys(PALETTE_VAR_MAP) as PaletteKey[])
            .map((key) => [detectedPalette[key], currentPalette[key]] as const)
            .filter(([from, to]) => from && to && from.toLowerCase() !== to.toLowerCase());

        let changedFilesCount = 0;
        const toSave: { path: string; content: string }[] = [];

        for (const path of filePaths) {
            const source = allFiles[path] || "";
            let next = applyPaletteVariables(source, currentPalette);

            for (const [from, to] of replacementPairs) {
                const replaceRegex = new RegExp(escapeRegExp(from), "gi");
                next = next.replace(replaceRegex, to);
            }

            if (next !== source) {
                toSave.push({ path, content: next });
            }
        }

        if (toSave.length === 0) {
            setSaveMessage("No color updates were needed.");
            return;
        }

        setIsSaving(true);
        let successCount = 0;
        for (const item of toSave) {
            setSaveMessage(`Saving palette changes: ${successCount + 1}/${toSave.length} (${item.path})...`);
            onChangeFile(item.path, item.content);
            const ok = await onSaveFile(item.path, item.content);
            if (ok) successCount += 1;
        }

        setIsSaving(false);
        setSaveMessage(`Successfully updated and saved palette in ${successCount} files.`);
    };

    const handleSaveCurrentFile = async () => {
        if (!selectedFile) return;
        setIsSaving(true);
        const ok = await onSaveFile(selectedFile, allFiles[selectedFile] || "");
        setIsSaving(false);
        setSaveMessage(ok ? `Saved ${selectedFile}` : `Failed to save ${selectedFile}`);
    };

    if (mode === "code") {
        return (
            <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--color-bg)", padding: '16px', gap: '12px' }}>
                {/* Monaco Header */}
                <div className="glass" style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 20px',
                    gap: '16px',
                    borderRadius: 'var(--radius-lg)'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--color-accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <FileCode size={18} color="var(--color-accent)" />
                        </div>
                        <div>
                            <div style={{ fontSize: 13, fontWeight: 700 }}>Code Editor</div>
                            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{selectedFile}</div>
                        </div>
                        {generationStatus === "generating" && (
                            <div style={{ marginLeft: 12, display: 'flex', alignItems: 'center', gap: 6, padding: '2px 10px', borderRadius: 20, background: 'var(--color-primary-glow)', border: '1px solid var(--color-border)' }}>
                                <RefreshCw size={12} className="animate-spin" />
                                <span style={{ fontSize: 10, fontWeight: 700 }}>STREAMING CONTENT</span>
                            </div>
                        )}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <CustomSearchSelect
                            value={selectedFile}
                            options={filePaths}
                            onChange={setSelectedFile}
                            placeholder="Select file..."
                        />

                        <button
                            onClick={handleSaveCurrentFile}
                            disabled={!selectedFile || isSaving}
                            className="btn btn-primary"
                            style={{ height: '38px', padding: '0 20px', gap: 8, fontSize: 13 }}
                        >
                            {isSaving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                            Save File
                        </button>
                    </div>
                </div>

                {/* Editor Container */}
                <div style={{ flex: 1, minHeight: 0, borderRadius: 'var(--radius-lg)', overflow: 'hidden', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-lg)' }}>
                    <Editor
                        height="100%"
                        language={getEditorLanguage(selectedFile)}
                        theme="vs-dark"
                        value={currentCode}
                        onChange={(val) => selectedFile && onChangeFile(selectedFile, val || "")}
                        options={{
                            minimap: { enabled: false },
                            fontSize: 13,
                            lineNumbers: "on",
                            wordWrap: "on",
                            scrollBeyondLastLine: false,
                            automaticLayout: true,
                            padding: { top: 16 }
                        }}
                    />
                </div>
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--color-bg)", padding: '16px', gap: '24px', overflowY: 'auto' }}>
            <header style={{ padding: '0 8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                    <div style={{ width: 40, height: 40, borderRadius: 12, background: 'var(--gradient-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
                        <Edit3 size={20} />
                    </div>
                    <div>
                        <h2 style={{ fontSize: 24, fontWeight: 800 }}>Manual Edit</h2>
                        <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Fine-tune your website visually without diving into code.</p>
                    </div>
                </div>
            </header>

            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
                {/* Left Column: Color Palette */}
                <div className="glass" style={{ padding: '32px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
                        <Palette size={20} color="var(--color-accent)" />
                        <h3 style={{ fontSize: 18, fontWeight: 700 }}>Website Colors</h3>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                        {[
                            { key: 'primary' as const, label: 'Primary', val: manualPrimaryColor, set: setManualPrimaryColor },
                            { key: 'secondary' as const, label: 'Secondary', val: manualSecondaryColor, set: setManualSecondaryColor },
                            { key: 'accent' as const, label: 'Accent', val: manualAccentColor, set: setManualAccentColor },
                            { key: 'background' as const, label: 'Background', val: manualBackgroundColor, set: setManualBackgroundColor },
                            { key: 'foreground' as const, label: 'Text', val: manualForegroundColor, set: setManualForegroundColor },
                            { key: 'muted' as const, label: 'Muted', val: manualMutedColor, set: setManualMutedColor },
                            { key: 'card' as const, label: 'Card', val: manualCardColor, set: setManualCardColor },
                            { key: 'border' as const, label: 'Border', val: manualBorderColor, set: setManualBorderColor },
                        ].map((c) => (
                            <div key={c.key} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--color-surface2)', borderRadius: 12, border: '1px solid var(--color-border)' }}>
                                <div style={{ position: 'relative', width: 32, height: 32 }}>
                                    <input
                                        type="color"
                                        value={c.val}
                                        onChange={(e) => c.set(e.target.value)}
                                        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0, cursor: 'pointer' }}
                                    />
                                    <div style={{ width: '100%', height: '100%', borderRadius: '50%', background: c.val, border: '2px solid #fff', boxShadow: '0 0 0 1px var(--color-border)' }} />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 10, fontWeight: 800, textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 2 }}>{c.label}</div>
                                    <div style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{c.val.toUpperCase()}</div>
                                </div>
                            </div>
                        ))}
                    </div>

                    <div style={{ marginTop: 32, display: 'flex', gap: 12 }}>
                        <button onClick={applyPaletteToAllFiles} className="btn-secondary" style={{ flex: 1, padding: '12px 20px', gap: 8 }}>
                            <Layers size={16} /> Apply Colors to All Files
                        </button>
                    </div>
                </div>

                {/* Right Column: Content & Targets */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                    <div className="glass" style={{ padding: '32px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
                            <Layout size={20} color="var(--color-accent)" />
                            <h3 style={{ fontSize: 18, fontWeight: 700 }}>Target & Content</h3>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                            <div>
                                <label style={labelStyle}>Target Component File</label>
                                <CustomSearchSelect
                                    value={manualTargetFile}
                                    options={filePaths}
                                    onChange={setManualTargetFile}
                                    placeholder="Select component..."
                                />
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                                <div>
                                    <label style={labelStyle}>Header (H1) Text</label>
                                    <div style={{ position: 'relative' }}>
                                        <Type size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted2)' }} />
                                        <input value={manualTitle} onChange={(e) => setManualTitle(e.target.value)} placeholder="New site title..." style={{ ...inputStyle, paddingLeft: 36 }} />
                                    </div>
                                </div>
                                <div>
                                    <label style={labelStyle}>Button Label</label>
                                    <div style={{ position: 'relative' }}>
                                        <MousePointer2 size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted2)' }} />
                                        <input value={manualButtonText} onChange={(e) => setManualButtonText(e.target.value)} placeholder="Click here..." style={{ ...inputStyle, paddingLeft: 36 }} />
                                    </div>
                                </div>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                                <div>
                                    <label style={labelStyle}>Find Text</label>
                                    <div style={{ position: 'relative' }}>
                                        <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted2)' }} />
                                        <input value={manualFindText} onChange={(e) => setManualFindText(e.target.value)} placeholder="Old text..." style={{ ...inputStyle, paddingLeft: 36 }} />
                                    </div>
                                </div>
                                <div>
                                    <label style={labelStyle}>Replace With</label>
                                    <div style={{ position: 'relative' }}>
                                        <Check size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted2)' }} />
                                        <input value={manualReplaceText} onChange={(e) => setManualReplaceText(e.target.value)} placeholder="New text..." style={{ ...inputStyle, paddingLeft: 36 }} />
                                    </div>
                                </div>
                            </div>

                            <button onClick={applyManualEdit} disabled={isSaving || !manualTargetFile} className="btn-primary" style={{ height: 48, marginTop: 12, gap: 10 }}>
                                {isSaving ? <RefreshCw size={18} className="animate-spin" /> : <Sparkles size={18} />}
                                Apply Manual Changes
                            </button>
                        </div>
                    </div>

                    <div style={{ padding: '16px 24px', borderRadius: 16, background: 'var(--color-surface2)', border: '1px solid var(--color-border)', fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                        <span style={{ fontWeight: 700, color: 'var(--color-text)', display: 'block', marginBottom: 4 }}>Pro Tip:</span>
                        Use the **Code** tab for granular edits. Manual mode is best for quick visual iterations on colors and key copy.
                        {saveMessage && <div style={{ marginTop: 12, color: 'var(--color-accent)', fontWeight: 600 }}>{saveMessage}</div>}
                    </div>
                </div>
            </div>
        </div>
    );
}

function getEditorLanguage(path: string) {
    if (path.endsWith(".tsx") || path.endsWith(".ts")) return "typescript";
    if (path.endsWith(".jsx") || path.endsWith(".js")) return "javascript";
    if (path.endsWith(".json")) return "json";
    if (path.endsWith(".css")) return "css";
    if (path.endsWith(".html")) return "html";
    return "plaintext";
}

const labelStyle: React.CSSProperties = {
    fontSize: 11, fontWeight: 800, color: 'var(--color-text-muted2)',
    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6, display: 'block'
}

const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 16px', borderRadius: 10,
    background: 'var(--color-surface2)', border: '1px solid var(--color-border)',
    color: 'var(--color-text)', fontSize: 14, outline: 'none', transition: 'var(--transition)',
    appearance: 'none'
}
