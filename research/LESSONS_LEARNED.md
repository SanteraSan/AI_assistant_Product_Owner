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
