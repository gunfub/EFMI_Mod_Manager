# -*- coding: utf-8 -*-
"""Two-level cache for local Mod preview thumbnails."""

import hashlib
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict

from PIL import Image, ImageOps


PROCESSING_VERSION = 1


class LocalPreviewCache:
    def __init__(self, cache_dir, memory_limit=128):
        self.cache_dir = cache_dir
        self.memory_limit = max(1, int(memory_limit))
        self._memory = OrderedDict()
        self._lock = threading.Lock()

    def load(self, source_path, target_size):
        """Return a fitted RGB thumbnail, loading or generating it as needed."""
        key = self.cache_key(source_path, target_size)
        if key is None:
            return None

        with self._lock:
            cached = self._memory.pop(key, None)
            if cached is not None:
                self._memory[key] = cached
                return cached.copy()

        cache_path = os.path.join(self.cache_dir, key + ".png")
        image = self._load_disk(cache_path, target_size)
        if image is None:
            image = self._load_source(source_path, target_size)
            if image is None:
                return None
            self._write_disk(cache_path, image)

        self._remember(key, image)
        return image.copy()

    @staticmethod
    def cache_key(source_path, target_size):
        try:
            stat = os.stat(source_path)
        except OSError:
            return None
        payload = {
            "path": os.path.normcase(os.path.abspath(source_path)),
            "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
            "size": stat.st_size,
            "target": [int(target_size[0]), int(target_size[1])],
            "version": PROCESSING_VERSION,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def prune(self, max_age_days=30, max_entries=512,
              max_bytes=256 * 1024 * 1024):
        """Remove stale cache entries and enforce count and size limits."""
        try:
            entries = []
            cutoff = time.time() - max_age_days * 86400
            with os.scandir(self.cache_dir) as iterator:
                for entry in iterator:
                    if not entry.name.endswith(".png") or not entry.is_file():
                        continue
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    if stat.st_atime < cutoff and stat.st_mtime < cutoff:
                        self._remove(entry.path)
                        continue
                    entries.append((max(stat.st_atime, stat.st_mtime),
                                    stat.st_size, entry.path))
        except OSError:
            return

        entries.sort(reverse=True)
        total = 0
        for index, (_used, size, path) in enumerate(entries):
            total += size
            if index >= max_entries or total > max_bytes:
                self._remove(path)

    def _remember(self, key, image):
        with self._lock:
            self._memory.pop(key, None)
            self._memory[key] = image.copy()
            while len(self._memory) > self.memory_limit:
                self._memory.popitem(last=False)

    @staticmethod
    def _load_source(source_path, target_size):
        try:
            with Image.open(source_path) as source:
                image = ImageOps.fit(
                    source.convert("RGB"), target_size, method=Image.LANCZOS)
                image.load()
                return image
        except (OSError, ValueError):
            return None

    @staticmethod
    def _load_disk(cache_path, target_size):
        try:
            with Image.open(cache_path) as source:
                if source.size != tuple(target_size):
                    return None
                image = source.convert("RGB")
                image.load()
                try:
                    os.utime(cache_path, None)
                except OSError:
                    pass
                return image
        except (OSError, ValueError):
            LocalPreviewCache._remove(cache_path)
            return None

    @staticmethod
    def _write_disk(cache_path, image):
        temp_path = None
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=".local-preview-", suffix=".tmp",
                dir=os.path.dirname(cache_path))
            with os.fdopen(fd, "wb") as handle:
                image.save(handle, format="PNG")
            os.replace(temp_path, cache_path)
        except OSError:
            pass
        finally:
            if temp_path:
                LocalPreviewCache._remove(temp_path)

    @staticmethod
    def _remove(path):
        try:
            os.remove(path)
        except OSError:
            pass
