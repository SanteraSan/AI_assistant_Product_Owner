from collections.abc import Iterable


class FeatureExtractor:
    def __init__(self) -> None:
        self._rules: dict[str, tuple[str, ...]] = {
            "notifications": (
                "notification",
                "notifications",
                "уведом",
                "slack",
                "telegram",
                "delivery",
                "доставк",
            ),
            "csv_import": (
                "csv",
                "import",
                "импорт",
                "mapping",
                "validation",
                "assignee_email",
            ),
            "permissions": (
                "permission",
                "permissions",
                "доступ",
                "роль",
                "роли",
                "прав",
                "viewer",
                "manager",
                "admin",
            ),
            "reports": (
                "report",
                "reports",
                "отчет",
                "отчёт",
                "sla",
                "nps",
                "adoption",
                "metric",
                "метрик",
            ),
            "search": (
                "search",
                "поиск",
                "найти",
                "фильтр",
                "assignee",
            ),
            "webhooks": (
                "webhook",
                "webhooks",
                "retry",
                "signature",
                "payload",
            ),
            "integrations": (
                "integration",
                "integrations",
                "интеграц",
                "github",
                "gitlab",
                "email",
            ),
            "tasks": (
                "task",
                "tasks",
                "задач",
                "status",
                "priority",
                "due date",
            ),
            "projects": (
                "project",
                "projects",
                "проект",
                "workspace",
            ),
            "sprints": (
                "sprint",
                "sprints",
                "спринт",
                "velocity",
                "capacity",
            ),
        }

    def extract(self, text: str) -> list[str]:
        normalized = text.lower()
        matched = [
            feature
            for feature, keywords in self._rules.items()
            if _contains_any(normalized, keywords)
        ]
        return matched


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)
