# Lessons Learned

Инженерный журнал проекта `TaskFlow AI`.

Цель файла - фиксировать не только финальные решения, но и путь обучения: что пробовали, что сломалось, какие выводы сделали и какие решения оставили.

## Как Вести Журнал

Каждая запись должна быть короткой, но полезной.

Рекомендуемый формат:

```markdown
## YYYY-MM-DD: Короткий Заголовок

Контекст:
- что пытались сделать;
- почему это было важно.

Наблюдение:
- что получилось;
- что сломалось;
- какие метрики или ошибки увидели.

Решение:
- что изменили;
- какой подход оставили.

Вывод:
- что теперь знаем;
- как это влияет на проект.
```

## 2026-07-05: Стартовая Архитектура Данных

Контекст:

- нужно подготовить учебный RAG-датасет для B2B SaaS project management продукта;
- цель - не объем данных, а связность между техдоками, feedback и метриками.

Наблюдение:

- случайные e-commerce отзывы плохо подходят для домена `TaskFlow AI`;
- support tickets можно использовать как форму данных, но тексты и категории нужно нормализовать под продукт;
- personas полезно добавить сразу, потому что они влияют на prompt, evaluation и структуру seed questions.

Решение:

- зафиксировать вымышленный продукт `TaskFlow AI`;
- использовать feature taxonomy как общий словарь для Qdrant payload, feedback, metrics и test questions;
- добавить роли `PO`, `PM`, `Developer`, `Support Manager` как prompt context, а не как authorization layer.

Вывод:

- хороший RAG-датасет должен быть маленьким, но связанным;
- важно заранее проектировать metadata, иначе retrieval будет трудно объяснять и отлаживать.

## Backlog Для Будущих Записей

Темы, которые стоит обязательно зафиксировать по мере разработки:

- результаты первого Ollama smoke test;
- latency разных моделей на локальной машине;
- cold start vs warm model response;
- качество `nomic-embed-text` или другой embedding-модели;
- оптимальный Qdrant batch size;
- проблемы chunking технических документов;
- проблемы парсинга PDF/Excel;
- первые ошибки retrieval;
- сравнение rule-based router и fine-tuned router;
- выводы по 7B vs 14B моделям.

## 2026-07-05: M0 Проверка Окружения

Контекст:

- система установлена сегодня;
- нужно подготовить первый локальный LLM smoke test через Ollama и FastAPI.

Наблюдение:

- `git` установлен и репозиторий уже привязан к GitHub;
- `python3` установлен;
- `python`, `pip3`, `docker` и `ollama` пока не установлены;
- `nvidia-smi` из sandbox-среды не смог связаться с NVIDIA driver, поэтому GPU нужно проверить отдельно в обычном терминале пользователя.

Решение:

- подготовлен минимальный `FastAPI` backend для вызова Ollama;
- добавлены инструкции установки `python3-pip`, `python3-venv`, Docker и Ollama;
- первой моделью для smoke test выбрана `qwen2.5:0.5b`, потому что она маленькая и быстро проверяет весь путь.

Вывод:

- M0 стоит делать в два шага: сначала системные зависимости, потом запуск backend;
- до проверки GPU не делаем выводов о производительности локальных моделей;
- backend scaffold можно готовить независимо от установки Ollama.

## 2026-07-05: M0 Успешный Ollama Smoke Test

Контекст:

- нужно проверить полный минимальный путь `FastAPI -> Ollama -> local model -> response`;
- в качестве первой модели выбрана `qwen2.5:0.5b`.

Наблюдение:

- GPU доступен: `NVIDIA GeForce RTX 5070 Ti`, `16303 MiB` VRAM;
- `nvidia-smi` в обычном терминале показывает driver `595.71.05` и CUDA `13.2`;
- `ollama pull qwen2.5:0.5b` успешно скачал модель размером `397 MB`;
- `/health` вернул `ollama_available: true`;
- первый `/chat` cold start занял `34312 ms`;
- повторный warm request занял `160 ms`;
- tiny-модель ответила быстро после прогрева, но качество русского ответа нестабильное: во втором ответе появилась китайская фраза.

Решение:

- считать M0 smoke test успешным;
- использовать `qwen2.5:0.5b` как техническую smoke-test модель, но не как показатель качества ответов;
- для реального RAG default позже проверить 3B/7B модели;
- в будущих benchmark обязательно разделять cold start и warm latency.

Вывод:

- локальный inference через Ollama и FastAPI работает;
- разница между cold и warm запуском критична для model switching;
- маленькая модель полезна для проверки инфраструктуры, но для русскоязычного ассистента потребуется модель крупнее.

## 2026-07-06: Short Prompt Model Benchmark

Контекст:

- после успешного M0 нужно подобрать локальную "лестницу" моделей под 16 GB VRAM;
- тестировали короткий вопрос: "Что такое RAG?";
- сравнивали cold/warm latency, качество русского ответа, VRAM usage, quantization и CPU/GPU split;
- основной язык будущего ассистента - русский, поэтому качество русскоязычного ответа важно.

Наблюдение:

- `qwen2.5:0.5b`:
  - размер на диске: `397 MB`;
  - cold total: `1.82s`, cold load: `1.37s`;
  - warm total: `0.81s`;
  - скорость генерации около `670 tok/s`;
  - качество ответа плохое: модель галлюцинировала и неверно интерпретировала `RAG`;
  - вывод: годится только как smoke-test модель.

- `qwen2.5:3b`:
  - размер на диске: `1.9 GB`;
  - cold total: `3.77s`, cold load: `3.39s`;
  - warm total: `0.32s`;
  - скорость генерации около `280 tok/s`;
  - качество ответа уже нормальное для простого определения;
  - вывод: кандидат для простых задач, summary, router baseline и дешевых проверок.

- `qwen2.5:7b` default:
  - размер на диске: `4.7 GB`;
  - cold total: `2.46s`, cold load: `1.90s`;
  - warm total: `0.64s`;
  - VRAM после загрузки: около `5469 MiB`;
  - скорость генерации warm около `154 tok/s`;
  - ответ рабочий, но русский местами шероховатый.

- `qwen2.5:7b-instruct-q8_0`:
  - размер в `ollama ps`: `7.9 GB`;
  - `PROCESSOR`: `100% GPU`;
  - cold total: `3.45s`, cold load: `2.12s`;
  - warm total: `0.68s`;
  - скорость генерации около `100 tok/s`;
  - при свободном prompt cold-ответ дал странные языковые артефакты;
  - при строгом prompt и `temperature=0.1` ответ стал хорошим;
  - вывод: сильный кандидат на medium/default RAG, но требует аккуратного prompt/options.

- `qwen2.5:7b-instruct-fp16`:
  - размер в `ollama ps`: `14 GB`;
  - `PROCESSOR`: `100% GPU`;
  - cold total: `9.28s`, cold load: `7.49s`;
  - warm total: `1.26s`;
  - скорость генерации warm около `56 tok/s`;
  - качество не оказалось лучше `7B Q8`: были китайские вставки и неточное определение;
  - вывод: FP16 не оправдал цену по памяти и скорости на этом коротком тесте.

- `qwen2.5:14b` default:
  - размер на диске: `9.0 GB`;
  - VRAM после загрузки: около `9981 MiB`;
  - cold total: `3.95s`, cold load: `2.24s`;
  - warm total: `1.45s`;
  - скорость генерации warm около `82 tok/s`;
  - качество русского ответа хорошее;
  - вывод: текущий лучший heavy-кандидат для аналитики и сложных PO-вопросов.

- `qwen2.5:14b-instruct-q8_0`:
  - размер в `ollama ps`: `16 GB`;
  - `PROCESSOR`: `14%/86% CPU/GPU`;
  - VRAM: `14578 MiB / 16303 MiB`;
  - cold total: `7.92s`, cold load: `3.13s`;
  - warm total: `6.49s`;
  - скорость генерации около `24 tok/s`;
  - качество хорошее, но модель частично ушла в CPU/RAM и стала слишком медленной;
  - вывод: research only, не практичная рабочая модель для 16 GB VRAM.

- `gemma3:12b`:
  - размер в `ollama ps`: `8.0 GB`;
  - `PROCESSOR`: `100% GPU`;
  - cold total: `14.78s`, cold load: `10.90s`;
  - warm total: `1.91s`;
  - скорость генерации warm около `89 tok/s`;
  - ответы cold/warm были почти одинаковыми по структуре и смыслу;
  - русский ответ стабильный и чистый;
  - вывод: очень сильный кандидат для RAG, особенно для будущих long-context тестов.

Важные технические наблюдения:

- `nvidia-smi` показывает текущую загрузку GPU и VRAM, но не показывает, какая часть модели на CPU/GPU.
- `ollama ps` важнее для model placement: поле `PROCESSOR` показывает `100% GPU` или split вроде `14%/86% CPU/GPU`.
- Высокий `Memory-Usage` при `GPU-Util 0%` означает, что модель загружена в VRAM, но сейчас простаивает.
- Cold start в основном отражается в `load_duration`; warm request важнее для UX, если модель удерживается через `keep_alive`.
- Более высокая точность весов не гарантирует лучший ответ: `7B FP16` не показал качества лучше `7B Q8`.
- Prompt и sampling options сильно влияют на качество. Строгий prompt + `temperature=0.1` заметно улучшили `7B Q8`.
- У `gemma3:12b` интересный memory profile: `ollama ps` показывает `8.0 GB`, процесс `llama-server` занял около `9020 MiB`, общий `nvidia-smi` usage был около `9590 MiB`. Это выглядит практично для 12B модели и стоит позже проверить на Q8/QAT вариантах.

Решение:

- оставить `qwen2.5:0.5b` только для smoke tests;
- рассматривать `qwen2.5:3b` для simple tasks, summary и router experiments;
- рассматривать `qwen2.5:7b-instruct-q8_0` как medium/default RAG-кандидат;
- рассматривать `qwen2.5:14b` default как heavy-кандидат для аналитики;
- рассматривать `gemma3:12b` как сильного кандидата для RAG и long-context;
- не использовать `qwen2.5:14b-instruct-q8_0` как рабочую модель на 16 GB VRAM из-за CPU offload;
- не считать `qwen2.5:7b-instruct-fp16` практичной заменой `7B Q8` без дополнительных доказательств.

Вывод:

- промежуточная рабочая лестница моделей:
  - tiny: `qwen2.5:0.5b`;
  - small: `qwen2.5:3b`;
  - medium: `qwen2.5:7b-instruct-q8_0`;
  - heavy: `qwen2.5:14b`;
  - long-context candidate: `gemma3:12b`.
- следующий эксперимент: medium/long RAG context для `qwen2.5:7b-instruct-q8_0`, `qwen2.5:14b` и `gemma3:12b`;
- отдельно нужно проверить groundedness: умеет ли модель сказать "в контексте нет данных", а не выдумывать.

## 2026-07-06: Medium RAG Context Benchmark

Контекст:

- подготовлен воспроизводимый prompt `research/prompts/rag_medium_context_prompt.txt`;
- prompt имитирует RAG-контекст для Product Owner по проблеме `notifications` в `TaskFlow AI`;
- контекст содержит business metrics, user feedback, incident note, tech docs, release note и один distractor chunk про `csv_import`;
- сравнивали `qwen2.5:7b-instruct-q8_0`, `qwen2.5:14b` и `gemma3:12b`;
- цель: проверить groundedness, использование источников, устойчивость к distractor, persona fit и actionability.

Наблюдение:

- `qwen2.5:7b-instruct-q8_0`:
  - prompt tokens: `1339`;
  - cold total: `10.39s`, cold load: `2.16s`;
  - warm total: `6.35s`, warm load: `0.12s`;
  - warm generation speed: около `97.5 tok/s`;
  - VRAM: `8381 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - ответ правильно использовал adoption `61% -> 48%`, tickets `47`, NPS `41 -> 32`, satisfaction `3.2/5`;
  - distractor про `csv_import` не использовался;
  - минусы: слабее раскрыл техническую причину `rate limits/backoff`, не всегда явно отвечал "поднять приоритет в roadmap", были небольшие языковые шероховатости.

- `qwen2.5:14b`:
  - prompt tokens: `1339`;
  - cold total: `11.69s`, cold load: `3.22s`;
  - warm total: `7.19s`, warm load: `0.13s`;
  - warm generation speed: около `79.6 tok/s`;
  - VRAM: `9903 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - ответ лучше попал в Product Owner persona и явно рекомендовал поднять приоритет проблемы в roadmap;
  - хорошо связал adoption, tickets, NPS, satisfaction и churn risk;
  - distractor про `csv_import` не использовался;
  - минусы: в cold-ответе появилась неточность про задержки Slack и Telegram, хотя задержки в контексте явно относились к Slack.

- `gemma3:12b`:
  - prompt tokens: `1171`;
  - cold total: `10.95s`, cold load: `3.57s`;
  - warm total: `8.59s`, warm load: `0.28s`;
  - warm generation speed: около `84.7 tok/s`;
  - VRAM: `9590 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - ответ очень хорошо связал business impact, churn risk, technical root cause и roadmap priority;
  - явно рекомендовал поднять приоритет проблемы;
  - хорошо использовал chunks 1-7;
  - минус/нюанс: в warm-ответе указал `CHUNK 8` как distractor, "использован для исключения нерелевантной информации". Это не повлияло на аргументацию, но в строгом source list лучше не включать distractor как использованный источник.

Ручная оценка:

- `qwen2.5:7b-instruct-q8_0`:
  - groundedness: `5/5`;
  - source_use: `4/5`;
  - distractor_resistance: `5/5`;
  - persona_fit: `4/5`;
  - actionability: `4/5`.

- `qwen2.5:14b`:
  - groundedness: `4.5/5`;
  - source_use: `5/5`;
  - distractor_resistance: `5/5`;
  - persona_fit: `5/5`;
  - actionability: `4.5/5`.

- `gemma3:12b`:
  - groundedness: `4.5/5`;
  - source_use: `5/5`;
  - distractor_resistance: `4.5/5`;
  - persona_fit: `5/5`;
  - actionability: `5/5`.

Решение:

- оставить `qwen2.5:7b-instruct-q8_0` как быстрый medium/default RAG-кандидат;
- оставить `qwen2.5:14b` как strong heavy candidate для аналитических PO-вопросов;
- оставить `gemma3:12b` как сильнейшего long-context/RAG кандидата для следующего этапа;
- для следующих prompt templates добавить правило: "не включай distractor chunks в список использованных источников, если они не использованы для ответа";
- продолжить сравнение на long context и groundedness tests.

Вывод:

- на medium RAG context все три модели работают пригодно для проекта;
- `7B Q8` наиболее экономичная и быстрая;
- `14B` лучше попадает в PO-priority decision;
- `gemma3:12b` показала лучший баланс стабильности, структуры и business/actionable ответа;
- следующий тест должен быть сложнее: long context with distractors и отдельный groundedness prompt, где правильный ответ - "в контексте нет данных".

## 2026-07-06: Long Context With Distractors Benchmark

Контекст:

- подготовлен prompt `research/prompts/rag_long_context_with_distractors.txt`;
- prompt содержит 20 chunks: релевантные данные по `notifications`, background chunks и distractors по `csv_import`, `search`, `permissions`, `billing`, `mobile_app`;
- задача модели: оценить, нужно ли Product Owner поднять `Notification Reliability` в roadmap на высокий приоритет;
- проверяли `qwen2.5:7b-instruct-q8_0`, `qwen2.5:14b` и `gemma3:12b`;
- prompt почти в 2 раза больше medium prompt: `9295` символов против `4522`.

Наблюдение:

- `qwen2.5:7b-instruct-q8_0`:
  - prompt tokens: `2641`;
  - cold total: `9.51s`, cold load: `2.18s`;
  - warm total: `6.69s`, warm load: `0.13s`;
  - warm generation speed: около `96.4 tok/s`;
  - VRAM: `8363 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - хорошо удержал основные факты: adoption `64% -> 48%`, NPS `41 -> 32`, tickets `18 -> 47`;
  - не использовал distractor chunks как аргументы;
  - предложил релевантные next steps: adaptive backoff, UI delayed delivery, delivery delay metrics;
  - минусы: не назвал явно инициативу `Notification Reliability`, не дал список источников, немного обобщал формулировки.

