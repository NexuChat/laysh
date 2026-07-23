from pathlib import Path

from tests.golden_cases import VALID_MODULE_OUTPUT, VALID_UNDERSTANDING

ROOT = Path(__file__).parents[1]


def test_portable_shell_uses_the_current_kufi_observatory_identity():
    from server.assemble import assemble_artifact

    artifact = assemble_artifact(VALID_UNDERSTANDING, VALID_MODULE_OUTPUT)

    assert artifact.count('font-family: "Laysh Kufi"') >= 3
    assert "noto-kufi" not in artifact
    assert "Laysh FreeSans" not in artifact
    assert "Laysh Display" not in artifact
    for color in ("#0d0f12", "#171b21", "#f1ecdf", "#ffc247", "#76d6c8"):
        assert color in artifact
    assert "letter-spacing: -" not in artifact
    assert artifact.count("data:font/woff2;base64,") == 2
    assert len(artifact.encode("utf-8")) < 2 * 1024 * 1024


def test_shell_and_host_share_the_same_core_design_tokens():
    host = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    shell = (ROOT / "sim_shell" / "shell.css").read_text(encoding="utf-8")

    for token in (
        "--space: #0d0f12",
        "--space-soft: #171b21",
        "--amber: #ffc247",
        "--moon: #76d6c8",
        "--cream: #f1ecdf",
        "--slate: #98a1ad",
    ):
        assert token in host
        assert token in shell
