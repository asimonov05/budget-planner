# Статус приемки

## Существующий бюджет в локальном супераппе: 2026-10-06

Рабочее дерево поверх commit `2e7143c37ddc6e217aa6fc8a7d9db5e59ecc510b`
остаётся незакоммиченным; исходные version-изменения сохранены. Изменён
Compose в соседнем каталоге `cap`: суперапп теперь подключает `budget-app` к
действующей сети `budget-planner_default` и базе `budget`, схема которой уже
на ревизии `0012`. Саму базу и старый сервис не переносили и не перезаписывали.
Среда: macOS arm64, Python 3.13.13, Docker 29.4.3/29.2.1, Compose 5.1.3.

| Проверка | Действие | Результат | Ограничение |
|---|---|---|---|
| Резервная копия | `docker compose exec -T postgres pg_dump -U budget -d budget -Fc --no-owner --no-acl` и `pg_restore --list` | [x] Дамп сохранён вне репозитория с правами `0600`; список объектов читается | Пробное восстановление в этом прогоне не выполнялось |
| Совместимость runtime | Контейнер с текущим образом вызвал `verify_database()` через `budget_runtime` в сети `budget-planner_default` | [x] Ревизия схемы и права runtime роли подтверждены до переключения | Не проверяет пароль пользователя |
| API и навигация | `docker compose up -d --build --force-recreate --remove-orphans --wait`; `node superapp/browser-smoke.mjs` | [~] Старый и новый адреса budget ready, photo health — 200; гостевой браузерный маршрут и 360 px прошли | Авторизованный browser flow требует учётных данных |

Для photo-access создан новый пустой локальный PostgreSQL том, чтобы ID
тестовых пользователей из временной базы бюджета не совпали с ID существующих
пользователей. Старые тестовые тома и их дампы сохранены; пользовательская VM
не затрагивалась.

## Возврат в photo-access после общего входа: 2026-10-06

Поверх commit `2e7143c37ddc6e217aa6fc8a7d9db5e59ecc510b` проверено
незакоммиченное дерево: ранее изменённые version-файлы сохранены; к изменённым
файлам супераппа добавлены `frontend/src/pages/Login.tsx`, `Register.tsx`,
`components/AuthIntro.tsx`, `lib/authRedirect.ts` и его тест. Среда та же, что
в разделе ниже: macOS arm64, Python 3.13.13, Node.js 26.4.0, npm 12.1.0,
Docker 29.4.3/29.2.1 и Compose 5.1.3.