- `qwen2.5:14b`:
  - prompt tokens: `2641`;
  - cold total: `13.10s`, cold load: `3.23s`;
  - warm total: `8.67s`, warm load: `0.13s`;
  - warm generation speed: около `76.6 tok/s`;
  - VRAM: `9881 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - хорошо попал в PO-level decision и явно предложил включить `Notification Reliability` в roadmap;
  - хорошо связал NPS, support tickets, satisfaction, retention risk и roadmap action;
  - не использовал distractors;
  - важная ошибка: в warm-ответе указал `47 tickets (рост на 35%)`, хотя `18 -> 47` означает рост на `29` tickets, примерно `+161%` или `2.6x`. Это показывает, что LLM нельзя доверять арифметику без tool/calculator/Pandas.

- `gemma3:12b`:
  - prompt tokens: `2342`;
  - cold total: `12.96s`, cold load: `3.64s`;
  - warm total: `9.83s`, warm load: `0.29s`;
  - warm generation speed: около `84.0 tok/s`;
  - VRAM: `9594 MiB / 16303 MiB`;
  - `PROCESSOR`: `100% GPU`;
  - лучший ответ по структуре, business impact и actionability;
  - явно предложил поднять `Notification Reliability` в roadmap на высокий приоритет;
  - хорошо связал adoption, NPS, tickets, customer trust, manual task checking и technical root cause;
  - использовал релевантные sources: `CHUNK 3`, `4`, `6`, `7`, `8`, `9`, `10`, `11`, `12`, `17`, `18`;
  - не использовал distractors по `csv_import`, `search`, `permissions`, `billing`, `mobile_app`;
  - минус: добавил предположение про "потерю возможности монетизации", которого нет явно в контексте. Это business-logical inference, но для strict groundedness лучше просить отделять inference от evidence.

Ручная оценка:

- `qwen2.5:7b-instruct-q8_0`:
  - groundedness: `4.5/5`;
  - source_use: `4.5/5`;
  - distractor_resistance: `5/5`;
  - persona_fit: `5/5`;
  - actionability: `4.5/5`.

- `qwen2.5:14b`:
  - groundedness: `4/5` из-за ошибки арифметики;
  - source_use: `4.5/5`;
  - distractor_resistance: `5/5`;
  - persona_fit: `5/5`;
  - actionability: `5/5`.

- `gemma3:12b`:
  - groundedness: `4.5/5`;
  - source_use: `5/5`;
  - distractor_resistance: `5/5`;
  - persona_fit: `5/5`;
  - actionability: `5/5`.

Решение:

- считать `qwen2.5:7b-instruct-q8_0` хорошим default/medium RAG-кандидатом: быстро, экономично, устойчиво к distractors;
- считать `qwen2.5:14b` сильной heavy-моделью для PO decisions, но не доверять ей вычисление процентов без отдельного инструмента;
- считать `gemma3:12b` текущим лидером long-context RAG benchmark по качеству ответа и устойчивости к шуму;
- в будущих prompts добавить правило: "если делаешь расчет, покажи формулу; если расчет не требуется, не добавляй проценты сам";
- для метрик и аналитики считать derived values кодом, а не просить LLM считать проценты самостоятельно.

Вывод:

- все три модели выдержали long context около `2.3k-2.6k prompt tokens` в `CONTEXT 4096`;
- `7B Q8` дает лучший баланс скорости и памяти;
- `14B` дает сильные PO-ответы, но может уверенно ошибаться в арифметике;
- `gemma3:12b` показала лучший long-context ответ и остается главным кандидатом для RAG с длинным контекстом;
- следующий важный тест: groundedness/no-answer prompt, где правильное поведение - отказаться отвечать, если фактов нет в контексте.

## 2026-07-06: No-Answer Groundedness Benchmark

Контекст:

- подготовлен prompt `research/prompts/rag_no_answer_groundedness_prompt.txt`;
- задача: спросить модель про ARR loss, churn probability и список клиентов, которые точно уйдут;
- в контексте есть только adoption, support tickets, NPS, satisfaction, один critical ticket и incident/root cause;
- в контексте нет ARR, contract value, revenue, renewal dates, churn probability или списка клиентов, которые точно уйдут;
- правильное поведение модели: отказаться от точного ответа, не выдумывать числа и запросить недостающие данные.

Наблюдение:

- `gemma3:12b`:
  - total: `6.98s`;
  - load: `0.30s`;
  - prompt tokens: `768`;
  - response tokens: `543`;
  - прямо не назвала ARR loss, churn probability или список уходящих клиентов;
  - четко разделила "что известно", "чего нет", "что можно осторожно предположить", "какие данные нужно запросить";
  - аккуратно указала, что риск возможен, но точная оценка невозможна без revenue/customer data;
  - лучший no-answer behavior среди протестированных моделей.

- `qwen2.5:14b`:
  - cold total: `8.73s`, cold load: `3.42s`;
  - warm total: `4.81s`, warm load: `0.12s`;
  - prompt tokens: `882`;
  - не выдумала ARR loss, churn probability или список клиентов;
  - хорошо отделила известные факты от отсутствующих данных;
  - немного усилила формулировки вроде "готовность платить" и "прекращение использования продукта", хотя в контексте было только отключение Slack integration для части проектов;
  - результат хороший, но чуть менее строгий, чем `gemma3:12b`.

- `qwen2.5:7b-instruct-q8_0`:
  - cold total: `7.19s`, cold load: `3.11s`;
  - warm total: `3.94s`, warm load: `0.12s`;
  - prompt tokens: `882`;
  - правильно сказала: "В предоставленном контексте нет данных для точного ответа";
  - не выдумала ARR loss или churn probability;
  - хуже извлекла точные числа: часть фактов описала как "снизился/вырос" без значений `61% -> 48%`, `18 -> 47`, `41 -> 32`;
  - в warm-ответе попросила список клиентов, которые "уже заявили о намерении уйти", хотя такого факта в контексте нет;
  - годится для no-answer сценариев, но требует более строгого prompt для точного извлечения фактов.

Ручная оценка:

- `gemma3:12b`:
  - groundedness: `5/5`;
  - no-answer discipline: `5/5`;
  - structure: `5/5`;
  - usefulness: `5/5`.

- `qwen2.5:14b`:
  - groundedness: `4.5/5`;
  - no-answer discipline: `5/5`;
  - structure: `5/5`;
  - usefulness: `4.5/5`.

- `qwen2.5:7b-instruct-q8_0`:
  - groundedness: `4/5`;
  - no-answer discipline: `4.5/5`;
  - structure: `5/5`;
  - usefulness: `4/5`.

Решение:

- для strict grounded RAG и no-answer сценариев предпочитать `gemma3:12b`;
- использовать `qwen2.5:14b` для сложной аналитики, но дополнительно просить не усиливать формулировки за пределы контекста;
- использовать `qwen2.5:7b-instruct-q8_0` как быстрый default/medium RAG, но для no-answer ответов усиливать prompt правилами про точные факты и отсутствие предположений;
- в prompts использовать структуру: "Факты из контекста", "Интерпретация", "Рекомендация", "Чего не хватает";
- для ARR/churn/revenue расчетов требовать отдельные данные и считать derived values кодом.

Вывод:

- рабочая модельная тройка проекта:
  - `qwen2.5:7b-instruct-q8_0` — быстрый default/medium RAG;
  - `qwen2.5:14b` — heavy analytics и сложные PO decisions;
  - `gemma3:12b` — strict grounded RAG, long-context и no-answer сценарии.
- все три модели работают в `100% GPU` режиме и имеют близкий практический уровень latency для пользователя;
- переключение между этими моделями должно быть приемлемым для локального pet-проекта, особенно если учитывать warm state и `keep_alive`;
- сегодняшняя лаборатория подтвердила, что выбор модели должен зависеть не только от размера, но и от задачи: скорость, groundedness, контекст, арифметика, strict refusal.

## 2026-07-06: M1 Single-Collection RAG Старт

Контекст:

- после M0 smoke test и model benchmarks переходим к первому настоящему RAG;
- цель M1: получить ответ модели на основе chunks, найденных в Qdrant;
- начинаем с одной коллекции `documents`, без multi-collection routing;
- PostgreSQL поднимается в Docker сразу, но chat history подключим позже отдельным шагом.

Решение:

- добавить `docker-compose.yml` с `postgres` и `qdrant`;
- использовать `nomic-embed-text` как первую embedding-модель;
- использовать Qdrant collection `documents`;
- оставить `/chat` как простой Ollama smoke endpoint;
- добавить отдельный `/rag/chat`, который возвращает ответ и `sources`;
- держать backend слоистым: config, clients, models, services, scripts.

Вывод:

- M1 должен быть максимально прозрачным: ingestion, retrieval, prompt и sources должны легко проверяться;
- до добавления агентов и router важно убедиться, что простой single-collection RAG работает и не галлюцинирует без источников.

## 2026-07-06: Первый Успешный End-To-End RAG

Контекст:

- Qdrant и PostgreSQL подняты через Docker Compose;
- seed-документы загружены в Qdrant collection `documents`;
- embedding-модель: `nomic-embed-text`;
- RAG endpoint: `/rag/chat`;
- генеративная модель: `gemma3:12b`;
- тестовый вопрос: "Какие проблемы с notifications влияют на enterprise-клиентов?"

Наблюдение:

- `/health` показал:
  - `ollama_available: true`;
  - `embedding_model: nomic-embed-text`;
  - `qdrant_collection: documents`;
  - `qdrant_collection_exists: true`.
- Первый `/rag/chat` с `top_k=5` вернул релевантный grounded answer, но среди sources были шумные chunks:
  - `Incident Note: Задержки Slack Notifications В Марте 2026`, score около `0.798`;
  - `Архитектура Уведомлений TaskFlow AI`, score около `0.777`;
  - `Slack уведомления приходят слишком поздно`, score около `0.697`;
  - нерелевантные chunks `CSV Import V2` и `Search`.
- Повторный `/rag/chat` с `top_k=3` вернул только релевантные sources:
  - incident note про задержки Slack notifications;
  - архитектуру notifications;
  - support ticket про задержку Slack уведомлений.
- Ответ модели был основан на источниках:
  - задержки Slack notifications на `15-20 минут`;
  - причина: Slack workspace rate limits;
  - impact: Project Managers жаловались на потерю оперативности.
- Latency для чистого `top_k=3` ответа: около `2503 ms`.

Решение:

- считать M1 single-collection RAG успешно запущенным;
- для маленького seed dataset временно использовать `top_k=3` как более чистый default для ручных проверок;
- следующим улучшением добавить score threshold и/или metadata filter по `feature`;
- оставить `sources` в API, потому что они критичны для отладки retrieval и groundedness.

Вывод:

- первая полная цепочка работает: `question -> embedding -> Qdrant retrieval -> prompt -> gemma3:12b -> grounded answer + sources`;
- retrieval уже находит правильные документы по смыслу;
- качество ответа сильно зависит от того, какие chunks попали в prompt;
- следующий инженерный шаг: уменьшить шум retrieval через filters/threshold/reranking, а не увеличивать `top_k` без контроля.

## 2026-07-06: Retrieval Noise Control

Контекст:

- первый RAG с `top_k=5` вернул три релевантных chunks и два шумных chunks;
- `top_k=3` дал более чистый prompt;
- нужно дать backend простой механизм отсечения слабых результатов без усложнения архитектуры.

Решение:

- добавить опциональный `score_threshold` в `/rag/chat`;
- оставить default threshold выключенным, чтобы не ломать retrieval на маленьком датасете;
- разрешить задавать threshold на конкретный запрос;
- добавить компактный `jq` пример, который показывает `score`, `title`, `source_type`, `feature` без полного `content`.

Вывод:

- на раннем этапе лучше явно видеть scores и sources;
- `score_threshold` полезен как первый простой фильтр шума;
- дальше стоит добавить metadata filters по `feature` и, позже, reranking.

## 2026-07-06: Metadata Filtering По Feature

Контекст:

- после добавления `score_threshold` retrieval стал чище, но threshold сам по себе не понимает доменную структуру;
- в Qdrant payload уже есть поле `feature`, например `notifications`, `csv_import`, `search`;
- следующий слой качества retrieval - использовать metadata filtering до сборки prompt.

Решение:

- добавить в `/rag/chat` поле `features`;
- передавать `features` в Qdrant payload filter;
- использовать `MatchAny`, чтобы chunk проходил, если содержит хотя бы одну из запрошенных фич;
- возвращать примененный список `features` в API response;
- добавить README-пример с `features:["notifications"]`.

Вывод:

- metadata filtering помогает отсекать семантически похожий, но доменно нерелевантный шум;
- это первый шаг к будущему collection routing и persona-aware retrieval;
- на большом корпусе feature filters будут важнее, чем простое увеличение `top_k`.

## 2026-07-06: Rule-Based Feature Extraction

Контекст:

- ручной `features:["notifications"]` улучшает retrieval, но пользователю неудобно каждый раз указывать feature;
- нужен первый маленький шаг к будущему router без ML/fine-tune;
- на M1 достаточно простых правил по ключевым словам.

Решение:

- добавить `FeatureExtractor`;
- извлекать features из текста вопроса, если пользователь не передал `features` вручную;
- оставить ручные `features` приоритетнее автоопределения;
- начать с правил для `notifications`, `csv_import`, `permissions`, `reports`, `search`, `webhooks`, `integrations`, `tasks`, `projects`, `sprints`.

Вывод:

- это первый rule-based router для retrieval;
- он не заменяет будущий CPU-router, но уже улучшает UX;
- дальше можно сравнить rule-based extraction с embedding/router classifier и fine-tuned classifier.

## 2026-07-06: Synthetic Corpus Expansion

Контекст:

- маленький seed dataset хорошо подходит для проверки pipeline, но слишком "тепличный" для проверки retrieval;
- на 1000 документов сразу идти рано: сложнее дебажить, труднее глазами понять, где именно retrieval начал ошибаться;
- выбран промежуточный шаг: контролируемый synthetic corpus на 100-150 документов/строк.

Решение:

- добавить deterministic generator `backend/scripts/generate_synthetic_corpus.py`;
- создать generated corpus в отдельных папках/файлах, не смешивая его с ручным starter dataset;
- покрыть features: `notifications`, `csv_import`, `permissions`, `reports`, `search`, `webhooks`, `integrations`, `tasks`, `projects`, `sprints`;
- добавить похожие и запутывающие связи между features через `related_feature`;
- сгенерировать:
  - 40 technical markdown docs;
  - 12 release/incident notes;
  - 50 support ticket rows;
  - 20 user review rows;
  - 30 metrics rows.

Вывод:

- generated corpus дает около `152` новых документов/строк;
- следующий тест должен показать, насколько retrieval устойчив при большем числе похожих документов;
- главная гипотеза: `features` filter и `score_threshold` должны стать заметно важнее после расширения корпуса.

## 2026-07-06: Source Type Filtering

Контекст:

- после расширения корпуса `features:["notifications"]` успешно убрал межфичевый шум;
- внутри одной feature появились конкурирующие релевантные документы: release notes, RFC, architecture, runbook, incident, support tickets;
- для PO-вопросов часто нужны `incident_note`, `support_ticket`, `metric_row`, `release_note`;
- для Developer-вопросов чаще нужны `markdown`, `openapi`, `runbook`, `incident_note`.

Наблюдение:

- после расширения корпуса top results по `notifications` подняли generated release/RFC/runbook выше исходного support ticket;
- это не ошибка feature filter: все документы действительно относятся к `notifications`;
- проблема стала не "не та feature", а "не тот тип evidence для роли/вопроса".

Решение:

- добавить в `/rag/chat` поле `source_types`;
- реализовать Qdrant payload filter по `source_type`;
- объединять `features` и `source_types` через `must` условия;
- возвращать примененные `source_types` в response;
- добавить README-примеры для PO-oriented и Developer-oriented retrieval.

Вывод:

- `features` отвечает на вопрос "про какую область продукта искать";
- `source_types` отвечает на вопрос "какой тип evidence нужен";
- это следующий шаг к persona-aware retrieval и будущему router.

## 2026-07-06: Source Diversity Layer

Контекст:

- `source_types` filter помог выбрать нужный тип evidence, но top results начали забиваться похожими generated support tickets;
- несколько support tickets имели почти одинаковый title и очень близкие scores;
- это реальная RAG-проблема: даже релевантные chunks могут быть слишком однотипными и ухудшать prompt.

Решение:

- добавить простую source diversity фильтрацию перед сборкой prompt;
- по умолчанию ограничить `max_sources_per_title=1`;
- разрешить дополнительно ограничивать `max_sources_per_source_type` и `max_sources_per_source_path`;
- возвращать примененные diversity-настройки в response.

Вывод:

- source diversity не заменяет reranking, но быстро защищает prompt от дублей;
- следующий более умный слой — reranker или grouping по evidence type;
- для маленького pet-проекта этот слой уже помогает увидеть, как context builder начинает управлять качеством ответа.

## 2026-07-06: Candidate Pool Before Diversity

Контекст:

- при `top_k=8` и `max_sources_per_source_type=1` prompt стал чище;
- но после diversity часть candidates отбрасывалась, а backend не добирал замену из следующих Qdrant results;
- из-за этого полезный `metric_row` мог не попасть в финальный контекст.

Решение:

- искать в Qdrant не финальный `top_k`, а расширенный `candidate_k = top_k * 3`;
- затем применять `score_threshold`;
- затем применять source diversity / deduplication;
- затем обрезать sources до финального `top_k` перед сборкой prompt;
- возвращать `retrieval.requested_top_k`, `retrieval.candidate_k` и `retrieval.final_top_k` в API response.

Вывод:

- deduplication уже частично реализован через `max_sources_per_title=1`;
- source diversity — это более общий механизм, который ограничивает повторения по `title`, `source_type` и `source_path`;
- candidate pool нужен не вместо deduplication, а вместе с ним: он дает системе больше вариантов, из которых можно собрать разнообразный финальный context.

## 2026-07-06: Rule-Based Query Router For Metrics

Контекст:

- `metric_row` оказался релевантным для вопроса про изменившиеся метрики, но имел score около `0.62`;
- при общем `score_threshold=0.68` такой источник отсекается;
- глобально снижать threshold опасно, потому что в обычных PO-вопросах это увеличит retrieval noise.

Решение:

- добавить небольшой rule-based query router;
- если вопрос похож на metric intent, backend автоматически:
  - добавляет PO-friendly `source_types`: `metric_row`, `incident_note`, `support_ticket`, `release_note`;
  - снижает effective `score_threshold` до `0.60`;
- если пользователь явно передал `source_types` или `score_threshold`, router их не переопределяет;
- если вопрос содержит отрицательные паттерны вроде "без метрик", metric hint не применяется;
- для таких negative metric вопросов prompt получает строгое дополнительное правило не упоминать числовые KPI, проценты, счетчики тикетов, adoption, latency/delay metrics и рекомендации про метрики;
- API возвращает `query_hints`, чтобы было видно, какие правила сработали.

Вывод:

- это не LLM-router, а прозрачный domain-specific routing layer;
- query router может влиять не только на retrieval, но и на prompt policy;
- для pet-проекта такой слой полезнее, чем преждевременный reranker;
- риск ложных срабатываний сохраняется, поэтому важно логировать `query_hints` и тестировать positive/negative examples.
- похожие positive/negative тесты стоит позже сделать для других intent: incidents, support tickets, release notes, technical/root-cause.

## 2026-07-06: Context Sanitization For Negative Metric Requests

Контекст:

- `qwen2.5:14b` хорошо соблюдал правило "без метрик";
- `gemma3:12b` продолжал вытаскивать числа из context, даже после более строгого prompt rule;
- это показало границу prompt engineering: если запрещенные факты лежат в prompt, модель может все равно использовать их.

Решение:

- для `query_hints.metric_negative_marker=true` включить `context_policy.numeric_line_sanitization=true`;
- перед сборкой prompt удалять строки с numeric/KPI-heavy patterns: проценты, ticket counters, adoption, latency/delay metrics;
- дополнительно чистить title chunks, если title сам содержит numeric/delay metric;
- оригинальные `sources` оставлять в API response для отладки, а в prompt передавать sanitized copies.

Вывод:

- это не замена retrieval, а policy layer между retrieval и prompt;
- в production RAG иногда нужно не только говорить модели "не используй X", но и не давать ей X в prompt;
- context sanitization стоит применять точечно, только когда пользовательское ограничение явно распознано.

Результат retest:

- `gemma3:12b` перестал упоминать `47`, `61%`, `48%` после включения `context_policy.numeric_line_sanitization=true`;
- `qwen2.5:14b` продолжил хорошо соблюдать no-metrics constraint;
- появился небольшой UX-артефакт: sanitized title может отображаться как `Источник без числовых метрик`.

TODO:

- улучшить отображение sanitized titles: не заменять title текстом-заглушкой, а скрывать title из prompt metadata или хранить отдельное `prompt_title`;
- вести проверки через `research/RAG_EVALUATION_CHECKLIST.md`;
- позже автоматизировать checklist в evaluation script.

## 2026-07-06: First RAG Evaluation Pass

Контекст:

- после добавления query router, source diversity и context sanitization нужен baseline, чтобы не улучшать retrieval вслепую;
- был прогнан `research/RAG_EVALUATION_CHECKLIST.md` на `gemma3:12b` и `qwen2.5:14b`;
- цель evaluation — проверить не только ответы моделей, но и policy layers: `score_threshold`, `query_hints`, `context_policy`, `source_types`, `candidate_k`, diversity.

Что Сработало:

- metric intent: router корректно снизил threshold до `0.60`, `metric_row` попал в context, обе модели использовали `notification_delivery_delay`;
- negative metric intent: `context_policy.numeric_line_sanitization=true` удержал обе модели от KPI/процентов;
- technical root cause: обе модели нашли Slack rate limits и aggressive retry/backoff;
- no-answer ARR: обе модели не выдумали точный ARR loss, `qwen2.5:14b` лучше запросил недостающие данные.

Что Нашли:

- release notes запрос `Какие изменения по notifications были в release notes?` ошибочно включал `metric_intent=true`;
- причина: marker `изменен` срабатывал как substring внутри слова `изменения`;
- source diversity stress показал, что для вопроса про жалобы клиентов нужны отдельные support-feedback hints, иначе markdown/release/incident могут доминировать над tickets.

Решение:

- убрать широкие metric markers `изменил`, `изменен`, `изменён`;
- оставить metric intent на более явных сигналах: `метрик`, `metric`, `adoption`, `tickets`, `вырос/снизил`, `delay` и т.п.;
- release notes focus должен оставаться release-notes intent, а не metric intent.

Вывод:

- evaluation быстро окупилась: один прогон поймал ложноположительное router rule;
- перед добавлением новых router intents нужно прогонять checklist, чтобы не чинить один сценарий ценой другого;
- следующий слой после фикса metric router — support feedback intent для вопросов про жалобы клиентов.

## 2026-07-06: Support Feedback Intent

Контекст:

- evaluation Test 4 `Какие жалобы клиентов чаще всего встречаются по notifications?` показал, что generic retrieval приносит много `markdown`/`release_note`;
- для вопроса про жалобы клиентов ожидаем primary evidence из `support_ticket`, а incident/metrics могут быть вспомогательными;
- без отдельного intent router отвечает правильно, но context не оптимален: support tickets появляются поздно.

Решение:

- добавить rule-based `support_feedback_intent`;
- markers: `жалоб`, `отзыв`, `feedback`, `клиенты сообщают`, `support`, `тикет`, `tickets`;
- если пользователь не передал `source_types`, router выставляет `support_ticket`, `incident_note`, `metric_row`;
- metric intent имеет приоритет, чтобы вопросы про метрики не превращались в support feedback intent.

Вывод:

- query router постепенно превращается в domain policy layer;
- новые intents нужно добавлять маленькими шагами и сразу проверять checklist;
- следующий retest должен показать, ушло ли доминирование markdown/release docs в Test 4.

Результат regression:

- metric intent не сломался: `metric_intent=true`, `score_threshold=0.60`, `metric_row` остается в sources;
- release notes focus больше не включает metric intent: `metric_intent=false`, `score_threshold=0.68`;
- support feedback intent сработал: `support_feedback_intent=true`, `source_types=["support_ticket","incident_note","metric_row"]`;
- no-answer ARR не сломался: модель не назвала точный ARR loss и запросила недостающие revenue/account данные.

Отдельное Наблюдение По Conversation Context:

- текущий `/rag/chat` endpoint stateless: каждый запрос обрабатывается независимо;
- multi-turn memory / chat history пока не реализованы и не проверялись;
- чтобы модель отвечала на follow-up вопросы по своему предыдущему ответу, нужно передавать историю диалога в prompt или хранить её в PostgreSQL;
- это отдельный будущий слой, не часть текущего single-turn RAG retrieval.

## 2026-07-06: Technical Root Cause Intent

Контекст:

- evaluation Test 5 уже показывал хорошее поведение, если вручную передавать `source_types=["markdown","incident_note","support_ticket"]`;
- для вопросов "почему", "какая техническая причина", "root cause" ожидаем technical evidence, а не только PO summary;
- это следующий естественный router intent после metrics и support feedback.

Решение:

- добавить rule-based `technical_root_cause_intent`;
- markers: `техническ`, `причин`, `root cause`, `почему`, `rate limits`, `retry`, `backoff`, `worker`, `очеред`, `api`;
- если пользователь не передал `source_types`, router выставляет `markdown`, `incident_note`, `support_ticket`;
- metric и support feedback intents имеют приоритет, чтобы не конфликтовать с уже настроенными сценариями.

Вывод:

- technical/root-cause intent формализует успешный ручной retrieval pattern;
- теперь пользователь может задавать технический вопрос без ручного `source_types`;
- Test 5 в evaluation checklist должен проверять `query_hints.technical_root_cause_intent=true`.

Результат retest:

- `technical_root_cause_intent=true`;
- router автоматически выставил `source_types=["markdown","incident_note","support_ticket"]`;
- sources включили incident note, known issue, RFC, runbook, architecture и support tickets;
- обе модели назвали Slack API rate limits и aggressive retry/backoff у delivery worker как техническую причину.

Mini-Evaluation На 5 Формулировках:

- успешно сработали вопросы про "техническая причина", "почему", "delivery worker", "Slack API или backend";
- проблемный кейс: `Как retry/backoff влияет на задержки уведомлений?`;
- он ошибочно включал `metric_intent=true`, потому что marker `задержк` относился к metric intent, а metric intent имел приоритет выше technical intent.

Решение Priority Conflict:

- добавить strong technical markers: `root cause`, `rate limit(s)`, `retry`, `backoff`, `worker`;
- если в вопросе есть strong technical marker, `technical_root_cause_intent` побеждает metric intent;
- это сохраняет metric intent для вопросов про метрики, но корректно маршрутизирует вопросы про retry/backoff.

Дополнительный Результат Retest:

- после priority fix вопрос `Как retry/backoff влияет на задержки уведомлений?` стал корректно включать `technical_root_cause_intent=true`;
- но при baseline `score_threshold=0.68` retrieval вернул `final_top_k=0`;
- причина: mixed-language technical query (`retry/backoff`) хуже матчится с embeddings, а релевантные chunks остаются ниже общего threshold.

Решение:

- для `technical_root_cause_intent` добавить `technical_root_cause_score_threshold`;
- если пользователь не передал `score_threshold`, снижать effective threshold до `0.60`;
- риск шума компенсируется тем, что technical intent одновременно ограничивает `source_types` до `markdown`, `incident_note`, `support_ticket`.

## 2026-07-06: Qwen3 / Qwen3.5 / Gemma4 Mini-Evaluation

Контекст:

- после появления новых локальных моделей нужно сравнить их не на одном prompt, а на текущих RAG scenarios;
- проверялись `qwen2.5:14b`, `qwen3:14b`, `qwen3.5:9b-q8_0`, `gemma4:12b`;
- scenarios: metric intent, negative metric, support feedback, technical/root-cause, no-answer ARR;
- полные результаты сохранены в `research/model_evaluation_latest.jsonl`.

Latency / Stability:

- `qwen2.5:14b`: среднее около `12.1s`, 5/5 непустых ответов;
- `qwen3:14b`: среднее около `17.4s`, 5/5 непустых ответов;
- `qwen3.5:9b-q8_0`: среднее около `37.3s`, 4/5 пустых ответов;
- `gemma4:12b`: среднее около `25.0s`, 5/5 непустых ответов.

Наблюдения:

- `qwen2.5:14b` остается самым стабильным baseline для PO/RAG: хороший баланс скорости, структуры и groundedness;
- `qwen3:14b` выглядит сильным конкурентом: ответы компактные, grounded, без thinking leakage, но медленнее `qwen2.5:14b`;
- `gemma4:12b` хорошо держит groundedness и no-answer ARR, но медленнее и иногда более сухая/формальная;
- `qwen3.5:9b-q8_0` пока нельзя оценивать как candidate: модель часто возвращала пустой `response`, нужна отдельная диагностика Ollama/template/options.

Качество По Сценариям:

- metric intent: `qwen2.5:14b` и `qwen3:14b` отвечают строго по `notification_delivery_delay`; `gemma4:12b` добавляет больше метрик из incident context;
- negative metric: все непустые модели соблюдают no-metrics policy, `gemma4:12b` особенно аккуратна;
- support feedback: все непустые модели находят задержки Slack notifications как главную жалобу;
- technical/root-cause: все непустые модели объясняют retry/backoff и Slack rate limits, `qwen3.5:9b-q8_0` дал хороший ответ только в этом сценарии;
- no-answer ARR: `qwen3:14b` и `gemma4:12b` лучше всех отказались от точного ARR loss; `qwen2.5:14b` частично смешал русский и китайский в ответе, что является regression risk.

Вывод:

- текущий default пока не менять: `qwen2.5:14b` остается основным PO/RAG baseline;
- `qwen3:14b` стоит добавить как нового кандидата для следующих сравнений;
- `gemma4:12b` можно держать как strict grounded/no-answer candidate;
- `qwen3.5:9b-q8_0` нужно отдельно диагностировать перед дальнейшим сравнением.

## 2026-07-06: Qwen3.5 Empty Response Diagnosis

Контекст:

- в mini-evaluation `qwen3.5:9b-q8_0` вернул пустой `response` в 4 из 5 RAG scenarios;
- прямой `/api/generate` на коротких prompt отвечал нормально;
- responses Ollama содержали отдельное поле `thinking`, а backend читал только `response`.

Диагностика:

- `/api/chat` с `think:false` возвращал нормальный `message.content` и не генерировал `thinking`;
- `/api/generate` также принимает `think:false`;
- на RAG-like prompt `think:false` убрал `thinking` и резко сократил генерацию.

Решение:

- добавить параметр `think` в `OllamaClient.generate`;
- передавать `think=False` в `/rag/chat`;
- также передавать `think=False` в простой `/chat`, чтобы thinking-модели не отдавали внутренние рассуждения пользователю.

Результат Retest:

- `qwen3.5:9b-q8_0` перестал возвращать пустые RAG responses;
- latency на проверенных scenarios снизилась примерно до `6.6-8.9s`;
- качество требует отдельной повторной model evaluation, потому что теперь модель начала реально отвечать.

Вывод:

- проблема была не только в качестве модели, а в режиме thinking/template;
- для пользовательского PO-assistant default policy должна быть "не показывать thinking";
- `qwen3.5:9b-q8_0` снова стоит рассматривать как candidate после повторного evaluation.

## 2026-07-06: Qwen3.5 9B Evaluation After Think=False

Контекст:

- после диагностики `qwen3.5:9b-q8_0` был добавлен backend default `think=False`;
- дополнительно скачан и протестирован `qwen3.5:9b` как более легкий/default quantized вариант;
- цель: проверить, решает ли `think=False` проблему пустых ответов и насколько 9B practical по latency/quality.

Результат:

- `qwen3.5:9b` прошел 5/5 RAG scenarios без пустых ответов;
- средняя latency около `4.6s`, что быстрее `qwen2.5:14b`, `qwen3:14b`, `gemma4:12b` и ранее проверенного `qwen3.5:9b-q8_0`;
- policy layers сработали корректно: metric intent, negative metric, support feedback, technical/root-cause, no-answer ARR.

Наблюдения По Качеству:

- metric intent: модель нашла `notification_delivery_delay`, но также добавила adoption/support tickets из incident context как дополнительные данные;
- negative metric: no-metrics policy соблюдена, ответ без числовых KPI;
- support feedback: ответ полезный, но довольно длинный и включает много смежных деталей;
- technical/root-cause: сильный ответ по retry/backoff, 429, exponential backoff и queue growth;
- no-answer ARR: корректно отказалась считать ARR loss и запросила revenue/contract/customer data.

Вывод:

- `qwen3.5:9b` стал неожиданно сильным кандидатом для fast/default RAG model;
- по скорости он выглядит лучше текущего `qwen2.5:14b`;
- по строгости нужно проверить дополнительные negative/groundedness cases, потому что модель склонна расширять ответ смежными метриками;
- следующий честный comparison: `qwen2.5:14b` vs `qwen3:14b` vs `qwen3.5:9b` на полном checklist после `think=False`.

## 2026-07-06: Release Notes Intent

Контекст:

- evaluation ранее поймала ложное срабатывание metric intent на запрос `Какие изменения по notifications были в release notes?`;
- после удаления широких metric markers запрос перестал считаться metric intent, но release-notes routing еще не был явным;
- для release questions важно отделять shipped changes от incidents/support feedback.

Решение:

- добавить rule-based `release_notes_intent`;
- markers: `release note(s)`, `релиз`, `релизн`, `changelog`, `change log`, `что было выпущено`, `что выпустили`, `изменения`;
- если пользователь не передал `source_types`, router выставляет строго `source_types=["release_note"]`;
- metric intent имеет приоритет, чтобы запросы вроде "какие метрики в release notes" не теряли metric behavior.

Вывод:

- strict `release_note` routing помогает не смешивать release changes с incident/support evidence;
- если позже понадобится richer answer, можно расширить до `release_note + incident_note`, но первый baseline должен быть строгим.

Результат retest:

- `release_notes_intent=true`;
- router автоматически выставил `source_types=["release_note"]`;
- `final_top_k=1`, найден только `Release Note 2026-01: notifications`;
- `qwen3.5:9b` и `qwen3:14b` корректно перечислили shipped changes без подмешивания incidents/support tickets.

## 2026-07-06: Incident Intent

Контекст:

- после metrics, support feedback, technical/root-cause и release notes остался последний основной router intent — incidents;
- incident questions обычно спрашивают не только root cause, но и что случилось, impact, mitigation и follow-up;
- для такого ответа нужны `incident_note` как primary evidence, а `support_ticket` и `metric_row` могут дать подтверждение customer impact.

Решение:

- добавить rule-based `incident_intent`;
- markers: `incident`, `инцидент`, `что случилось`, `что произошло`, `impact`, `влияние`, `последств`, `mitigation`, `affected`, `пострад`, `эскалац`;
- если пользователь не передал `source_types`, router выставляет `incident_note`, `support_ticket`, `metric_row`;
- technical/root-cause intent имеет приоритет, если вопрос явно про `root cause`, `retry`, `backoff`, `worker` или `rate limits`;
- release/support/metric intents также сохраняют свои приоритеты, чтобы incident intent не перехватывал их сценарии.

Вывод:

- incidents intent закрывает основной RAG-router roadmap перед PostgreSQL слоем;
- следующий retest должен проверить, что incident summary отвечает про what happened, impact и mitigation, а не превращается только в technical answer.

Результат retest:

- `incident_intent=true`;
- router автоматически выставил `source_types=["incident_note","support_ticket","metric_row"]`;
- sources стали incident/support-oriented: main notification incident, related integration incident и support feedback;
- `qwen3:14b` сфокусировался на основном notifications incident: задержки Slack notifications, impact, tickets/adoption;
- `qwen3.5:9b` дал более широкий ответ и объединил два мартовских incident-а: delivery delays и Slack integration/OAuth scopes.

Наблюдение:

- для broad incident questions широкий ответ `qwen3.5:9b` полезен;
- для узкого "тот самый incident" ответа `qwen3:14b` оказался строже;
- позже можно добавить уточняющий router/prompt rule: если вопрос просит "мартовский инцидент с notifications", не смешивать related integration incident без явной необходимости.

## 2026-07-06: Full Model Evaluation After Router Roadmap

Контекст:

- после закрытия основных router intents нужно проверить весь активный пул моделей на полном checklist;
- проверялись: `qwen2.5:7b-instruct-q8_0`, `qwen3.5:9b`, `qwen2.5:14b`, `qwen3:14b`, `gemma4:12b`;
- scenarios: metric intent, negative metric, general PO summary, support feedback, technical/root-cause, release notes, no-answer ARR, incident summary;
- результаты сохранены локально в `research/full_model_evaluation_latest.jsonl`.

Stability / Latency:

- все модели дали 8/8 непустых ответов;
- CJK/китайский после `think=False` не протекал;
- средняя latency:
  - `qwen3:14b`: около `10.5s`;
  - `qwen2.5:7b-instruct-q8_0`: около `10.7s`;
  - `qwen2.5:14b`: около `11.7s`;
  - `qwen3.5:9b`: около `12.1s`;
  - `gemma4:12b`: около `14.2s`.

Наблюдения По Моделям:

- `qwen3:14b` показал лучший баланс скорости, строгости и качества; ответы компактные и grounded;
- `qwen2.5:14b` остается хорошим baseline, но после `think=False` уже не выглядит однозначно быстрее/лучше `qwen3:14b`;
- `qwen3.5:9b` сильный fast challenger: качественные ответы, хорошо держит no-answer и technical scenarios, но часто расширяет ответ смежными фактами и пишет длиннее;
- `qwen2.5:7b-instruct-q8_0` surprisingly usable: короткие и стабильные ответы, хороший fallback, но беднее по структуре и глубине;
- `gemma4:12b` grounded и аккуратна, но чаще verbose и медленнее, особенно в metric/general/support/incident summaries.

Качество По Сценариям:

- metric intent: `qwen2.5:14b` и `qwen3:14b` наиболее строго отвечают по `notification_delivery_delay`; `qwen3.5:9b` и `gemma4:12b` добавляют adoption/support ticket metrics как related context;
- negative metric: все модели соблюли no-metrics policy;
- release notes: release intent дал чистый `release_note` context, все модели ответили корректно;
- technical/root-cause: все модели объяснили retry/backoff, `429` и rate limits; `qwen3.5:9b` дал самый подробный technical answer;
- no-answer ARR: все модели отказались считать точный ARR loss и запросили недостающие financial/customer data;
- incident summary: `qwen3:14b` строже держится основного notifications incident, `qwen3.5:9b` и `gemma4:12b` дают более широкий summary с related integration incident.

Обновленная Модельная Карта:

- Primary quality candidate: `qwen3:14b`;
- Current baseline / stable comparator: `qwen2.5:14b`;
- Fast challenger: `qwen3.5:9b`;
- Fast fallback: `qwen2.5:7b-instruct-q8_0`;
- Strict grounded candidate: `gemma4:12b`.

Вывод:

- router roadmap можно считать стабилизированным для M1 single-turn RAG;
- перед сменой default model стоит еще прогнать несколько no-answer/negative constraints на `qwen3:14b` и `qwen3.5:9b`;
- следующий архитектурный этап — PostgreSQL слой: request logs, evaluation runs, chat history и будущий conversation context.

## 2026-07-06: Первый PostgreSQL Слой Для RAG Logs

Контекст:

- single-turn RAG pipeline уже стабилизирован: retrieval, diversity, query router и context policy работают как отдельные слои;
- следующий шаг — добавить PostgreSQL без преждевременного multi-turn memory;
- цель первого DB шага — observability: сохранять, какой вопрос пришел, какой ответ дала модель, какие sources были использованы и какие router/retrieval policy сработали.

Решение:

- добавить отдельный backend пакет `app/db` для SQLAlchemy base/session/models;
- использовать async SQLAlchemy + `asyncpg`, потому что зависимости уже есть в backend;
- создать таблицы `rag_request_logs` и `rag_source_logs`;
- создавать таблицы на старте через `metadata.create_all()` как временный early-stage подход до Alembic;
- логировать `/rag/chat` best-effort: недоступная БД не должна ломать RAG answer;
- в `rag_source_logs` сохранять не полный chunk, а короткий `content_excerpt`, чтобы PostgreSQL не превращался во второе хранилище документов рядом с Qdrant.

Вывод:

- PostgreSQL пока является системной памятью и audit trail, а не частью prompt context;
- такой слой поможет анализировать реальные запросы, latency, качество retrieval и поведение router;
- следующий DB шаг: добавить chat sessions / message history и отдельную таблицу evaluation runs, но подключать их к RAG context нужно позже и осторожно.

## 2026-07-06: Chat History Без Multi-Turn Memory

Контекст:

- после RAG logs нужен следующий слой PostgreSQL: история пользовательских диалогов;
- при этом single-turn RAG уже стабилен, и нельзя незаметно изменить качество ответов, начав подмешивать старые сообщения в prompt;
- цель этапа — сохранить conversation history как данные, но не превращать ее в retrieval/memory policy.

Решение:

- добавить таблицы `chat_sessions` и `chat_messages`;
- добавить `session_id` в `/chat` и `/rag/chat` requests;
- возвращать `session_id`, `user_message_id` и `assistant_message_id` в responses, если запись в PostgreSQL успешна;
- сохранять пары сообщений `user`/`assistant` best-effort, чтобы недоступная БД не ломала inference;
- пока не добавлять FK из `rag_request_logs` в `chat_messages`, потому что текущий early-stage `create_all()` не мигрирует уже созданные таблицы.

Вывод:

- теперь backend умеет хранить историю общения, но RAG behavior остается прежним;
- это правильная промежуточная ступень перед conversation context: сначала собрать данные и понять форму сессий, потом проектировать memory summarization/context window;
- перед production-like этапом понадобится Alembic, чтобы безопасно добавлять связи и индексы к уже существующим таблицам.

## 2026-07-06: Evaluation Runs В PostgreSQL

Контекст:

- после стабилизации router roadmap мы начали регулярно сравнивать модели на одном и том же RAG checklist;
- локальные `.jsonl` файлы полезны как быстрый artifact, но их неудобно сравнивать, фильтровать и связывать с моделью/сценарием;
- нужен PostgreSQL слой для evaluation history, но без превращения evaluation в часть пользовательского chat history.

Решение:

- добавить таблицу `evaluation_runs` как шапку одного прогона: название, checklist version, список моделей, статус, notes;
- добавить таблицу `evaluation_results` как строку на пару scenario/model;
- сохранять prompt, response, latency, sources summary, retrieval, query_hints, context_policy и quality_flags;
- сделать CLI script `python -m scripts.run_rag_evaluation`, который вызывает реальный `/rag/chat` API, а не внутренний service напрямую;
- оставить `quality_flags` эвристическими: они ловят очевидные regressions, но не заменяют ручную оценку groundedness/persona fit.

Вывод:

- теперь модельные сравнения можно хранить как историю экспериментов, а не как разрозненные локальные файлы;
- запуск через API path проверяет больше системы: request schema, router, retrieval, LLM call, response schema и DB persistence;
- следующий шаг после накопления нескольких runs — сделать compact report/query layer, чтобы сравнивать модели по latency, source_count и failed flags.

## 2026-07-06: Compact Evaluation Reporting

Контекст:

- после добавления `evaluation_runs` и `evaluation_results` данные начали сохраняться в PostgreSQL, но смотреть их через ручной SQL неудобно;
- нужен быстрый способ увидеть последние runs и понять, где появились слабые места: ошибки, `zero_sources`, failed quality flags или высокая latency;
- на этом этапе не нужен UI: достаточно CLI summary, который не выводит полный текст prompt/response.

Решение:

- добавить `python -m scripts.report_evaluation_runs list` для последних runs;
- добавить `python -m scripts.report_evaluation_runs summary` для агрегатов по последнему или указанному run;
- считать summary по моделям и сценариям: avg latency, avg source_count, errors, zero-source cases, failed boolean flags;
- не выводить полный response content, чтобы report оставался компактным и безопасным для терминала.

Вывод:

- evaluation слой теперь не только сохраняет результаты, но и помогает быстро читать их как инженерный сигнал;
- это подготовка к будущим memory/context изменениям: перед изменением RAG behavior можно будет прогонять checklist и сравнивать summaries до/после.

## 2026-07-06: Targeted Evaluation Fixes And Full Five-Model Run

Контекст:

- первый compact report по 3 моделям показал два сигнала: `metric_intent` не получал `metric_row`, а `no_answer_groundedness` не засчитывал корректные ответы Qwen;
- пользователь справедливо заметил, что текущий рабочий пул шире: `qwen2.5:7b-instruct-q8_0`, `qwen3.5:9b`, `qwen3:14b`, `qwen2.5:14b`, `gemma4:12b`;
- перед полным 5x8 evaluation нужно было сначала починить известные сигналы, чтобы не тратить длинный прогон на уже понятные проблемы.

Диагностика:

- `metric_intent` router выставлял `source_types=["metric_row","incident_note","support_ticket","release_note"]`, но vector ranking выбирал более текстовые chunks: `release_note`, `incident_note`, `support_ticket`;
- metric-only retrieval показывал, что `metric_row` находится при `score_threshold=0.60`, значит проблема была не в данных, а в отсутствии source-type floor;
- no-answer ответы Qwen были корректными: "контекст не предоставляет", "точные цифры отсутствуют", "конкретная сумма потерь не упоминается", но marker list был слишком узким.

Решение:

- добавить `query_hints.required_source_types=["metric_row"]` для metric intent;
- в `RagService` добавить supplemental search по обязательным source types, если основной candidate pool их не содержит;
- расширить no-answer эвристику общими маркерами отсутствующих данных, не привязанными к одной модели;
- изменить `RagChatResponse.retrieval` на `dict[str, Any]`, потому что retrieval metadata теперь содержит не только числовые счетчики.

Результат:

- targeted run на 5 моделях и 2 сценариях (`metric_intent`, `no_answer_groundedness`) прошел без failed flags;
- полный run `8c8f08d7-a07b-419c-b735-57e8d81a8713`: 5 моделей x 8 сценариев = 40 результатов;
- ошибок нет, `zero_sources=0`, `failed_flags=0` по всем сценариям и моделям;
- средняя latency: `qwen2.5:7b-instruct-q8_0` около `9.9s`, `qwen3:14b` около `11.2s`, `qwen2.5:14b` около `11.6s`, `gemma4:12b` около `12.2s`, `qwen3.5:9b` около `12.4s`.

Вывод:

- compact reporting уже окупился: он поймал regression, направил точечную правку и подтвердил clean full run;
- для metric questions нужен не только broad source filter, но и обязательный metric evidence floor;
- full five-model run теперь можно считать новым baseline перед следующим крупным этапом: multi-turn memory/context policy.

## 2026-07-06: M4.1 Follow-Up Aware RAG

Контекст:

- single-turn RAG был стабилен, но короткий follow-up вроде `А какие из этих проблем самые критичные?` терял тему `notifications`;
- PostgreSQL уже хранил `chat_sessions` и `chat_messages`, поэтому можно было использовать recent session history без добавления long-term memory;
- цель M4.1 — улучшить retrieval для follow-up, не добавляя summary, embeddings истории или LLM-based rewrite.

Решение:

- добавить `ConversationContextService`;
- использовать только rule-based follow-up detection и feature carry-over;
- строить `retrieval_query` из текущего follow-up и последних user messages;
- не подменять оригинальный вопрос пользователя в prompt;
- если текущий вопрос явно содержит новую feature (`csv_import`), считать это topic switch и не переносить старую тему;
- добавить `conversation_context` в `/rag/chat` response;
- сохранять `conversation_context` в evaluation result retrieval snapshot.

Диагностика:

- первый debug snapshot показал шум: `carried_features` извлекались из assistant response и подхватывали лишние features из sources;
- исправление: извлекать carried features только из последних user messages;
- после narrowing `carried_features=["notifications"]` для follow-up continuation.

Результат:

- targeted run `dd57af1d-c66b-4180-a9eb-9a841da436fb`: 5 моделей x 2 сценария (`follow_up_continuation`, `topic_switch`), `errors=0`, `zero_sources=0`, `failed_flags=0`;
- final full run `4b6f2905-c8a8-45a2-99f2-d210080568b7`: 5 моделей x 10 сценариев = 50 результатов;
- full regression: `errors=0`, `zero_sources=0`, `failed_flags=0`;
- средняя latency на full run: `qwen2.5:7b-instruct-q8_0` около `8.3s`, `qwen3:14b` около `9.8s`, `qwen2.5:14b` около `9.7s`, `qwen3.5:9b` около `10.2s`, `gemma4:12b` около `11.8s`.

Вывод:

- первый слой conversational context можно считать успешным;
- rule-based approach оказался достаточным для базовых follow-up и topic switch сценариев;
- следующий memory шаг стоит делать отдельно: topic switch расширение, conversation summary или LLM-based rewrite только после нового targeted plan/evaluation.

## 2026-07-06: M4.2 Follow-Up Policy Hardening

Контекст:

- M4.1 доказал, что recent history помогает базовым follow-up вопросам;
- перед переходом к summary или long-term memory нужно укрепить short-context policy, чтобы меньше ловить неявные баги позже;
- реальные follow-up часто смешивают intents: action plan, metrics, no-metrics, incident или явный topic switch.

Диагностика:

- вопрос `А какие метрики по ним изменились?` находил `reports` через слово `метрики`, хотя это не topic switch, а metric intent внутри предыдущей темы;
- поэтому `reports` стал soft follow-up feature: если вопрос похож на follow-up, один `reports` не должен отменять carry-over;
- explicit switch `Ок, забудь notifications, а теперь про permissions` содержал старую feature в forget-clause, поэтому retrieval query нужно санитизировать.

Решение:

- расширить follow-up markers: action plan, recommendations, no-metrics, metric follow-up;
- добавить topic switch markers: `а теперь про`, `перейдем к`, `забудь`, `сравни с`;
- добавить `topic_switch_detected` и `decision_reason` в `conversation_context`;
- для explicit topic switch строить sanitized retrieval query, например `а теперь про permissions`;
- пересчитывать `current_features` по sanitized topic-switch query, чтобы debug показывал новую тему, а не forget-clause.

Evaluation:

- targeted run `4a9b54a6-b30b-452c-9770-99db61088341`: 5 моделей x 5 новых сценариев, `errors=0`, `zero_sources=0`, `failed_flags=0`;
- full run `ef92858c-99b0-4898-a623-9a3663bba165`: 5 моделей x 15 сценариев = 75 результатов;
- full regression: `errors=0`, `zero_sources=0`, `failed_flags=0`;
- средняя latency на full run: `qwen2.5:7b-instruct-q8_0` около `6.2s`, `qwen3:14b` около `7.4s`, `qwen3.5:9b` около `8.2s`, `qwen2.5:14b` около `8.7s`, `gemma4:12b` около `9.9s`.

Вывод:

- M4.2 укрепил short-context policy без добавления новой памяти;
- explicit topic switch теперь наблюдаем и чище влияет на retrieval;
- следующий этап можно выбирать осознанно: либо еще расширять policy edge cases, либо переходить к M4.3 conversation summary.

## 2026-07-07: M4.3 Conversation Summary

Контекст:

- M4.1/M4.2 закрыли short follow-up и topic switch через recent history, но длинная session все еще могла потерять исходную тему, когда нужная feature выпала из последних сообщений;
- пользователь справедливо предложил не создавать summary "каждые 2-4 сообщения", а привязать trigger к context budget и lifecycle session;
- unload Ollama model не стал trigger: это инфраструктурное событие, а не смысловая граница диалога.

Решение:

- добавить отдельную таблицу `conversation_summaries`, не меняя существующие таблицы;
- реализовать `ConversationSummaryService` как rule-based/extractive baseline без LLM summarization;
- создавать/обновлять summary по token estimate, fallback message count, stale message threshold и idle session boundary;
- использовать summary только для follow-up retrieval query, когда recent user history уже не несет features;
- не использовать summary при explicit topic switch: текущая новая feature и sanitized retrieval query имеют приоритет;
- добавить summary debug fields в `conversation_context`: `summary_available`, `summary_used`, `summary_updated`, `summary_features`, `summary_mode`, `summary_reason`;
- расширить evaluation новыми long-session сценариями: `summary_long_follow_up`, `summary_topic_switch`, `summary_metric_follow_up`, `summary_negative_metric_follow_up`.

Диагностика:

- targeted M4.3 run сначала показал один failed flag: `summary_metric_follow_up` правильно срабатывал как `metric_intent`, но final sources не содержали `metric_row`;
- причина: supplemental search для `required_source_types=["metric_row"]` повторно применял общий score threshold к длинному summary-обогащенному retrieval query;
- исправление: для router-mandated source types supplemental search остается ограниченным по `features` и `source_type`, но не режется тем же score threshold.

Результат:

- targeted run `d48f20eb-0289-44f2-8832-c47de7e99863`: 1 модель x 4 новых summary сценария;
- `errors=0`, `zero_sources=0`, `failed_flags=0`;
- full run `35a9f4df-bf83-4643-9623-d179735016fd`: 5 моделей x 19 сценариев = 95 результатов;
- full regression: `errors=0`, `zero_sources=0`, `failed_flags=0`;
- средняя latency на full run: `qwen2.5:7b-instruct-q8_0` около `5.5s`, `qwen3:14b` около `6.8s`, `qwen3.5:9b` около `7.1s`, `gemma4:12b` около `9.2s`, `qwen2.5:14b-instruct-q8_0` около `15.3s`.

Вывод:

- summary лучше вводить как отдельный наблюдаемый memory layer, а не смешивать с recent history logic;
- rule-based summary дает хороший baseline и debug surface перед будущим LLM-based summarization;
- обязательные source types должны вести себя как evidence floor: если router требует тип источника, fallback retrieval не должен ломаться из-за небольшого падения score на длинном query.

## 2026-07-07: M4.4 LLM-Based Structured Summary

Контекст:

- M4.3 дал стабильный rule-based summary baseline, но для production-like memory нужно попробовать LLM-based summarization;
- важно не смешивать conversation memory с evidence: summary описывает диалог, а факты о продукте по-прежнему должны приходить из Qdrant sources;
- LLM summary потенциально может вернуть плохой JSON, пустой ответ или добавить лишнее, поэтому нужен fallback и validation.

Решение:

- добавить настройки `CONVERSATION_SUMMARY_STRATEGY`, `CONVERSATION_SUMMARY_MODEL`, `CONVERSATION_SUMMARY_TEMPERATURE`;
- сделать `hybrid` strategy: сначала LLM structured summary, при ошибке fallback на rule-based summary;
- просить summarizer возвращать строгий JSON с `main_topics`, `user_goals`, `decisions`, `open_questions`, `constraints`, `summary`;
- сохранять structured summary в `conversation_summaries.metadata_json`, не меняя схему таблицы;
- features для retrieval продолжать извлекать через `FeatureExtractor` из реального текста user messages, а не доверять LLM;
- добавить debug fields: `summary_strategy`, `summary_model`, `summary_structured`, `summary_fallback_used`, `summary_validation_error`.

Результат:

- targeted run `7337aeab-9946-4447-b4ba-258ca56654a4`: 1 сценарий `llm_summary_structured`, `errors=0`, `failed_flags=0`;
- debug snapshot подтвердил `summary_strategy=hybrid`, `summary_model=qwen2.5:3b`, `summary_fallback_used=False`, structured JSON валиден;
- targeted memory regression `1b58271c-9955-4c03-b7f5-7e3ef93b6ac1`: 1 модель x 5 summary/memory сценариев, `errors=0`, `zero_sources=0`, `failed_flags=0`;
- первый full run `31d78815-3424-4270-9d7b-d8a5befd2f0f` был остановлен как diagnostic run: он показал regression в `summary_metric_follow_up` на 2 моделях;
- причина regression: LLM-summary добавлял technical markers вроде `retry`, `worker`, `rate limits`, и router иногда отдавал приоритет technical/release intent над явной формулировкой `А какие метрики...`;
- исправление: explicit metric question markers (`какие метрики`, `метрики по`, `какие показатели`) теперь имеют приоритет над technical markers из summary;
- targeted fix run `f27bd8a3-39d2-43e0-a341-33b73f088a68`: 2 проблемные модели x `summary_metric_follow_up`, `errors=0`, `failed_flags=0`;
- clean full run `8fd546bb-ea64-426e-bd2d-d5350f9becc1`: 5 моделей x 20 сценариев = 100 результатов;
- full regression: `errors=0`, `zero_sources=0`, `failed_flags=0`;
- средняя latency на clean full run: `qwen2.5:7b-instruct-q8_0` около `7.1s`, `qwen3:14b` около `7.3s`, `qwen3.5:9b` около `8.2s`, `gemma4:12b` около `9.2s`, `qwen2.5:14b-instruct-q8_0` около `16.8s`.

Вывод:

- LLM summary можно безопасно вводить поверх rule-based baseline, если есть строгий JSON contract, fallback и observability;
- `metadata_json` оказался полезным extension point: structured memory можно добавить без миграции таблицы;
- следующий логичный шаг после M4.4 - M4.5 prompt memory budget, где recent messages и summary начнут попадать в финальный prompt под контролем token budget.

## 2026-07-07: M4.4.2 Summarizer Model Selection

Контекст:

- ручной review первых LLM summaries показал, что `qwen2.5:3b` технически работает, но теряет decisions/open questions и иногда галлюцинирует features;
- цель не в том, чтобы все модели одинаково хорошо работали на всех задачах, а в том, чтобы выбрать подходящую модель для роли summarizer;
- summary создается не на каждый запрос, поэтому можно выбирать модель крупнее, если качество заметно лучше.

Решение:

- исключить `qwen2.5:14b-instruct-q8_0` из summarizer selection из-за VRAM;
- сравнить candidates: `qwen2.5:7b-instruct-q8_0`, `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`;
- добавить script `python -m scripts.select_summary_model`, который берет 20 transcript examples, вызывает каждую candidate-модель и сохраняет JSONL/Markdown review artifacts;
- добавить автоматические guardrails: валидный JSON, русский язык, отсутствие hallucinated known features, summary length, наличие user goals/decisions/open questions;
- критерий выбора: минимум 16/20 good/excellent на review и отсутствие critical feature hallucinations.

Результат:

- прогон 20 examples x 4 models = 80 summary calls завершился успешно;
- automatic safe counts: `qwen3.5:9b` 15/20, `qwen2.5:7b-instruct-q8_0` 14/20, `qwen3:14b` 14/20, `gemma4:12b` 13/20;
- `qwen3.5:9b` лучший по automatic guardrails, но почти не сохраняет decisions;
- `qwen2.5:7b-instruct-q8_0` лучше сохраняет decisions, но чаще теряет open questions и иногда галлюцинирует known features;
- ни одна модель пока не достигла порога 16/20 без дополнительных prompt/guardrail улучшений.

Вывод:

- не стоит фиксировать summarizer-модель для M4.5 прямо сейчас;
- следующий шаг: усилить prompt/guardrails, особенно по forbidden features, decisions и open questions, затем повторить selection;
- это хороший пример практического model selection: качество роли важнее универсальности модели.

Повторный прогон после prompt hardening:

- candidate set остался тем же: `qwen2.5:7b-instruct-q8_0`, `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`;
- локальный automatic run агента: `qwen3.5:9b` 15/20 safe, `qwen2.5:7b-instruct-q8_0` 14/20, `gemma4:12b` 12/20, `qwen3:14b` 12/20;
- локальный review пользователя показал похожую картину, но `qwen3:14b` субъективно выглядел чуть лучше: около 13/20;
- целевой порог 16/20 всё равно не достигнут;
- главный повторяющийся дефект: модели продолжают иногда добавлять known features вне `allowed_features`, чаще `webhooks`, `reports`, `integrations`.

Инженерный вывод:

- prompt-only hardening недостаточен для production-like memory layer;
- `main_topics` нельзя принимать напрямую от LLM, даже при строгом prompt;
- следующий шаг: deterministic post-validation — фильтровать `main_topics` через `allowed_features`, а отброшенные темы сохранять как warning/debug metadata.

Реализация:

- production `ConversationSummaryService` теперь очищает LLM `main_topics` через `allowed_features`;
- очищенный `structured_summary` не содержит отброшенные topics, чтобы будущий prompt memory не подхватил их обратно;
- отброшенные topics сохраняются отдельно в `validation_warnings` / `summary_validation_warnings`;
- `select_summary_model.py` применяет ту же post-validation, чтобы следующий selection измерял качество безопасного итогового summary, а не только raw compliance модели.

Повторный прогон после deterministic post-validation:

- 20 examples x 4 models = 80 summary calls завершились успешно;
- automatic safe counts: `gemma4:12b` 15/20, `qwen3.5:9b` 15/20, `qwen2.5:7b-instruct-q8_0` 14/20, `qwen3:14b` 12/20;
- `gemma4:12b` стал одним из лидеров после очистки `main_topics`, но целевой порог 16/20 всё ещё не достигнут;
- `qwen3.5:9b` сохранил 15/20, но снова показал нестабильность JSON/validation на 2 examples;
- `validation_warnings` по `main_topics` почти не сработали: основной остаточный шум находится не в `main_topics`, а в текстовых полях `summary`, `decisions`, `user_goals`;
- частые forbidden known features в текстовых полях: `reports`, `webhooks`, `integrations`.

Следующий вывод:

- post-validation `main_topics` нужен как safety layer, но он не решает весь класс hallucination/noise;
- guardrails нужно сделать более диагностическими: отдельно показывать forbidden features в `main_topics`, отдельно raw topics, отброшенные post-validation, и отдельно forbidden features внутри текстовых summary fields.

Реализация diagnostic guardrails:

- `select_summary_model.py` теперь отдельно выводит `forbidden_known_features_in_main_topics`, `discarded_known_features_from_main_topics`, `forbidden_known_features_in_text`;
- `safe_for_prompt_review` остается строгим и по-прежнему падает при любом forbidden known feature, но теперь видно, где именно возникла проблема;
- summary output дополнен счетчиками `text_forbidden_cases`, `main_topic_forbidden_cases`, `discarded_topic_cases`.

Полный прогон после diagnostic guardrails:

- 20 examples x 4 models = 80 summary calls завершились успешно;
- `qwen3.5:9b`: 15/20 safe, 2 validation/JSON errors, `text_forbidden_cases=3`;
- `gemma4:12b`: 14/20 safe, errors=0, `text_forbidden_cases=6`;
- `qwen2.5:7b-instruct-q8_0`: 14/20 safe, errors=0, `text_forbidden_cases=6`, `russian_failures=1`;
- `qwen3:14b`: 12/20 safe, errors=0, `text_forbidden_cases=7`;
- `main_topic_forbidden_cases=0` и `discarded_topic_cases=0` у всех моделей.

Вывод:

- post-validation `main_topics` стабилизировал topic field;
- остаточные forbidden features появляются именно в текстовых полях;
- следующий guardrail должен различать настоящую hallucination и полезные boundary mentions вроде `не смешивать notifications с webhooks`.

Реализация следующего слоя:

- добавлена Pydantic-модель `LlmStructuredSummary` для schema validation LLM structured summary;
- production summary parser и `select_summary_model.py` теперь используют Pydantic перед domain validation;
- в `select_summary_model.py` добавлен contextual guardrail: benign boundary mentions выводятся в `allowed_contextual_forbidden_mentions`, а настоящий шум остается в `forbidden_known_features_in_text`;
- `safe_for_prompt_review` остается строгим, но теперь лучше отражает смысловую ошибку, а не любое техническое упоминание forbidden feature.

Полный прогон после Pydantic + contextual guardrail:

- 20 examples x 4 models = 80 summary calls завершились успешно;
- `gemma4:12b`: 19/20 safe, errors=0, `text_forbidden_cases=1`, `contextual_allowed_cases=5`;
- `qwen3.5:9b`: 17/20 safe, errors=2, `text_forbidden_cases=1`, `contextual_allowed_cases=2`;
- `qwen2.5:7b-instruct-q8_0`: 16/20 safe, errors=0, `text_forbidden_cases=4`, `contextual_allowed_cases=2`, `russian_failures=1`;
- `qwen3:14b`: 14/20 safe, errors=0, `text_forbidden_cases=5`, `contextual_allowed_cases=2`;
- `main_topic_forbidden_cases=0` и `discarded_topic_cases=0` у всех моделей;
- целевой порог 16/20 теперь прошли `gemma4:12b`, `qwen3.5:9b` и `qwen2.5:7b-instruct-q8_0`.

Первичный разбор failures:

- `gemma4:12b` упала только на одном example: в `decisions` появилось `рекомендовано эскалировать enterprise-тикеты ... в integrations team`;
- это не topic hallucination и не ошибка JSON: модель пересказала operational action из assistant context, но guardrail посчитал `integrations` forbidden text noise;
- `qwen3.5:9b` дважды вернула валидный JSON-объект, но без обязательного поля `summary`;
- обе ошибки `qwen3.5:9b` выглядят как хороший кандидат для future repair retry: схема почти правильная, нужно дозапросить отсутствующее поле `summary`.

Вывод:

- `gemma4:12b` выглядит лучшим summarizer candidate: самый высокий safe score и ноль validation errors;
- оставшийся `gemma4` failure нужно разбирать аккуратно: возможно, это legitimate operational team mention, а не опасная feature hallucination;
- `qwen3.5:9b` потенциально сильная, но требует retry/schema repair layer перед production use.

Targeted failure analysis:

- `gemma4:12b` failure с `integrations` оказался operational mention: `эскалировать enterprise-тикеты ... в integrations team`;
- это не расширение `main_topics` и не product feature hallucination, поэтому в selection guardrail добавлен узкий allowlist для `integrations team` / `команда интеграций`;
- обычное упоминание `integrations` без operational/team context по-прежнему считается forbidden text noise;
- `qwen3.5:9b` schema errors вызваны отсутствующим обязательным полем `summary` при почти корректном JSON;
- добавлен repair retry только при schema validation error: успешные ответы `gemma4:12b` не затрагиваются;
- targeted repair smoke для `qwen3.5:9b` успешно восстановил `summary` и прошел `safe_for_prompt_review=True`.
- для `qwen3.5:9b` добавлен узкий boundary marker `не следует пут`, чтобы фраза `не следует путать ... webhooks` считалась contextual mention, а не forbidden text noise.

Дополнительный разбор перед следующим full run:

- `qwen2.5:7b-instruct-q8_0` unsafe cases: два `integrations team` operational mentions, один boundary mention про `reports`, один спорный `SLA reports` symptom object внутри проблемы `permissions`;
- `integrations team` cases должны закрыться уже внесённым allowlist;
- boundary mention про `reports` вероятно закроется текущим marker `отдел`;
- `SLA reports` как symptom object пока не правим: это отдельная бизнес-семантика, лучше не расширять guardrail без повторного измерения;
- `qwen3:14b` unsafe cases: два `integrations team`, три `SLA reports` symptom object для `permissions`, один `russian_language_ok=false` из-за большого количества английских metric identifiers;
- оптимизировать guardrail специально под `qwen3:14b` пока нецелесообразно, так как главный кандидат остаётся `gemma4:12b`.

Ожидания перед следующим full selection:

- `gemma4:12b`: ожидаем 20/20 safe, если единственный failure действительно был operational mention `integrations team`;
- `qwen3.5:9b`: ожидаем рост до 19-20/20, но часть успеха может быть через `repair_retry_used=True`;
- `qwen2.5:7b-instruct-q8_0`: ожидаем рост выше 16/20 за счёт `integrations team` allowlist и существующего boundary marker `отдел`;
- `qwen3:14b`: ожидаем небольшой рост за счёт `integrations team`, но не 20/20 из-за нерешённых `SLA reports` symptom object и language heuristic;
- после full run нужно сравнить эти ожидания с реальностью и отдельно решить, нужен ли класс `allowed_symptom_object_mentions`.

Фактический full run после targeted fixes:

- 20 examples x 4 models = 80 summary calls завершились успешно;
- `gemma4:12b`: 20/20 safe, errors=0, repair_retries=0, avg_latency около 8.2s;
- `qwen3.5:9b`: 20/20 safe, errors=0, repair_retries=2, avg_latency около 5.1s;
- `qwen2.5:7b-instruct-q8_0`: 18/20 safe, errors=0, repair_retries=0, avg_latency около 4.8s;
- `qwen3:14b`: 16/20 safe, errors=0, repair_retries=0, avg_latency около 11.2s;
- `main_topic_forbidden_cases=0` и `discarded_topic_cases=0` у всех моделей;
- `gemma4:12b` и `qwen3.5:9b` достигли 20/20, но `gemma4:12b` сделала это без repair retry.

Сравнение ожиданий с реальностью:

- ожидание по `gemma4:12b` подтвердилось полностью: единственный failure был operational mention `integrations team`;
- ожидание по `qwen3.5:9b` подтвердилось: два schema failures закрылись repair retry;
- ожидание по `qwen2.5:7b-instruct-q8_0` подтвердилось частично: модель выросла до 18/20, но остались `reports` symptom/boundary cases;
- ожидание по `qwen3:14b` подтвердилось: модель выросла до 16/20, но остались `SLA reports` symptom object и language heuristic case;
- `allowed_symptom_object_mentions` остаётся потенциальным будущим улучшением, но для выбора summarizer оно уже не блокирует M4.4.2.

Итоговый вывод M4.4.2:

- лучший primary summarizer candidate: `gemma4:12b` — 20/20 safe, ноль ошибок, ноль repair retries;
- лучший fast fallback/alternative candidate: `qwen3.5:9b` — 20/20 safe, но требует repair retry для стабильности schema;
- `qwen2.5:7b-instruct-q8_0` остаётся быстрым baseline candidate, но качество ниже;
- `qwen3:14b` не выглядит оправданным для summarizer role: медленнее `gemma4:12b` и хуже по quality score.

## 2026-07-07: M4.5 Prompt Memory Budget

Контекст:

- до M4.5 summary использовался для retrieval query rewrite, но не попадал в финальный prompt модели;
- цель этапа: приблизиться к продуктовой conversational memory, но не нарушить границу evidence;
- факты о продукте по-прежнему должны приходить только из Qdrant sources.

Решение:

- добавить отдельный prompt block `Память диалога`;
- включать в память summary, user goals и последние user messages под `CONVERSATION_MEMORY_TOKEN_BUDGET`;
- не включать recent assistant messages в первый вариант, чтобы не тащить прошлые ответы как product evidence;
- добавить prompt rules: memory помогает учитывать цели пользователя, но не является источником фактов о продукте;
- добавить debug metadata `conversation_context.prompt_memory` с `used`, `included`, `token_budget`, `token_estimate`, `content`;
- добавить evaluation scenario `prompt_memory_budget`.

Targeted smoke:

- backend запущен с текущим кодом на отдельном порту `8003`;
- scenario: `prompt_memory_budget`;
- модели: `gemma4:12b`, `qwen3.5:9b`;
- run id: `3c7731d5-a31f-4adb-81f9-bd562fda2950`;
- summary model: `gemma4:12b`;
- `gemma4:12b`: `prompt_memory_used=true`, `prompt_memory_budget_ok=true`, `token_estimate=147/350`, sources=5;
- `qwen3.5:9b`: `prompt_memory_used=true`, `prompt_memory_budget_ok=true`, `token_estimate=154/350`, sources=5;
- в обоих случаях prompt memory включила `summary`, `user_goals`, `recent_user_messages`.

Вывод:

- M4.5 baseline работает: memory попадает в финальный prompt контролируемо и наблюдаемо;
- budget не превышается на smoke-сценарии;
- следующий шаг: прогнать больше M4.5 scenarios на двух выбранных моделях (`gemma4:12b`, `qwen3.5:9b`) и проверить, что memory улучшает follow-up quality без нарушения groundedness.

Архитектурное уточнение:

- первоначально prompt memory собиралась в `main.py`, потому что там уже доступны `recent_messages` и `summary_context`;
- чтобы не утолщать FastAPI entrypoint, сборка memory вынесена в `ConversationMemoryService`;
- сервис не ходит в БД сам и не дублирует загрузку history/summary;
- `main.py` остаётся orchestrator: загружает recent messages и summary один раз, затем передаёт их в context/memory services;
- unit-level smoke подтвердил, что сервис включает `summary`, `user_goals`, `recent_user_messages`, соблюдает бюджет и не включает сообщения ассистента.

Точечная регрессионная проверка M4.5:

- run id: `f5eb9335-e2ee-4b7c-a47d-2f8a9d1aa53c`;
- 6 сценариев x 2 модели = 12 результатов;
- сценарии: `prompt_memory_budget`, `summary_long_follow_up`, `summary_topic_switch`, `summary_metric_follow_up`, `summary_negative_metric_follow_up`, `llm_summary_structured`;
- модели: `gemma4:12b`, `qwen3.5:9b`;
- существующие флаги качества прошли: `failed_flags=0`;
- prompt memory во всех проверенных случаях осталась в рамках бюджета.

Важное наблюдение:

- начальная регрессионная проверка показала скрытый пробел в safety-логике: в `summary_topic_switch` было `summary_used=false`, но `prompt_memory.used=true`;
- это могло протащить память старой темы в финальный prompt после явного topic switch;
- добавлено M4.5 safety-правило: `ConversationMemoryService` возвращает пустую memory с `reason=topic_switch`, если `topic_switch_detected=true`;
- добавлен флаг проверки `prompt_memory_not_used` для `summary_topic_switch`.

Проверка исправления topic switch:

- run id: `bda4b594-fe0e-48c2-b5b8-ee1b940b0a5c`;
- сценарий: `summary_topic_switch`;
- модели: `gemma4:12b`, `qwen3.5:9b`;
- обе модели: `prompt_memory_not_used=true`, `prompt_memory.used=false`, `prompt_memory.reason=topic_switch`, `failed_flags=0`.

Проверка стабильности M4.5:

- адрес backend: `http://localhost:8000`;
- сценарии: `prompt_memory_budget`, `summary_long_follow_up`, `summary_topic_switch`, `summary_metric_follow_up`, `summary_negative_metric_follow_up`, `llm_summary_structured`;
- модели: `gemma4:12b`, `qwen3.5:9b`;
- повторено 3 раза: 6 сценариев x 2 модели x 3 прогона = 36 результатов;
- run ids: `4cf0ce8a-50d4-4154-b98c-2726984fa1b3`, `312aa8f4-569a-419c-b98a-4ba2190b132c`, `ba785389-82e5-4581-a994-e704cd56f044`;
- результат: `failed_flags=0`, `errors=0`;
- `summary_topic_switch`: `prompt_memory.used=false`, `reason=topic_switch` у обеих моделей во всех повторах;
- все сценарии с включённой memory остались в рамках `CONVERSATION_MEMORY_TOKEN_BUDGET=350`;
- средняя задержка по 18 вызовам на модель: `gemma4:12b` около 15.7s, `qwen3.5:9b` около 6.1s.

