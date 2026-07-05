# RAG Prompt Benchmarks

Папка содержит воспроизводимые prompt-файлы для ручных benchmark-тестов локальных моделей.

## Medium Context Test

Файл:

```text
research/prompts/rag_medium_context_prompt.txt
```

Цель:

- проверить, как модель работает с RAG-like контекстом;
- проверить, умеет ли связывать metrics, feedback, incident note и tech docs;
- проверить, игнорирует ли distractor chunk;
- сравнить `qwen2.5:7b-instruct-q8_0`, `qwen2.5:14b` и `gemma3:12b`.

## Long Context With Distractors Test

Файл:

```text
research/prompts/rag_long_context_with_distractors.txt
```

Цель:

- проверить, как модель работает с более длинным RAG-like контекстом;
- проверить устойчивость к большому числу нерелевантных chunks;
- проверить, отделяет ли модель evidence от distractors;
- проверить, сохраняет ли модель Product Owner focus;
- сравнить поведение `7B Q8`, `14B` и `gemma3:12b` перед будущим настоящим RAG.

## No-Answer Groundedness Test

Файл:

```text
research/prompts/rag_no_answer_groundedness_prompt.txt
```

Цель:

- проверить, умеет ли модель отказаться от ответа, если в контексте нет нужных фактов;
- проверить, не выдумывает ли модель ARR loss, churn probability и список клиентов;
- проверить, отделяет ли модель факты от осторожных интерпретаций;
- проверить, какие модели лучше подходят для strict enterprise RAG.

## Модели Для Первого Прогона

```text
qwen2.5:7b-instruct-q8_0
qwen2.5:14b
gemma3:12b
```

## Универсальная Команда

Из корня проекта:

```bash
cd /home/santera/Projects
MODEL="qwen2.5:7b-instruct-q8_0"
jq -Rs --arg model "$MODEL" \
  '{model:$model,prompt:.,stream:false,keep_alive:"10m",options:{temperature:0.1,top_p:0.9}}' \
  research/prompts/rag_medium_context_prompt.txt | \
curl -s http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d @- | jq
```

Для long-context теста поменять файл:

```bash
cd /home/santera/Projects
MODEL="gemma3:12b"
PROMPT_FILE="research/prompts/rag_long_context_with_distractors.txt"
jq -Rs --arg model "$MODEL" \
  '{model:$model,prompt:.,stream:false,keep_alive:"10m",options:{temperature:0.1,top_p:0.9}}' \
  "$PROMPT_FILE" | \
curl -s http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d @- | jq
```

Для no-answer groundedness теста:

```bash
cd /home/santera/Projects
MODEL="gemma3:12b"
PROMPT_FILE="research/prompts/rag_no_answer_groundedness_prompt.txt"
jq -Rs --arg model "$MODEL" \
  '{model:$model,prompt:.,stream:false,keep_alive:"10m",options:{temperature:0.1,top_p:0.9}}' \
  "$PROMPT_FILE" | \
curl -s http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d @- | jq
```

Для другой модели поменять только `MODEL`:

```bash
MODEL="qwen2.5:14b"
```

или:

```bash
MODEL="gemma3:12b"
```

## Что Выполнить После Каждого Запроса

```bash
ollama ps
nvidia-smi
```

## Что Сохранять Из JSON

Нужны поля:

```json
{
  "model": "...",
  "response": "...",
  "total_duration": 0,
  "load_duration": 0,
  "prompt_eval_count": 0,
  "prompt_eval_duration": 0,
  "eval_count": 0,
  "eval_duration": 0
}
```

Длительности Ollama отдает в наносекундах.

## Как Оценивать Качество

Оценить ответ вручную по шкале `1-5`:

- `groundedness`: ответ основан на контексте, без выдуманных фактов;
- `source_use`: модель использует metrics, feedback, incident и tech docs;
- `distractor_resistance`: модель игнорирует CSV import chunk;
- `persona_fit`: ответ полезен Product Owner, а не только инженеру;
- `actionability`: есть практичные next steps.

## Ожидаемый Хороший Ответ

Хорошая модель должна:

- указать, что главная проблема - задержка Slack notifications на 15-20 минут;
- связать проблему с падением adoption с 61% до 48%;
- упомянуть рост support tickets до 47;
- упомянуть падение NPS с 41 до 32;
- объяснить техническую причину: Slack rate limits и слишком агрессивный retry/backoff;
- предложить поднять приоритет проблемы в roadmap;
- предложить next steps: исправить retry policy, добавить delivery status UI, включить metric notification delivery delay, подготовить workaround через email notifications;
- не использовать CSV import как аргумент.

Для long-context prompt хорошая модель дополнительно должна:

- использовать trend за январь-февраль-март;
- отличить релевантные chunks `notifications` от distractors `csv_import`, `search`, `permissions`, `billing`, `mobile_app`;
- не включать distractor chunks в список использованных источников;
- связать enterprise retention risk с потерей доверия, ручной проверкой задач и возможным отключением Slack integration;
- предложить roadmap initiative `Notification Reliability` или аналогичный набор работ.

Для no-answer groundedness prompt хорошая модель должна:

- явно сказать, что в контексте нет данных для точного ARR loss;
- не назвать выдуманную сумму revenue loss;
- не назвать выдуманную churn probability;
- не назвать список клиентов, которые "точно уйдут";
- перечислить известные факты: adoption, tickets, NPS, satisfaction, critical ticket;
- осторожно сказать, что риск удержания есть, но его нельзя количественно оценить без revenue/customer data;
- запросить недостающие данные: ARR по затронутым клиентам, contract value, renewal dates, account health, список affected accounts.