| Уровень | Команда / действие | Результат | Граница доказательства |
|---|---|---|---|
| Маршрут входа | `npm --prefix frontend test -- src/lib/authRedirect.test.ts` | [x] 2 passed: путь в photo-access сохранён, внешний адрес отклонён | Unit-тест не запускает браузер |
| Repository gates и изолированный Compose | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-superapp-photo-return-20261006 SMOKE_PORT=18087 make acceptance` | [~] Ruff clean; 127 backend и 83 frontend теста прошли; сборка, миграция и ready прошли; 2 гостевых browser smoke passed, 2 authenticated skipped | Тестовый владелец не создаётся в изолированном проекте; временный `curl` shim описан ниже. Контейнеры остановлены без `-v` |
| Локальный суперапп | `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --build --force-recreate --wait`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Гость нажал photo-access, перешёл между входом и регистрацией с сохранённым адресом, вошёл и попал в photo-access; новая регистрация также вернула в photo-access. Проверены бюджет, выход и ширина 360 px | Использованы отдельные локальные PostgreSQL тома и тестовые аккаунты; VM не затрагивалась |


## Локальный суперапп: 2026-10-06

Проверено дерево поверх commit `2e7143c37ddc6e217aa6fc8a7d9db5e59ecc510b`
с незакоммиченными изменениями. До этой работы уже были изменены файлы версии
(`backend/app/__init__.py`, `backend/pyproject.toml`, `backend/uv.lock`,
`frontend/package.json`, `frontend/package-lock.json`) и этот журнал; они не
сбрасывались. Текущая работа добавила `Dockerfile`, `frontend/vite.config.ts`,
`frontend/src/main.tsx`, `frontend/src/components/Layout.tsx` и
`frontend/src/vite-env.d.ts`; интеграционный Compose и photo-access находятся в
соседних каталогах. Среда: macOS arm64, Python 3.13.13, Node.js 26.4.0,
npm 12.1.0, Docker 29.4.3/29.2.1, Compose 5.1.3. Локальный Node не является
рекомендуемой версией 22.

| Уровень | Команда / действие | Результат | Граница доказательства |
|---|---|---|---|
| Repository gates | `make lint`, `make test`, `make build` | [x] Ruff clean; 127 backend и 81 frontend тест прошли; production SPA и Compose config прошли | Backend suite использует SQLite fixture; Vite предупредил о чанке 1,057.35 kB |
| Изолированная приемка бюджета | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-superapp-acceptance-20261006 SMOKE_PORT=18086 make acceptance` | [~] Свежие PostgreSQL и migration job запустились, ready ответил; 2 гостевых browser smoke passed, 2 authenticated skipped | `curl` отсутствует в окружении, поэтому временный `/private/tmp/cap-bin/curl` делал эквивалентный HTTP GET через Python. В изолированном проекте владелец не создавался; контейнеры остановлены без `-v` |
| Интеграция супераппа | Из корня `cap`: `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --build --wait`; `python3 superapp/smoke.py` | [x] Оба приложения и PostgreSQL healthy; две новые учётные записи, отдельные корни, создание папки, CSRF 403, выход 401 | Использован отдельный локальный Compose проект `cap-superapp` и отдельные тома; VM не затрагивалась |
| Browser flow супераппа | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Главная, вход владельца, бюджет, возврат на главную, photo-access, выход и ширина 360 px прошли | Chromium запускался вне macOS sandbox из-за отказа MachPort; снимки главной и photo-access просмотрены. Скрипт не проверяет глубокие финансовые операции |


## Release candidate `0.1.2`: 2026-10-05

Проверено дерево поверх commit `2e7143c37ddc6e217aa6fc8a7d9db5e59ecc510b`
(`Фикс фронта и импорта`) с единственным version-патчем: изменены
`backend/app/__init__.py`, `backend/pyproject.toml`, `backend/uv.lock`,
`frontend/package.json` и `frontend/package-lock.json`. Среда: macOS `arm64`,
Python `3.13.13`, Node.js `26.4.0`, npm `12.1.0`, Docker `29.4.3`, Docker
Compose `5.1.3`. Локальные frontend-команды выполнялись на Node.js 26, а не
на поддерживаемом Node.js 22.

