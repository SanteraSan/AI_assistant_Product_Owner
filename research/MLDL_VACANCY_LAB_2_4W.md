# Lab 2–4 недели: OCR vs VLM, агенты, инференс

Цель: закрыть разговор на вакансии ML/DL (OCR vs end-to-end VLM, оценка агентов, локальный LoRA, latency/VRAM), **не** превратить TaskFlow в прод-тренер и не повторять Text-to-SQL V5.

Ограничения:

- коммерция параллельно: ориентир **8–12 часов в неделю**;
- GPU: RTX 5070 Ti 16 GB — 7B QLoRA уже доказан, VLM 7B может не влезть, начинать с 3B;
- прод-путь ingestion не ломать: Tesseract + grid остаётся default, новое — spike/optional;
- каждый эксперимент: фикстура → прогон → метрика → запись в `LESSONS_LEARNED.md`.

Не делать за этот срок: OpenCV-детекция с нуля, TensorRT, ASR/TTS, DDP, LangChain-перепись агента, новый pet-репозиторий.

---

## Что уже есть — не переделывать

| Слой | Статус | Зачем помнить |
| --- | --- | --- |
| Tesseract OCR | M5.6.1 / Test 32 | классический baseline |
| Scanned table grid | M5.8.2 | `scanned-table-products.png` |
| PaddleOCR PP-Structure | M5.8.3 spike | JSON в `research/m583_paddleocr_structure_spike_latest.json` |
| Vision digest | `gemma4:12b`, Test 33 | caption, не field extraction |
| QLoRA Text-to-SQL V5 | 400 steps, holdout 30/30 | якорь «умею учить», новый цикл не сюда |
| LangGraph lab | E6 closed | default остаётся handwritten |

---

## Два горизонта

**2 недели (обязательный каркас):** сравнение OCR vs VLM на золотом наборе + оценка агента (retry/цикл) + цифры инференса. Этого достаточно, чтобы честно говорить по второму направлению вакансии и по пункту «сравнивать пайплайны».

**4 недели (если есть время):** маленький SFT/LoRA на поля документа **или** QLoRA маленькой VLM + optional evidence layer в RAG. Без этого вакансия всё равно stretch, но появляется «я дообучал под домен».

---

## Неделя 1. Bake-off: классический OCR vs VLM

Вакансия почти дословно: качество, стоимость инференса, latency.

### 1.1 Золотой набор полей (4–6 ч)

Не больше **8 картинок**. Новые файлы — только если дыра в типах, не коллекция с интернета.

| Файл | Зачем | Тип ошибки, которую ловим |
| --- | --- | --- |
| `data/raw/docx_fixtures/just_text.png` | чистый текст | OCR должен выигрывать |
| `data/raw/docx_fixtures/tablet.png` | таблица/КП | поля цена / позиция |
| `data/raw/scanned_fixtures/scanned-table-products.png` | скан таблицы | layout + «грязные» цифры (з5оо vs 3500) |
| `data/raw/docx_fixtures/image.png` | фото с надписью | OCR vs vision |
| `data/raw/docx_fixtures/charts.png` | график | OCR должен проиграть |
| `data/raw/docx_fixtures/zabbix.jpg` | мониторинг-скрин | то же |
| `data/raw/uploads/.../таблица в картинке.png` | ещё одна таблица-картинка | повтор класса |
| опционально 1 «грязное» фото с телефона | domain shift | не идеальный скан |

Артефакт: `data/eval/ocr_vlm_gold/manifest.jsonl`

На каждую картинку:

- `image_id`, путь;
- `gold_text` (если есть связный текст);
- `gold_fields`: 3–8 слотов (`title`, `price`, `qty`, `label_ufa`…);
- `must_not`: то, чего модель любит додумать;
- `expected_winner`: `ocr` / `vlm` / `tie` — гипотеза до прогона.

Нормализация чисел как в RAG-eval: `з5оо` / `3 500` / `3500` → одно значение.

DoD: манифест в git, картинки уже в репо не дублировать.

### 1.2 Четыре раннера, один протокол (6–8 ч)

Один скрипт, четыре backend-а. Не четыре ноутбука.

Предлагаемый путь: `backend/scripts/eval_ocr_vlm_bakeoff.py`

| ID | Движок | Откуда брать |
| --- | --- | --- |
| `tesseract` | текущий image OCR loader | `document_loader` |
| `paddle_structure` | spike M5.8.3 | отдельный 3.11 venv, как сейчас |
| `vlm_ollama` | `gemma4:12b` | тот же вызов, что vision digest, но **JSON-поля**, не 3–8 предложений |
| `vlm_hf` | Qwen2.5-VL-3B Instruct (HF) | `.venv-lora` / отдельный venv; если OOM — остановить и записать finding |

