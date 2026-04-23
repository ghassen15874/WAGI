import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.codegen.parser import ResponseParser


class TestResponseParser:
    def test_parse_strict_json_generation_payload(self):
        text = """
{
  "files": [
    {
      "path": "src/App.tsx",
      "content": "export default function App() {\\n  return <main>Hello</main>;\\n}\\n"
    },
    {
      "path": "src/pages/Home.tsx",
      "content": "export default function Home() {\\n  return <section>Home</section>;\\n}\\n"
    }
  ],
  "commands": [
    {"command": "npm run lint"}
  ],
  "chunk_index": 1,
  "chunk_total": 1
}
""".strip()

        calls = ResponseParser.parse_tool_calls(text, model_id="openai")
        write_paths = [call["params"]["path"] for call in calls if call["tool"] == "write_file"]
        commands = [call["params"]["command"] for call in calls if call["tool"] == "execute_command"]

        assert write_paths == ["src/App.tsx", "src/pages/Home.tsx"]
        assert commands == ["npm run lint"]

    def test_parse_strict_json_files_object_payload(self):
        text = """
{
  "files": {
    "package.json": "{\\n  \\"name\\": \\"demo\\"\\n}\\n",
    "vite.config.ts": "import { defineConfig } from 'vite'\\nexport default defineConfig({})\\n"
  },
  "commands": []
}
""".strip()

        calls = ResponseParser.parse_tool_calls(text, model_id="openai")
        parsed = {call["params"]["path"]: call["params"]["content"] for call in calls if call["tool"] == "write_file"}

        assert set(parsed) == {"package.json", "vite.config.ts"}
        assert '"name": "demo"' in parsed["package.json"]
        assert "defineConfig" in parsed["vite.config.ts"]

    def test_rejects_strict_json_payload_with_duplicate_keys(self):
        text = """
{
  "files": [
    {
      "path": "package.json",
      "content": "{\\n  \\"name\\": \\"demo\\"\\n}",
      "path": "tailwind.config.js",
      "content": "export default {}\\n"
    }
  ],
  "commands": []
}
""".strip()

        calls = ResponseParser.parse_tool_calls(text, model_id="openai")
        assert calls == []

    def test_salvages_completed_files_from_truncated_json_payload(self):
        text = """
{
  "files": [
    {
      "path": "package.json",
      "content": "{\\n  \\"name\\": \\"demo\\"\\n}\\n"
    },
    {
      "path": "src/main.tsx",
      "content": "export default function Main() {\\n  return null;\\n}\\n"
    },
    {
      "path": "src/App.tsx",
      "content": "export default function App() {
""".strip()

        calls = ResponseParser.parse_tool_calls(text, model_id="deepseek")
        parsed = {call["params"]["path"]: call["params"]["content"] for call in calls if call["tool"] == "write_file"}

        assert set(parsed) == {"package.json", "src/main.tsx"}
        assert '"name": "demo"' in parsed["package.json"]
        assert "export default function Main()" in parsed["src/main.tsx"]

    def test_parse_markdown_heading_blocks(self):
        text = """
### FILE: src/components/Hero.tsx
```tsx
// FILE: src/components/Hero.tsx
import React from 'react';

export default function Hero() {
  return <section>Hello</section>;
}
```

### FILE: src/components/Footer.tsx
```tsx
// FILE: src/components/Footer.tsx
import React from 'react';

export default function Footer() {
  return <footer>Footer</footer>;
}
```
""".strip()

        calls = ResponseParser.parse_tool_calls(text, model_id="groq")
        parsed = {call["params"]["path"]: call["params"]["content"] for call in calls}

        assert set(parsed) == {"src/components/Hero.tsx", "src/components/Footer.tsx"}
        assert "export default function Hero()" in parsed["src/components/Hero.tsx"]
        assert "export default function Footer()" in parsed["src/components/Footer.tsx"]
        assert "```" not in parsed["src/components/Hero.tsx"]
        assert "```" not in parsed["src/components/Footer.tsx"]

    def test_parse_ui_rendered_code_blocks_with_expected_files(self):
        text = """
I'll create the foundational configuration files for the blog platform.
Code Blockjson

{
  "name": "blog-platform",
  "private": true
}

Code Blocktypescript

// FILE: vite.config.ts
import { defineConfig } from 'vite'
export default defineConfig({})

Code Blockjson

{
  "compilerOptions": {
    "target": "ES2020"
  }
}

Code Blockjson

{
  "compilerOptions": {
    "composite": true
  }
}

Code Blockhtml

<!doctype html>
<html lang="en"><body><div id="root"></div></body></html>

Code Blockenv

# FILE: .env
VITE_API_URL=http://localhost:3001

Code Blockgitignore

# FILE: .gitignore
node_modules
dist
""".strip()

        expected = [
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.node.json",
            "index.html",
            ".env",
            ".gitignore",
        ]

        calls = ResponseParser.parse_tool_calls(text, model_id="anthropic", expected_files=expected)
        parsed = {call["params"]["path"]: call["params"]["content"] for call in calls}

        assert set(parsed) == set(expected)
        assert '"name": "blog-platform"' in parsed["package.json"]
        assert "defineConfig" in parsed["vite.config.ts"]
        assert '"target": "ES2020"' in parsed["tsconfig.json"]
        assert '"composite": true' in parsed["tsconfig.node.json"]
        assert "<!doctype html>" in parsed["index.html"].lower()
        assert "VITE_API_URL=http://localhost:3001" in parsed[".env"]
        assert "node_modules" in parsed[".gitignore"]

    def test_rejects_malformed_multi_path_file_headers(self):
        text = """
Code Blocktypescript

// FILE: src/main.tsx, src/App.tsx, src/styles/global.css
import './styles/global.css';
import App from './App';

Code Blocktypescript

// FILE: src/App.tsx
export default function App() {
  return <main>Hello</main>;
}
""".strip()

        calls = ResponseParser.parse_tool_calls(
            text,
            model_id="anthropic",
            expected_files=["src/main.tsx", "src/App.tsx"],
        )
        parsed = {call["params"]["path"]: call["params"]["content"] for call in calls}

        assert "src/main.tsx" not in parsed
        assert parsed["src/App.tsx"].startswith("export default function App()")