| Уровень | Команда / действие | Результат | Граница доказательства |
|---|---|---|---|
| Activity API | `backend/.venv/bin/python -m pytest backend/tests/test_activity.py -q` | [x] 3 passed | SQLite fixture проверяет pagination, поиск, суммы по дням, 401 и второго пользователя; не заменяет PostgreSQL RLS |
| Activity UI | `npm --prefix frontend test -- Resources.test.tsx components/Layout.test.tsx` | [x] 2 файла, 27 tests passed | Fetch/API подменены |
| Repository gates | `make lint`, `make test`, `make build` | [x] Ruff clean; 127 backend passed с одним сторонним `DeprecationWarning`; 17 frontend files / 81 tests passed; production SPA (2306 modules) и `docker compose config --quiet` прошли | Vite предупредил о JS chunk `1,056.77 kB` при пороге `500 kB` |
| Fresh PostgreSQL/Compose | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-planner-release-012b SMOKE_PORT=18084 make acceptance` | [x] Сборка, новая PostgreSQL БД, migration job и ready прошли | Проверен fresh install; upgrade с историческими данными не проверен |
| Browser smoke | Та же `make acceptance` команда | [~] 2 passed, 2 skipped | Гостевой redirect и login на 360 px прошли. Авторизованные сценарии skipped: disposable контур не создаёт владельца автоматически |
| Live PostgreSQL activity smoke | Отдельный disposable проект `budget-planner-release-012c` на `18085`: две test-учётные записи, login, accounts, transaction, transfer, `GET /api/v1/activity` | [x] Owner увидел расход `1234` и перевод в одной дневной группе; Alice увидела только свою запись; запрос без сессии вернул 401 | Реальная PostgreSQL runtime-роль; не заменяет полный RLS integration suite |

Первый `make acceptance` для `budget-planner-release-012` дошёл до healthy
Compose, но остановился до browser smoke из-за отсутствующего Chromium. После
установки тестового runtime в `/private/tmp/budget-planner-playwright-012`
повторный независимый прогон `budget-planner-release-012b` завершился успешно.
Все disposable контейнеры остановлены без `-v`; пользовательская VM и её база
не использовались.

## Актуальный отчет: 2026-10-05

Проверено рабочее дерево поверх commit `4805205` с незакоммиченными изменениями,
включая новые файлы. Это снимок состояния на момент команд, а не результат
проверки одного неизменного commit или опубликованного образа. Локальная среда:
macOS `arm64`, Python `3.13.13`, Node.js `26.4.0`, npm `12.1.0`. Описанный в
[процедуре](acceptance.md) поддерживаемый Node.js 22 для локальных frontend
команд в этом прогоне не использовался.

Обозначения: `[x]` проверка выполнена на указанном уровне, `[~]` выполнена
частично, `[ ]` не выполнена. Успешный тест с подменённым API или SQLite не
является доказательством работы того же сценария в браузере с PostgreSQL.

Итог: все выполненные автоматические проверки прошли (127 backend-тестов,
81 frontend-тест, 4 browser smoke-сценария); свежая PostgreSQL схема дошла до
`0012`, а выборочный live API smoke прошёл. Полная приемка всех финансовых
сценариев и PostgreSQL-изоляции пока не подтверждена.

### Выполненные проверки

| Уровень | Команда / действие (секреты скрыты) | Результат | Граница доказательства |
|---|---|---|---|
| Backend suite | `backend/.venv/bin/python -m pytest backend/tests -q` | [x] 127 тестов прошли; одно стороннее `DeprecationWarning` из Starlette/anyio | `backend/tests/conftest.py` задаёт SQLite-файл и создаёт схему через SQLAlchemy; тесты не проверяют PostgreSQL RLS |
| Backend static | `backend/.venv/bin/python -m ruff check backend/app backend/tests backend/alembic backend/scripts` | [x] `All checks passed!` | Проверка стиля и статических правил, без выполнения API |
| Frontend unit | из `frontend/`: `npm test` | [x] 17 файлов, 81 тест прошёл | Fetch/API подменены; реальная БД не участвует |
| Frontend types | из `frontend/`: `npm run typecheck`; `npm run lint` | [x] оба exit 0 | `lint` сейчас повторяет `tsc -b --pretty false`, отдельного ESLint нет |
| Frontend production bundle | из `frontend/`: `npx vite build --outDir /private/tmp/budget-planner-frontend-audit-build-20261005` после проверки типов | [x] 2306 модулей, сборка прошла | Vite предупредил об основном JS чанке `1,056.77 kB` при пороге `500 kB`; сборка выполнена на Node 26 |
| E2E types | `npm --prefix e2e run typecheck` | [x] exit 0 | Не запускает браузер |
| Compose config | `docker compose config --quiet` | [x] exit 0 | Проверяет конфигурацию, но не запускает контейнеры |
| PostgreSQL/Compose | `BIND_HOST=127.0.0.1 APP_PORT=18082 TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=e2e-audit docker compose -p budget-planner-e2e-audit up -d --build --wait` | [x] PostgreSQL и app healthy, migration job exit 0, `alembic_version=0012`, ready и `/login` → 200, неизвестный API route → JSON 404 | BuildKit использовал кэш слоёв; проверен запуск новой БД, но не upgrade `0011→0012` с историческими данными |
| Browser smoke | С заданными через окружение `E2E_USERNAME`/`E2E_PASSWORD`: `BASE_URL=http://127.0.0.1:18082 PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-browsers npm --prefix e2e test -- --output=/private/tmp/budget-planner-e2e-audit-full-unsandboxed` | [x] 4 passed, 0 skipped | Гостевой вход, ширина 360 px, вход владельца, годовой план и мобильная навигация. Chromium потребовал запуска вне macOS sandbox из-за отказа MachPort; пароль в отчет не записан |
| Live API smoke | В том же тестовом Compose-проекте: login; `POST /api/v1/accounts`; `POST /api/v1/transactions`; `GET /api/v1/activity?search=Smoke`; `GET /api/v1/transactions/suggestions?query=Sm&type=expense&account_id=…` | [x] 200/201; одна расходная запись, дневной итог `1234` minor units, подсказка нашла её | Реальный PostgreSQL и тестовый владелец; остальные финансовые пути не затронуты |