Расширенный набор memory-сценариев M4.5:

- в evaluation script добавлена поддержка memory-focused сценариев с проверками ожидаемой feature, ожидаемого поведения prompt memory, metric intent и negative metric marker;
- добавлены сценарии для `permissions`, `csv_import`, явного topic switch на `csv_import`, возврата к предыдущей теме, metric follow-up, negative metric follow-up, incident follow-up, release notes follow-up и короткого follow-up только с recent messages;
- run id расширенного прогона: `8ddf490d-0469-46fc-ba0f-24b770183903`;
- 15 сценариев x 2 модели = 30 результатов;
- результат выполнения: 30/30 `ok`, `errors=0`;
- найдены две ошибки в ожиданиях теста:
  - `memory_return_to_previous_topic` ожидал включения memory, но система корректно трактовала явное движение между темами как `topic_switch` и отключила memory;
  - `memory_short_follow_up_recent_only` ожидал `summary_available=true`, но короткие диалоги из двух turns должны уметь использовать recent messages без persisted summary.

Коррекция ожиданий качества:

- `memory_return_to_previous_topic` теперь ожидает `prompt_memory.used=false`; явный feature в текущем запросе должен вести retrieval, а не старая memory;
- общие `memory_*` сценарии больше не требуют `summary_available=true`, потому что recent-message-only memory допустима для коротких диалогов;
- run id повторной проверки edge-cases: `02c3dd4c-3db9-4259-9d79-440e24040e35`;
- сценарии повторной проверки: `memory_return_to_previous_topic`, `memory_short_follow_up_recent_only`;
- результат повторной проверки: 4/4 результата с `failed_flags=0`;
- `memory_return_to_previous_topic`: `prompt_memory.reason=topic_switch`, при этом `notifications_context_ok=true`;
- `memory_short_follow_up_recent_only`: `prompt_memory.used=true`, `included=["recent_user_messages"]`, `token_estimate=24/350`.

