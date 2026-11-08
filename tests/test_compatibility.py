"""Contrat de paquetage Python et preservation du runtime PyTorch Kaggle."""

from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


@pytest.mark.parametrize("python,accepted", [("3.11.9", True), ("3.12.0", True), ("3.13.16", True),
                                           ("3.10.20", False), ("3.14.0", False), ("4.0.0", False)])
def test_declared_python_versions_and_installed_metadata_agree(python, accepted):
    declared = SpecifierSet(PROJECT["requires-python"])
    installed = SpecifierSet(metadata.metadata("resilientinspect-ai")["Requires-Python"])
    assert declared == installed
    assert declared.contains(python) is accepted


def test_kaggle_dependency_tree_does_not_request_a_torch_or_cuda_distribution():
    # Metadonnees des versions installees, marqueurs evalues pour CPython 3.13 Linux.
    # Cela ne remplace pas la resolution et l'execution dans le vrai notebook.
    environment = default_environment()
    environment.update(python_version="3.13", python_full_version="3.13.16", platform_system="Linux",
                       sys_platform="linux", os_name="posix", platform_machine="x86_64",
                       platform_python_implementation="CPython", implementation_name="cpython",
                       implementation_version="3.13.16")
    pending = list(PROJECT["dependencies"])
    for extra in ("dev", "eda", "train", "eval"):
        pending.extend(PROJECT["optional-dependencies"][extra])
    seen = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        assert name not in {"torch", "torchvision", "torchaudio", "triton"}
        assert not name.startswith(("nvidia-", "cuda-")), name
        if name in seen:
            continue
        seen.add(name)
        distribution = metadata.distribution(name)
        python_specifier = distribution.metadata.get("Requires-Python", "")
        assert SpecifierSet(python_specifier).contains("3.13.16"), (name, python_specifier)
        pending.extend(distribution.requires or [])
    assert "mlflow-skinny" in seen


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Bootstrap PowerShell verifie uniquement sur Windows.")
def test_bootstrap_python_probe_accepts_the_same_versions_and_checks_exit_code(tmp_path):
    # Extraire la vraie fonction sans executer le bootstrap ni modifier un venv.
    script = tmp_path / "probe_bootstrap.ps1"
    source = str(ROOT / "scripts/bootstrap.ps1").replace("'", "''")
    script.write_text(f"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{source}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ throw 'Bootstrap syntax error' }}
$function = $ast.Find({{ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-SupportedPython'
}}, $true)
Invoke-Expression $function.Extent.Text
function Mock-Python {{ $global:LASTEXITCODE = $script:mockExitCode; Write-Output $script:mockDetails }}
$results = @()
foreach ($details in @('3.11;64','3.12;64','3.13;64','3.10;64','3.14;64','4.11;64','3.13;32')) {{
    $script:mockDetails = $details
    $script:mockExitCode = 0
    $result = Test-SupportedPython -Executable Mock-Python
    $results += [pscustomobject]@{{ Details=$details; Accepted=$result.IsValid }}
}}
$script:mockDetails = '3.13;64'
$script:mockExitCode = 1
$result = Test-SupportedPython -Executable Mock-Python
$results += [pscustomobject]@{{ Details='failed process'; Accepted=$result.IsValid }}
ConvertTo-Json -InputObject $results -Compress
""", encoding="utf-8")
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(script)],
                            capture_output=True, text=True, check=True, timeout=30)
    assert {entry["Details"]: entry["Accepted"] for entry in json.loads(result.stdout)} == {
        "3.11;64": True, "3.12;64": True, "3.13;64": True, "3.10;64": False,
        "3.14;64": False, "4.11;64": False, "3.13;32": False, "failed process": False,
    }