После проверки выполнено `docker compose -p budget-planner-e2e-audit down` без
`-v`: контейнеры остановлены, отдельный тестовый том сохранён по правилам
[процедуры](acceptance.md). Существующая пользовательская база не изменялась.
Первый запуск Chromium внутри macOS sandbox завершился до выполнения тестов
из-за `MachPort Permission denied`; повторный запуск вне sandbox выполнил все
четыре сценария успешно.

### Проверенный функционал и пределы

| Область | Статус | Текущее доказательство и недостающая проверка |
|---|:---:|---|
| Вход, регистрация, роли, CSRF, изоляция пользователей | [~] | Прошли `test_api.py`, `test_registration.py`, `test_admin_auth.py`, `test_shared_budgets.py` и `App.test.tsx`; авторизованный вход прошёл на изолированном Compose. Backend suite работает на SQLite fixture; RLS и права PostgreSQL для нескольких владельцев в этом прогоне отдельно не проверялись. |
| Счета, факты, переводы, валюты, лента и подсказки похожих операций | [~] | Прошли `test_account_balances.py`, `test_multicurrency.py`, `test_activity.py`, `test_transaction_suggestions.py`, `Accounts.test.tsx` и `Resources.test.tsx`. Live API на PostgreSQL создал счёт/расход и прочитал ленту/подсказку. Переводы, валютные покупки и полный браузерный путь создания операций на PostgreSQL ещё не проверены. |
| План, прогноз, календарь, аналитика, цели, кредиты и зарплата | [~] | Прошли расчетные/property/API-тесты (`test_calculations.py`, `test_properties.py`, `test_loan_features.py`, `test_salary_api.py` и смежные) и UI-тесты `Plan`, `Dashboard`, `Calendar`, `Analytics`, `Goals`, `Resources`. Сквозной браузерный прогноз с реальной базой и промежуточные платежи цели не проверены. |
| CSV и ZIP импорт/экспорт | [~] | `test_csv_operations_transfers.py` проверяет импорт переводов, валютные покупки, preview ошибок, повтор и откат при закрытии месяца; `test_api.py` содержит ZIP round-trip. `Exchange.test.tsx` проверяет UI формата и подтверждения. Банковский PDF в этом прогоне не обрабатывался; полный импорт через браузер и PostgreSQL не проверен. |
| Уведомления и release notes | [~] | `test_notifications.py`, `Notifications.test.tsx` и `Layout.test.tsx` покрывают приватность, черновик/однократную публикацию, краткий анонс, прочтение и переход к полной заметке. Проверка API использует SQLite, UI — подменённый API; публикация через браузер на PostgreSQL не проверена. |
| Миграции и схема данных | [~] | `test_migrations.py` и `test_database_schema_diagram.py` прошли; миграция свежей PostgreSQL базы достигла `0012`. Upgrade с историческими данными, отдельная проверка RLS и визуальный осмотр Excalidraw в этом прогоне не выполнялись. |
| Настройки, темы и меню | [~] | `Settings.test.tsx`, `theme.test.tsx`, `Layout.test.tsx` проверяют настройку/сохранение предпочтений и доступность скрытых пунктов. Визуальная проверка текущей сборки на нескольких размерах экрана не выполнялась. |
| Резервное копирование и производительность | [ ] | В текущем прогоне не выполнялись внешний `pg_dump`/`pg_restore`, проверка восстановления и benchmark под контейнерными лимитами; прежние измерения находятся только в архиве ниже. |