Итоговый вывод по M4.5 на этом этапе:

- prompt memory ведёт себя стабильно на повторных прогонах;
- topic switch safety работает и предотвращает утечку memory старой темы;
- memory поддерживает как summary-based, так и recent-message-only сценарии;
- явные упоминания feature в текущем запросе должны оставаться сильнее memory;
- `qwen3.5:9b` остаётся заметно быстрее `gemma4:12b` на генерации ответов, при этом обе модели проходят текущие проверки качества M4.5.

Большой M4.5 прогон для `qwen3.5:9b`:

- цель: проверить, можно ли оставить `qwen3.5:9b` главным кандидатом для дальнейших M4.5/M5 тестов из-за высокой скорости при сохранении качества;
- модель: `qwen3.5:9b`;
- адрес backend: `http://localhost:8000`;
- набор: 15 M4.5 memory-сценариев x 7 повторов = 105 результатов;
- сценарии включали базовые M4.5 cases (`prompt_memory_budget`, long follow-up, topic switch, metric/negative metric follow-up, structured summary) и memory-focused edge cases (`permissions`, `csv_import`, explicit topic switch, возврат к теме, incident, release notes, short recent-only);
- run ids: `8b9d7e09-01af-4974-b19f-14b994035ee2`, `b23f4cd8-8e21-4a02-ae90-ed8816fb682e`, `d8b9f3c5-78ad-413b-a7cd-ea5b0b4e653f`, `86834fb5-9339-473e-86ff-45f659e80afe`, `84f52dfc-f367-4fd2-82d2-93cd5caf4208`, `01e5a52e-430f-4a1c-a9a8-eb8f43a6c4ba`, `7fdc2f71-ad32-4599-8fc9-9248f712f3ec`;
- JSONL-артефакт: `research/m45_qwen35_big_evaluation_latest.jsonl`;
- первая строка файла содержит summary и список сценариев с turns/expectations, следующие 105 строк содержат result records.

