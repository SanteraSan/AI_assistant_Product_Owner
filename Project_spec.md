# Умный AI-ассистент для Product Owner

Учебный pet-проект для практического изучения локальных LLM, RAG, Qdrant, PostgreSQL, Ollama, model routing, fine-tuning и постепенного перехода от простого RAG к agentic-сценариям.

## 1. Главная Идея

Мы разрабатываем AI-ассистента для Product Owner, который помогает связывать в одну картину:

- техническую документацию продукта;
- пользовательский фидбек;
- бизнес-метрики;
- историю обсуждений с пользователем.

Цель проекта не в том, чтобы сразу построить enterprise-ready систему, а в том, чтобы руками пройти ключевые слои LLM-приложения:

- ingestion данных;
- chunking;
- embeddings;
- vector search;
- metadata filtering;
- prompt/context assembly;
- chat memory;
- локальный inference через Ollama;
- ручной и автоматический выбор модели;
- fine-tune маленького classifier/router;
- логирование и сравнение качества разных подходов.

Итоговая версия может выглядеть как Agentic RAG с мультимодельным роутингом, но первая версия должна быть максимально прозрачной и отлаживаемой.

## 2. Принцип Реализации

Проект строится по принципу "сначала научиться ходить, потом бежать марафон".

На ранних этапах мы не прячем логику в сложный agent framework. Вместо этого делаем явные компоненты:

- `ingestion service` - загрузка и подготовка документов;
- `embedding service` - получение векторов;
- `retriever service` - поиск в Qdrant;
- `context builder` - сборка промпта из истории и найденных chunks;
- `model client` - вызов Ollama;
- `router` - выбор модели по сложности запроса;
- `chat API` - единая точка входа для UI.

Так будет проще понять, почему ассистент ответил хорошо или плохо: проблема в чанках, embeddings, retrieval, prompt, модели или роутере.

## 3. Целевая Архитектура

### 3.1 Backend

Backend пишем на `FastAPI`.

Основные задачи backend:

- принимать chat-запросы;
- хранить историю диалогов в PostgreSQL;
- вызывать retrieval в Qdrant;
- собирать контекст для модели;
- выбирать модель вручную или автоматически;
- вызывать Ollama;
- возвращать ответ, источники, выбранную модель и diagnostic metadata.

### 3.2 Qdrant

Qdrant используется для хранения векторных представлений документов.

В первой версии используем одну коллекцию, чтобы быстро получить рабочий RAG. После этого расширяемся до трех доменных коллекций:

- `tech_knowledge` - техническая документация;
- `user_feedback` - голос пользователя;
- `business_metrics` - бизнес-показатели.

На старте лучше использовать одну embedding-модель для всех коллекций. Это упростит сравнение результатов и отладку retrieval. Эксперименты с разными embeddings для разных коллекций можно добавить позже.

### 3.3 PostgreSQL

PostgreSQL хранит не сами vectors, а состояние приложения:

- chat sessions;
- user messages;
- assistant messages;
- conversation summaries;
- выбранные модели;
- решения router;
- retrieval logs;
- latency/token metrics;
- feedback пользователя на ответы.

Postgres нужен не "для галочки", а как основа памяти, наблюдаемости и последующего анализа качества.

### 3.4 Ollama

Ollama используется как основной локальный LLM provider.

Важно: при работе через Ollama мы не управляем моделями напрямую через `torch.cuda.empty_cache()`. Вместо этого backend выбирает имя модели в запросе, а Ollama сам занимается загрузкой, удержанием и выгрузкой модели.

Для управления поведением можно использовать:

- имя модели в каждом запросе;
- `keep_alive`;
- настройки Ollama;
- логирование времени первого и повторного вызова модели.

### 3.5 Frontend

Frontend можно сделать на `React`.

Минимальный UI:

- окно чата;
- выбор модели вручную;
- индикатор текущей модели;
- индикатор выбранной сложности запроса;
- список источников, на которых основан ответ;
- простая панель диагностики: latency, retrieval count, router decision.

## 4. Данные И Коллекции

### 4.1 MVP: Одна Коллекция

Первая версия RAG должна работать на одной коллекции, например `documents`.

Цель:

- загрузить небольшой набор Markdown/текстовых/CSV данных;
- нарезать на chunks;
- сохранить в Qdrant;
- получить grounded answer с источниками.

Это позволит быстро проверить весь путь:

`document -> chunk -> embedding -> Qdrant -> retrieval -> prompt -> Ollama -> answer`

### 4.2 Целевая Версия: Три Коллекции

После рабочего MVP добавляем три коллекции.

#### `tech_knowledge`

Источник:

- OpenAPI/Swagger;
- README;
- технические описания сервисов;
- архитектурные заметки.

Метаданные:

- `source_type`;
- `service_name`;
- `endpoint`;
- `method`;
- `version`;
- `file_path`.

Chunking:

- 400-700 токенов;
- overlap 50-100 токенов;
- не разрывать описание endpoint без необходимости.

#### `user_feedback`

Источник:

- CSV с отзывами;
- support tickets;
- Kaggle datasets;
- письма или комментарии пользователей.

Метаданные:

- `date`;
- `sentiment`;
- `product_feature`;
- `source`;
- `customer_segment`.

Chunking:

- одна строка CSV может быть одним документом;
- для длинных обращений можно делать chunks по 150-300 токенов.

#### `business_metrics`

Источник:

- CSV/Excel с NPS;
- retention;
- churn;
- error rate;
- adoption metrics.

Метаданные:

- `period`;
- `metric_type`;
- `product_feature`;
- `region`;
- `source_file`.

Особенность:

- числовые данные переводим в текстовый digest;
- например: "В марте NPS по функции X снизился с 52 до 45".

## 5. RAG Pipeline

### 5.1 Базовый RAG

Первый рабочий pipeline:

1. Пользователь отправляет вопрос.
2. Backend сохраняет сообщение в PostgreSQL.
3. Запрос превращается в embedding.
4. Qdrant возвращает top-k chunks.
5. Context builder собирает prompt.
6. Ollama генерирует ответ.
7. Backend сохраняет ответ и diagnostic metadata.
8. UI показывает ответ и источники.

### 5.2 Multi-Collection Retrieval

После MVP добавляем поиск по трем коллекциям:

- `tech_knowledge` - технические вопросы;
- `user_feedback` - проблемы и голос пользователя;
- `business_metrics` - вопросы про метрики, даты, динамику.

На первом этапе можно искать во всех коллекциях параллельно и объединять top-k. Позже router сможет решать, какие коллекции нужны для конкретного запроса.

### 5.3 Ranking И Context Builder

Context builder должен явно контролировать, что попадает в prompt:

- system instruction;
- summary диалога, если оно есть;
- последние 3-5 сообщений;
- найденные chunks;
- краткие metadata по источникам;
- инструкция отвечать только на основе найденного контекста.

Важно логировать:

- какие chunks были выбраны;
- какие score они получили;
- из какой коллекции они пришли;
- сколько токенов ушло в prompt.

## 6. Память Диалога

Память делаем через PostgreSQL.

### 6.1 Сырые Сообщения

Храним все сообщения:

- `session_id`;
- `role`;
- `content`;
- `model`;
- `created_at`;
- `metadata`.

### 6.2 Саммари

Когда диалог становится длинным, создаем summary.

Summary должно содержать:

- цель пользователя;
- важные решения;
- ограничения;
- открытые вопросы;
- краткий контекст разговора.

При новом запросе в prompt передаем:

- system instruction;
- summary, если есть;
- последние несколько сообщений;
- найденные chunks из Qdrant.

Так контекст сохраняется даже при переключении моделей.