Проверенные ограничения реализации: CSV-перевод не имеет устойчивого внешнего
ID между разными batch ([TD-008](technical-debt.md)); мультивалютные цели,
кредиты, лимиты и зарплата пока ограничены основной валютой бюджета
([TD-007](technical-debt.md)). Это ограничения текущего функционала, а не
падения тестов.

### Что делать перед следующей приемкой

1. Добавить воспроизводимый PostgreSQL integration suite: RLS, чужой `user_id`,
   ограничения и upgrade `0011→0012` с данными. Свежая схема до `0012` и
   несколько API-запросов на PostgreSQL уже проверены выше.
2. Дополнить четыре пройденных browser smoke-сценария сквозными тестами
   перевода, CSV preview/confirm и публикации release note.
3. Повторить frontend-сборку на поддерживаемом Node.js 22 и оценить
   предупреждение о размере чанка, если оно влияет на загрузку интерфейса.

Процедура и правило записи доказательств находятся в [acceptance.md](acceptance.md),
инструкции для будущих агентов — в [AGENTS.md](../AGENTS.md). Известный переход
backend-тестов с SQLite на PostgreSQL отслеживает [TD-003](technical-debt.md).

## Архив: приемка прежнего SQLite-развёртывания (сентябрь 2026)

Ниже сохранены исторические результаты и ограничения старого runtime. Они не
описывают автоматически состояние текущей PostgreSQL установки: например,
импорт CSV-переводов уже реализован и проверен в актуальном отчете выше, а
application-managed физический backup удалён.

Легенда: `[x]` подтверждено; `[~]` подтверждена только часть; `[ ]` не подтверждено. Доказательство относится к текущему рабочему дереву только там, где указана свежая команда; старый образ не считается доказательством для нового кода.

## Последние локальные прогоны

- Backend, 2026-09-28, Python 3.13.13: `.venv/bin/python -m pytest backend/tests -q` — 52 passed (43 прежних + 9 CRUD/dependency tests); одно стороннее `DeprecationWarning` из Starlette/anyio.
- Frontend, 2026-09-28, Node 26.4.0: `npm --prefix frontend test` — 9 files, 45 tests passed. `npm --prefix frontend run lint` и `npm --prefix frontend run build` — exit 0; Vite оставил предупреждение о JS chunk 930,40 kB. Поддерживаемый bootstrap использует Node 22; отдельный прогон именно на Node 22 еще не зафиксирован.
- Theme visual smoke, 2026-09-28: системный Google Chrome через Playwright отрисовал светлую и тёмную настройки на 1365 px, тёмные настройки и вход на 390 px, тёмные dashboard и analytics с графиками, все три дополнительные тёмные цветовые схемы и светлый «Океан» на 390 px. API для этого визуального smoke был перехвачен детерминированными fixtures; это не новый live backend E2E.
- Live E2E, 2026-09-21: `npm --prefix e2e run typecheck` прошел; свежая Alembic-БД, реальный Uvicorn с собранной static SPA на `127.0.0.1:18081`, системный Chrome и заданные test-owner credentials — 4 Playwright tests passed. Проверены гостевой redirect/login, 360 px login, реальный вход/переход в годовой план и authenticated mobile navigation 360 px. Ready и SPA вернули 200; неизвестный API route вернул JSON 404.
- Compose config, 2026-09-21: `docker compose config --quiet` — exit 0.
- Container drill, 2026-09-21, `linux/arm64`: финальные backend/static слои наложены на ранее полностью собранный runtime-образ; Compose `init-admin`, ready, авторизованное создание счёта, `force-recreate`, backup и restore прошли. После restore старая сессия получила 401, а состояние счёта восстановилось. Runtime: UID/GID 10001, SQLite 3.53.4, read-only root, `cap_drop=ALL`, `no-new-privileges`; `/data` и `/backups` доступны для записи, а `/app` — нет.
- Performance, 2026-09-21: два запуска `PYTHONPATH=backend .venv/bin/python backend/scripts/benchmark_forecast.py` — 100 000 операций, 24 месяца, по 20 теплых замеров; p50 `0,0598–0,0617 с`, p95 `0,0649–0,0675 с`.