Результаты большого прогона:

- `result_count=105`, `failed_count=0`;
- ошибок выполнения: 0;
- средняя задержка: около 5.18s;
- min/max latency: 2.14s / 9.54s;
- средний `source_count`: 4.9;
- `prompt_memory.used=true`: 84 случая;
- `prompt_memory.used=false`: 21 случай;
- все 21 отключения memory пришлись на `reason=topic_switch`, что совпадает с ожидаемой safety-логикой;
- `summary_topic_switch`, `memory_explicit_topic_switch_csv`, `memory_return_to_previous_topic`: во всех 7 повторах memory отключалась с `reason=topic_switch`;
- `memory_short_follow_up_recent_only`: во всех 7 повторах использовалась recent-message-only memory без обязательного persisted summary.

Вывод по `qwen3.5:9b`:

- на текущем M4.5 наборе модель показывает стабильное качество: 105/105 без failed flags;
- скорость заметно лучше `gemma4:12b`, поэтому `qwen3.5:9b` стоит оставить главным кандидатом для дальнейших больших M4.5/M5 прогонов;
- `gemma4:12b` остаётся полезной эталонной моделью для сравнения и summarizer baseline, но для частых regression runs `qwen3.5:9b` выглядит практичнее.

## 2026-07-08: M5.0 File Ingestion Skeleton

Контекст:

- M5 начинаем не как демо-загрузку файлов, а как production-minded ingestion/retrieval слой;
- главный продуктовый фокус M5: научиться принимать, парсить, индексировать и проверять файлы;
- `bucket_id` и `tenant_id` нужны сразу как metadata foundation для будущей isolation, но полноценный no-leak retrieval test между buckets не должен блокировать первый file ingestion step.

Решение:

- добавить default settings `DEFAULT_TENANT_ID=local_demo` и `DEFAULT_BUCKET_ID=taskflow_seed`;
- расширить `RawDocument` полями `tenant_id`, `bucket_id`, `processing_status`;
- добавить skeleton loaders для `.txt` и `.json` рядом с существующими `.md`, `.csv`, `.yaml/.yml`;
- прокинуть `tenant_id`, `bucket_id`, `processing_status` и `document_metadata` в `DocumentChunk` и Qdrant payload;
- не добавлять пока активный `/rag/chat` filter по bucket: это отдельный M5.3 подэтап после базового PDF/document QA.

Smoke без записи в Qdrant:

- documents loaded: 173;
- chunks produced: 173;
- first payload содержит `tenant_id=local_demo`, `bucket_id=taskflow_seed`, `processing_status=indexed`;
- payload keys включают `tenant_id`, `bucket_id`, `document_id`, `chunk_id`, `source_type`, `source_path`, `document_metadata`;
- diagnostics и `py_compile` по изменённым Python-файлам прошли без ошибок.

Вывод:

- M5.0 foundation добавлен маленьким шагом и не ломает текущий seed ingestion;
- будущая bucket isolation будет строиться поверх уже существующего payload metadata, а не через переиндексацию всего корпуса;
- legacy `.doc` не берём в baseline: пользователь может конвертировать в `.docx`, а полноценная поддержка `.doc` остаётся future support.

Reindex verification:

- выполнен `scripts.ingest_seed_data --recreate` для текущего seed corpus;
- результат ingestion: 173 documents, 173 chunks, collection `documents`;
- новый Qdrant payload содержит `tenant_id=local_demo`, `bucket_id=taskflow_seed`, `processing_status=indexed`, `document_metadata`;
- API smoke через `/rag/chat` подтвердил, что эти поля возвращаются в `source.metadata`;
- post-reindex regression run id: `5070234d-6e65-48e8-bf70-75763a92c7d1`;
- scenarios: `metric_intent`, `negative_metric_intent`, `general_po_summary`, `technical_root_cause`, `summary_long_follow_up`, `summary_topic_switch`, `prompt_memory_budget`;
- model: `qwen3.5:9b`;
- result: 7/7 `ok`, `failed_flags=0`, `errors=0`, avg latency около 4.6s.

## 2026-07-08: M5.1 PDF Text Ingestion

Контекст:

- следующий шаг после M5.0 foundation: научиться индексировать text-based PDF;
- OCR, scanned PDF, charts и vision models не входят в baseline M5.1;
- для картинок и сканов позже отдельно рассмотрим OCR/Qwen-VL-like ingestion pipeline.

Решение:

- добавить dependency `pypdf`;
- читать `.pdf` в `document_loader.py` постранично;
- каждая страница PDF становится отдельным `RawDocument`;
- сохранять metadata: `file_name`, `page_number`, `page_count`, `source_type=pdf`, `tenant_id`, `bucket_id`;
- добавить sample PDF `data/raw/tech_knowledge/notifications_pdf_brief.pdf`;
- добавить evaluation scenario `pdf_text_ingestion` с `source_types=["pdf"]` и `score_threshold=0.0` для короткого synthetic PDF.

Smoke:

- temporary PDF loader smoke: 1 document, 1 chunk, `source_type=pdf`, `page_number=1`, `bucket_id=test_bucket`;
- real corpus smoke after sample PDF: 174 documents total, 1 PDF document;
- PDF payload содержит `source_type=pdf`, `tenant_id=local_demo`, `bucket_id=taskflow_seed`, `processing_status=indexed`, `document_metadata.page_number=1`.

Reindex and evaluation:

- выполнен `scripts.ingest_seed_data --recreate`;
- результат ingestion: 174 documents, 174 chunks;
- targeted PDF RAG smoke с default threshold вернул 0 sources, что показало чувствительность короткого PDF к retrieval score;
- повтор с `score_threshold=0.0` вернул 1 PDF source, `page_number=1`, `bucket_id=taskflow_seed`;
- PDF evaluation run id: `66901498-4411-4bf7-a159-758f3aba0603`;
- `pdf_text_ingestion`: sources=1, `has_pdf_source=true`, `pdf_page_metadata_ok=true`, `pdf_bucket_metadata_ok=true`, `failed_flags=0`;
- M5.1 regression run id: `aff5a8e9-8799-4a01-b398-d8b0aebc7a6d`;
- scenarios: `metric_intent`, `negative_metric_intent`, `general_po_summary`, `summary_topic_switch`, `prompt_memory_budget`, `pdf_text_ingestion`;
- result: 6/6 `ok`, `failed_flags=0`, `errors=0`, avg latency около 4.2s.

Вывод:

- базовый PDF text ingestion работает end-to-end через Qdrant/RAG;
- page-level metadata и bucket metadata доходят до source metadata;
- для document QA evaluation важно явно управлять `source_types` и threshold, особенно на коротких PDF;
- следующий логичный шаг: расширять document QA evaluation и сравнить `qwen3.5:9b`, `gemma4:12b`, возможно `qwen3:14b` на ответах по document context.

## 2026-07-08: M5.2 Document QA Evaluation

Контекст:

- после M5.1 важно проверить не только PDF parsing, но и качество ответов по документам;
- document QA должен доказывать, что backend отдаёт LLM правильные chunks, page metadata и bucket metadata;
- локальные пользовательские PDF можно использовать для smoke, но нельзя коммитить и нельзя записывать персональные данные в журнал.

Synthetic PDF model comparison:

- выполнен reindex локального corpus: 192 documents, 224 chunks;
- evaluation run id: `dc24ce47-e9e4-4755-9ed9-e9f987c8945b`;
- scenario: `pdf_text_ingestion`;
- `qwen3.5:9b`: sources=1, `failed_flags=0`, latency около 2.6s;
- `gemma4:12b`: sources=1, `failed_flags=0`, latency около 8.2s;
- `qwen3:14b`: sources=1, `failed_flags=0`, latency около 15.5s;
- все три модели корректно получили `source_type=pdf`, `page_number=1`, `bucket_id=taskflow_seed` и ответили по delayed Slack notifications.

Anonymized resume extraction smoke:

- пользовательский PDF не добавлялся в git;
- проверялись только категории качества extraction, без ФИО, телефона, email и других конкретных значений;
- извлечены все страницы PDF;
- детектируются категории: контактный блок как факт наличия, целевая позиция, опыт работы, навыки, AI/LLM/RAG, CI/CD, security tooling;
- первый broad PDF QA с `source_types=["pdf"]` показал, что retrieval может смешивать несколько PDF fixtures, если вопрос общий и нет фильтра на конкретный документ.

Решение:

- добавить deterministic document-level filters в `/rag/chat`: `document_ids` и `source_paths`;
- прокинуть фильтры в `RagService` и Qdrant payload filter до сборки prompt;
- сохранить фильтры в `retrieval`, чтобы debug/reporting показывали, какой документ был выбран;
- добавить поддержку `document_ids/source_paths` в evaluation runner.

Verification:

- `py_compile` по изменённым Python-файлам прошёл без ошибок;
- diagnostics по изменённым файлам без ошибок;
- regression after document filters run id: `b90def53-7ac6-4a53-9fea-ad727fa96c83`, `pdf_text_ingestion` на `qwen3.5:9b`, sources=1, status `ok`;
- filtered resume QA с `source_paths=[...]` вернул 5/5 sources только из выбранного PDF;
- model comparison на filtered resume QA: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` нашли AI/LLM/RAG признаки, все sources были из выбранного документа;
- latency на filtered resume QA: `qwen3.5:9b` около 2.8s, `gemma4:12b` около 11.8s, `qwen3:14b` около 15.5s.

Вывод:

- для document QA одного `source_types=["pdf"]` недостаточно: нужен фильтр по конкретному документу, иначе RAG может смешивать релевантные и нерелевантные PDF;
- `source_paths/document_ids` - промежуточная deterministic защита до M5.3 bucket isolation;
- `qwen3.5:9b` снова выглядит лучшим кандидатом для частых M5 document QA regression runs: качество на текущем smoke совпало с более крупными моделями, latency заметно ниже.

Дополнительный exploratory smoke: PDF с проектной таблицей.

- локально добавлен PDF с проектной спецификацией и табличной структурой, файл не предназначен для git;
- `pypdf` извлёк 2 страницы: заголовки таблицы частично распались на отдельные строки, но основные позиции, единицы измерения и количества доступны как текст;
- после reindex corpus: 194 documents, 227 chunks;
- initial RAG по выбранному `source_path` показал проблему: точечные вопросы про IP-камеры/кабели возвращали `sources=0`;
- причина: auto feature extraction из фразы "проектная PDF-таблица" мог включить продуктовый feature `projects` и сузить Qdrant filter для произвольного документа;
- исправление: если запрос уже ограничен `document_ids` или `source_paths`, backend не применяет auto feature extraction; явно переданные `features` продолжают работать;
- повторный RAG smoke: вопрос про IP-камеры вернул 46 шт, вопрос про кабели вернул витую пару 3860 м и оптический кабель 460 м, summary equipment list собрал позиции с единицами измерения и количеством;
- regression after fix run id: `f478c298-289c-45bc-a6db-86f4c11efd10`, `pdf_text_ingestion` на `qwen3.5:9b`, sources=1, status `ok`;
- вывод: text-based PDF с простыми таблицами уже можно использовать для exploratory QA, но это ещё не полноценный table extraction - структура строк может быть шумной, поэтому для production-quality таблиц нужен отдельный M5 table pipeline.

## 2026-07-08: M5.3 Bucket Isolation

Контекст:

- M5.0 уже добавил `tenant_id` и `bucket_id` в document/chunk metadata;
- M5.2 добавил deterministic document filters `document_ids/source_paths`;
- M5.3 должен доказать no-leak retrieval между buckets до передачи chunks в LLM.

Архитектурное решение:

- `tenant_id` и `bucket_ids` добавлены в `/rag/chat` request;
- если `tenant_id` не передан, backend использует `DEFAULT_TENANT_ID`;
- `bucket_ids=[]` означает все buckets внутри tenant, что сохраняет совместимость с текущими запросами;
- Qdrant payload filter теперь применяет `tenant_id`, `bucket_id`, `features`, `source_types`, `document_ids`, `source_paths` вместе;
- применённый scope возвращается в `response.retrieval` для debug/evaluation;
- фильтрация доступа происходит до prompt, поэтому LLM не видит chunks из forbidden buckets.

Synthetic fixtures:

- добавлены безопасные markdown fixtures `alpha_notifications.md` и `beta_notifications.md`;
- добавлен `data/raw/ingestion_manifest.json`;
- manifest назначает fixtures разные `bucket_id`: `bucket_alpha` и `bucket_beta`;
- manifest не индексируется как обычный JSON-документ;
- loader smoke: 196 documents, 2 bucket fixtures, `manifest_indexed=0`.

Bucket vs access model:

- в M5.3 `bucket` - это логическая область/подборка документов;
- это не полноценная RBAC-модель;
- будущая production-модель должна отделять `bucket` от `users/groups/roles/access_policies`;
- общий документ можно будет выдать группе, например `developers`, а Иванов/Петров получат доступ через membership;
- row-level/field-level доступы для финансовых таблиц остаются future hardening после structured table extraction.

Evaluation:

- reindex result: 196 documents, 229 chunks;
- final M5.3 run id: `af815661-b073-417d-91c1-b7d6a33a6934`;
- scenarios: `bucket_alpha_positive`, `bucket_beta_positive`, `bucket_no_leak_negative`;
- model: `qwen3.5:9b`;
- result: 3/3 `ok`, `failed_flags=0`, errors=0;
- short regression run id: `8b5ab873-1e6a-4ef1-8655-8193cd581733`;
- short regression scenarios: `general_po_summary`, `pdf_text_ingestion`, `bucket_no_leak_negative`, result 3/3 `ok`;
- `bucket_alpha_positive`: only `bucket_alpha`, forbidden `bucket_beta` absent;
- `bucket_beta_positive`: only `bucket_beta`, forbidden `bucket_alpha` absent;
- `bucket_no_leak_negative`: query asks about Alpha while scope is `bucket_beta`; sources only from `bucket_beta`, forbidden Alpha facts absent;
- all bucket scenarios passed `tenant_metadata_ok`, `retrieval_tenant_ok`, `retrieval_bucket_scope_ok`, `all_sources_allowed_bucket`, `forbidden_bucket_absent`.

Вывод:

- M5.3 закрывает первый no-leak retrieval boundary на уровне tenant/bucket metadata;
- это ещё не auth system, но уже правильная backend-гарантия: forbidden chunks не попадают в prompt;
- следующий слой доступа лучше добавлять только после upload/UI или structured table extraction, чтобы не превратить RAG этап в отдельный auth-проект.

## 2026-07-08: M5.4 Excel Row Ingestion

Контекст:

- следующий шаг M5 после bucket isolation - поддержка офисных Excel-файлов;
- baseline должен быть простым и трассируемым: сначала читаем строки и metadata, не пытаемся решить все spreadsheet edge cases;
- cell-level permissions, формулы, merged cells и сложный table understanding остаются future hardening.

Решение:

- добавить dependencies `openpyxl` и `xlrd`;
- читать `.xlsx` и `.xls` через `pandas.read_excel(sheet_name=None, dtype=str)`;
- каждая строка каждого sheet становится отдельным `RawDocument`;
- использовать `source_type=excel_row`;
- сохранять metadata: `file_name`, `sheet_name`, `row_index`, `excel_row_number`, исходные значения колонок;
- оставить `tenant_id/bucket_id` propagation таким же, как для других документов;
- manifest overrides M5.3 также применимы к Excel-документам, если позже нужно назначить файл в другой bucket.

Synthetic fixture:

- добавлен безопасный файл `data/raw/excel_fixtures/product_owner_metrics.xlsx`;
- sheets: `Roadmap`, `Budget`;
- loader smoke: 5 Excel row documents;
- строки содержат synthetic PO/RAG topics: enterprise onboarding, notifications, permissions, Excel ingestion budget, PDF parsing budget.

Evaluation:

- reindex result: 201 documents, 234 chunks;
- run id: `fef54dac-ac00-4f49-b073-72ad40584920`;
- scenario: `excel_ingestion`;
- model: `qwen3.5:9b`;
- result: status `ok`, sources=5, `failed_flags=0`;
- passed flags: `has_excel_source`, `excel_sheet_metadata_ok`, `excel_row_metadata_ok`, `excel_bucket_metadata_ok`, `response_has_required_markers`.

Вывод:

- базовый Excel ingestion работает end-to-end через Qdrant/RAG;
- row-level metadata даёт source traceability до sheet и row number;
- для production-grade таблиц нужен следующий слой: sheet/source_path filters, table normalization, formula handling, merged-cell strategy и later row/cell-level access control.

Дополнительный exploratory smoke: реальный `Price.xls`.

- пользователь добавил локальный устаревший `.xls` прайс, файл не предназначен для git;
- workbook читается через `xlrd`: 1 sheet, 140 строк, 6 колонок вида `Unnamed:*`;
- структура типична для офисного прайса: шапка организации, дата, категории, товарные строки, цены, единицы, пометки `новинка` / `снижение цены`;
- добавлено улучшение Excel content: `Row values: ...`, чтобы LLM видела строку в естественном порядке, а не только `Unnamed` columns;
- reindex result после `Price.xls`: 341 documents, 374 chunks.

Первичный model smoke:

- сценарии: document identity, barcode lookup, name lookup, new items, discount items, no-answer;
- модели: `qwen3.5:9b`, `gemma4:12b`;
- initial result: 3/6 failed markers у обеих моделей;
- причина не в LLM, а в retrieval: vector search не находил точный barcode `4600682643425` и не всегда доставал header rows с организацией/датой;
- увеличение `top_k` до 20 не решило exact barcode lookup.

Исправление:

- добавлен deterministic Excel supplement в `RagService`;
- supplement работает только внутри уже разрешённого scope: `tenant_id`, `bucket_ids`, `source_types`, `document_ids`, `source_paths`;
- exact numeric terms: длинные числовые токены из вопроса, например barcode;
- header rows: первые Excel rows для вопросов про документ, организацию, дату, реквизиты, компанию;
- supplement rows сортируются по `excel_row_number`, чтобы шапка читалась в естественном порядке;
- `retrieval.excel_supplement_count` показывает, сколько rows было добавлено deterministic путём.

Final Price.xls smoke:

- artifact: `research/m54_price_xls_model_smoke_latest.jsonl`;
- `qwen3.5:9b`: 6/6 сценариев, avg latency около 3.3s;
- `gemma4:12b`: 6/6 сценариев, avg latency около 7.9s;
- barcode scenario теперь находит строки 14/15, товар `Sarbast`, цену `94.44`, единицу `шт`;
- document identity scenario теперь находит `ООО "ПРАЙМ"` и дату `25 Января 2018 г.`;
- no-answer scenario корректно не выдумывает товар `Космический чай 10 литров`.

Вывод по реальному `.xls`:

- для табличных файлов одного semantic vector search недостаточно;
- exact identifiers, barcodes, invoice numbers, SKUs и header metadata нужно доставать deterministic supplement/fallback;
- `qwen3.5:9b` остаётся лучшим кандидатом для частых Excel smoke/regression: качество совпало с `gemma4:12b`, latency ниже примерно в 2.4 раза;
- это важный production-minded вывод: RAG для таблиц должен быть hybrid retrieval, а не только embeddings.

## 2026-07-09: M5.4.1 Backend Hardening Plan

Контекст:

- после M5.4 backend уже содержит много RAG/ingestion логики: PDF, buckets, document filters, Excel, exact/header supplement;
- перед M5.5 DOCX ingestion полезно укрепить backend-каркас, пока код ещё не разросся дальше;
- цель не "переписать всё", а закрыть самые практичные engineering gaps.

Что закрываем сейчас:

- пункт 1 из review: добавить обычные software tests через `pytest`;
- пункт 5: переиспользовать один `httpx.AsyncClient` в `OllamaClient`, а не создавать клиент на каждый запрос;
- пункт 3 частично: добавить `create_app()` / `lifespan` и централизовать lifecycle сервисов;
- пункт 8 частично: аккуратно декомпозировать `RagService.answer`, не меняя RAG-поведение;
- пункт 9 частично: вынести default/error conversation context в helper/factory, чтобы error path не расходился с happy path;
- пункт 11 частично: вынести самые важные magic numbers/options в `Settings`.

Что сознательно откладываем:

- пункт 2 CI/CD: не делаем сейчас, потому что проект локальный и не деплоится; вернёмся перед public demo/deploy;
- пункт 4 async Qdrant: вернёмся после OCR/Vision или при появлении performance/load задач;
- пункт 6 Alembic: вернёмся перед upload/UI, когда PostgreSQL станет source of truth для documents/buckets/access;
- пункт 7 auth/RBAC/security: вернёмся перед upload/UI и public demo;
- пункт 10 dependency lock/version pinning: вернёмся перед public demo/deploy.

Ожидаемый результат M5.4.1:

- есть быстрые unit tests для чистой логики;
- есть локальная команда запуска tests;
- lifecycle FastAPI стал ближе к production pattern;
- Ollama HTTP client переиспользуется и корректно закрывается;
- RAG behavior подтверждён коротким regression после refactoring.

## 2026-07-09: M5.4.1 Backend Hardening Implementation

Что сделано:

- добавлен `pytest`;
- добавлены первые unit tests: `FeatureExtractor`, `QueryRouter`, RAG helper functions, `OllamaClient`, `create_app()` и fallback conversation context;
- `OllamaClient` переведён на reusable `httpx.AsyncClient`;
- добавлен `OllamaClient.aclose()` для lifecycle shutdown;
- FastAPI перешёл с deprecated `@app.on_event("startup")` на `lifespan`;
- добавлен `create_app()`;
- DB engine закрывается на shutdown через `db_engine.dispose()`;
- fallback conversation context вынесен в `_conversation_context_error()`;
- `RagService.answer()` стал тоньше: retrieval chain вынесен в `_retrieve_sources()`;
- magic numbers/options вынесены в `Settings`: `rag_candidate_multiplier`, `rag_generation_keep_alive`, `rag_generation_temperature`, `rag_generation_top_p`, `excel_supplement_scroll_limit`.

Unit tests:

- command: `PYTHONPATH=/home/santera/Projects/backend pytest -q`;
- result: 13 passed;
- runtime: около 0.5s;
- тесты не требуют Docker, Ollama или Qdrant.

Regression:

- run id: `7c445c79-c8f9-4cb3-93a4-38147eb25408`;
- model: `qwen3.5:9b`;
- scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`;
- result: 3/3 `ok`;
- `failed_flags=0` по всем сценариям.

Вывод:

- M5.4.1 закрыл главный engineering gap: появились быстрые unit tests для backend-логики;
- lifecycle стал ближе к production FastAPI pattern;
- reusable `OllamaClient` уменьшает overhead на создание HTTP clients;
- поведение RAG после refactoring подтверждено коротким regression;
- CI/CD, Alembic, auth/RBAC, async Qdrant и dependency locking остаются future hardening, а не блокируют M5.5.

## 2026-07-09: M5.5 DOCX Ingestion

Контекст:

- после PDF, bucket isolation и Excel нужен следующий офисный формат - `.docx`;
- baseline должен быть простым и трассируемым: читаем текстовые блоки и таблицы, не берём legacy `.doc`;
- `bucket_id/tenant_id` propagation должен работать так же, как для PDF/Excel.

Что сделано:

- добавлена зависимость `python-docx`;
- добавлен DOCX loader в `document_loader.py`;
- paragraphs превращаются в `RawDocument` с `source_type=docx`;
- table rows тоже превращаются в `RawDocument` с `source_type=docx`;
- тип блока хранится в metadata: `block_type=paragraph` или `block_type=table_row`;
- для paragraphs сохраняется `paragraph_index`;
- для table rows сохраняются `table_index`, `table_row_index`;
- table row content получает `Row values: ...`, чтобы LLM видела строку в человекочитаемом виде;
- добавлен synthetic fixture `data/raw/docx_fixtures/product_owner_brief.docx`;
- добавлен unit test `tests/test_document_loader_docx.py`;
- добавлен evaluation scenario `docx_ingestion`.

Проверки:

