from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        result[name.lstrip("*")] = digest.lower()
    return result


def select(checksums: dict[str, str], predicate, label: str) -> tuple[str, str]:
    matches = sorted(name for name in checksums if predicate(name))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label} asset, found: {matches}")
    name = matches[0]
    return name, checksums[name]


def render(template: Path, target: Path, replacements: dict[str, str]) -> None:
    content = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        content = content.replace(f"@{key}@", value)
    unresolved = sorted(part.split("@", 1)[0] for part in content.split("@") if "@" in part)
    if unresolved:
        raise ValueError(f"unresolved template placeholders in {template}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render release distribution manifests from SHA256SUMS")
    parser.add_argument("--version", required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    checksums = read_checksums(args.checksums)
    windows = select(checksums, lambda n: n.endswith("-windows-x86_64.exe"), "Windows x64")
    linux = select(checksums, lambda n: n.endswith("-linux-x86_64"), "Linux x64")
    mac_arm = select(checksums, lambda n: n.endswith("-macos-arm64"), "macOS arm64")
    mac_x64 = select(checksums, lambda n: n.endswith("-macos-x86_64"), "macOS x64")
    sdist = select(checksums, lambda n: n.endswith(".tar.gz") and "workflow" in n, "sdist")

    values = {
        "VERSION": args.version,
        "WINDOWS_ASSET": windows[0],
        "WINDOWS_SHA256": windows[1],
        "LINUX_X64_ASSET": linux[0],
        "LINUX_X64_SHA256": linux[1],
        "MACOS_ARM_ASSET": mac_arm[0],
        "MACOS_ARM_SHA256": mac_arm[1],
        "MACOS_X64_ASSET": mac_x64[0],
        "MACOS_X64_SHA256": mac_x64[1],
        "SDIST_ASSET": sdist[0],
        "SDIST_SHA256": sdist[1],
    }
    outputs = [
        ("packaging/winget/manifest.yaml.in", "Taki7980.AIWorkflow.yaml"),
        ("packaging/winget/installer.yaml.in", "Taki7980.AIWorkflow.installer.yaml"),
        ("packaging/winget/defaultLocale.yaml.in", "Taki7980.AIWorkflow.locale.en-US.yaml"),
        ("packaging/homebrew/ai-workflow.rb.in", "ai-workflow.rb"),
        ("packaging/conda/meta.yaml.in", "meta.yaml"),
    ]
    for source, name in outputs:
        render(ROOT / source, args.output_dir / name, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