Чистая повторная multi-stage сборка именно последнего дерева заблокирована локальным DNS Docker Hub. Поэтому container drill использовал ранее полностью собранный runtime/dependencies с локальным слоем финального кода и SPA. Это доказывает runtime-поведение текущего кода, но не заменяет чистую сборку `Dockerfile`.

## Функциональные сценарии

| № | Сценарий и ожидаемый результат | Статус | Доказательство |
|---:|---|:---:|---|
| 1 | Зарплата 120 000 ежемесячно + подработка 25 000 только в ноябре → 120/145/120 тыс. | [x] | `test_salary_once_override_zero_and_inherit` |
| 2 | Override зарплаты ноября `0`, подработка остается → ноябрь 25 000, соседи не меняются | [x] | `test_salary_once_override_zero_and_inherit` |
| 3 | Удаление override через inherit/null возвращает базовую зарплату | [x] | `test_salary_once_override_zero_and_inherit` |
| 4 | Части зарплаты 50 000 + 70 000 дают 120 000, не 240 000 | [x] | `test_split_salary_and_end_date` |
| 5 | Кредит 20 000 до марта включительно отсутствует с апреля | [x] | `test_split_salary_and_end_date` |
| 6 | План кредита 20 000 + связанный факт 20 000 дают прогноз 20 000 | [x] | `test_fully_matched_plan_and_fact_are_counted_once` |
| 7 | План 20 000 + частичный факт 12 000 → остаток 8 000, прогноз 20 000 | [x] | `test_matching_partial_and_complete_no_double_count`, `test_loan_payments_are_atomic_idempotent_and_not_double_counted` |
| 8 | План 20 000 + факт 18 000 «исполнено» → остаток 0, исходный план сохранен | [x] | `test_matching_partial_and_complete_no_double_count`; дополнительно кредитный API-тест подтверждает completed-under-plan = 18 000 |
| 9 | Лимит Авто 15 000 и платеж внутри 8 000 → прогноз 15 000, U=7 000 | [x] | `test_category_limit_inside_not_added_twice` |
| 10 | Лимит 15 000, факт 9 000, ожидается 8 000 → прогноз 17 000, превышение 2 000 | [x] | `test_category_limit_inside_not_added_twice` |
| 11 | C=200 000, резерв отпуска 30 000 → R=30 000, F=170 000 | [x] | `test_initial_goal_reserve_does_not_exist_before_accounting_start` явно проверяет 200 000 / 30 000 / 170 000 на дате начала учета |
| 12 | Дополнительно выделить 20 000 → C=200 000, R=50 000, F=150 000 | [x] | `test_goal_cash_reserve_free_staged_transitions` |
| 13 | Оплатить 40 000 из цели → C=160 000, R=10 000, F=150 000 | [x] | `test_goal_cash_reserve_free_staged_transitions` |
| 14 | Возврат 10 000 в цель → C=170 000, R=20 000, F=150 000 | [x] | `test_goal_reserve_transitions_and_recommendation` |
| 15 | Перевод 10 000 между своими счетами не меняет C/R/F и доходы/расходы | [x] | `test_internal_transfer_is_idempotent_and_total_neutral` + zero-sum property-test |
| 16 | Цель 150 000, резерв 30 000, 6 дат → шесть взносов по 20 000 | [~] | `test_goal_reserve_transitions_and_recommendation` проверяет деление 120 000 на шесть равных частей; property `test_goal_split_preserves_every_kopeck` проверяет копейки. Сквозной календарь шести дат не создан |
| 17 | Частично оплаченная цель не накапливается повторно; промежуточные сроки учтены | [ ] | Нет сквозного теста промежуточных платежей цели |
| 18 | Расход 1 000 с двумя тегами и OR-фильтр → общий итог 1 000 | [x] | `test_multi_tag_filter_counts_transaction_once` проверяет OR и AND без дублирования |
| 19 | Правило 31-го: конец февраля корректен, в марте снова 31-е, включая високосный год | [x] | `test_last_day_rule_recovers_after_february` проверяет 28/29 февраля и возврат к 31 марта |
| 20 | Закрыть, переоткрыть, изменить факт → последующие остатки пересчитаны, история сохранена | [x] | `test_close_and_reopen_month_switches_fact_only_and_preserves_audit` |
| 21 | Смена окна октябрь→декабрь не сдвигает записи и сохраняет входящий остаток | [x] | `test_forecast_window_does_not_shift_carrying_balance` |
| 22 | Нет даты/счета у части плана → дневной/посчетный прогноз явно неполон | [x] | `test_month_only_or_accountless_plan_marks_daily_forecast_incomplete` |
| 23 | UTF-8 BOM и CP1251, запятая в сумме, кавычки, русские теги импортируются без потерь | [x] | `test_cp1251_csv_import_and_repeat_batch`, `test_utf8_bom_csv_preserves_quoted_newline_and_russian_tags` |
| 24 | Повтор того же подтвержденного import batch не создает записи | [x] | `test_cp1251_csv_import_and_repeat_batch` |
| 25 | Две одинаковые покупки без external ID можно сохранить обе | [x] | `test_identical_real_purchases_without_external_id_are_both_kept` |
| 26 | Project export → чистый import сохраняет сущности, связи, overrides и итоги | [x] | `test_project_export_import_round_trip_preserves_links_and_totals`; также default settings/empty strings в отдельном тесте |
| 27 | Formula-like CSV и ZIP traversal не исполняются; небезопасный архив отклонен | [x] | `test_formula_safe_csv_export`, `test_project_import_rejects_traversal` |
| 28 | Одинаковый idempotency key проведения → одна операция и одна связь | [x] | `test_idempotent_transaction`, `test_idempotent_plan_match_is_exposed_on_transaction_list`, кредитный idempotency-тест |
| 29 | Два изменения одной версии → одно успешно, второе получает понятный 409 | [x] | `test_version_conflict`; ORM race guard: `test_sqlalchemy_version_guard_rejects_actual_concurrent_update` |
| 30 | Обрыв в середине перевода/import confirm не оставляет половинчатых изменений | [~] | `test_import_confirmation_is_atomic_and_respects_closed_month` и `test_invalid_project_archive_rolls_back_all_rows`; fault injection в середине перевода отсутствует |
| 31 | Restart, recreate и rebuild контейнера сохраняют подтвержденные данные | [~] | В изолированном Compose project счёт 123456 сохранился после `force-recreate` и смены локального image layer; чистый multi-stage rebuild не повторён из-за DNS |
| 32 | Online backup WAL-базы и restore при остановленном app сохраняют целостность и итоги | [x] | После container backup добавлен второй счёт; app остановлен, CLI restore вернул ровно первый счёт, ready прошёл, а старая сессия получила 401; дополнительно — `test_restore_publishes_checked_database_without_old_sessions_or_sidecars` |
| 33 | Неавторизованные data/export/backup и мутация без CSRF отклонены | [x] | `test_auth_and_csrf` проверяет data/export/backup 401 и CSRF 403; spoofed forwarded host/origin: `test_origin_cannot_be_whitelisted_by_spoofed_forwarded_host` |
| 34 | После сборки основные экраны и операции работают без внешнего интернета | [ ] | Актуальный offline container/E2E прогон не выполнен |
| 35 | Архивирование категории/цели/счета сохраняет историю и отчеты | [x] | `test_archiving_account_and_category_preserves_history_and_forecast` проверяет категорию, счёт, цель с сохранённым резервом, историю и итог прогноза |

