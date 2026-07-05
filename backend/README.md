# Backend M0: Ollama Smoke Test

Минимальный `FastAPI` backend для проверки локального inference через Ollama.

На этом этапе нет RAG, Qdrant и PostgreSQL. Цель M0 - убедиться, что backend умеет отправить запрос в локальную модель и вернуть ответ.

## Что Нужно Установить

На новой Ubuntu/Debian-системе:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv curl
```

Docker понадобится для следующих этапов:

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

После добавления пользователя в группу `docker` нужно перелогиниться или выполнить:

```bash
newgrp docker
```

Ollama лучше установить официальным скриптом:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Проверить GPU в обычном терминале:

```bash
nvidia-smi
```

Если `nvidia-smi` не видит драйвер, сначала нужно починить NVIDIA-драйвер. Без этого Ollama может работать на CPU, но будет медленно.

## Первая Модель

Скачать маленькую модель для smoke test:

```bash
ollama pull qwen2.5:0.5b
```

Проверить напрямую:

```bash
ollama run qwen2.5:0.5b
```

## Запуск Backend

Из папки проекта:

```bash
cd /home/santera/Projects/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Проверка

Health check:

```bash
curl http://localhost:8000/health
```

Chat request:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Привет! Ответь одним предложением, что ты работаешь локально.","model":"qwen2.5:0.5b"}'
```

Ожидаемый результат:

- backend отвечает HTTP 200;
- поле `provider` равно `ollama`;
- поле `model` равно выбранной модели;
- поле `latency_ms` показывает время ответа;
- поле `response` содержит текст модели.

## Если Ollama Не Доступна

Проверить сервис:

```bash
ollama list
```

Если команда не работает, запустить:

```bash
ollama serve
```

В отдельном терминале снова проверить `/health`.

## Что Коммитить После M0

После успешного smoke test:

```bash
git status
git add backend research/LESSONS_LEARNED.md
git commit -m "feat: add ollama smoke test backend"
git push
```