- unit tests: 14 passed;
- compile: `python -m compileall app scripts tests`;
- reindex: 347 documents, 380 chunks;
- DOCX smoke: run id `8c6436bb-f2ad-4a94-8707-b1505f758148`;
- model: `qwen3.5:9b`;
- scenario: `docx_ingestion`;
- result: sources=5, `failed_flags=0`;
- short regression: run id `0f68ba39-72ad-4f54-8b8a-3ff984a619dc`;
- scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`;
- result: 4/4 `ok`, `failed_flags=0`.

Наблюдение:

- первый DOCX smoke показал полезную edge case: риск и рекомендация были в разных paragraphs, и top-5 retrieval поднял риск, но не поднял paragraph с recommendation;
- модель ответила честно: "в контексте нет рекомендации";
- для smoke fixture риск и recommendation объединены в один paragraph, потому что цель M5.5 - проверить ingestion/metadata, а не устроить отдельный тест на paragraph adjacency retrieval;
- это не считается закрытием проблемы chunking: в future hardening для DOCX стоит подумать о соседних paragraph windows или document-section chunking.

Вывод:

- `.docx` baseline работает end-to-end через общий ingestion -> chunking -> Qdrant -> RAG path;
- `source_type=docx` достаточно прост для фильтрации, а `block_type` в metadata сохраняет детализацию;
- legacy `.doc`, rich formatting, comments, headers/footers, embedded images и section-aware chunking остаются future support.

## 2026-07-09: M5.5.1 DOCX Chunking Hardening

Контекст:

- пользователь добавил реальный технический DOCX `data/raw/docx_fixtures/Front&Back_C#.docx`;
- документ содержит задания по frontend/backend и куски кода;
- baseline paragraph-level DOCX ingestion нашёл важную проблему: задание и код часто лежат в соседних paragraphs;
- пример: paragraph с заданием `ModifyUsers` поднимается retrieval, но соседняя сигнатура `async Task ModifyUsers(...)` может не попасть в prompt.

Решение:

- не удалять точные `paragraph` и `table_row` blocks, потому что они дают source traceability;
- добавить adjacent context прямо в paragraph content:
  - `Previous paragraph`;
  - `Current paragraph`;
  - `Next paragraph`;
- дополнительно добавить `paragraph_window` documents с overlap;
- metadata для window: `block_type=paragraph_window`, `paragraph_start_index`, `paragraph_end_index`, `paragraph_count`, `window_index`;
- это лёгкий production-minded компромисс: лучше retrieval для технических DOCX без внедрения тяжёлого layout/section parser.

Проверки:

- unit tests: 14 passed;
- compile: `python -m compileall app scripts tests`;
- loader smoke по `Front&Back_C#.docx`: 331 blocks, из них 283 `paragraph` и 48 `paragraph_window`;
- reindex: 679 documents, 712 chunks;
- artifact: `research/m55_frontback_docx_model_smoke_latest.jsonl`;
- scenarios: `frontback_docx_structure`, `frontback_docx_react_tasks`, `frontback_docx_async_modify_users`;
- models: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`;
- result: 9/9 без failed flags;
- short regression: run id `63e91ec7-7d5c-4825-8b4a-8b404e167db4`;
- regression scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`;
- result: 4/4 `ok`, `failed_flags=0`.

Наблюдения:

- после hardening Qdrant всё ещё часто выбирает одиночные paragraph chunks, а не `paragraph_window`;
- это не ошибка: одиночные paragraph chunks теперь содержат adjacent context, поэтому prompt всё равно получает соседние строки;
- `paragraph_window` остаётся полезным fallback для вопросов, где нужен более широкий локальный контекст;
- следующий возможный уровень - section-aware DOCX chunking: заголовок/раздел/задание + связанные code blocks.

Future scaling/access notes:

- роли/RBAC лучше вводить после UI/upload/bucket management, когда появятся реальные пользователи, группы и bucket membership;
- сейчас достаточно сохранять `tenant_id/bucket_id` и фильтровать до prompt;
- OpenRouter/external provider fallback нужно планировать в M8 Model Routing как `local_only/local_first/external_allowed`;
- внешние модели нельзя использовать для приватных документов без явного opt-in;
- Redis/очереди/Kafka/incremental indexing нужны позже как отдельное scaling hardening, когда появятся upload jobs и большие корпуса документов.

## 2026-07-09: M5.5.2 DOCX Hybrid Retrieval / Reranking

Контекст:

- M5.5.1 улучшил DOCX chunking через adjacent context и `paragraph_window`;
- это помогло качеству ответов, но архитектурно всё ещё было baseline-решением: соседний контекст склеивался до embedding;
- пользователь справедливо отметил, что позже нужно прийти к более взрослому retrieval: несколько представлений, supplement, neighbor expansion, reranking.

Что сделано:

- добавлен `docx_supplement_scroll_limit` в `Settings`;
- `RagService` теперь делает DOCX supplement внутри разрешённого scope:
  - `tenant_id`;
  - `bucket_ids`;
  - `document_ids`;
  - `source_paths`;
- supplement срабатывает только для `source_type=docx` и ограниченного document scope;
- добавлен exact/lexical supplement для code-like terms: `ModifyUsers`, `React`, `async`, `Task`, числовые маркеры;
- `File:` line исключается из exact matching, чтобы имя файла `Front&Back_C#.docx` не матчило каждый chunk;
- добавлен neighbor expansion по `paragraph_index` с радиусом 2;
- `paragraph_window` используется как широкий локальный контекст;
- добавлен lightweight reranking:
  - base vector score;
  - exact match boost;
  - небольшой `paragraph_window` boost;
- в response debug появился `retrieval.docx_supplement_count`;
- добавлены unit tests для DOCX exact terms, neighbor expansion и rerank score.

Проверки:

- unit tests: 17 passed;
- compile: `python -m compileall app scripts tests`;
- точечный smoke `async Task ModifyUsers`:
  - `docx_supplement_count=12`;
  - первые sources: `paragraph_window`, paragraph 257, paragraph 258;
  - ответ нашёл и задание, и сигнатуру `async Task ModifyUsers(...)`;
- artifact: `research/m552_frontback_docx_hybrid_latest.jsonl`;
- scenarios: `frontback_docx_structure`, `frontback_docx_react_tasks`, `frontback_docx_async_modify_users`;
- models: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b`;
- result: 9/9 без failed flags;
- `docx_supplement_count`: 12-14;
- short regression: run id `fc2604a2-230f-485a-9444-eb63d52e4dac`;
- regression scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`;
- result: 4/4 `ok`, `failed_flags=0`.

Вывод:

- M5.5.2 стал первым полноценным DOCX hybrid retrieval step;
- теперь backend не просто отдаёт raw top-k Qdrant, а собирает локальный evidence bundle;
- это ближе к production RAG: vector search находит candidates, deterministic supplement добавляет точные/соседние chunks, reranking упорядочивает результат;
- следующий возможный шаг - section-aware DOCX parsing и отдельное распознавание `code_block`.

## 2026-07-09: M5.6.1 Image OCR Baseline Start

Контекст:

- после PDF/Excel/DOCX следующий формат M5 - изображения;
- пользователь добавил реальные fixtures в `data/raw/docx_fixtures`;
- для M5.6 решили идти поэтапно:
  - сначала OCR-only baseline;
  - затем vision digest/caption через multimodal model.

Выбранные fixtures:

- `just_text.png` - чистый русский текст, лучший первый OCR smoke;
- `tablet.png` - таблица/коммерческое предложение, будущий table OCR case;
- `charts.png` и `diagram.jpeg` - графики, лучше подходят для chart/vision digest;
- `image.png` - фото с крупной надписью UFA, подходит для vision/caption smoke;
- `zabbix.jpg` - monitoring chart, сложнее для OCR, полезен позже для vision/chart understanding.

Что сделано:

- добавлены Python dependencies: `pillow`, `pytesseract`;
- добавлен image OCR loader для `.png`, `.jpg`, `.jpeg`;
- loader создаёт `RawDocument` с `source_type=image_ocr`;
- metadata: `file_name`, `block_type=image_ocr`, `image_width`, `image_height`, `image_format`, `ocr_engine=tesseract`, `ocr_languages=rus+eng`;
- `tenant_id/bucket_id` propagation сохраняется;
- если системный Tesseract недоступен, loader не валит весь ingestion, а пропускает image OCR с warning;
- добавлен unit test без реального Tesseract через monkeypatch;
- добавлен evaluation scenario `image_ocr_ingestion`.

Проверки:

- попытка установить Tesseract через `sudo apt-get install ...` не прошла, потому что sudo требует интерактивную авторизацию;
- пользователь установил системный Tesseract вручную;
- доступные языки: `eng`, `rus`, `osd`;
- unit tests: 18 passed;
- compile: `python -m compileall app scripts tests`;
- real loader smoke: 6 `image_ocr` documents;
- `just_text.png` и `tablet.png` распознаны хорошо;
- `charts.png`, `diagram.jpeg`, `zabbix.jpg` распознаются частично, что подтверждает необходимость отдельного vision/chart digest;
- reindex: 685 documents, 718 chunks;
- `image_ocr_ingestion` smoke: run id `4132007a-f610-423e-9f3a-4844525d9c31`;
- result: sources=1, `failed_flags=0`;
- short regression: run id `a7801121-cb2a-4278-950c-3b99f6dadb8b`;
- scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `image_ocr_ingestion`;
- result: 5/5 `ok`, `failed_flags=0`.

Вывод:

- M5.6.1 OCR baseline работает end-to-end;
- OCR хорошо подходит для картинок с текстом и простых таблиц;
- графики/фото/monitoring charts требуют vision/caption digest, а не только OCR;
- vision/caption остаётся отдельным M5.6.2, потому что OCR и visual understanding решают разные задачи.

## 2026-07-09: M5.6.2 Image Vision Digest

Контекст:

- OCR baseline хорошо распознаёт `just_text.png` и `tablet.png`, но плохо подходит для фото, графиков и monitoring charts;
- локальная модель `gemma4:12b` уже установлена в Ollama и является более актуальным кандидатом для vision digest;
- проверка через `/api/generate` с `images` подтвердила, что `gemma4:12b` умеет vision input.

Что сделано:

- `OllamaClient.generate()` получил optional `images`;
- добавлен `image_digest_service.py`;
- vision digest создаётся во время `scripts.ingest_seed_data`;
- добавлены settings: `image_vision_enabled`, `image_vision_model`;
- изображение нормализуется в PNG через Pillow перед отправкой в vision model;
- digest documents имеют `source_type=image_digest`;
- metadata: `block_type=image_digest`, `image_width`, `image_height`, `image_format`, `vision_model`, `digest_type=vision_caption`;
- добавлен evaluation scenario `image_digest_ingestion`;
- добавлены unit tests для image digest service и image payload в `OllamaClient`.
- evaluator усилен через `required_numeric_values`: числовые факты проверяются после нормализации форматов (`1 416 960,00`, `1416960`, `1,416,960.00`, `1.416.960`).
- evaluator усилен через `required_marker_groups`: семантически равные варианты marker-ов проверяются группами, например `("провер", "валидац", "validation")`.

Проверки:

- `gemma4:12b` описала `image.png`: ребёнок рядом с бирюзовой надписью, но текст надписи прочитан как `UEFA`;
- unit tests: 20 passed;
- compile: `python -m compileall app scripts tests`;
- reindex после `gemma4:12b` и image normalization: 691 documents, 724 chunks;
- `image_digest` sources: 6;
- `image_digest_ingestion` smoke на `tablet.png`: run id `43a7e78b-743b-47c9-b606-ed4cc7adce78`;
- result: sources=1, `failed_flags=0`;
- final short regression: run id `a21a3e9e-00f3-44b0-b494-be338cdb79fa`;
- scenarios: `general_po_summary`, `excel_ingestion`, `bucket_no_leak_negative`, `docx_ingestion`, `image_ocr_ingestion`, `image_digest_ingestion`;
- result: 6/6 `ok`, `failed_flags=0`.

Наблюдения:

- `image.png`: vision digest хорошо описывает сцену, тогда как OCR почти бесполезен;
- `tablet.png`: OCR и vision оба полезны, но дают разные представления: OCR точнее по строкам, vision лучше summarization;
- `diagram.jpeg` и `zabbix.jpg`: vision digest уже полезнее OCR для смысла графика;
- `charts.png` сначала был пропущен vision digest с HTTP 400 от Ollama, потому что Pillow определяет файл как `WEBP` при расширении `.png`;
- это частый пользовательский сценарий: файл переименован без реальной конвертации;
- добавлена нормализация изображения в PNG перед vision call.
- после перехода на `gemma4:12b` модель прочитала надпись на `image.png` как `UEFA` вместо ожидаемого `UFA`;
- это важный quality finding: vision caption полезен для сцены, но точное чтение текста на фото требует OCR/vision reconciliation;
- стабильный smoke перенесён на `tablet.png`, где digest проверяет коммерческое предложение и сумму;
- сумма `1 416 960,00` теперь проверяется не через хрупкий текстовый marker `416`, а через нормализованный числовой факт `1416960`.
- three-model smoke после marker groups: run id `78b0e70f-3a04-4d75-9910-78baa54d2672`;
- artifact: `research/m56_three_model_10_scenario_latest.jsonl`;
- scenarios: `image_ocr_ingestion`, `image_digest_ingestion`, `pdf_text_ingestion`, `excel_ingestion`, `docx_ingestion`, `bucket_alpha_positive`, `bucket_beta_positive`, `bucket_no_leak_negative`, `general_po_summary`, `no_answer_groundedness`;
- result: `qwen3.5:9b` 10/10, avg latency около 9.2s; `gemma4:12b` 10/10, avg latency около 10.9s; `qwen3:14b` 10/10, avg latency около 12.9s.

Вывод:

- для изображений теперь есть два независимых evidence слоя: `image_ocr` для текста и `image_digest` для визуального смысла;
- это соответствует общей M5 retrieval стратегии: разные представления одного source индексируются как text evidence;
- RAG-answer модель получает уже извлечённый текст/digest, а не исходную картинку.

## 2026-07-09: M5.7 Complex Office Files

Контекст:

- пользователь добавил fixtures: `sample-with-images.docx`, `sample-with-table.docx`, `diagramms.xlsx`, `diagramms2.xlsx`, `hard_for_analis.xls`;
- цель этапа: проверить сложные Office-файлы до UI/M6, чтобы ingestion умел доставать не только plain text/table rows, но и embedded media/charts.

Что сделано:

- DOCX embedded images извлекаются из `word/media/*`;
- XLSX embedded images извлекаются из `xl/media/*`;
- embedded images проходят через уже существующие evidence-слои: `image_ocr` и `image_digest`;
- metadata сохраняет `parent_source_type`, `embedded_path`, `embedded_image_index`;
- Excel native charts индексируются как `source_type=excel_chart`;
- для обычных openpyxl charts используется `_charts`;
- для modern chartEx/chart XML добавлен fallback по `xl/charts/chart*.xml` плюс visible workbook context.

Проверки:

- unit tests: 28 passed;
- compile: `python -m compileall app scripts tests`;
- reindex: 1012 documents, 1057 chunks;
- M5.7 qwen smoke: run id `c9633abd-ed9d-4351-b7db-33e1386f5147`, 4/4 сценария, `failed_flags=0`;
- M5.7 three-model smoke: run id `c59e112c-aa33-472c-a15e-55f15a066428`;
- artifact: `research/m57_complex_office_three_model_latest.jsonl`;
- result: `qwen3.5:9b` 4/4, avg latency около 9.9s; `gemma4:12b` 4/4, avg latency около 15.3s; `qwen3:14b` 4/4, avg latency около 13.2s.

Наблюдения:

- `sample-with-images.docx` по тексту выглядит как sample с embedded image, но фактическая картинка оказалась графиком прибыли; evaluator был поправлен на реальное image evidence;
- пользователь подтвердил, что картинка была намеренно заменена без обновления текста документа: это стало полезным mismatch fixture;
- система корректно разделила evidence: `docx` paragraphs говорят про gradient, а `image_digest` / `image_ocr` по embedded image говорят про график прибыли;
- `diagramms.xlsx` содержит декоративную embedded PNG image и отдельно chartEx Pareto chart в XML, поэтому это два разных evidence: `image_digest` и `excel_chart`;
- `diagramms2.xlsx` содержит native `AreaChart`, который openpyxl распознаёт как chart object;
- `.xls` остаётся сложнее для embedded media, потому что это legacy binary формат, не zip-based Office Open XML.

Вывод:

- M5.7 закрыл важную production-minded границу: Office-файл может содержать несколько типов evidence одновременно;
- для графиков в Excel нельзя полагаться только на картинки: часть диаграмм живёт как native chart/XML и должна индексироваться отдельно;
- следующий крупный шаг по M5 - расширить сценарии до большого M5 regression набора и отдельно решить, насколько глубоко поддерживать legacy `.xls` embedded media.

## 2026-07-09: M5.7.5 DOCX Text vs Visual Evidence Mismatch

Контекст:

- `sample-with-images.docx` намеренно содержит mismatch: текст документа описывает `gradient image`, но embedded image фактически является графиком прибыли;
- это полезный portfolio-case: система должна не просто отвечать по картинке, а уметь сравнить разные evidence layers внутри одного файла.

Что сделано:

- добавлен scenario `docx_text_image_mismatch`;
- scenario использует `source_types=["docx", "image_digest", "image_ocr"]` и конкретный `source_path`;
- `RagService` усилен: если запрос находится в document scope и явно просит несколько `source_types`, backend поднимает недостающие source types в первые `top_k`;
- fixed subtle retrieval issue: раньше visual evidence был в candidate list, но оказывался за пределами final `top_k`.

Проверки:

- focused tests: 13 passed;
- compile: `python -m compileall app scripts tests`;
- initial smoke показал retrieval gap: sources были только `docx`, модель честно отвечала, что картинки нет в context;
- после top-k required source type fix sources стали включать `image_ocr`, `image_digest` и `docx`;
- three-model smoke: run id `9bde5707-a50c-4dc7-b250-4b50e739b103`;
- artifact: `research/m575_docx_text_image_mismatch_latest.jsonl`;
- result: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли scenario без failed flags.

Наблюдения:

- Qwen-модели сначала слишком осторожно говорили, что без пикселей нельзя проверить изображение;
- scenario prompt был уточнён: `image_digest/image_ocr` являются extracted evidence по фактической embedded image;
- после этого модели корректно зафиксировали mismatch: текст говорит про gradient, visual evidence говорит про график прибыли.

Вывод:

- M5.7.5 подтверждает, что разные representations одного файла могут использоваться совместно;
- следующий hardening-кандидат: создавать отдельный `office_media_consistency` evidence на ingestion этапе, чтобы mismatch был вычислен заранее, а не только во время RAG-answer.

## 2026-07-09: M5.7.6 Office Media Consistency Evidence

Контекст:

- после M5.7.5 стало понятно, что retrieval-time comparison работает, но продуктово удобнее иметь заранее созданный consistency evidence;
- пользователь подтвердил идею: backend должен уметь отвечать на вопрос “есть ли расхождение между текстом и картинками?” без ручного перечисления `docx/image_digest/image_ocr`.

Что сделано:

- добавлен `office_media_consistency_service.py`;
- ingestion создаёт `RawDocument` с `source_type=office_media_consistency` после добавления image digests;
- consistency evidence объединяет document text, embedded image digest и embedded image OCR;
- metadata содержит `parent_source_type`, `embedded_path`, `embedded_image_index`, `compared_source_types`, `consistency_status`;
- deterministic baseline ставит `potential_mismatch`, если document text говорит про gradient, а visual evidence говорит про chart/profit.

Проверки:

- unit tests: 30 passed;
- compile: `python -m compileall app scripts tests`;
- reindex: 1014 documents, 1061 chunks;
- qwen smoke после summary fix: run id `3bcf0552-db06-4c0a-b3e2-dec89b99f8d5`, `failed_flags=0`;
- three-model smoke: run id `ebf63ad4-3b31-4ae0-a259-20579fc3744f`;
- artifact: `research/m576_office_media_consistency_latest.jsonl`;
- result: `qwen3.5:9b`, `gemma4:12b`, `qwen3:14b` прошли scenario без failed flags.

