"""Product files (delivery ZIPs, listing images) are stored as *encrypted* GitHub
Release assets, one release per product. This keeps the git history small.
When running locally (no GITHUB_TOKEN) files go to .work/local_assets/."""
import time

import requests

from . import config
from .storage import decrypt_bytes, encrypt_bytes

API = "https://api.github.com"


def _local_dir(pid):
    d = config.WORK_DIR / "local_assets" / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _h():
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _remote() -> bool:
    return bool(config.GITHUB_TOKEN and config.GITHUB_REPOSITORY)


def _tag(pid):
    return f"asset-{pid}"


def _get_release(pid):
    r = requests.get(f"{API}/repos/{config.GITHUB_REPOSITORY}/releases/tags/{_tag(pid)}", headers=_h(), timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _ensure_release(pid):
    rel = _get_release(pid)
    if rel:
        return rel
    r = requests.post(
        f"{API}/repos/{config.GITHUB_REPOSITORY}/releases",
        headers=_h(),
        json={
            "tag_name": _tag(pid),
            "name": f"Ürün dosyaları {pid} (şifreli)",
            "body": "Bot tarafından otomatik oluşturuldu. Dosyalar şifrelidir.",
            "prerelease": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upload(pid: str, files: dict) -> list:
    """files: {name: bytes}. Returns stored names."""
    names = []
    if not _remote():
        d = _local_dir(pid)
        for name, data in files.items():
            (d / (name + ".enc")).write_bytes(encrypt_bytes(data))
            names.append(name)
        return names
    rel = _ensure_release(pid)
    upload_url = rel["upload_url"].split("{")[0]
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    for name, data in files.items():
        aname = name + ".enc"
        if aname in existing:
            requests.delete(f"{API}/repos/{config.GITHUB_REPOSITORY}/releases/assets/{existing[aname]}", headers=_h(), timeout=30)
        payload = encrypt_bytes(data)
        for attempt in range(4):
            try:
                r = requests.post(
                    upload_url,
                    params={"name": aname},
                    headers={**_h(), "Content-Type": "application/octet-stream"},
                    data=payload,
                    timeout=300,
                )
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"[assets] {aname} yükleme tekrar: {e}")
                time.sleep(5 * (attempt + 1))
        names.append(name)
    return names


def download(pid: str, name: str) -> bytes:
    if not _remote():
        return decrypt_bytes((_local_dir(pid) / (name + ".enc")).read_bytes())
    rel = _get_release(pid)
    if not rel:
        raise FileNotFoundError(f"{pid} için dosya deposu bulunamadı")
    for a in rel.get("assets", []):
        if a["name"] == name + ".enc":
            r = requests.get(
                a["url"], headers={**_h(), "Accept": "application/octet-stream"}, timeout=300
            )
            r.raise_for_status()
            return decrypt_bytes(r.content)
    raise FileNotFoundError(f"{pid}/{name} bulunamadı")


def delete_all(pid: str) -> None:
    if not _remote():
        d = _local_dir(pid)
        for f in d.glob("*"):
            f.unlink()
        return
    rel = _get_release(pid)
    if rel:
        requests.delete(f"{API}/repos/{config.GITHUB_REPOSITORY}/releases/{rel['id']}", headers=_h(), timeout=30)
    requests.delete(f"{API}/repos/{config.GITHUB_REPOSITORY}/git/refs/tags/{_tag(pid)}", headers=_h(), timeout=30)
