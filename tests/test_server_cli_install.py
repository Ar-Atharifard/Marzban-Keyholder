import subprocess
import sys
from pathlib import Path

from scripts.admin.install_cli import MODULES, install


def test_installed_cli_has_current_commands_and_is_idempotent(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]
    install(checkout, tmp_path)
    install(checkout, tmp_path)
    command = tmp_path / "bin/keyholder"
    for path, expected in [
        (["user", "inbounds", "--help"], "[username]"),
        (["user", "defaults", "--help"], "--select"),
        (["user", "create", "--help"], "--inbounds"),
    ]:
        result = subprocess.run(
            [sys.executable, str(command), *path], capture_output=True, text=True
        )
        assert result.returncode == 0 and expected in result.stdout
    for name in MODULES:
        assert (tmp_path / "lib/keyholder-admin/keyholder" / name).read_bytes() == (
            checkout / "src/keyholder" / name
        ).read_bytes()
    assert (tmp_path / "share/man/man1/keyholder.1").is_file()


def test_server_wrapper_defaults_to_local_dispatch(tmp_path: Path) -> None:
    install(Path(__file__).resolve().parents[1], tmp_path)
    module = tmp_path / "lib/keyholder-admin/keyholder/cli.py"
    module.write_text("def main(args):\n print(args)\n return 0\n")
    command = tmp_path / "bin/keyholder"
    for args in [["system", "health"], ["--local", "system", "health"]]:
        result = subprocess.run(
            [sys.executable, str(command), *args], capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.count("--local") == 1


def test_installed_standalone_bot_has_all_imports_and_formats_updates(tmp_path: Path) -> None:
    import shutil

    checkout = Path(__file__).resolve().parents[1]
    install(checkout, tmp_path)
    directory = tmp_path / "lib/keyholder-admin"
    for name in ("management_bot.py", "billing_bot.py", "component_config.py"):
        shutil.copyfile(checkout / "scripts" / name, directory / name)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys,runpy; sys.path.insert(0,sys.argv[1]); "
            "bot=runpy.run_path(sys.argv[1]+'/management_bot.py', run_name='install_check'); "
            "bot['command'].__globals__['dispatch']=lambda *a: "
            "{'username':'alice','data_limit':5368709120,'used_traffic':1073741824}; "
            "print(bot['command']('/update alice quota=5',{}))",
            str(directory),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Traffic allowance: 5.00 GiB" in result.stdout
    assert "Remaining quota: 4.00 GiB" in result.stdout
