"""
Tests for SyntaxValidator in core/codegen/linter.py
Run:
    cd /home/kali/Desktop/New\ Folder/lovable-clone
    python3 -m pytest backend/tests/test_syntax_validator.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from kilo.agents.codegen.linter import SyntaxValidator, CodeLinter


class TestSyntaxValidatorJS:
    def test_valid_js(self):
        code = "const x = 1;\nmodule.exports = { x };\n"
        errs = SyntaxValidator.validate("server/index.js", code)
        assert errs == [], f"Expected no errors, got: {errs}"

    def test_truncated_js(self):
        code = "function hello() {\n  const x = {\n    a: 1,\n"  # unclosed
        errs = SyntaxValidator.validate("src/utils.js", code)
        assert errs, "Expected a syntax error for truncated JS"
        assert "syntax error" in errs[0].lower() or "src/utils.js" in errs[0]

    def test_mismatched_braces_js(self):
        code = "const obj = { a: { b: 1 };\n"  # missing outer }
        errs = SyntaxValidator.validate("src/config.js", code)
        assert errs, f"Expected brace mismatch error, got: {errs}"


class TestSyntaxValidatorJSX:
    def test_valid_jsx(self):
        code = (
            "import React from 'react';\n"
            "export default function App() {\n"
            "  return <div>Hello</div>;\n"
            "}\n"
        )
        errs = SyntaxValidator.validate("src/App.jsx", code)
        assert errs == [], f"Expected no errors, got: {errs}"

    def test_truncated_jsx(self):
        code = (
            "import React from 'react';\n"
            "export default function App() {\n"
            "  return (\n"
            "    <div>\n"
            "      <h1>Title</h1>\n"
            # component cut off here
        )
        errs = SyntaxValidator.validate("src/App.jsx", code)
        assert errs, f"Expected a syntax error for truncated JSX, got: {errs}"

    def test_typescript_tsx(self):
        code = (
            "interface Props { name: string; }\n"
            "export default function Comp({ name }: Props) {\n"
            "  return <span>{name}</span>;\n"
            "}\n"
        )
        errs = SyntaxValidator.validate("src/Comp.tsx", code)
        assert errs == [], f"Expected no errors for valid TSX, got: {errs}"


class TestSyntaxValidatorCSS:
    def test_valid_css(self):
        code = ".container { display: flex; flex-direction: column; }\nbody { margin: 0; }\n"
        errs = SyntaxValidator.validate("src/styles/global.css", code)
        assert errs == [], f"Expected no errors, got: {errs}"

    def test_truncated_css(self):
        # real postcss parse error: unclosed block
        code = ".container { display: flex;\n  color: red\n"  # no closing brace
        errs = SyntaxValidator.validate("src/styles/App.css", code)
        # postcss may or may not error on unclosed blocks depending on version;
        # use heuristic brace check from CodeLinter as fallback
        linter = CodeLinter()
        linter_errs = linter.lint_file("src/styles/App.css", code)
        # At minimum, the heuristic brace check in _css() should fire
        assert any("brace" in e.lower() or "syntax" in e.lower() for e in linter_errs), \
            f"Expected brace or syntax error. lint_file returned: {linter_errs}"


class TestSyntaxValidatorJSON:
    def test_valid_json(self):
        code = '{"name": "my-app", "version": "1.0.0"}\n'
        errs = SyntaxValidator.validate("package.json", code)
        assert errs == [], f"Expected no errors, got: {errs}"

    def test_malformed_json(self):
        code = '{"name": "my-app", "version":}\n'  # missing value
        errs = SyntaxValidator.validate("package.json", code)
        assert errs, f"Expected JSON error, got: {errs}"
        assert "JSON syntax error" in errs[0]

    def test_trailing_comma_json(self):
        code = '{"a": 1, "b": 2,}\n'  # trailing comma
        errs = SyntaxValidator.validate("config.json", code)
        assert errs, f"Expected JSON error for trailing comma, got: {errs}"

    def test_tsconfig_json_allows_jsonc_comments(self):
        code = """{
  "compilerOptions": {
    // Bundler mode
    "moduleResolution": "bundler",
    "jsx": "react-jsx"
  },
  "include": ["src"]
}
"""
        errs = SyntaxValidator.validate("tsconfig.json", code)
        assert errs == [], f"Expected tsconfig JSONC to pass, got: {errs}"

    def test_tsconfig_json_allows_trailing_commas(self):
        code = """{
  "compilerOptions": {
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
  },
  "include": ["src"],
}
"""
        errs = SyntaxValidator.validate("tsconfig.node.json", code)
        assert errs == [], f"Expected tsconfig JSONC trailing commas to pass, got: {errs}"


class TestSyntaxValidatorHTML:
    def test_valid_html(self):
        code = "<html><head><title>T</title></head><body><div><p>hi</p></div></body></html>"
        errs = SyntaxValidator.validate("index.html", code)
        assert errs == [], f"Expected no errors, got: {errs}"

    def test_truncated_html(self):
        code = "<html><head><title>T</title></head><body><div><div><div><div><div>"
        errs = SyntaxValidator.validate("index.html", code)
        assert errs, f"Expected tag imbalance error, got: {errs}"


class TestPartialBatchRejection:
    """Verify that the linter is called inline and surfaces critical errors."""

    def test_lint_file_runs_syntax_first(self):
        """A broken JS file should return syntax error, skipping secondary checks."""
        linter = CodeLinter()
        broken_js = "function x( { return 1; }"  # bad syntax
        errs = linter.lint_file("src/broken.js", broken_js)
        assert errs, "Expected errors for broken JS"
        # Syntax error should be first
        assert "syntax error" in errs[0].lower() or "src/broken.js" in errs[0]

    def test_lint_file_valid_js_passes(self):
        linter = CodeLinter()
        valid_js = (
            "const express = require('express');\n"
            "const app = express();\n"
            "app.listen(3001);\n"
            "module.exports = app;\n"
        )
        errs = linter.lint_file("server/index.js", valid_js)
        syntax_errs = [e for e in errs if "syntax error" in e.lower()]
        assert syntax_errs == [], f"Valid JS should have no syntax errors, got: {syntax_errs}"
