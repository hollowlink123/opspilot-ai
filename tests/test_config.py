"""Configuration checks use only temporary files and synthetic credentials."""
import os

import pytest
from pydantic import ValidationError

from opspilot import config
from opspilot.config import Settings


def test_local_dotenv_loads_without_mutating_environment_or_file(caplog):
    content = ('GEMINI_API_KEY="SYNTHETIC_DOTENV_CREDENTIAL"\n'
               'GEMINI_MODEL=synthetic-model\nOPSPILOT_MAX_STEPS=4\n')
    config.ENV_FILE.write_text(content, encoding='utf-8-sig')
    original_file = config.ENV_FILE.read_bytes()
    original_environment = dict(os.environ)

    settings = Settings.from_env()

    assert settings.api_key.get_secret_value() == 'SYNTHETIC_DOTENV_CREDENTIAL'
    assert settings.model == 'synthetic-model'
    assert settings.max_steps == 4
    assert dict(os.environ) == original_environment
    assert config.ENV_FILE.read_bytes() == original_file
    assert 'SYNTHETIC_DOTENV_CREDENTIAL' not in repr(settings) + settings.model_dump_json() + caplog.text


def test_process_environment_takes_precedence(monkeypatch):
    config.ENV_FILE.write_text('GEMINI_API_KEY=SYNTHETIC_FILE_KEY\nGEMINI_MODEL=file-model\n'
                              'OPSPILOT_MAX_STEPS=3\n', encoding='utf-8')
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_ENV_KEY')
    monkeypatch.setenv('GEMINI_MODEL', 'environment-model')
    monkeypatch.setenv('OPSPILOT_MAX_STEPS', '5')
    settings = Settings.from_env()
    assert settings.api_key.get_secret_value() == 'SYNTHETIC_ENV_KEY'
    assert settings.model == 'environment-model'
    assert settings.max_steps == 5


def test_empty_environment_values_do_not_fall_back_to_file(monkeypatch):
    config.ENV_FILE.write_text('GEMINI_API_KEY=SYNTHETIC_FILE_KEY\nGEMINI_MODEL=file-model\n', encoding='utf-8')
    monkeypatch.setenv('GEMINI_API_KEY', '')
    monkeypatch.setenv('GEMINI_MODEL', '')
    settings = Settings.from_env()
    assert settings.api_key is None
    assert settings.model == ''


def test_missing_dotenv_keeps_environment_only_configuration(monkeypatch):
    assert not config.ENV_FILE.exists()
    monkeypatch.setenv('GEMINI_API_KEY', 'SYNTHETIC_ENV_KEY')
    monkeypatch.setenv('GEMINI_MODEL', 'environment-model')
    settings = Settings.from_env()
    assert settings.api_key.get_secret_value() == 'SYNTHETIC_ENV_KEY'
    assert settings.model == 'environment-model'
    assert not config.ENV_FILE.exists()


def test_dotenv_does_not_expand_environment_variables(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_OTHER_SECRET', 'SYNTHETIC_DO_NOT_EXPAND')
    config.ENV_FILE.write_text('GEMINI_API_KEY="literal-${SYNTHETIC_OTHER_SECRET}"\n', encoding='utf-8')
    assert Settings.from_env().api_key.get_secret_value() == 'literal-${SYNTHETIC_OTHER_SECRET}'


def test_dotenv_path_does_not_follow_working_directory_or_parent(monkeypatch, tmp_path):
    config.ENV_FILE.write_text('GEMINI_MODEL=checkout-model\n', encoding='utf-8')
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    (unrelated / '.env').write_text('GEMINI_MODEL=wrong-model\n', encoding='utf-8')
    nested = unrelated / 'nested'
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert Settings.from_env().model == 'checkout-model'


@pytest.mark.parametrize('value', ['not-a-number', '0', '999'])
def test_dotenv_resource_settings_still_require_validation(value):
    config.ENV_FILE.write_text(f'OPSPILOT_MAX_STEPS={value}\n', encoding='utf-8')
    with pytest.raises(ValidationError):
        Settings.from_env()
