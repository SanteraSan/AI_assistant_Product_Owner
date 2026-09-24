from types import SimpleNamespace

from app.services.sticky_document_scope import (
    confine_document_ids,
    resolve_sticky_document_scope,
)


def _doc(document_id: str, file_name: str) -> SimpleNamespace:
    return SimpleNamespace(id=document_id, file_name=file_name, title=file_name)


def test_question_without_a_name_stays_on_the_active_file() -> None:
    documents = [
        _doc("resume", "резюме.pdf"),
        _doc("timing", "вставленное изображение.png"),
    ]
    scope = resolve_sticky_document_scope(
        message="Подскажи в какое время был самый лучший advanced?",
        requested_document_ids=["resume", "timing"],
        attached_document_ids=["resume", "timing"],
        active_document_id="timing",
        documents=documents,  # type: ignore[arg-type]
    )
    assert scope.narrowed is True
    assert scope.document_ids == ["timing"]


def test_last_attachment_is_active_until_a_file_is_named() -> None:
    documents = [
        _doc("resume", "резюме.pdf"),
        _doc("timing", "вставленное изображение.png"),
    ]
    scope = resolve_sticky_document_scope(
        message="Что в этом файле?",
        requested_document_ids=["resume", "timing"],
        attached_document_ids=["resume", "timing"],
        active_document_id=None,
        documents=documents,  # type: ignore[arg-type]
    )
    assert scope.document_ids == ["timing"]
    assert scope.active_document_id == "timing"


def test_naming_a_file_switches_the_active_file_and_sticks() -> None:
    documents = [
        _doc("resume", "резюме.pdf"),
        _doc("timing", "вставленное изображение.png"),
    ]
    named = resolve_sticky_document_scope(
        message="так хорошо, а теперь про файл резюме — какой стек?",
        requested_document_ids=["timing"],
        attached_document_ids=["resume", "timing"],
        active_document_id="timing",
        documents=documents,  # type: ignore[arg-type]
    )
    assert named.document_ids == ["resume"]
    assert named.active_document_id == "resume"

    follow_up = resolve_sticky_document_scope(
        message="а какой там был UI kit?",
        requested_document_ids=["resume", "timing"],
        attached_document_ids=["resume", "timing"],
        active_document_id=named.active_document_id,
        documents=documents,  # type: ignore[arg-type]
    )
    assert follow_up.document_ids == ["resume"]


def test_topic_words_do_not_jump_to_another_file() -> None:
    documents = [
        _doc("resume", "резюме.pdf"),
        _doc("smeta", "smeta-materials-table.png"),
    ]
    scope = resolve_sticky_document_scope(
        message="Какая итоговая сумма в смете?",
        requested_document_ids=["resume", "smeta"],
        attached_document_ids=["smeta", "resume"],
        active_document_id="resume",
        documents=documents,  # type: ignore[arg-type]
    )
    assert scope.document_ids == ["resume"]


def test_inventory_question_is_not_narrowed() -> None:
    documents = [_doc("resume", "резюме.pdf")]
    scope = resolve_sticky_document_scope(
        message="Какие файлы доступны?",
        requested_document_ids=[],
        attached_document_ids=["resume"],
        active_document_id="resume",
        documents=documents,  # type: ignore[arg-type]
    )
    assert scope.narrowed is False
    assert scope.document_ids == []


def test_confine_document_ids_cannot_leave_the_active_file() -> None:
    assert confine_document_ids(["resume"], ["timing"]) == ["timing"]
    assert confine_document_ids([], ["timing"]) == ["timing"]
    assert confine_document_ids(["other"], []) == ["other"]


def test_confine_document_ids_can_switch_to_another_file_in_the_chat() -> None:
    assert confine_document_ids(["timing"], ["smeta"], ["smeta", "timing"]) == ["timing"]
    assert confine_document_ids([], ["smeta"], ["smeta", "timing"]) == ["smeta"]
    assert confine_document_ids(["other"], ["smeta"], ["smeta", "timing"]) == ["smeta"]