Промпт VLM один на всех:

```text
Извлеки только видимые поля. Ответ — JSON.
Если поля нет на картинке — null, не угадывай.
```

Метрики на картинку и сводка:

- `field_exact` / `field_numeric_normalized`;
- `hallucinated_fields` (заполнил `must_not` или не-null там, где gold=null);
- latency p50 (wall clock);
- VRAM peak (`nvidia-smi`, как в LoRA eval);
- грубая «стоимость»: секунды GPU × 1, без выдуманных облачных цен.

Артефакт: `research/ocr_vlm_bakeoff_latest.json` + таблица в `research/OCR_VLM_BAKEOFF.md`

DoD:

- все 8 картинок прогнаны хотя бы на `tesseract` + `vlm_ollama`;
- PaddleOCR — если venv жив, иначе `missing_dependency` как в M5.8.3, не блокирует неделю;
- в выводе есть **когда какой пайплайн брать**, не «VLM круче».

Гипотеза, которую стоит проверить, а не утверждать заранее: на `just_text` и линейных таблицах OCR дешевле и точнее; на графиках и фото — VLM; на `scanned-table-products` PaddleOCR богаче layout, но поля цены может врать так же, как Tesseract.

---

## Неделя 2. Агенты + инференс

### 2.1 Надёжность агента, не новый фреймворк (6–8 ч)

Вакансия: retry, зацикливание, деградация, LLM-as-a-judge, regression-наборы.

Default **не** переключать на LangGraph. Добавить поведение в orchestrator (и зеркально в adapter, если дешево).

Сценарии — маленький JSON, по образцу `research/e6_handwritten_vs_langgraph_smoke.json`:

| ID | Что ломаем | Ожидание |
| --- | --- | --- |
| `tool_error_retry` | rag_search / SQL один раз 500, второй ok | повтор tool, не выдуманный ответ |
| `rbac_no_retry` | viewer + SQL | deny, **без** retry (retry только на infra, не на ACL) |
| `loop_same_tool` | модель зовёт `list_buckets` трижды | стоп по одинаковому tool+args, в trace `loop_break` |
| `max_steps_degrade` | вопрос, который требует 6 tools | на шаге 4 честный «не успел», не галлюцинация |
| `vision_then_rag` | цвет на картинке + факт из bucket | `analyze_image` затем `rag_search`, evidence не из memory |
| `judge_grounded` | ответ с фактом вне tool results | judge / marker: fail |

Реализация минимальная:

- retry: 1 повтор на `status=error` (сеть/500), не на `denied`;
- loop: fingerprint `(name, canonical_args)` → break;
- judge: сначала **детерминированные** проверки (tool sequence, denied, empty sources). LLM-as-a-judge — второй слой на 3 сценариях, отдельный промпт в `research/prompts/`, не в продуктовый system prompt.

Скрипт: `backend/scripts/eval_agent_reliability.py`  
Модель: `qwen3.5:9b`  
Артефакт: `research/agent_reliability_latest.jsonl`

DoD: 6 сценариев зелёные или с честным fail + записью, почему; unit-тесты на retry/loop без Ollama.

### 2.2 Инференс с цифрами (3–5 ч)

Не внедрять vLLM в `/chat`. Боковой бенч.

Один и тот же промпт (~256 in / 128 out), n=20:

| Runtime | Модель | Зачем |
| --- | --- | --- |
| Ollama (как в продукте) | `qwen2.5:7b` или coder 7b, что уже локально | baseline продукта |
| llama.cpp | тот же вес/квант, если есть GGUF | путь из `package_text_to_sql_lora_ollama.py` |
| vLLM **или** HF+transformers 4-bit | если vLLM встанет на драйвер за <2 ч; иначе skip + finding | вакансия просит vLLM, но совместимость 5070 Ti не обещать |

Снять: tokens/s, latency p50/p95, VRAM, batch=1. Batch>1 — только если runtime это умеет без войны с Ollama за GPU: **не гонять оба сервера сразу**.

Артефакт: `research/INFERENCE_RUNTIME_BENCH.md`

DoD: таблица из ≥2 рантаймов **или** один рантайм + documented blocker (драйвер, VRAM, конфликт с Ollama).

W&B/MLflow на этом шаге не обязательны.

---

## Неделя 3 (stretch). Дообучение под поля, не новый SQL

V5 Text-to-SQL закрыт. Новый цикл — **structured extraction / антигаллюцинации в полях**.