## Инфраструктура, UI и производительность

| Проверка | Статус | Доказательство |
|---|:---:|---|
| Backend suite | [x] | `.venv/bin/python -m pytest backend/tests -q` → 52 passed; `.venv/bin/python -m ruff check backend/app backend/tests backend/alembic backend/scripts` → clean |
| Frontend suite | [x] | `npm --prefix frontend test` → 9 files, 45 passed (Node 26.4.0) |
| Ruff + TypeScript strict + production SPA build | [x] | Ruff clean; `npm --prefix frontend run lint` и `npm --prefix frontend run build` → exit 0. Build предупреждает о 930,40 kB JS chunk |
| Темы и цветовые схемы | [x] | Unit/integration tests проверяют persistence, system listener, четыре схемы и переключатели настроек; Playwright visual smoke проверил desktop, 390 px, login, dashboard, settings и Recharts |
| `docker compose config --quiet` | [x] | 2026-09-21, exit 0 |
| Текущий Docker image rebuild + ready smoke | [~] | Текущие backend/static прошли Compose ready/persistence/restore в локальном overlay-образе; чистая multi-stage сборка последнего дерева заблокирована DNS Docker Hub |
| Runtime Python связан с SQLite >= 3.51.3 | [x] | Container probe: Python SQLite 3.53.4; Dockerfile и entrypoint дополнительно падают при версии <3.51.3 |
| Контейнер работает UID 10001 и пишет только в `/data`, `/backups`, `/tmp` | [x] | Runtime probe: UID/GID 10001, rootfs read-only, `/app` write rejected, `/data` и `/backups` write passed, `cap_drop=ALL`, `no-new-privileges` |
| `linux/amd64` build + smoke | [ ] | — |
| `linux/arm64` build + smoke | [~] | Ранее полная arm64 multi-stage сборка + финальный code/static overlay прошли smoke; нет чистой финальной multi-stage сборки |
| Playwright guest + authenticated desktop/360 px на текущем production build | [~] | 4/4 live E2E passed на сборке 2026-09-21; для текущей theme-сборки выполнен отдельный mocked visual smoke, но полный live E2E не повторён |
| Ready, SPA fallback и JSON 404 для неизвестного API | [x] | В live-протоколе ready и SPA → 200, неизвестный API route → JSON/404 |
| 100 000 операций, 24 месяца, p95 обзора < 1 s | [~] | Два прогона репозиторного benchmark по 20 warm runs: p50 0,0598–0,0617 s, p95 0,0649–0,0675 s; нет RSS/CPU и контейнерного лимита 2 vCPU / 2 GiB |

