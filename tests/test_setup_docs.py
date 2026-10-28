"""Check the documented locked Windows recipe without installing or invoking a shell."""
import re
from importlib.metadata import metadata
from pathlib import Path

from packaging.specifiers import SpecifierSet


def test_windows_locked_recipe_uses_supported_python_and_install_order():
    readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8')
    recipe = re.search(r'```powershell\n(.*?)```', readme, re.S).group(1)
    python_version = re.search(r'py -(\d+\.\d+) -m venv', recipe).group(1)
    assert tuple(map(int, python_version.split('.'))) >= (3, 12)
    assert python_version in SpecifierSet(metadata('numpy')['Requires-Python'])
    commands = recipe.splitlines()
    locked = next(i for i, line in enumerate(commands) if 'pip install -r requirements-dev.lock' in line)
    editable = next(i for i, line in enumerate(commands) if 'pip install --no-deps -e .' in line)
    assert locked < editable