## 7. Модели И Свопинг

### 7.1 Модельная Лестница

Для 16 GB VRAM имеет смысл держать несколько уровней моделей.

Tiny:

- `qwen2.5:0.5b`;
- `llama3.2:1b`.

Задачи:

- быстрые ответы;
- smoke tests;
- fallback;
- простые router/summarization эксперименты.

Small:

- `qwen2.5:3b`;
- `llama3.2:3b`.

Задачи:

- простые Q&A;
- короткие summary;
- дешевые ответы.

Medium:

- `qwen2.5:7b`;
- `mistral:7b`;
- `llama3.1:8b`.

Задачи:

- основной RAG default;
- ответы по документации;
- большинство пользовательских вопросов.

Heavy:

- `qwen2.5:14b`;
- `phi4:14b`, если комфортно работает локально.

Задачи:

- глубокая аналитика;
- сравнение источников;
- ответы на вопросы "почему";
- сложные PO-сценарии.

Embedding:

- `nomic-embed-text`;
- `bge-m3`;
- sentence-transformers baseline.

### 7.2 Manual Model Switching

Сначала делаем ручной выбор модели:

- пользователь выбирает модель в UI;
- backend получает `model_name`;
- Ollama вызывается с этой моделью;
- Postgres сохраняет, какая модель ответила.

Это даст понятный baseline до автоматического router.

### 7.3 Automatic Model Routing

После ручного выбора добавляем router.

Классы сложности:

- `low` - приветствия, простые факты, короткие вопросы;
- `medium` - обычные RAG-вопросы, уточнения, вопросы по одному источнику;
- `high` - аналитика, сравнение, причинно-следственные вопросы, запросы по нескольким источникам.

Router возвращает:

- `complexity`;
- `intent`;
- `selected_model`;
- `confidence`;
- `reason`.

Все решения router логируются в PostgreSQL.

## 8. Fine-Tune Router

Fine-tune не убираем далеко. Он становится отдельным ранним research milestone после появления простого baseline-router.

### 8.1 Зачем Нужен Baseline До Fine-Tune

Перед fine-tune нужен простой baseline, чтобы было с чем сравнивать.

Сначала реализуем:

- rule-based router;
- возможно embedding-based classifier;
- логирование ошибок router.

После этого fine-tune становится осмысленным экспериментом, а не магическим усложнением.

### 8.2 Fine-Tune Эксперимент

Модель:

- `distilbert-base-uncased` или более подходящая multilingual/ru-compatible модель, если запросы будут на русском;
- альтернативно можно рассмотреть `cointegrated/rubert-tiny2` для русскоязычного router.

Датасет:

- 500-1000 синтетических запросов;
- классы `low`, `medium`, `high`;
- отдельная разметка intent;
- часть запросов на русском, если основной UI будет русскоязычным.

Метрики:

- accuracy;
- confusion matrix;
- latency на CPU;
- сравнение с rule-based router;
- сравнение с embedding baseline.

Критерий успеха:

- fine-tuned router быстрее и/или точнее baseline;
- ошибки понятны и задокументированы;
- решение router объяснимо в debug output.

## 9. Agentic Layer

Agentic RAG добавляем только после того, как обычный RAG стабильно работает.

Возможные agentic-функции:

- router решает, какие коллекции искать;
- ассистент задает уточняющий вопрос, если данных недостаточно;
- отдельный evaluator проверяет, есть ли ответ в найденном контексте;
- planner разбивает сложный PO-запрос на подзадачи.

LangChain или другой framework можно подключить на этом этапе, но не раньше.

Главное правило:

- каждый шаг агента должен логироваться;
- пользователь или разработчик должен понимать, почему агент сделал именно это.

## 10. Технологический Стек

Core stack:

- `Python`;
- `FastAPI`;
- `PostgreSQL`;
- `Qdrant`;
- `Ollama`;
- `React`;
- `Docker Compose`.