### 3.1 Сначала без картинок: SFT на JSON с OCR-шумом (8–10 ч)

Датасет ~80–150 примеров, intent-split как в SQL V2:

- input: сырой OCR (включая реальные ошибки Tesseract с недели 1);
- output: JSON полей + `null`;
- негативы: пустые поля, чужой документ, must_not.

База: `Qwen2.5-3B-Instruct` или 7B, если 3B слабовато. Контур тот же: `transformers` + PEFT + QLoRA, `.venv-lora`.

Сравнить **два instruction format** (это пункт вакансии):

- A: «верни JSON»;
- B: «сначала список видимых строк, потом JSON» (меньше выдуманных полей — гипотеза).

Метрики: `field_exact`, `hallucinated_fields`, latency. Training loss не считать победой.

Артефакт: `data/field_extract/v1/` + `research/FIELD_EXTRACT_LORA.md`

DoD: baseline (base model) vs LoRA на holdout; если LoRA не бьёт галлюцинации — это тоже результат.

### 3.2 Только если 3.1 зелёный и VRAM есть: VLM QLoRA (остаток недели)

`Qwen2.5-VL-3B` QLoRA на 5–8 картинок gold + аугментации (jpeg q=40, поворот 2–3°, downscale). Не InternVL-14B.

Если OOM / нет диска — compatibility finding, не геройство.

W&B: один run на этот тренинг, если аккаунт уже есть. Иначе CSV как в текущих `*.memory.json`.

---

## Неделя 4 (stretch). Вшить победителя в TaskFlow и упаковать рассказ

### 4.1 Optional evidence layer (6–8 ч)

Не заменять Tesseract.

- новый `source_type`, например `vlm_fields` **или** нормализованный `paddle_structure` — **только тот движок, который выиграл bake-off на таблицах**;
- те же `tenant_id` / `bucket_id` / `document_id` / `source_path`;
- поля в `document_metadata`, не сырой HTML PaddleOCR в промпт (правило M5.8.3);
- flag в config, default **off**.

Один RAG-сценарий в checklist: вопрос про цену с `tablet.png` / scanned table, expected source_type победителя.

DoD: unit-тест нормализации + 1 eval scenario на `qwen3.5:9b`.

### 4.2 Портфолио (2–3 ч)

Обновить:

- `research/LESSONS_LEARNED.md` — одна запись на эксперимент, не простыня;
- `research/RAG_EVALUATION_CHECKLIST.md` — только если появился scenario;
- `README.md` — 5–7 строк: bake-off, агент retry/loop, инференс-таблица, LoRA полей если было;
- `.local-portfolio/hh-resume-llm.md` и cover letter — цифры из JSON, не «изучал VLM».

---

## Календарь

При 10 ч/неделю:

| Неделя | Фокус | Часы | Обязательно для вакансии |
| --- | --- | --- | --- |
| 1 | gold + bake-off | 10–14 | да |
| 2 | agent reliability + inference bench | 9–13 | да |
| 3 | field-extract LoRA | 8–12 | желательно |
| 4 | optional layer + текст резюме | 8–11 | если 1–3 закрыты |

Если времени на 2 недели: **только 1 и 2**. Неделя 3 без bake-off бесполезна: неясно, на каких ошибках учить.

Порядок внутри недели 2: сначала агент (это ваш сильный слой), инференс — вечером, когда Ollama можно остановить.

---

## Критерии «можно говорить на собесесе»

Минимум:

1. Таблица OCR vs VLM: качество / latency / VRAM и правило выбора пайплайна.
2. Агент: retry ≠ обход ACL; как ловите цикл; чем judge отличается от marker groups.
3. LoRA: V5 SQL как прошлый цикл + (если успели) поля документа; truncation, 4-bit, почему метрика не loss.
4. Инференс: Ollama vs llama.cpp/vLLM, хотя бы batch=1.

Ещё не говорить:

- «дообучал InternVL/Donut в проде»;
- «выкатил TensorRT»;
- «3 года CV».

---

## Файлы, которые появятся

```text
data/eval/ocr_vlm_gold/manifest.jsonl
backend/scripts/eval_ocr_vlm_bakeoff.py
backend/scripts/eval_agent_reliability.py
research/OCR_VLM_BAKEOFF.md
research/ocr_vlm_bakeoff_latest.json
research/agent_reliability_latest.jsonl
research/INFERENCE_RUNTIME_BENCH.md
data/field_extract/v1/          # только неделя 3
research/FIELD_EXTRACT_LORA.md  # только неделя 3
```

Адаптеры по-прежнему в `models/` (gitignore), в git — скрипты, датасеты, отчёты.