## Открытые ограничения реализации

- CSV-мастер не умеет произвольное сопоставление колонок, общий счет на файл, построчное исключение через UI, импорт переводов, лимитов и взносов целей. Подтвержденный batch нельзя отменить.
- Читаемый CSV с русскими заголовками и именами счетов/категорий экспортирует только фактические операции; полный перенос выполняет отдельный канонический ZIP.
- UI поддерживает редактирование, архив/восстановление и безопасное удаление счетов, категорий, тегов, целей, кредитов, планов, фактов, переводов и строк кредитного графика. Сумму и дату отдельного повторения можно изменить через календарь; ручная сортировка справочников и изменение базовой периодичности существующего плана остаются ограничены.
- Нет версий повторяющихся правил и областей изменения «этот и будущие/диапазон»; месячный итог зарплаты и её части не имеют общей групповой идентичности, поэтому их нельзя вводить одновременно.
- График взносов цели и обеспеченность промежуточных оплат по датам не моделируются end-to-end. Обычный возврат уменьшает чистый расход, но не хранит ссылку на исходную покупку.
- Кредитный график и связанный с ним плановый платёж не дублируются в прогнозе. Закрытие месяца блокирует мутации и фиксирует факт, но не ведёт мастер переноса/отмены каждого неоплаченного ожидания.
- Frontend DTO пока описаны вручную, а не сгенерированы из OpenAPI; дневной/посчетный прогноз и отдельные analytics endpoints покрыты не полностью.
- Канонический ZIP импортируется только в пустую финансовую установку. Проверяются whitelist, traversal и общий заявленный размер; отдельной проверки symlink attributes/compression ratio нет.
- Нет автоматической ротации backup. Compose restore при остановленном app проведён; аварийное восстановление после искусственного crash не проверялось.
- E2E покрытие пока smoke-уровня; большинство финансовых сценариев доказаны backend integration/unit-тестами, а не браузером.
- Production SPA собирается, но основной minified JS chunk сейчас около 930,40 kB; Vite рекомендует code splitting.
- Не закрыты сквозные проверки промежуточных платежей цели и offline/current multi-arch образов.
