# RFC: CSV Import V2

Feature: `csv_import`, `tasks`, `permissions`

Persona relevance: `Developer`, `PM`, `Support Manager`

## Цель

CSV Import V2 должен позволить командам массово создавать задачи в проекте из CSV-файла без ручного копирования данных.

## Обязательные Колонки

- `title`;
- `project_key`;
- `assignee_email`, если задача должна быть назначена;
- `priority`, если приоритет отличается от `medium`;
- `due_date`, если есть срок выполнения.

## Validation Rules

Импорт возвращает `400`, если:

- отсутствует `title`;
- `project_key` не существует;
- `assignee_email` не принадлежит workspace;
- `priority` не входит в `low`, `medium`, `high`, `critical`;
- `due_date` не является валидной датой.

Импорт возвращает `403`, если пользователь не имеет права создавать задачи в проекте.

## Partial Import

Если `rollback_on_error=true`, весь импорт откатывается при первой ошибке.

Если `rollback_on_error=false`, валидные строки импортируются, а ошибки возвращаются в отчете.

## Known Risk

Пользователи часто путают `assignee_email` и `assignee_name`. Для support-команды нужно подготовить macro-ответ с примером корректного CSV.
