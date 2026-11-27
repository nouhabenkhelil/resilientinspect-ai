"""Run existing tests against this worktree, without rewriting a shared editable install."""
import importlib.util
from pathlib import Path
import sys
from .common import LOCAL, ROOT


def main():
    # The reused venv's editable package belongs to the original worktree. Bind the
    # same package name to this checkout before importing any scientific modules.
    spec=importlib.util.spec_from_file_location('resilientinspect',ROOT/'src/__init__.py',submodule_search_locations=[str(ROOT/'src')])
    module=importlib.util.module_from_spec(spec)
    sys.modules['resilientinspect']=module
    spec.loader.exec_module(module)
    import pytest
    return pytest.main(['tests/test_backend_api.py','tests/test_deployment_portability.py',
        'tests/test_compose_deployment.py','mlops/tests','scripts/ci/tests','-q',
        '--junitxml='+str(LOCAL/'regression-tests-corrected.xml')])


if __name__=='__main__':sys.exit(main())
