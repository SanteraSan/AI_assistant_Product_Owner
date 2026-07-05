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
