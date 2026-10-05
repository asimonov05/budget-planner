# Приемка и тестирование

## Воспроизводимое окружение разработчика

Используйте uv, Python 3.13 и Node.js 22. Зависимости должны устанавливаться из репозиторных lock-файлов, а не обновляться попутно:

```bash
uv sync --locked --project backend
npm --prefix frontend ci
npm --prefix e2e ci
npx --prefix e2e playwright install chromium
```

`backend/pyproject.toml` описывает runtime- и dev-зависимости, а `backend/uv.lock` фиксирует весь граф. Frontend и E2E используют отдельные `package-lock.json`. В Dockerfile также закреплены версии uv, Python 3.13 и Node 22, но успешные локальные unit-тесты не заменяют сборку и smoke именно текущего образа.

Для локального запуска в актуальной конфигурации используйте `docker compose up -d --build`: отдельный migration job сначала поднимает PostgreSQL-схему, затем стартует API. Запуск API напрямую с локальным PostgreSQL требует `DATABASE_URL` и секрет роли. Исторический SQLite fallback и SQLite-fixtures остаются переходным долгом [TD-003](technical-debt.md), а не поддерживаемым production-режимом.

## Команды проверок

```bash
make lint             # Ruff + TypeScript strict
make test             # pytest + Vitest
make build            # production SPA + docker compose config
make test-e2e         # Playwright против уже запущенного BASE_URL
make smoke            # отдельный Compose project: build, wait, ready, down
make acceptance       # lint, unit/integration, build, Compose smoke и Playwright
```

`make smoke` и `make acceptance` используют Compose project `budget-planner-smoke` и порт `18080` по умолчанию; их можно изменить через `SMOKE_PROJECT` и `SMOKE_PORT`. Для этих команд требуются `.secrets/postgres-password`, `.secrets/postgres-runtime-password` и `.secrets/postgres-debug-admin-password`. Завершающий `down` не передает `-v`, поэтому named volumes сохраняются. Не направляйте smoke на production project и не удаляйте production volumes ради чистого теста.

Для проверки текущего дерева задайте отдельное имя Compose project и свободный
порт; `BASE_URL` браузерных тестов должен указывать именно на этот порт.
Фиксируйте результат migration job, `alembic_version`, ответ `ready`, число
`passed`/`skipped` в Playwright и факт использования кеша при сборке образа.
Повторный запуск с тем же именем проекта использует сохранённый тестовый том;
для проверки миграции с нуля создайте новое имя проекта. Не записывайте пароль
тестового владельца или токены в отчет и лог команд.

Playwright не создает владельца и не сбрасывает сервер. Гостевые сценарии login/360 px запускаются всегда. Для двух authenticated smoke-сценариев заранее создайте тестового владельца и передайте учетные данные только окружением:

```bash
BASE_URL=http://127.0.0.1:8082 \
E2E_USERNAME=owner \
E2E_PASSWORD='локальный тестовый пароль' \
npm --prefix e2e test
```

Без обеих переменных authenticated-сценарии будут помечены skipped; такой прогон нельзя записывать как полный live E2E.

Текущие результаты и границы доказательств записываются только в [acceptance-status.md](acceptance-status.md). Наличие сценария в этом документе само по себе не означает, что он выполнен.

## Уровни

- Unit/property: расчетное ядро, парсер денег, календарные правила, распределение копеек, `F=C-R`, нулевой итог переводов, double-counting и idempotency.
- Integration: текущий backend suite ещё использует SQLite fixture (TD-003). Дополнительно на disposable PostgreSQL проверены миграции `0007` и `0008`, RLS, составные FK, регистрация с отдельным бюджетом и авторизованный API/ZIP smoke. Physical backup/restore проверяется отдельно инфраструктурой PostgreSQL.
- Frontend: Vitest/Testing Library для loading/empty/error, форм, API-контракта, переводов, сверки плана с фактом, кредитных оплат, движений резерва цели, закрытия месяца и обмена данными.
- E2E: Playwright против production-style сервера для входа, основных переходов и ширины 360 px.
- Container: отдельный migration job, перенос owner из `budget_auth` в `budget`, RLS, `pg_dump`/`pg_restore` вне приложения, непривилегированный runtime, read-only root и persistence named volume.

## Правила фиксации результата

Ставить `[x]` можно только рядом с точной командой/именем теста и наблюдаемым результатом. `[~]` означает, что проверена лишь часть сценария; `[ ]` — что сценарий не проверен или не реализован. Ручная проверка фиксирует дату, платформу, commit/состояние дерева и шаги. Не переносите результат старого образа на текущий код или одной архитектуры на другую.

Отдельно различайте:

- unit/integration ZIP round-trip и отдельный инфраструктурный PostgreSQL restore-drill;
- прохождение `docker compose config` и реальную сборку/запуск текущего образа;
- Playwright с skipped authenticated-тестами и полный прогон с учетными данными;
- разовый замер производительности и воспроизводимый benchmark с fixture и сохраненным протоколом.

## Производительность

Целевой benchmark использует 100 000 фактических операций и окно 24 месяца. После прогрева нужно сохранить генератор fixture, точную команду/запрос, число повторов, p50/p95, RSS, CPU, Python/SQLite или digest образа и характеристики лимита 2 vCPU / 2 GiB. Цель p95 обзора — менее 1 секунды.

В репозитории есть воспроизводимый синтетический fixture. Два локальных прогона 21 сентября 2026 года после одного прогрева и 20 замеров дали p50 `0,0598–0,0617 с` и p95 `0,0649–0,0675 с`:

```bash
uv run --locked --project backend --directory backend python scripts/benchmark_forecast.py
```

Скрипт каждый раз создает временную файловую SQLite, один счет, 100 000 расходных операций, считает окно 24 месяца и печатает параметры и результат. Это подтверждает время расчетного ядра на машине прогона, но еще не полностью закрывает production-критерий: RSS, CPU/модель машины, digest образа и отдельный запуск с лимитом 2 vCPU / 2 GiB не зафиксированы.

## Известные пробелы приемки

Актуальные результаты и границы проверки перечислены в
[acceptance-status.md](acceptance-status.md); ниже в том же файле сохранён
отдельно помеченный архив прежнего runtime. Не переносите его выводы на
текущую PostgreSQL установку.

До полной приемки остаются PostgreSQL integration suite для RLS и upgrade с
историческими данными, более глубокие browser-сценарии финансовых операций и
импорта, а также отдельные multi-arch и container benchmark прогоны с
зафиксированными RSS/CPU. Успешный Compose `ready` и четыре browser smoke-теста
не закрывают эти сценарии.
