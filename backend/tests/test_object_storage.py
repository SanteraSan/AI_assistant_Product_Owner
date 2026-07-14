from pathlib import Path

from app.services.object_storage import (
    LocalFilesystemStorage,
    display_name_from_ref,
    is_storage_uri,
    storage_uri,
)


def test_local_storage_put_move_get(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    ref = storage.put("tenant/staging/u1_note.txt", b"hello", content_type="text/plain")
    assert Path(ref).is_file()
    assert storage.get(ref) == b"hello"
    moved = storage.move(ref, "tenant/documents/d1_note.txt")
    assert storage.get(moved) == b"hello"
    assert not Path(ref).exists()


def test_storage_uri_helpers() -> None:
    assert is_storage_uri("storage://a/b.txt")
    assert not is_storage_uri("/tmp/a.txt")
    assert storage_uri("a/b.txt") == "storage://a/b.txt"
    assert display_name_from_ref("storage://tenant/documents/id_photo.jpg") == "id_photo.jpg"
    assert display_name_from_ref("/abs/path/id_photo.jpg") == "id_photo.jpg"
