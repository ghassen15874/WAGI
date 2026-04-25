import { useEffect, useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import { Save, Sparkles } from "lucide-react";

interface LivePreviewWorkbenchProps {
    files: Record<string, string>;
    output: string;
    mode: "code" | "manual";
    generationStatus: "idle" | "generating" | "done" | "error";
    onChangeFile: (path: string, content: string) => void;
    onSaveFile: (path: string, content: string) => Promise<boolean>;
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

    const handleSaveManualTarget = async () => {
        if (!manualTargetFile) return;
        setIsSaving(true);
        const ok = await onSaveFile(manualTargetFile, allFiles[manualTargetFile] || "");
        setIsSaving(false);
        setSaveMessage(ok ? `Saved ${manualTargetFile}` : `Failed to save ${manualTargetFile}`);
    };

    if (mode === "code") {
        return (
            <div
                style={{
                    display: "flex",
                    flexDirection: "column",
                    minHeight: 0,
                    height: "100%",
                    padding: 12,
                    background: "var(--color-surface)",
                    gap: 8,
                }}
            >
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "8px 10px",
                        border: "1px solid var(--color-border)",
                        borderRadius: 10,
                        background: "var(--color-surface2)",
                        flexShrink: 0,
                    }}
                >
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text)" }}>
                        File Code (Monaco Editor)
                    </span>
                    {generationStatus === "generating" && selectedFile && streamedFiles[selectedFile] && (
                        <span
                            style={{
                                fontSize: 10,
                                borderRadius: 999,
                                padding: "2px 8px",
                                background: "rgba(99,102,241,0.15)",
                                color: "var(--color-primary)",
                                fontWeight: 600,
                                letterSpacing: "0.03em",
                            }}
                        >
                            STREAMING
                        </span>
                    )}
                    <select
                        value={selectedFile}
                        onChange={(event) => setSelectedFile(event.target.value)}
                        style={{
                            marginLeft: "auto",
                            maxWidth: 360,
                            background: "var(--color-surface)",
                            color: "var(--color-text)",
                            border: "1px solid var(--color-border)",
                            borderRadius: 8,
                            padding: "6px 8px",
                            fontSize: 12,
                        }}
                    >
                        {filePaths.map((path) => (
                            <option key={path} value={path}>
                                {path}
                            </option>
                        ))}
                    </select>
                    <button
                        onClick={handleSaveCurrentFile}
                        disabled={!selectedFile || isSaving}
                        className="btn btn-primary"
                        style={{ padding: "6px 10px", fontSize: 12 }}
                    >
                        <Save size={13} /> {isSaving ? "Saving..." : "Save File"}
                    </button>
                </div>

                <div style={{ flex: 1, minHeight: 0, border: "1px solid var(--color-border)", borderRadius: 10, overflow: "hidden" }}>
                    <Editor
                        height="100%"
                        language={
                            selectedFile.endsWith(".tsx")
                                ? "typescript"
                                : selectedFile.endsWith(".ts")
                                    ? "typescript"
                                    : selectedFile.endsWith(".jsx")
                                        ? "javascript"
                                        : selectedFile.endsWith(".js")
                                            ? "javascript"
                                            : selectedFile.endsWith(".json")
                                                ? "json"
                                                : selectedFile.endsWith(".css")
                                                    ? "css"
                                                    : "plaintext"
                        }
                        theme="vs-dark"
                        value={currentCode}
                        onChange={(value) => {
                            if (!selectedFile) return;
                            onChangeFile(selectedFile, value ?? "");
                        }}
                        options={{
                            minimap: { enabled: false },
                            fontSize: 12,
                            lineNumbers: "on",
                            wordWrap: "on",
                            scrollBeyondLastLine: false,
                            automaticLayout: true,
                        }}
                    />
                </div>
            </div>
        );
    }

    return (
        <div
            style={{
                border: "1px solid var(--color-border)",
                borderRadius: 10,
                background: "var(--color-surface2)",
                margin: 12,
                padding: 10,
                height: "calc(100% - 24px)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                overflowY: "auto",
            }}
        >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text)" }}>
                    Manual Edit (after generation)
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                    {generationStatus === "generating" ? "Generating..." : "Ready"}
                </div>
            </div>
            <select
                value={manualTargetFile}
                onChange={(event) => setManualTargetFile(event.target.value)}
                style={{
                    background: "var(--color-surface)",
                    color: "var(--color-text)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 8,
                    padding: "6px 8px",
                    fontSize: 12,
                }}
            >
                {filePaths.map((path) => (
                    <option key={path} value={path}>
                        {path}
                    </option>
                ))}
            </select>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontWeight: 600 }}>
                Website Colors (palette)
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, alignItems: "center" }}>
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Primary</label>
                <input
                    type="color"
                    value={manualPrimaryColor}
                    onChange={(event) => setManualPrimaryColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Secondary</label>
                <input
                    type="color"
                    value={manualSecondaryColor}
                    onChange={(event) => setManualSecondaryColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Accent</label>
                <input
                    type="color"
                    value={manualAccentColor}
                    onChange={(event) => setManualAccentColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Background</label>
                <input
                    type="color"
                    value={manualBackgroundColor}
                    onChange={(event) => setManualBackgroundColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Text / Foreground</label>
                <input
                    type="color"
                    value={manualForegroundColor}
                    onChange={(event) => setManualForegroundColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Muted</label>
                <input
                    type="color"
                    value={manualMutedColor}
                    onChange={(event) => setManualMutedColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Card</label>
                <input
                    type="color"
                    value={manualCardColor}
                    onChange={(event) => setManualCardColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Border</label>
                <input
                    type="color"
                    value={manualBorderColor}
                    onChange={(event) => setManualBorderColor(event.target.value)}
                    style={{ width: 50, height: 28, border: "none", background: "transparent", cursor: "pointer" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Title Text</label>
                <input
                    value={manualTitle}
                    onChange={(event) => setManualTitle(event.target.value)}
                    placeholder="New H1 title"
                    style={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)", padding: "6px 8px" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Button Text</label>
                <input
                    value={manualButtonText}
                    onChange={(event) => setManualButtonText(event.target.value)}
                    placeholder="New button label"
                    style={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)", padding: "6px 8px" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Find Text</label>
                <input
                    value={manualFindText}
                    onChange={(event) => setManualFindText(event.target.value)}
                    placeholder="Text to find"
                    style={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)", padding: "6px 8px" }}
                />
                <label style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Replace With</label>
                <input
                    value={manualReplaceText}
                    onChange={(event) => setManualReplaceText(event.target.value)}
                    placeholder="Replacement text"
                    style={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--color-border)", padding: "6px 8px" }}
                />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
                <button onClick={applyManualEdit} className="btn btn-ghost" style={{ padding: "6px 10px", fontSize: 12 }}>
                    <Sparkles size={13} /> Apply To Target File
                </button>
                <button onClick={applyPaletteToAllFiles} className="btn btn-ghost" style={{ padding: "6px 10px", fontSize: 12 }}>
                    <Sparkles size={13} /> Apply Colors To All Files
                </button>
                <button onClick={handleSaveManualTarget} disabled={isSaving || !manualTargetFile} className="btn btn-primary" style={{ padding: "6px 10px", fontSize: 12 }}>
                    <Save size={13} /> Save Component File
                </button>
            </div>
            <div style={{ fontSize: 11, color: generationStatus === "error" ? "var(--color-error)" : "var(--color-text-muted)" }}>
                {saveMessage || "Tip: use Monaco for full edits, and manual controls for fast color/title/button updates."}
            </div>
        </div>
    );
}
