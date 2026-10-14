"""Create the ignored local credential master key without printing it."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    env_path = backend_dir / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    setting = "CREDENTIAL_ENCRYPTION_KEY"

    for index, line in enumerate(lines):
        key, separator, value = line.partition("=")
        if separator and key.strip() == setting:
            if value.strip():
                print("Local credential encryption key is already configured.")
                return
            lines[index] = f"{setting}={Fernet.generate_key().decode('ascii')}"
            break
    else:
        if lines and lines[-1]:
            lines.append("")
        lines.append(f"{setting}={Fernet.generate_key().decode('ascii')}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Configured local credential encryption key in ignored backend/.env.")


if __name__ == "__main__":
    main()