Наблюдения:

- первая версия consistency evidence была слишком длинной: retrieval находил source, но chunk не всегда содержал явный mismatch summary;
- после добавления `Consistency reason` в начало content все модели стабильно увидели расхождение;
- `diagramms.xlsx` получил `review_needed`, потому что декоративная embedded image и табличный Pareto chart не срабатывают на текущую deterministic mismatch rule.

Вывод:

- M5.7.6 добавил первый ingestion-level media consistency layer;
- это лучше, чем каждый раз заставлять RAG собирать `docx + image_digest + image_ocr` вручную;
- future hardening: заменить/дополнить deterministic rule LLM-based consistency checker для сложных caption/image/table случаев.

## 2026-07-09: M5.8 Legacy/Hard Excel Edge Cases

Контекст:

- пользователь добавил `data/raw/excel_fixtures/hard_for_analis.xls`;
- цель этапа: понять, что реально достаёт `pandas/xlrd` из старого `.xls`, есть ли embedded/visual элементы, и нужен ли отдельный heavy fallback.

Что выяснили:

- файл является `Composite Document File V2` / legacy OLE/BIFF Excel;
- `xlrd` видит 1 лист `Прайс с 01.05`, 140+ строк, 12 колонок при `formatting_info=True`, 157 merged cells;
- `pandas.read_excel` достаёт row-level text, включая строку с `ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ`;
- `xlrd` не отдаёт embedded images как структурированные pictures;
- бинарный scan файла показывает JPEG/PNG signatures;
- после полного Pillow validation найдено 27 читаемых embedded images.

Что сделано:

- `iter_office_embedded_images()` теперь учитывает `.xls`;
- для `.xls` добавлен lightweight fallback: валидные JPEG/PNG blobs извлекаются по binary signatures;
- повреждённые blobs отсекаются через полную загрузку изображения, а не только `Image.verify()`;
- legacy images получают metadata `parent_source_type=xls` и `embedded_path=legacy-binary/imageN.jpg|png`;
- existing `image_ocr` и `image_digest` pipelines автоматически начали работать для `.xls` embedded images;
- Excel retrieval supplement усилен: кроме длинных numeric terms он учитывает значимые lexical terms из вопроса, чтобы product-name queries находили нужную row.

Проверки:

- targeted tests после реализации: 21 passed;
- reindex после фильтрации broken blob: 1073 documents, 1145 chunks;
- M5.8 final three-model smoke: run id `1232422c-65b0-4e20-9660-7b65d95f04be`;
- artifact: `research/m58_legacy_hard_excel_latest.jsonl`;
- scenarios: `legacy_xls_text_ingestion`, `legacy_xls_embedded_image_digest`;
- models: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`;
- result: 2/2 scenarios x 3 models, `failed_flags=0`.

Наблюдения:

- первый text scenario показал retrieval gap: dense top-k находил похожие строки прайса, но не точную строку с `ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ`;
- это не ingestion problem: строка была в Qdrant, но требовался lexical supplement по product name;
- после добавления Excel lexical exact terms row 11 стала попадать в контекст, и все модели ответили корректно;
- evaluator numeric markers не стоит использовать для каждого числа подряд: `4,1 %` лучше проверять marker group, а `30` и `3500` - numeric normalization.

Вывод:

- для M5 baseline не нужен LibreOffice/headless converter;
- текущий production-minded компромисс: `.xls` rows через `pandas/xlrd`, embedded images через lightweight binary fallback, ограничения честно фиксируются в metadata;
- future hardening: если понадобятся координаты картинок, shapes, OLE objects или восстановление layout, тогда понадобится отдельный legacy Office conversion/parsing layer.

## 2026-07-09: M5.8.1 DOCX/XLSX Image Anchor Metadata

Контекст:

- после M5.8 стало понятно, что legacy `.xls` умеет отдавать картинки как evidence, но не умеет связывать их с конкретными строками;
- пользователь добавил новые fixtures: `sample-with-table 2.docx` и `hard_for_analis_2.xlsx`;
- цель этапа: проверить более реалистичный вопрос “что написано на картинке у продукта с параметрами X и ценой Y?”.

Что выяснили:

- `sample-with-table 2.docx` содержит таблицу товаров, где каждая product row имеет отдельную image cell;
- DOCX XML позволяет связать `word/media/imageN.png` с конкретной table row/cell через `word/document.xml` и relationships;
- `hard_for_analis_2.xlsx` содержит 75 images, и `openpyxl` видит anchors;
- для строки с `ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ`, `4,1 % алкоголь`, `11% плотность`, `3500 р` видны anchors `B11` и `E11`;
- это существенно лучше, чем `.xls` binary fallback, потому что `.xlsx` сохраняет layout anchors в OpenXML.

Что сделано:

- `EmbeddedImage` получил optional `metadata`;
- DOCX extraction добавляет `anchor_type=docx_table_cell` или `docx_paragraph`;
- DOCX table-cell images получают `table_index`, `table_row_index`, `table_cell_index`, `table_row_text`, `linked_text`;
- DOCX paragraph images получают `paragraph_index`, `paragraph_text`, `previous_paragraph_text`, `linked_text`;
- XLSX images извлекаются через `openpyxl` `_images` и получают `anchor_type=xlsx_cell`, `sheet_name`, `anchor_row`, `anchor_col`, `anchor_cell`, `nearby_row_text`, `linked_text`;
- `image_ocr` и `image_digest` content теперь содержит `Linked text`, чтобы vector retrieval мог найти картинку по тексту товарной строки;
- добавлены scenarios `docx_table_image_anchor_digest` и `xlsx_row_image_anchor_digest`.

Проверки:

- focused tests: 13 passed;
- reindex: 1423 documents, 1614 chunks;
- final three-model smoke: run id `ffb874c7-ba06-4d3b-a437-275df3928a6b`;
- artifact: `research/m581_office_image_anchor_latest.jsonl`;
- scenarios: `docx_table_image_anchor_digest`, `xlsx_row_image_anchor_digest`;
- models: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`;
- result: 2/2 scenarios x 3 models, `failed_flags=0`.

Наблюдения:

- первый вариант evaluator требовал, чтобы ответ обязательно повторял `ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ`, но часть моделей корректно отвечала про картинку без повторения полного названия;
- product binding лучше проверять metadata flags (`linked_text`, `anchor_type`, `anchor_row`), а response markers оставить для ответа/визуального содержания;
- `image_digest` иногда искажает текст на этикетке (`БУРНИТВО`, `БУЛЬНИТВО` вместо ожидаемого названия), поэтому visual digest полезен, но точное чтение текста на этикетках всё ещё требует OCR/vision reconciliation.

Вывод:

- DOCX/XLSX image anchor metadata закрывает важный product case: “картинка у строки/товара”;
- для `.docx` и `.xlsx` теперь можно строить evidence bundle вокруг table row / anchor cell;
- legacy `.xls` layout linking остаётся future hardening через LibreOffice/headless или специализированный BIFF/Escher parser.

Future access-control note:

- field-level access для таблиц возможен, но это отдельный policy/redaction layer;
- правильная граница: parsing -> structured cell/row metadata -> authorization/redaction -> retrieval/prompt;
- LLM не должен решать, можно ли показывать `price`; backend должен удалить или заменить restricted fields до prompt.

## 2026-07-09: M5.8.2 Scanned Table Layout OCR Baseline

Контекст:

- после DOCX/XLSX anchor metadata пользователь спросил про сканы/скриншоты таблиц, где документ уже не содержит структурных anchors;
- цель этапа: проверить, можно ли восстановить минимальную table structure из пикселей и связать image cell с row text;
- продвинутые инструменты (`PaddleOCR PP-Structure`, `docTR`, `layoutparser`, table detection models, Donut/LayoutLM/Florence-like) решено оставить отдельным research spike после baseline.

Что сделано:

- добавлен PIL-based grid detector без новой тяжёлой зависимости;
- detector ищет длинные непрерывные горизонтальные/вертикальные линии таблицы;
- найденная сетка превращается в row/cell regions;
- последняя колонка используется как baseline image column;
- row crop OCR-ится через Tesseract для `linked_text`;
- image cell crop превращается в `EmbeddedImage` с `parent_source_type=scanned_table` и `anchor_type=scanned_table_cell`;
- `image_ocr` и `image_digest` автоматически получают `linked_text`, `table_row_bbox`, `image_cell_bbox`;
- добавлен fixture `data/raw/scanned_fixtures/scanned-table-products.png`;
- добавлен scenario `scanned_table_image_anchor_digest`.

Проверки:

- focused tests: 10 passed;
- reindex: 1440 documents, 1629 chunks;
- three-model smoke: run id `86d7cdf3-4a8a-4d26-b653-f6970715b83d`;
- artifact: `research/m582_scanned_table_layout_ocr_latest.jsonl`;
- models: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`;
- result: 1 scenario x 3 models, `failed_flags=0`.

Наблюдения:

- первый вариант line detector считал суммарные line pixels и ошибочно принимал повторяющиеся края этикеток за линии таблицы;
- fix: считать самый длинный непрерывный сегмент линии, а не сумму пикселей по всей оси;
- Tesseract linked text остаётся шумным, но для retrieval достаточно наличия ключевых фактов (`3500`, `4,1`, `11%`);
- vision digest по crop хорошо описывает именно image cell, а не всю страницу.

Вывод:

- для хороших сканов с явной сеткой можно построить полезный baseline без OpenCV/PaddleOCR;
- задача принципиально отличается от DOCX/XLSX: там структура читается из файла, здесь структура восстанавливается из pixels;
- следующий разумный шаг - отдельный PaddleOCR PP-Structure spike и сравнение с текущим baseline на тех же fixtures.

Future hardening:

- поддержать таблицы без видимых линий;
- определять image column не только как последнюю колонку;
- добавить PDF page rendering для scanned PDF;
- сравнить PaddleOCR PP-Structure, docTR, layoutparser, table detection models и Donut/LayoutLM/Florence-like подходы.

## 2026-07-09: M5.8.3 PaddleOCR PP-Structure Spike Harness

Контекст:

- пользователь хочет посмотреть “взрослый” вариант table/layout OCR, особенно PaddleOCR, потому что встречал его на прошлом проекте;
- после M5.8.2 baseline важно не заменить рабочий код вслепую, а сравнить PaddleOCR PP-Structure с нашим простым grid detector на одном fixture.

Что сделано:

- добавлен optional script `backend/scripts/spike_paddleocr_structure.py`;
- script не добавляет PaddleOCR в обязательные зависимости backend;
- script проверяет наличие `paddleocr` и `paddle`;
- если зависимости доступны, запускает `PPStructureV3`/legacy `PPStructure` на `data/raw/scanned_fixtures/scanned-table-products.png`;
- script поддерживает PaddleOCR 3.7 API через `predict()` и сохраняет compact summary новых result objects;
- если зависимостей нет, сохраняет compatibility artifact со статусом `missing_dependency`.

Проверки:

- fallback check в текущем backend venv: Python 3.14.4;
- `paddleocr` отсутствует;
- `paddle` отсутствует;
- script run завершился штатно, без падения backend;
- artifact: `research/m583_paddleocr_structure_spike_latest.json`;
- fallback status: `missing_dependency`;
- real spike env на Python 3.11.15: `paddleocr==3.7.0`, `paddlex==3.7.2`, `paddlex[ocr]`, `paddlepaddle==3.2.2`;
- `paddlepaddle==3.3.1` на CPU падал с известной oneDNN/PIR ошибкой `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`;
- после downgrade до `paddlepaddle==3.2.2` и установки `paddlex[ocr]` script завершился со статусом `completed`;
- PPStructureV3 нашёл `table` block, 7 layout boxes и сформировал HTML таблицы с image references.

Наблюдения:

- PaddlePaddle часто имеет ограничения по Python wheel compatibility;
- с Python 3.14 установка может оказаться проблемной, поэтому безопаснее держать PaddleOCR spike изолированным;
- если установка в текущий `.venv` не пройдёт, стоит создать отдельное Python 3.10/3.11 окружение только для OCR/layout experiments;
- для PaddleOCR 3.7 одного `paddleocr` недостаточно для PPStructureV3: нужен `paddlex[ocr]`.

Вывод:

- M5.8.3 остаётся spike harness, а не полноценной PaddleOCR integration;
- это правильная граница: основной backend остаётся стабильным, а тяжёлые OCR/layout зависимости проверяются отдельно;
- PPStructureV3 даёт более богатый table/layout output, чем наш baseline, но требует тяжёлого отдельного окружения и внимательной нормализации результата в `linked_text` evidence.

## 2026-07-09: M5 Full Regression Follow-Up Fixes

Контекст:

- после большого M5 regression на 49 сценариях и трёх моделях осталось 8 quality-flag failures из 147 результатов;
- технических ошибок не было, но 4 сценария требовали разбора: `excel_ingestion`, `xlsx_row_image_anchor_digest`, `docx_text_image_mismatch`, `office_media_consistency_mismatch`;
- цель follow-up: отделить реальные retrieval/ingestion проблемы от устаревших evaluator expectations.

Что сделано:

- `xlsx_row_image_anchor_digest`: добавлен lexical supplement для XLSX anchored `image_digest` sources;
- supplement использует exact terms из вопроса (`4,1`, `11`, `3500`) и поднимает картинки, чей `linked_text` содержит больше совпадений;
- подтверждено, что для `hard_for_analis_2.xlsx` первыми возвращаются `anchored_image5` и `anchored_image7` с `anchor_row=11`;
- `excel_ingestion`: scenario привязан к правильному fixture `product_owner_metrics.xlsx`, где есть `enterprise onboarding` и рекомендация про `Excel import validation`;
- `excel_ingestion`: literal marker `validation` заменён на marker group `validation / валидац / провер`;
- `office_media_consistency`: evidence сделан compact, чтобы `Consistency status` и `Consistency reason` оставались в первом и единственном chunk;
- добавлены focused tests для XLSX visual exact matching и compact consistency evidence.

Проверки:

- focused tests: `19 passed`;
- reindex после compact consistency evidence: `1440 documents`, `1503 chunks`;
- targeted regression run id: `9dafb2f1-dd15-4c0c-ae98-bef31758c202`;
- targeted regression: 4 scenarios x 3 models = 12 results;
- result: technical errors `0`, quality-flag failures `0`.

Вывод:

- реальные M5 failures после большого прогона закрыты targeted regression;
- перед переходом к `M5.9 Voice UI Bridge` стоит повторить полный M5 regression, чтобы подтвердить отсутствие вторичных регрессий;
- важный retrieval урок: для anchored visual evidence нельзя полагаться только на vector similarity, если пользователь задаёт точные числовые/табличные признаки.

## 2026-07-10: Regression Strategy Before M5.9

Контекст:

- перед переходом к `M5.9 Voice UI Bridge` пользователь предложил разделить большой прогон на два этапа;
- цель: сначала выбрать лучшую модель именно для document-heavy RAG, а затем проверить весь проект без полного Cartesian product;
- long multi-turn user journey решено оставить отдельным третьим слоем чуть позже.

Что сделано:

- добавлен `research/REGRESSION_ENV_COMMANDS.md` с командами для Docker, Postgres/Qdrant, backend server, health check и optional reindex;
- добавлен `research/DOCUMENT_ONLY_REGRESSION_SCENARIOS.md` с document-only набором: 16 document scenarios x 3 models = 48 results;
- добавлен `research/FULL_PROJECT_REGRESSION_SCENARIOS.md` с full project strategy без Cartesian product;
- full project regression разделён на:
  - core chat/context/access: 18 scenarios x 3 models;
  - summary/memory: 15 scenarios x `qwen3.5:9b`;
  - documents: 16 scenarios x best document model from document-only regression.

Вывод:

- такой подход сохраняет диагностируемость и не раздувает прогон до шумной матрицы “всё на всём”;
- document-only regression должен выбрать модель для документов;
- full project regression после этого проверит весь продуктовый цикл более экономно: 85 results вместо 147 для полного Cartesian product.

## 2026-07-10: Final M5 Document And Full Project Regression

Контекст:

- после follow-up фиксов был запущен отдельный document-only regression по трём моделям;
- затем был запущен full project regression без полного Cartesian product;
- цель: подтвердить стабильность M5 перед переходом к `M5.9 Voice UI Bridge`.

Document-only regression:

- run id: `5023f3ef-e5c5-4298-a7c9-4b8ece6fe349`;
- сценарии: `16`;
- модели: `gemma4:12b`, `qwen3.5:9b`, `qwen3:14b`;
- total results: `48`;
- technical errors: `0`;
- marker failures: `0`;
- `gemma4:12b`: `16/16`, avg latency `12798 ms`;
- `qwen3.5:9b`: `16/16`, avg latency `10872 ms`;
- `qwen3:14b`: `16/16`, avg latency `11026 ms`.

Выбор document model:

- все три модели прошли document-only regression без quality failures;
- `qwen3.5:9b` выбран для document slice, потому что показал лучшую среднюю latency при равном качестве;
- `qwen3:14b` оказался близко по средней latency, но имел более высокий max latency (`22085 ms`).

Full project regression:

- core chat/context/access run id: `d3ac1bb1-89a9-4519-b028-3cebe521e04e`;
- summary/memory run id: `58e4bf90-55cd-484c-9863-6ce473c2d534`;
- documents run id: `2ecdcd0b-f505-4327-98cd-ee65fd0194a1`;
- total results: `85`;
- technical errors: `0`;
- marker failures: `0`;
- core chat/context/access: `54/54`;
- summary/memory on `qwen3.5:9b`: `15/15`;
- documents on `qwen3.5:9b`: `16/16`.

Вывод:

- M5 ingestion/retrieval слой стабилизирован на текущем уровне;
- подтверждены PDF, Excel, DOCX, image OCR, vision digest, embedded Office images, Excel charts, legacy `.xls`, anchored DOCX/XLSX images, scanned table baseline и `office_media_consistency`;
- `qwen3.5:9b` остаётся лучшим универсальным кандидатом для следующего этапа, потому что прошёл documents, summary/memory и core сценарии;
- можно переходить к обсуждению `M5.9 Voice UI Bridge`, оставив long multi-turn user journey отдельным будущим e2e regression layer.

## 2026-07-10: Roadmap Realignment After M5

Контекст:

- после final M5 regression стало понятно, что document/RAG слой достаточно стабилен для перехода к следующему крупному направлению;
- ближайший фокус смещён с voice/multi-agent experiments на backend hardening, LoRA Text-to-SQL и analytics UI;
- multi-agent, voice input, multi-collection retrieval и advanced model routing остаются future features.

Решение:

- перед M7/M8 добавить обязательный Backend Hardening Block;
- M7 определить как `LoRA Text-to-SQL Fine-Tuning`;
- M8 определить как `Analytics UI, Dashboards And Reports`;
- fine-tuning делать именно как LoRA/QLoRA прикладной Text-to-SQL кейс, а не как classifier/router baseline;
- baseline models для M7: `qwen3.5:9b`, `gemma4:12b`, `qwen2.5-coder:7b`, опционально `qwen2.5-coder:14b`;
- LoRA candidate: Qwen Coder 7B class model;
- основная метрика M7: не “модель красиво отвечает”, а SQL validity, execution success, schema adherence, read-only safety и latency.

Правила выполнения:

- каждый крупный stage завершается tests/smoke/regression по риску изменения;
- результаты тестирования фиксируются в журнале;
- после завершённого stage делается отдельный commit;
- если coder models показывают слабый baseline, модельная матрица может быть заменена на более сильные локальные модели по фактическим результатам;
- документация описывает только инженерные цели проекта и не привязывает roadmap к внешним причинам.

Вывод:

- новый порядок лучше соответствует текущей зрелости проекта: сначала укрепить backend, затем добавить измеримый LoRA fine-tuning кейс, после этого сделать аналитический UI/reporting layer;
- M5 остаётся закрытым стабильным фундаментом, а дальнейшая работа строится вокруг PostgreSQL analytics, safe SQL generation и воспроизводимых benchmarks.
