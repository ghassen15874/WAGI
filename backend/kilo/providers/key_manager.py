"""
KeyManager — multi-key rotation + cooldown system.
Feature 3: Safe new file. Not imported by any existing code until __init__.py wires it.
"""
import time
import os
from typing import Optional


class KeyManager:
    """
    Manages multiple API keys per provider with:
    - Round-robin rotation on success
    - Cooldown (60s) on 429 rate limit
    - Removal of invalid keys
    Loads from comma-separated env vars on startup.
    """

    def __init__(self):
        self._keys: dict[str, list[str]] = {}
        self._idx: dict[str, int] = {}
        self._cooldowns: dict[str, float] = {}
        self._load_env()

    def _load_env(self):
        """Load keys from CSV env vars (e.g. GROQ_API_KEY=key1,key2,key3)."""
        for p in ["groq", "anthropic", "openai", "openrouter", "deepseek"]:
            raw = os.getenv(f"{p.upper()}_API_KEY", "")
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            if keys:
                self._keys[p] = keys
                self._idx[p] = 0

    def add_keys(self, provider: str, keys: list[str]):
        """Register keys for a provider (called from settings save)."""
        cleaned = [k.strip() for k in keys if k.strip()]
        if not cleaned:
            return
        existing = self._keys.get(provider, [])
        if existing == cleaned:
            if provider not in self._idx:
                self._idx[provider] = 0
            return
        self._keys[provider] = cleaned
        self._idx[provider] = self._idx.get(provider, 0) % len(cleaned)
        print(f"[KEYS] {provider}: {len(cleaned)} key(s) registered")

    def get_key(self, provider: str) -> Optional[str]:
        """
        Return next available key for provider.
        Skips keys on cooldown. Returns None if all are rate-limited.
        """
        keys = self._keys.get(provider, [])
        if not keys:
            return None
        idx = self._idx.get(provider, 0) % len(keys)
        key = keys[idx]

        # If current key is on cooldown, scan for a free one
        if self._cooldowns.get(key, 0) > time.time():
            for i in range(1, len(keys)):
                nidx = (idx + i) % len(keys)
                nkey = keys[nidx]
                if self._cooldowns.get(nkey, 0) <= time.time():
                    self._idx[provider] = nidx
                    return nkey
            return None  # All keys on cooldown

        return key

    def reset_rotation(self, provider: str):
        """Restart rotation from the first registered key for a provider."""
        keys = self._keys.get(provider, [])
        if keys:
            self._idx[provider] = 0

    def total_keys(self, provider: str) -> int:
        """Return number of registered keys for a provider."""
        return len(self._keys.get(provider, []))

    def key_slot(self, provider: str, key: str | None = None) -> tuple[int, int]:
        """Return 1-based slot position for a key within a provider pool."""
        keys = self._keys.get(provider, [])
        total = len(keys)
        if total == 0:
            return (0, 0)

        if key and key in keys:
            return (keys.index(key) + 1, total)

        idx = self._idx.get(provider, 0) % total
        return (idx + 1, total)

    def seconds_until_available(self, provider: str) -> int:
        """Return seconds until any key for the provider is available."""
        keys = self._keys.get(provider, [])
        if not keys:
            return 0

        now = time.time()
        active = [self._cooldowns.get(k, 0) for k in keys]
        if any(ts <= now for ts in active):
            return 0

        next_available = min(active)
        return max(0, int(next_available - now))

    async def wait_for_available_key(
        self, provider: str, max_wait: int = 70, restart_from_first: bool = False
    ) -> Optional[str]:
        """
        Wait until a key becomes available.
        If all keys on cooldown, wait for the shortest cooldown.
        Returns key when available, None if max_wait exceeded.
        """
        import asyncio
        start = time.time()
        
        while time.time() - start < max_wait:
            if restart_from_first:
                self.reset_rotation(provider)
            key = self.get_key(provider)
            if key:
                return key
            
            # Find shortest cooldown
            keys = self._keys.get(provider, [])
            if not keys:
                return None
            
            cooldowns = [
                self._cooldowns.get(k, 0) for k in keys
            ]
            next_available = min(cooldowns)
            wait_secs = max(0, next_available - time.time()) + 1
            
            print(
                f"[KEYS] All {provider} keys on cooldown. "
                f"Waiting {wait_secs:.0f}s..."
            )
            # Yield to event loop while waiting
            await asyncio.sleep(min(wait_secs, 5))
        
        return None  # Timed out

    def mark_rate_limited(self, provider: str, key: str, secs: int = 60):
        """Put key on cooldown and advance to next."""
        self._cooldowns[key] = time.time() + secs
        keys = self._keys.get(provider, [])
        if keys:
            self._idx[provider] = (self._idx.get(provider, 0) + 1) % len(keys)
        print(f"[KEYS] {provider} key rate-limited → rotated to next (cooldown {secs}s)")

    def mark_used(self, provider: str, key: str):
        """Advance to the next key after a successful use."""
        keys = self._keys.get(provider, [])
        if not keys:
            return
        if key in keys:
            self._idx[provider] = (keys.index(key) + 1) % len(keys)
        else:
            self._idx[provider] = (self._idx.get(provider, 0) + 1) % len(keys)

    def mark_invalid(self, provider: str, key: str):
        """Permanently remove an invalid key."""
        keys = self._keys.get(provider, [])
        if key in keys:
            keys.remove(key)
            self._cooldowns.pop(key, None)
            if not keys:
                self._idx.pop(provider, None)
            else:
                self._idx[provider] = self._idx.get(provider, 0) % len(keys)
            print(f"[KEYS] {provider} invalid key removed ({len(keys)} remaining)")

    def get_status(self) -> dict:
        """Return masked key status for /api/settings/keys/status endpoint."""
        now = time.time()
        out: dict = {}
        for p, keys in self._keys.items():
            out[p] = []
            for k in keys:
                masked = k[:8] + "..." + k[-4:] if len(k) > 12 else "***"
                cooldown_until = self._cooldowns.get(k, 0)
                out[p].append({
                    "masked": masked,
                    "active": cooldown_until <= now,
                    "cooldown_remaining": max(0, round(cooldown_until - now)),
                })
        return out


# Singleton instance
key_manager = KeyManager()
