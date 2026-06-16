from rental_alert_bot.__main__ import main


def valid_environment(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("AUTHORIZED_TELEGRAM_USER_ID", "123456")


def test_startup_check_succeeds_with_required_configuration(monkeypatch) -> None:
    valid_environment(monkeypatch)

    assert main(["--check"]) == 0


def test_startup_check_fails_without_required_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AUTHORIZED_TELEGRAM_USER_ID", raising=False)

    assert main(["--check"]) == 2


def test_application_skeleton_starts(monkeypatch) -> None:
    valid_environment(monkeypatch)

    assert main([]) == 0
