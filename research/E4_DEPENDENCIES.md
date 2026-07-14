# E4 Dependencies Checklist

Установи **до** начала реализации E4.1. После установки напиши в чат — можно переходить к коду.

## 1. n8n (Docker)

Вариант A — отдельный контейнер (проще для старта):

```bash
docker run -d --name taskflow-n8n \
  -p 5678:5678 \
  -v taskflow_n8n_data:/home/node/.n8n \
  -v /home/santera/Projects/data/integrations:/data/integrations \
  docker.n8n.io/n8nio/n8n
```

Вариант B — добавить сервис в `docker-compose.yml` (сделаем в коде E4; пока достаточно A).

Проверка: открыть http://localhost:5678 и пройти initial owner setup (локальный аккаунт n8n).

## 2. Synthetic external Postgres

Отдельная БД (не путать с `taskflow-postgres` на `5432`):

```bash
docker run -d --name taskflow-postgres-external \
  -e POSTGRES_DB=external_demo \
  -e POSTGRES_USER=external_user \
  -e POSTGRES_PASSWORD=external_password \
  -p 5433:5432 \
  postgres:16-alpine
```

Проверка:

```bash
docker exec taskflow-postgres-external pg_isready -U external_user -d external_demo
```

Seed-таблицы положим скриптом в E4.1 (тебе сейчас достаточно контейнера up).

## 3. Inbox folder на диске

```bash
mkdir -p /home/santera/Projects/data/integrations/inbox
mkdir -p /home/santera/Projects/data/integrations/processed
```

Сюда n8n будет читать файлы (и/или мы смонтируем путь в compose позже).

## 4. Уже должно быть запущено (TaskFlow)

- `docker compose up -d` (postgres 5432, qdrant, redis, keycloak)
- backend `:8000`, BFF `:8001` (для agent smoke)
- Ollama + tag `qwen2_5_coder_7b_v5_projection_steps400` (Text-to-SQL)

## 5. Не нужно для E4.1

- Gmail / Yandex / Outlook OAuth
- Jira Cloud account
- Kafka

## Когда готово

Чеклист выполнен, если:

```text
n8n: http://localhost:5678 OK
external postgres: 5433 OK
inbox dir: exists
```

Реализация E4.1: см. `backend/README.md` § E4.1 и `.cursor/plans/e4_n8n_integrations.plan.md`.
