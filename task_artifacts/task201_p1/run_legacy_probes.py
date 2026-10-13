"""Run unchanged TASK-102 assertions with valid TASK-201 configuration fixtures.

The original review file remains untouched. Its path, credential reference and
placeholder hash are adapted in a temporary copy. The cancel_params probe uses
the Provider directly: its intentionally secret-bearing `user` SDK parameter is
now rejected by the TASK-201 service configuration allowlist. All its cancellation
and redaction assertions remain intact, and still use a real local HTTP server.
This is execution regression evidence, not a new independent review.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / "review_artifacts/task102_incremental/test_review.py").read_text("utf-8")
replacements = {
    "ROOT = Path(__file__).resolve().parents[2]": f"ROOT = Path({str(root)!r})",
    'credential_ref="env/DASHSCOPE_API_KEY"': 'credential_ref="DASHSCOPE_API_KEY"',
    "    config.update(kwargs)": (
        "    config.update(kwargs)\n"
        "    from app.schemas.config import model_hash\n"
        '    config["model_config_hash"] = model_hash(ModelConfigSnapshot.model_validate(config))'
    ),
    '                if path.startswith("cancel"):\n'
    "                    task = asyncio.create_task(service(p, sink).analyze(text=TEXT))": (
        '                if path.startswith("cancel"):\n'
        "                    call = (p.invoke(PromptBuilder().build(snapshot(), text=TEXT))\n"
        '                            if path == "cancel_params"\n'
        "                            else service(p, sink).analyze(text=TEXT))\n"
        "                    task = asyncio.create_task(call)"
    ),
}
for old, new in replacements.items():
    assert source.count(old) == 1, "legacy fixture changed; inspect before adapting"
    source = source.replace(old, new)

temporary_root = Path(tempfile.gettempdir()).resolve()
with tempfile.TemporaryDirectory(prefix="aicoach-legacy-probes-", dir=temporary_root) as directory:
    target = Path(directory).resolve()
    assert target.parent == temporary_root
    probe = target / "test_review.py"
    probe.write_text(source, encoding="utf-8")
    print(
        "TASK-102 assertions unchanged; valid credential/hash fixtures; "
        "cancel_params at Provider boundary.",
        flush=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--rootdir",
            str(target),
            "--confcutdir",
            str(target),
            "-o",
            "addopts=",
            "-q",
            "-rs",
            "--tb=short",
            str(probe),
        ],
        cwd=root / "backend",
        env={**os.environ, "PYTHONPATH": str(root / "backend")},
        check=False,
    )
raise SystemExit(result.returncode)