Data processing:

- `Pandas` для CSV/Excel;
- `Unstructured` или более простые парсеры для документов;
- `sentence-transformers` или Ollama embeddings.

ML/Fine-tune:

- `transformers`;
- `datasets`;
- `scikit-learn`;
- `torch`;
- `evaluate`.

Отложить на поздние этапы:

- `Keycloak`;
- `OpenRouter fallback`;
- CPU pinning;
- сложный hybrid search;
- полноценный LangChain agent graph.

## 11. Roadmap

### M0. Local LLM Smoke Test

Цель: проверить, что локальные модели реально работают.

Задачи:

- установить и проверить Ollama;
- скачать 3-4 модели разных размеров;
- сделать простой FastAPI endpoint для вызова выбранной модели;
- измерить latency первого и повторного ответа.

Definition of Done:

- backend умеет вызвать любую выбранную модель;
- результаты записаны в README;
- понятно, какие модели комфортно работают на текущем железе.

### M1. Single-Collection RAG

Цель: собрать первый рабочий RAG.

Задачи:

- поднять Qdrant и PostgreSQL через Docker Compose;
- написать ingestion для простых документов;
- сделать chunking;
- сохранить embeddings в Qdrant;
- реализовать `/chat`;
- возвращать ответ с источниками.

Definition of Done:

- ассистент отвечает на основе загруженных документов;
- в ответе есть источники;
- можно посмотреть, какие chunks попали в prompt.

### M2. Chat Memory

Цель: добавить память и сохранение контекста.

Задачи:

- создать таблицы sessions/messages/summaries;
- сохранять user и assistant messages;
- добавить summary после длинного диалога;
- использовать summary при сборке prompt.

Definition of Done:

- после переключения модели контекст диалога не теряется;
- последние сообщения и summary попадают в prompt;
- все это видно в debug/log output.

### M3. Manual Model Switching

Цель: научиться управлять моделями явно.

Задачи:

- добавить список моделей в конфиг;
- передавать выбранную модель в `/chat`;
- сохранять выбранную модель в PostgreSQL;
- показать текущую модель в UI или debug response.

Definition of Done:

- можно вручную переключать модели;
- видно, какая модель ответила;
- можно сравнить latency и качество ответов.

### M4. Baseline Router

Цель: сделать первый автоматический выбор модели.

Задачи:

- реализовать rule-based router;
- классифицировать запросы на `low`, `medium`, `high`;
- выбирать модель по сложности;
- логировать решение router.

Definition of Done:

- router автоматически выбирает модель;
- пользователь может переопределить выбор вручную;
- каждое решение объясняется в metadata.

### Backend Hardening Block

Цель: перед новыми возможностями укрепить backend как production-minded foundation.

Задачи:

- перейти к Alembic migrations для развития схемы БД;
- добавить DB constraints и индексы для ключевых таблиц;
- усилить config validation;
- добавить structured logging и request/correlation id;
- унифицировать error handling;
- добавить request validation и limits;
- заложить Auth/RBAC foundation с deterministic access filtering до prompt;
- сделать ingestion idempotency и status model;
- вынести heavy ingestion/OCR/vision/future audio в background jobs;
- разделить health/readiness diagnostics;
- добавить Redis-backed queueing, rate limiting и Ollama concurrency control.

Definition of Done:

- каждый hardening sub-step имеет тесты или smoke checks;
- после существенных backend изменений запускается targeted regression;
- результаты фиксируются в инженерном журнале.

### M7. LoRA Text-to-SQL Fine-Tuning

Цель: добавить прикладной fine-tuning слой для аналитических вопросов к PostgreSQL.

Задачи:

- собрать schema context для PostgreSQL;
- сделать prompt-only Text-to-SQL baseline;
- сравнить `qwen3.5:9b`, `gemma4:12b`, `qwen2.5-coder:7b` и опционально `qwen2.5-coder:14b`;
- подготовить dataset формата `instruction/input/output`;
- покрыть SQL cases: JOIN, GROUP BY, CTE, window functions, JSONB, date filters, top-N, evaluation analytics;
- обучить LoRA/QLoRA adapter для Qwen Coder 7B class модели;
- сравнить baseline vs LoRA на holdout benchmark;
- добавить SQL validator: только read-only `SELECT`, schema adherence, timeout, запрет destructive statements;
- интегрировать safe Text-to-SQL flow в backend только после validation и regression.

Definition of Done:

- есть baseline report;
- есть versioned dataset и train/validation/test split;
- есть LoRA adapter artifact или documented compatibility finding;
- есть holdout evaluation: SQL validity, execution success, schema adherence, safety, latency;
- понятно, где LoRA улучшает baseline, а где нет.

### M8. Analytics UI, Dashboards And Reports

Цель: сделать аналитический слой демонстрируемым и полезным без curl/Postman.

Задачи:

- Streamlit UI для аналитических вопросов;
- отображать сгенерированный SQL;
- выполнять только валидированные read-only queries;
- показывать таблицу результата;
- строить Plotly charts;
- экспортировать Excel/PDF reports;
- показывать debug metadata: model, latency, validator decision, execution status.

Definition of Done:

- есть end-to-end flow `question -> SQL -> table -> chart/report`;
- есть smoke scenarios для UI/reporting;
- результаты и ограничения задокументированы.

### Future Features

Направления, которые остаются в backlog и не блокируют M7/M8:

- voice input / local STT / transcript-to-chat;
- multi-collection Qdrant retrieval;
- advanced model routing/provider strategy;
- multi-agent layer.

Правило: future features добавляются только после observability, evaluation criteria и clear failure modes.

## 12. Переменные Окружения

```bash
# LLM PROVIDERS
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434

# MODELS
MODEL_TINY=qwen2.5:0.5b
MODEL_SMALL=qwen2.5:3b
MODEL_MEDIUM=qwen2.5:7b
MODEL_HEAVY=qwen2.5:14b

# EMBEDDINGS
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text

# VECTOR DB
QDRANT_HOST=localhost
QDRANT_PORT=6333

# POSTGRES
POSTGRES_DSN=postgresql://user:pass@localhost:5432/po_assistant

# ROUTER
ROUTER_MODE=rules
ROUTER_MODEL_PATH=models/router-classifier
```

## 13. Критерии Успеха

MVP успешен, если:

- локальная модель отвечает через FastAPI;
- документы загружаются в Qdrant;
- ассистент отвечает на основе найденных chunks;
- ответ содержит источники;
- история сохраняется в PostgreSQL;
- можно вручную выбрать модель.

Расширенная версия успешна, если:

- backend имеет migrations, validation, observability и overload protection;
- LoRA Text-to-SQL сравнен с prompt-only baseline;
- SQL generation проходит validation и read-only safety checks;
- analytics UI показывает SQL, таблицу, график и report export;
- context сохраняется при смене модели;
- README содержит честные benchmark-выводы.

## 14. Главные Учебные Вопросы

В процессе проекта нужно постоянно отвечать на вопросы:

- какие chunks реально попадают в prompt;
- почему retrieval нашел именно эти документы;
- насколько модель следует контексту;
- когда маленькой модели достаточно;
- когда нужна 7B или 14B модель;
- дает ли LoRA Text-to-SQL пользу относительно prompt-only baseline;
- сколько стоит переключение модели по latency;
- какие metadata улучшают поиск;
- где RAG начинает галлюцинировать;
- где SQL model нарушает schema или safety constraints;
- какие решения стоит оставить для "почти production", а какие были просто учебным экспериментом.

Главная цель проекта - не просто собрать демо, а понять внутреннюю механику LLM-приложения так, чтобы потом уверенно проектировать более серьезные системы.