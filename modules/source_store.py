# -*- coding: utf-8 -*-
"""Central and portable metadata for installed online Mods."""

import json
import os
import time
import uuid
from urllib.parse import urlparse

from modules.config import APP_DIR, ConfigManager


COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _load_config():
    return ConfigManager.load()


def save_gamebanana_source(mod_path, details, remote_file):
    config = _load_config()
    records = config.setdefault("installed_sources", {})
    instance_id = str(uuid.uuid4())
    record = {
        "instance_id": instance_id, "provider": "gamebanana",
        "submission_id": details.id, "file_id": remote_file.id,
        "folder_name": os.path.basename(mod_path), "path": os.path.abspath(mod_path),
        "file_name": remote_file.name, "file_size": remote_file.size,
        "file_md5": remote_file.md5, "file_version": remote_file.version,
        "file_description": remote_file.description, "file_date_added": remote_file.date_added,
        "source_url": "https://gamebanana.com/mods/{}".format(details.id),
        "installed_at": int(time.time()),
    }
    records[instance_id] = record
    ConfigManager.save(config)
    metadata_dir = os.path.join(mod_path, ".efmi_mod_manager")
    os.makedirs(metadata_dir, exist_ok=True)
    with open(os.path.join(metadata_dir, "source.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    return record


def save_patreon_source(mod_path, campaign_id, post, attachment):
    """记录从 Patreon 安装的 Mod（provider="patreon"）。"""
    config = _load_config()
    records = config.setdefault("installed_sources", {})
    instance_id = str(uuid.uuid4())
    record = {
        "instance_id": instance_id, "provider": "patreon",
        "campaign_id": campaign_id, "post_id": post.get("post_id"),
        "file_id": attachment.get("file_id") if attachment else None,
        "folder_name": os.path.basename(mod_path), "path": os.path.abspath(mod_path),
        "file_name": attachment.get("name") if attachment else None,
        "post_title": post.get("title"),
        "source_url": post.get("post_url") or "",
        "installed_at": int(time.time()),
    }
    records[instance_id] = record
    ConfigManager.save(config)
    metadata_dir = os.path.join(mod_path, ".efmi_mod_manager")
    os.makedirs(metadata_dir, exist_ok=True)
    with open(os.path.join(metadata_dir, "source.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    return record


def get_installed_sources():
    return _load_config().get("installed_sources", {})


def save_gamebanana_cover(fetch, cover_url, mod_path, mod_name, overwrite=False):
    """Fetch the GameBanana cover original into the mod folder and set it as preview.

    The image is stored as .efmi_mod_manager/cover.<ext> inside the Mod folder and
    registered as the Mod's preview via a relative path (survives enable/disable
    moves). Skips entirely (returns None) when the Mod already has a preview and
    overwrite is False. Raises on fetch or write failure.
    """
    if not overwrite and ConfigManager.get_mod_images().get(mod_name):
        return None
    parsed = urlparse(cover_url)
    _, ext = os.path.splitext(parsed.path)
    ext = ext.lower()
    if ext not in COVER_EXTENSIONS:
        ext = ".jpg"
    metadata_dir = os.path.join(mod_path, ".efmi_mod_manager")
    target = os.path.join(metadata_dir, "cover" + ext)
    os.makedirs(metadata_dir, exist_ok=True)
    content = fetch(cover_url)
    temp_path = target + ".tmp"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(content)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
    ConfigManager.set_mod_image(mod_name, os.path.relpath(target, mod_path))
    return target


def update_gamebanana_source(record, details, remote_file, path=None):
    config = _load_config()
    records = config.setdefault("installed_sources", {})
    current = dict(records.get(record["instance_id"], record))
    current.update({
        "submission_id": details.id,
        "file_id": remote_file.id,
        "file_name": remote_file.name,
        "file_size": remote_file.size,
        "file_md5": remote_file.md5,
        "file_version": remote_file.version,
        "file_description": remote_file.description,
        "file_date_added": remote_file.date_added,
        "path": os.path.abspath(path or current["path"]),
        "folder_name": os.path.basename(path or current["path"]),
        "updated_at": int(time.time()),
    })
    records[current["instance_id"]] = current
    ConfigManager.save(config)
    metadata_dir = os.path.join(current["path"], ".efmi_mod_manager")
    os.makedirs(metadata_dir, exist_ok=True)
    with open(os.path.join(metadata_dir, "source.json"), "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, ensure_ascii=False)
    return current


def restore_source_from_manifest(mod_path, instance_id):
    manifest_path = os.path.join(mod_path, ".efmi_mod_manager", "source.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        record = json.load(handle)
    record["instance_id"] = instance_id
    record["path"] = os.path.abspath(mod_path)
    record["folder_name"] = os.path.basename(mod_path)
    config = _load_config()
    config.setdefault("installed_sources", {})[instance_id] = record
    ConfigManager.save(config)
    return record
