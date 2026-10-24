"""Tests du script de purge d'un bot désactivé (forex/strategies/remove.py)."""

from forex.strategies import remove


def test_purge_removes_the_bot_directory(tmp_path, monkeypatch):
    bot_dir = tmp_path / "old-bot"
    bot_dir.mkdir()
    (bot_dir / "trade_journal.jsonl").write_text("{}\n")
    monkeypatch.setattr(remove, "BOTS_DIR", str(tmp_path))

    msg = remove.purge("old-bot")

    assert not bot_dir.exists()
    assert "supprimé" in msg


def test_purge_archive_renames_instead_of_deleting(tmp_path, monkeypatch):
    bot_dir = tmp_path / "old-bot"
    bot_dir.mkdir()
    monkeypatch.setattr(remove, "BOTS_DIR", str(tmp_path))

    msg = remove.purge("old-bot", archive=True)

    assert not bot_dir.exists()
    assert any(p.name.startswith("old-bot.bak-") for p in tmp_path.iterdir())
    assert "archivé" in msg


def test_purge_missing_bot_directory_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(remove, "BOTS_DIR", str(tmp_path))
    msg = remove.purge("never-existed")
    assert "aucun dossier" in msg
