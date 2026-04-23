import { useState } from 'react'
import { FileText, Folder, ChevronRight, ChevronDown, Download } from 'lucide-react'

interface FileTreeProps {
    files: Record<string, string>
    sessionId: string | null
}

interface TreeNode {
    name: string
    path: string
    isDir: boolean
    children: TreeNode[]
    content?: string
}

function buildTree(files: Record<string, string>): TreeNode[] {
    const root: Record<string, TreeNode> = {}

    for (const [path, content] of Object.entries(files)) {
        const parts = path.split('/')
        let current = root

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i]
            const isLast = i === parts.length - 1
            const fullPath = parts.slice(0, i + 1).join('/')

            if (!current[part]) {
                current[part] = {
                    name: part,
                    path: fullPath,
                    isDir: !isLast,
                    children: [],
                    content: isLast ? content : undefined,
                }
            }
            if (!isLast) {
                const childMap: Record<string, TreeNode> = {}
                for (const child of current[part].children) {
                    childMap[child.name] = child
                }
                current[part].children = Object.values(childMap)
                current = childMap
                // We need to refresh after this
                const existingChildren: Record<string, TreeNode> = {}
                for (const c of current[part]?.children || []) existingChildren[c.name] = c
                current = existingChildren
            }
        }
    }

    // Simpler approach: just list all files
    return Object.entries(files).map(([path, content]) => ({
        name: path.split('/').pop() || path,
        path,
        isDir: false,
        children: [],
        content,
    }))
}

function getFileExt(name: string): string {
    return name.split('.').pop() || ''
}

function getFileColor(name: string): string {
    const ext = getFileExt(name)
    const colors: Record<string, string> = {
        tsx: '#61dafb',
        jsx: '#61dafb',
        ts: '#3b82f6',
        js: '#f59e0b',
        css: '#a855f7',
        html: '#f97316',
        json: '#10b981',
        md: '#64748b',
        sql: '#ec4899',
    }
    return colors[ext] || '#64748b'
}

export default function FileTree({ files, sessionId }: FileTreeProps) {
    const [selectedFile, setSelectedFile] = useState<string | null>(null)
    const [showContent, setShowContent] = useState(false)

    const fileList = buildTree(files)

    const handleDownload = () => {
        if (!selectedFile || !files[selectedFile]) return
        const blob = new Blob([files[selectedFile]], { type: 'text/plain' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = selectedFile.split('/').pop() || 'file'
        a.click()
        URL.revokeObjectURL(url)
    }

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            background: 'var(--color-surface)',
        }}>
            {/* Header */}
            <div style={{
                padding: '10px 16px',
                borderBottom: '1px solid var(--color-border)',
                fontSize: 11,
                color: 'var(--color-text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
            }}>
                <span>Files ({Object.keys(files).length})</span>
                {selectedFile && (
                    <button
                        onClick={handleDownload}
                        className="btn btn-text"
                        style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, padding: "4px 8px" }}
                    >
                        <Download size={11} />
                        Save
                    </button>
                )}
            </div>

            {/* File list */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {fileList.length === 0 ? (
                    <div style={{
                        padding: 16,
                        color: 'var(--color-text-muted)',
                        fontSize: 12,
                        textAlign: 'center',
                    }}>
                        No files yet
                    </div>
                ) : (
                    fileList.map(file => (
                        <div
                            key={file.path}
                            id={`file-${file.path.replace(/[/.]/g, '-')}`}
                            onClick={() => {
                                setSelectedFile(file.path)
                                setShowContent(true)
                            }}
                            style={{
                                padding: '5px 16px',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                fontSize: 12,
                                background: selectedFile === file.path ? 'rgba(99,102,241,0.12)' : 'transparent',
                                borderLeft: selectedFile === file.path
                                    ? '2px solid var(--color-primary)'
                                    : '2px solid transparent',
                                transition: 'var(--transition)',
                            }}
                            onMouseEnter={e => {
                                if (selectedFile !== file.path) {
                                    e.currentTarget.style.background = 'var(--color-surface2)'
                                }
                            }}
                            onMouseLeave={e => {
                                if (selectedFile !== file.path) {
                                    e.currentTarget.style.background = 'transparent'
                                }
                            }}
                        >
                            <FileText size={12} color={getFileColor(file.name)} />
                            <span style={{
                                color: selectedFile === file.path ? 'var(--color-text)' : 'var(--color-text-muted)',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                flex: 1,
                            }}>
                                {file.path}
                            </span>
                            <span style={{
                                fontSize: 10,
                                color: getFileColor(file.name),
                                fontFamily: 'var(--font-mono)',
                            }}>
                                .{getFileExt(file.name)}
                            </span>
                        </div>
                    ))
                )}
            </div>

            {/* File content preview */}
            {showContent && selectedFile && files[selectedFile] && (
                <div style={{
                    height: '45%',
                    borderTop: '1px solid var(--color-border)',
                    display: 'flex',
                    flexDirection: 'column',
                }}>
                    <div style={{
                        padding: '6px 16px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        borderBottom: '1px solid var(--color-border)',
                        background: 'var(--color-surface2)',
                    }}>
                        <span style={{ fontSize: 11, color: getFileColor(selectedFile) }}>
                            {selectedFile.split('/').pop()}
                        </span>
                        <button
                            onClick={() => setShowContent(false)}
                            className="btn btn-text"
                            style={{ fontSize: 16, lineHeight: 1, padding: "4px 8px" }}
                        >
                            ×
                        </button>
                    </div>
                    <pre style={{
                        flex: 1,
                        overflowY: 'auto',
                        padding: '10px 16px',
                        margin: 0,
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        lineHeight: 1.6,
                        color: 'var(--color-text)',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                    }}>
                        {files[selectedFile]}
                    </pre>
                </div>
            )}
        </div>
    )
}
