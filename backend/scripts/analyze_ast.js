
const fs = require('fs');
const pathLib = require('path');
const { parse } = require('acorn');

const path = process.argv[2];
const relativePath = process.argv[3] || path;
if (!path) {
    console.error("Usage: node analyze_ast.js <file_path> [relative_path]");
    process.exit(1);
}

try {
    const code = fs.readFileSync(path, 'utf8');
    const ast = parse(code, {
        ecmaVersion: 'latest',
        sourceType: 'module'
    });

    const metadata = {
        filename: pathLib.basename(relativePath),
        relative_path: relativePath.replace(/\\/g, '/'),
        exports: [],
        imports: [],
        api_calls: [],
        ast_summary: {
            functions: [],
            classes: []
        }
    };

    // Simple AST Walker
    function walk(node) {
        if (!node) return;

        // 1. Exports
        if (node.type === 'ExportNamedDeclaration') {
            if (node.declaration) {
                if (node.declaration.id) metadata.exports.push(node.declaration.id.name);
                if (node.declaration.declarations) {
                    node.declaration.declarations.forEach(d => {
                        if (d.id) metadata.exports.push(d.id.name);
                    });
                }
            }
            if (node.specifiers) {
                node.specifiers.forEach(s => metadata.exports.push(s.exported.name));
            }
        }
        if (node.type === 'ExportDefaultDeclaration') {
            if (node.declaration.id) {
                metadata.exports.push(node.declaration.id.name);
            } else if (node.declaration.type === 'Identifier') {
                metadata.exports.push(node.declaration.name);
            } else {
                metadata.exports.push("default");
            }
        }

        // 2. Imports
        if (node.type === 'ImportDeclaration') {
            metadata.imports.push(node.source.value);
        }
        if (
            node.type === 'Literal'
            && typeof node.value === 'string'
            && /^\/api(?:\/|$)/.test(node.value)
        ) {
            metadata.api_calls.push(node.value);
        }

        // 3. Summaries
        if (node.type === 'FunctionDeclaration' && node.id) {
            metadata.ast_summary.functions.push(node.id.name);
        }
        if (node.type === 'ClassDeclaration' && node.id) {
            metadata.ast_summary.classes.push(node.id.name);
        }

        for (const key in node) {
            const child = node[key];
            if (Array.isArray(child)) {
                child.forEach(c => walk(c));
            } else if (child && typeof child === 'object' && child.type) {
                walk(child);
            }
        }
    }

    walk(ast);
    console.log(JSON.stringify(metadata, null, 2));

} catch (err) {
    // Fallback if acorn fails (might be JSX or non-standard)
    // Here we'd typically have a fallback or return error
    console.error(err.message);
    process.exit(1);
}
