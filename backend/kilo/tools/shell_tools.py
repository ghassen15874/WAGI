import asyncio
import os
import signal
import subprocess
from typing import Optional

class ShellTool:
    """
    Runs shell commands inside the sandbox directory.
    Inspired by deepagents/backends/filesystem.py execute pattern.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    async def execute(
        self, command: str, timeout: int = 30
    ) -> str:
        """Run command in sandbox, return stdout+stderr."""
        if not command:
            return "Error: command is required"
        proc = None
        try:
            # We want timeout as int 
            timeout = int(timeout)
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.base_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, 'HOME': self.base_dir},
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            out = stdout.decode('utf-8', errors='ignore')
            err = stderr.decode('utf-8', errors='ignore')
            output = out + err
            # Keep the tail because validator JSON is emitted at the end.
            return output[-50000:] if output else ""
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except Exception:
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass

                try:
                    await asyncio.wait_for(proc.communicate(), timeout=5)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                    try:
                        await proc.communicate()
                    except Exception:
                        pass
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error: {str(e)}"

    def get_description(self) -> str:
        return (
            "<execute_command>\n"
            "<command>shell command</command>\n"
            "<timeout>30</timeout>\n"
            "</execute_command>\n"
            "execute_command: Run a shell command in the sandbox.\n"
            "  params: command (str), timeout (int, optional)\n"
            "  Use for: npm install, running tests, checking output"
        )
