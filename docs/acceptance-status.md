# Статус приемки

## Точный поиск получателя доступа Photo-access: 2026-10-16

Добавлен `GET /api/v1/superapp/apps/photo/users/resolve?username=...`:
после проверки общей сессии и доступности приложения он возвращает только
`id` и точный логин одного активного пользователя. Списка пользователей,
подстрочного поиска и паролей в ответе нет. Photo-access использует этот
контракт для назначения доступа; схема и миграции бюджета в этой итерации
не менялись.

Budget HEAD `82db3f8e4cc6224a8546e2051857e51b831b6fd9`; рабочее дерево
dirty, включая существовавшие ранее изменения и новые незакоммиченные файлы
резолвера, identity boundary и тестов. Корневой `cap` остаётся без коммитов.
Среда: macOS arm64, backend venv Python 3.13.13, Node.js 26.4.0,
Chrome 150.0.7871.182, Docker client 29.4.3 / server 29.2.1.
Собранный контейнер: Python 3.13.15; disposable PostgreSQL 17.11,
`alembic_version=0013`.

| Проверка | Точная команда | Наблюдаемый результат и границы |
| --- | --- | --- |
| Статика и полный suite текущего дерева | `make lint test` из `budget-planner/` | [x] Ruff и TypeScript завершились успешно; 175 pytest passed, 0 failed/skipped; 90 Vitest passed в 19 файлах, 0 failed/skipped. Backend fixture использует SQLite. Лог: `photo-access/.acceptance/sharing-budget-gates.log` относительно корня `cap`. |
| Сборка суперапп-пути | `VITE_BASE_PATH=/budget/ make build` | [x] TypeScript, Vite SPA и `docker compose config --quiet` прошли. Прежние предупреждения о `/contour.css` и JS chunk больше 500 kB сохраняются. |
| Изолированная приёмка | `BUILDX_CONFIG=/private/tmp/photo-library-buildx PLAYWRIGHT_CHANNEL=chrome make -o lint -o test -o build acceptance SMOKE_PROJECT=photo-sharing-auth-20261016 SMOKE_PORT=18087` | [x] exit 0: текущий образ собран с кешем неизменившихся слоёв, новый PostgreSQL volume, migration job завершён, ready вернул `{"status":"ok"}`. Playwright: 2 passed, 3 skipped, 0 failed за 2.2 s; 5 workers. `-o` исключает повтор уже прошедших в этой итерации lint/test/build. Лог: `photo-access/.acceptance/sharing-budget-acceptance.log`. Chrome запущен вне macOS sandbox. |
| Версия мигрированной БД | `BIND_HOST=127.0.0.1 APP_PORT=18087 TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=smoke docker compose -p photo-sharing-auth-20261016 up -d --wait postgres`; `docker exec photo-sharing-auth-20261016-postgres-1 psql -U budget -d budget -Atc 'SELECT version_num FROM alembic_version; SHOW server_version;'` | [x] После автоматического `down` повторно поднят только PostgreSQL на том же тестовом томе; запрос подтвердил `0013` и `17.11`. |
| Runtime и образ | `docker run --rm --entrypoint python budget-planner:smoke --version`; `docker image inspect budget-planner:smoke --format '{{.Id}}'` | [x] Python 3.13.15; `sha256:b4bad42f6e5891d48a977038d54f169e25830f6f50e3a5e3c9a3d0ccc6b1b092`. |
| Очистка тестового окружения | `BIND_HOST=127.0.0.1 APP_PORT=18087 TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=smoke docker compose -p photo-sharing-auth-20261016 down --volumes` | [x] Удалены только контейнер, сеть и `photo-sharing-auth-20261016_postgres_data`. Рабочие локальные базы и production не использовались. |

Без `E2E_USERNAME`/`E2E_PASSWORD` явно пропущены три сценария бюджета:
вход и годовой план, авторизованная мобильная навигация, открытие и скачивание
bank-PDF skill. Этот прогон доказывает гостевые экраны и миграцию/readiness,
но не полный авторизованный browser flow и не сам резолвер на PostgreSQL;
его сквозной вызов проверяется отдельной интеграцией Photo-access.
Прежнее предупреждение Starlette/AnyIO остаётся. Релиз и уведомления не
публиковались; эта приёмка не меняла рабочее приложение на 8083.

## Глазок для скрытых полей админки: 2026-10-16

В таблицах и карточках `/admin/` добавлено точечное раскрытие значения.
Повторное нажатие, смена раздела, закрытие карточки и скрытие вкладки
убирают раскрытый текст; pending-запрос отменяется и не возвращает значение
на другой экран. Раскрытие не заполняет форму замены и не создаёт PATCH.

Обычные list/detail/mutation ответы сохраняют маски. Отдельный
`POST /api/v1/superapp/admin/tables/{table_name}/record/reveal?key=...`
принимает одно имя поля, проверяет текущего администратора, CSRF и Origin.
Список разрешённых полей явный: новые столбцы закрыты по умолчанию;
credentials, hashes и служебный JSON недоступны. Аудит хранит актора,
идентификатор и имя поля без значения. Уточнён ADR-009; схема/миграции и ER
не менялись.

Корневой `cap` без коммитов; budget base
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`. Существующие изменения сохранены,
новые файлы не закоммичены. Python в backend venv 3.13.13, контейнеры
3.13.15 / PostgreSQL 17.11, Node.js 26.4.0, Docker server 29.2.1.

| Проверка | Команда / действие | Результат и границы |
| --- | --- | --- |
| Фокусированный backend | `backend/.venv/bin/python -m pytest backend/tests/test_superapp_admin_data.py -q` из `budget-planner/` | [x] 27 passed, 0 failed/skipped: имена/суммы/даты, другой владелец, отсутствие прав/сессии/CSRF, чужой Origin, отзыв роли, запрещённые секреты/JSON/неизвестные поля, no-store и аудит без значений. SQLite fixture. |
| Статическая админка в браузере | `PLAYWRIGHT_CHANNEL=chrome node superapp/admin-browser-smoke.mjs` | [x] Полный существующий flow и новые проверки: list/detail show/hide, ошибка запроса, запоздалый ответ после навигации, pagehide, отсутствие автоматической записи раскрытого значения, credentials без глазка, обычные CRUD/конфликты/доступы. 0 page errors; mock API. |
| Полная приёмка | `python3 /private/tmp/cap-admin-eye-20261016/verify.py acceptance` запускает `CI=1 PLAYWRIGHT_CHANNEL=chrome COMPOSE_FILE=<budget-compose>:<private-secrets-override> E2E_USERNAME=<synthetic-owner> E2E_PASSWORD=<env-only> make acceptance SMOKE_PROJECT=cap-eye-acceptance-20261016-2f40 SMOKE_PORT=<isolated-port> 'SMOKE_ENV=BIND_HOST=127.0.0.1 APP_PORT=<isolated-port> TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=eye-check-20261016-2f40'` | [x] exit 0: Ruff/TypeScript, 170 pytest, 90 Vitest / 19 файлов, SPA build, Compose migration/readiness и 5/5 Playwright (4.2 s), 0 failed/skipped. Новая отдельная PostgreSQL и тестовый владелец. `workers=1` не закрывает TD-011. |
| Реальный UI и PostgreSQL | `python3 /private/tmp/cap-admin-eye-20261016/verify.py stage`; `SUPERAPP_TEST_STATE=/private/tmp/cap-admin-eye-20261016/state.json PLAYWRIGHT_CHANNEL=chrome node superapp/admin-reveal-live-smoke.mjs` | [x] Отдельный `cap-admin-check-eye-20261016-2f40`, настоящий Nginx/API/PostgreSQL. Два владельца; show/hide имён и сумм в списке/карточке, повторное открытие скрыто, POST только выбранного поля, CSRF/Origin, отказ обычному пользователю и раскрытию password_hash. Литерал `<b>` отображается текстом, storage не содержит значение, нажатие Save без изменения не отправляет PATCH. 320 px: кнопка 44×44, страница без горизонтального overflow. 0 page errors. |
| PostgreSQL роли и аудит | `docker exec -i -e SUPERAPP_DISPOSABLE=1 cap-admin-check-eye-20261016-2f40-budget-app-1 python - < superapp/admin-reveal-postgres-smoke.py` | [x] В журнале только actor/field metadata; debug_admin имеет SELECT без UPDATE; runtime без elevated privileges, scope разделяет двух владельцев и сбрасывается после transaction; текущая схема 0013. |
| Визуально | Просмотр `/private/tmp/cap-admin-mobile-viewport-dark.png` и `/private/tmp/cap-admin-eye-live-mobile.png` | [x] В light/dark при 320 px глазок видим, текст и кнопки не пересекаются, карточка прокручивается в пределах viewport. Только синтетические данные. |
| Локальное применение | `python3 /private/tmp/cap-admin-eye-20261016/apply_local.py` | [x] Оба проверенных образа установлены как `cap-budget:local` и `budget-planner:local`, перезапущены только API с `--no-deps --no-build`. Readiness 8082/8083 и наличие маршрута прошли. Контрольные суммы всех 30 таблиц сохранились; 8 счетов, 54 операции, 10 переводов. 63 Python source-файла app/Alembic в обоих контейнерах совпали с текущим деревом. |
| Дополнительная статика | `node --check superapp/www/admin.js`; `node --check superapp/admin-reveal-live-smoke.mjs`; `budget-planner/backend/.venv/bin/python -m ruff check superapp/admin-reveal-postgres-smoke.py`; `git -C budget-planner diff --check` | [x] Все проверки прошли. |

Первоначальную подготовку тестового Compose остановила недоступность file
secrets непривилегированному процессу. Исправлены только права тестовых
файлов внутри приватного каталога; последующая полная приёмка прошла.
Браузерные проверки выполнялись разрешённым запуском вне macOS sandbox.
Остались прежние предупреждения Starlette/AnyIO и Vite CSS/chunk.

Локальные образы:
`cap-budget:local` — `sha256:046c837a125a85ddc05c026eae3d7a3f80095d8aa34a8afb33275bb1e5e266fa`,
`budget-planner:local` — `sha256:ef92b7de2aa53b8eebcfcbaa5b418a3a08341c1d54718b9d3bc73d10cc9e1c88`.
Предыдущие сохранены под `*:before-sensitive-eye-20261016`.
Контейнеры и сети обоих disposable projects удалены; volumes оставлены
согласно процедуре. Рабочая БД не использовалась для smoke/E2E.
Версия остаётся локальной 0.1.4, новый релиз и уведомления не публиковались;
продакшен не менялся. Photo/storage интеграция этим изменением не проверялась.

## Восстановление локального приложения из 0004: 2026-10-16

Пользователь выбрал 0004 с 54 операциями и 10 переводами вместо 0005,
сохраняющего старый прод до переноса данных. Восстановление выполнено
только локально, без подключения к продакшену. В исходном дампе схема
0012, у текущего приложения — 0013. Бюджет принадлежит `owner`, ID 1;
логины, хеши паролей и остальные исходные данные сохранены.

Корневой `cap` без коммитов; budget base
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`, прежнее dirty tree сохранено.
Прикладной код и миграции в этой операции не редактировались. Среда:
macOS arm64, host Python 3.14.5 / Node.js 26.4.0; контейнеры Python 3.13.15,
PostgreSQL 17.11; Docker client 29.4.3 / server 29.2.1; Chrome 150.0.7871.182.
Для Docker использованы `DOCKER_HOST=unix:///Users/asimonov05/.colima/default/docker.sock`
и `DOCKER_CONFIG=/private/tmp/cap-vk-20261013/docker`.

| Проверка | Точная команда / действие | Результат и границы |
| --- | --- | --- |
| Свежая копия локальной БД | `python3 /private/tmp/cap-local-restore-20261016/capture_local.py` | [x] Согласованный `pg_export_snapshot` + `pg_dump -Fc --no-owner --no-acl`; реестр 0006, схема 0013. Дата снимка 15 октября UTC = 16 октября МСК. |
| Restore и обновление схемы | `python3 /private/tmp/cap-local-restore-20261016/restore_local.py stage` | [x] Реальный restore 0004: все 28 исходных таблиц совпали по counts/MD5. Текущий migration job обновил 0012 → 0013; 27 таблиц сохранились без изменения строк, изменился `alembic_version`, добавлены две таблицы доступа. Повторный restore 0006 проверен по всем 30 таблицам. |
| Авторизация и изоляция | Disposable auth probe из `deploy/restore_db.py`; `python3 /private/tmp/cap-local-restore-20261016/owner_probe.py verify` | [x] Два синтетических пользователя: регистрация, вход/выход, запись счёта и отсутствие чужих счетов. На другом клоне с временным паролем владельца: 8 счетов / 54 операции / 10 переводов, прогноз на 3 месяца, ZIP-экспорт, каталог 29 прикладных таблиц, новые таблицы read-only, хеши пользователей маскируются. Рабочие пароли и данные не изменялись. |
| FORCE RLS и runtime | `docker compose -f compose.yaml run --rm --no-deps -T -e DATABASE_URL=<owner-probe-db-as-budget_runtime> budget-app python -c <read-only-scope-check>` через приватный helper | [x] Runtime без elevated privileges; без scope 0 счетов, owner 8/54, другой существующий пользователь 0/0; новый transaction не наследует scope. На восстановленной БД нет непроверенных ограничений PostgreSQL. |
| Браузер на клоне | `node /private/tmp/cap-local-restore-20261016/browser_probe.mjs` | [x] Один полный авторизованный flow: вход owner через реальный UI, 8/54/10 через API браузера, страница операций, админка с двумя новыми таблицами и тремя пользователями; 0 page errors. Первое sandbox-запускание Chrome прервано ОС до открытия страницы; разрешённый повтор вне sandbox прошёл. |
| Переключение | `python3 /private/tmp/cap-local-restore-20261016/restore_local.py activate` | [x] На время переключения приостановлены оба API и шлюз. При остановленных записях рабочая БД совпала с 0006. Атомарно переименованы базы, прежняя оставлена с `ALLOW_CONNECTIONS=false`; после подключения все counts/MD5 совпали с мигрированным кандидатом. |
| Актуальные маршруты | `docker compose -f compose.yaml up -d --no-build --no-deps --force-recreate --wait gateway` | [x] Исправлено предшествовавшее восстановлению состояние шлюза с устаревшим шаблоном: `/`, `/budget/`, `/budget/login`, `/admin/`, readiness возвращают 200. Флаги budget/photo сохранены. |
| Совместимость отдельного запуска | `docker compose -f budget-planner/compose.yaml build app`; `docker compose -f budget-planner/compose.yaml up -d --no-build --no-deps --force-recreate --wait app` | [x] Standalone 8082 обновлён с устаревшего образа 0.1.1/head 0012 до текущего дерева 0.1.4/head 0013. TypeScript/Vite build прошёл с прежними предупреждениями CSS/chunk; новый контейнер успешно запущен. Прежний image сохранён под `budget-planner:before-local-restore-20261016`. |
| Окончательное состояние | `verify_schema_current()` + `verify_database()` в обоих API; HTTP readiness 8082/8083; повторная сверка всех таблиц | [x] Оба entrypoint: 0.1.4/head 0013, PostgreSQL ok, readiness 200; 27 исходных таблиц совпадают с 0004. Disposable базы и контейнеры удалены, тестовых записей в рабочей БД нет. |

Квитанция восстановления:
`backups-external/db-registry/restore-events/e8cc3c382823467b8263a379a88be52f.json`.
Позднейшая проверка совместимых локальных runtime и шлюза:
`backups-external/db-registry/maintenance-events/r20261015_210734_c277-local-runtime.json`.
Файлы приватные и исключены из Git. Откат — 0006; дополнительно сохранена
база `budget_before_r20261015_210734_c277`. Новые релизы и уведомления не
публиковались. Полные `make lint`, `make test`, `make acceptance` не
повторялись для операции восстановления данных; вместо них выполнены
реальные PostgreSQL restore/migration и авторизованный API/browser smoke
на клонах. Это не новая проверка всех прикладных сценариев.

## Проверка Photo mutations через общую identity: 2026-10-16

Добавлен `POST /api/v1/superapp/apps/photo/identity`: существующая сессия,
связанный с ней CSRF-токен, обычная same-origin проверка и доступ к `photo`
проверяются до выдачи `{id, username}`. GET сохраняет прежний контракт.
Оба маршрута используют общий presentation provider; финансовые данные не
меняются и не блокируются. Контракт интеграции требует от Photo отдельной
проверки исходного browser Origin и upstream-запроса с Origin статически
настроенного identity URL.
Доверие к `X-Forwarded-Host` или `X-Forwarded-Proto` не добавлено.

Изменения локальные, без release/deploy и изменения схемы. Budget base:
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`; исходное dirty tree сохранено,
новые файлы не закоммичены. Среда: macOS arm64, Python 3.13.13,
Node.js 26.4.0, npm 12.1.0, Docker 29.4.3.

Команды выполнены из `budget-planner`:

| Проверка | Команда | Результат и границы |
| --- | --- | --- |
| Identity и доступ | `backend/.venv/bin/python -m pytest backend/tests/test_photo_identity.py backend/tests/test_superapp_access.py -q` | 14 passed, 0 failed/skipped. Успех; отсутствующая/невалидная CSRF; сессия другого пользователя; чужой Origin со spoofed forwarded headers; глобальное закрытие; персональное исключение; отозванная сессия; GET совместимость. |
| Линтеры | `make lint` | Ruff и TypeScript прошли. |
| Регрессия | `make test` | Backend: 157 passed; frontend: 90 passed, 19 файлов; 0 failed/skipped. Существующая SQLite fixture, не доказательство PostgreSQL RLS. |
| Сборка | `make build` | SPA build и Compose config прошли. Прежние предупреждения Vite: внешний `/contour.css` и JS bundle больше 500 kB. |

Обязательный Compose acceptance дополнительно выполнен на новом изолированном
проекте `photo-auth-acceptance-20261016`, порт `18087`, без существующих
контейнеров, томов и пользовательских данных. Команда:

```bash
env -u E2E_USERNAME -u E2E_PASSWORD PLAYWRIGHT_CHANNEL=chrome \
  make acceptance SMOKE_PROJECT=photo-auth-acceptance-20261016 SMOKE_PORT=18087
```

В этом прогоне Ruff/TypeScript, 157 backend-тестов и 90 frontend-тестов
прошли; SPA и Compose config собраны. Первая Docker-сборка остановилась
из-за запрета sandbox на запись служебного файла `~/.docker/buildx/activity`.
После разрешённого запуска вне sandbox повторён только оставшийся recipe,
без повторения уже прошедших проверок:

```bash
env -u E2E_USERNAME -u E2E_PASSWORD PLAYWRIGHT_CHANNEL=chrome \
  make -o lint -o test -o build acceptance \
  SMOKE_PROJECT=photo-auth-acceptance-20261016 SMOKE_PORT=18087
```

Текущий образ `budget-planner:smoke` собран с использованием 17 cached steps.
Новая PostgreSQL успешно запущена; migration job завершился успешно,
`/api/v1/health/ready` вернул 200 `{"status":"ok"}`. Playwright/Chrome:
**2 passed / 3 skipped / 0 failed**. Пройдены гостевой redirect на login и
login при ширине 360 px. Пропущены вход/годовой план, авторизованная мобильная
навигация и открытие/скачивание банковского PDF-скилла, поскольку
`E2E_USERNAME`/`E2E_PASSWORD` явно не заданы. Это не полный авторизованный E2E.

`make` остановил и удалил все контейнеры и сеть тестового проекта. Для записи
ревизии затем ненадолго поднят только его собственный PostgreSQL и выполнен
read-only `SELECT version_num FROM alembic_version`: результат **0013**;
после чтения PostgreSQL и сеть вновь удалены. Новый disposable volume
`photo-auth-acceptance-20261016_postgres_data` оставлен согласно поведению
`make acceptance`; рабочие базы и сервисы не затрагивались.

Логи: `/private/tmp/photo-auth-acceptance-20261016.log` и
`/private/tmp/photo-auth-acceptance-20261016-container.log`. Полный сквозной
Photo→budget сценарий не входит в этот бюджетный acceptance; его отдельные
API/browser проверки фиксируются в документации Photo.

## Главная для гостей: 2026-10-16

Статическая главная супераппа теперь предлагает вход и регистрацию до
проверки сессии. Карточки скрыты в исходном HTML; гостю не запрашиваются
`/apps.json` и `/api/v1/superapp/apps`. После входа/регистрации с главной
`next=/` возвращает на выбор доступного приложения. Пока выполняется выход,
каталог скрывается; при неудачном выходе восстанавливается.

Изменения локальные, без выкладки и изменений БД. Корневой `cap` по-прежнему
без коммитов; budget base `82db3f8e4cc6224a8546e2051857e51b831b6fd9`,
прежнее dirty tree сохранено. Среда: macOS arm64, Node.js 26.4.0,
Playwright с установленным Google Chrome (`PLAYWRIGHT_CHANNEL=chrome`).

| Проверка | Команда | Результат и границы |
| --- | --- | --- |
| Гостевая и авторизованная главная | `PLAYWRIGHT_CHANNEL=chrome node superapp/home-browser-smoke.mjs` | [x] 8 сценариев passed, 0 failed/skipped: pending auth, 401, ошибка сети, отсутствие запросов каталога у гостя, успешная сессия и персональная/deploy-фильтрация, ошибка каталога, выход, 320 px. Mock API; рабочие аккаунты не используются. |
| Регрессия админки | `PLAYWRIGHT_CHANNEL=chrome node superapp/admin-browser-smoke.mjs` | [x] Полный существующий mocked browser flow прошёл с новым поведением главной. |
| Общие стили | `VITE_BASE_PATH=/budget/ npm --prefix budget-planner/frontend run build`; `PLAYWRIGHT_CHANNEL=chrome node superapp/appearance-integration-smoke.mjs` | [x] Build и browser integration прошли. Первый запуск fixture не загрузил старый standalone dist с base=/; пересборка с нужным base=/budget/ восстановила предусловие. Остались прежние Vite-предупреждения про внешний CSS и размер bundle. |
| Статика | `node --check superapp/www/home.js`; `docker compose config --quiet`; `git -C budget-planner diff --check`; `git -C photo-access diff --check` | [x] Прошли. Схема, backend и собираемые приложения не менялись; полные backend/Compose acceptance повторно не запускались для этой правки статической главной. |
| Визуально | `/private/tmp/cap-home-guest-desktop.png`, `/private/tmp/cap-home-guest-mobile.png` | [x] Desktop и 320 px: видны вход/регистрация, нет карточек приложений, кнопки и заголовок не обрезаны. |

Ожидания `superapp/browser-smoke.mjs` и `superapp/flags-browser-smoke.mjs`
обновлены под гостевую главную и возврат `next=/`; live/Docker-прогоны этих
сценариев в этой правке не выполнялись. Предыдущие результаты ниже относятся
к прежнему состоянию главной.

## Админка супераппа и доступ к приложениям: 2026-10-15

Изменения локальные, без release/deploy. Корневой `cap` не имеет коммитов;
бюджет — `82db3f8e4cc6224a8546e2051857e51b831b6fd9` с ранее изменённым
рабочим деревом и новыми незакоммиченными файлами. Прежние изменения сохранены.
Среда: macOS arm64, Python 3.13.13, Node.js 26.4.0, Docker Compose 5.1.3.

Добавлены общая админка `/admin/`, каталог всех 29 прикладных таблиц,
маскирование данных на сервере, версии и аудит табличных правок, глобальный
доступ к двум приложениям и пользовательские исключения. Миграция `0013`
добавляет две таблицы и RLS; схема Excalidraw обновлена. Административные
операции и общий вход доступны при закрытых приложениях.

| Проверка | Точная команда / действие | Результат и границы |
| --- | --- | --- |
| Backend gate, окончательные guards | `make test-backend` из `budget-planner/` | [x] 149 passed, 0 failed/skipped, 13.66 s; один прежний Starlette/AnyIO deprecation warning. SQLite fixtures, не доказательство PostgreSQL. |
| Первоначальный полный gate | `make test` из `budget-planner/` | [x] На первом варианте изменений: 139 pytest + 89 Vitest, 0 failed/skipped. Позднейшие защитные изменения покрыты окончательными проверками ниже/выше, этот результат сам по себе их не подтверждает. |
| Статика и сборка первого варианта | `make lint`; `make build` из `budget-planner/` | [x] Ruff и TypeScript, Vite build и Compose config. Первый lint поймал неиспользуемый import, удалён; повтор прошёл. Vite сохраняет прежние предупреждения о внешнем contour.css и размере chunk. |
| Фото backend | `../budget-planner/backend/.venv/bin/python -m pytest tests -q` из `photo-access/` | [x] 6 passed, включая отказ 403 при закрытом приложении и ошибки общего сервиса. |
| Whitespace | `git -C budget-planner diff --check`; `git -C photo-access diff --check` | [x] Оба прошли. |
| UI focused | `npm --prefix budget-planner/frontend test -- src/App.test.tsx src/lib/authRedirect.test.ts src/pages/Settings.test.tsx src/pages/Notifications.test.tsx src/components/Layout.test.tsx` | [x] 22 passed: закрытый бюджет, возврат из входа в админку, перенос настроек пользователей и публикации. |
| Admin browser fixture | `PLAYWRIGHT_CHANNEL=chrome node superapp/admin-browser-smoke.mjs` | [x] CRUD, ревизии/конфликт, CSRF, маски/пустое поле замены, настройки доступа, создание/пароль пользователя, черновик/edit/preview/publish, сообщение, Photo 403. Mock API, не доказательство реальной БД. Desktop dark и 320×740: заголовок помещается, modal в viewport, последние действия доступны через внутренний scroll. |
| Фото production build | `VITE_BASE_PATH=/photo/ VITE_API_BASE_URL=/photo-api npm --prefix photo-access/frontend run build` | [x] TypeScript + Vite прошли. |
| Schema diagram | Фокусированный `test_schema_diagram.py`, JSON/model/FK checks; визуальная проверка в локальном Excalidraw viewer | [x] Новые таблицы, все столбцы и FK с привязками; после переноса user_app_access стрелка CASCADE не пересекает таблицы, заголовок и легенда видны. |
| Deployment flag matrix | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/cap-playwright SUPERAPP_TEST_NETWORK=cap-admin-check-20261015_default python3 superapp/flags-smoke.py --browser` | [x] 4×29 HTTP checks и 4/4 browser runs; общий вход остаётся доступным при обоих выключенных флагах. Изолированная сеть. |

| Окончательная изолированная приёмка | `python3 /private/tmp/cap-superapp-admin-20261015/acceptance.py` запускает `CI=1 PLAYWRIGHT_BROWSERS_PATH=/private/tmp/cap-playwright COMPOSE_FILE=<budget-compose>:<temporary-secrets-override> E2E_USERNAME=<test-owner> E2E_PASSWORD=<env-only> make acceptance SMOKE_PROJECT=cap-admin-acceptance-20261015 SMOKE_PORT=50015 'SMOKE_ENV=BIND_HOST=127.0.0.1 APP_PORT=50015 TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=admin-acceptance-20261015'` | [x] exit 0: Ruff/TypeScript, 149 pytest, 90 Vitest (19 files), сборка/Compose ready, 5 Playwright passed, 0 failed/skipped. CI использует workers=1; это не доказывает исправление прежней параллельной гонки TD-011. Новая PostgreSQL и синтетический владелец, рабочие данные не использовались. |
| Окончательный API на PostgreSQL | `SUPERAPP_DISPOSABLE=1 SUPERAPP_URL=http://127.0.0.1:<isolated-port> E2E_USERNAME=<test-owner> E2E_PASSWORD=<env-only> python3 superapp/admin-integration-smoke.py` | [x] 98 проверок: все 29 таблиц, маскирование, CRUD и ревизии, запрет чужих связей, два пользователя, глобальный и персональный доступ, закрытие обоих приложений и сохранение административного доступа. |
| PostgreSQL scope/схема/роли | `docker exec -i -e SUPERAPP_DISPOSABLE=1 cap-admin-check-20261015-budget-app-1 python - < superapp/admin-postgres-smoke.py` | [x] 29 таблиц совпадают с metadata; FORCE RLS новых таблиц, отсутствие elevated runtime privileges, скрытые чужие/нескопированные строки, отказ runtime-записи обычному пользователю, diagnostic SELECT всех таблиц без write privileges, CHECK/FK/ON DELETE CASCADE на синтетических записях. |
| Дополнительная статика | `budget-planner/backend/.venv/bin/python -m ruff check superapp/admin-integration-smoke.py superapp/admin-postgres-smoke.py superapp/flags-smoke.py`; `node --check superapp/www/admin.js`; `node --check superapp/www/home.js`; `docker compose -f compose.production.yaml config --quiet` | [x] Прошли на окончательном дереве. |

Дополнительные проверки после общей приёмки:

- `SUPERAPP_TEST_STATE=/private/tmp/cap-superapp-admin-20261015/state.json PLAYWRIGHT_CHANNEL=chrome node superapp/admin-live-smoke.mjs` — прошёл против окончательной PostgreSQL: 29 таблиц, возврат после общего входа в `/admin/`, пользователь и маски, account CRUD, персональный запрет фото с 403, создание release draft, отказ не-администратору.
- Визуальная проверка обнаружила сжатие строк бокового каталога с длинными названиями. CSS исправлен (`grid-auto-rows: max-content`); повторный `PLAYWRIGHT_CHANNEL=chrome node superapp/admin-browser-smoke.mjs` с 29 таблицами прошёл. Проверены границы соседних элементов и текстовых областей, desktop dark и 320×740. Снимки `/private/tmp/cap-admin-desktop-dark.png`, `/private/tmp/cap-admin-mobile-viewport-dark.png` просмотрены.
- В локальный корневой `compose.yaml` добавлен такой же `migrate` job до backend. `docker compose config --quiet` и `docker compose -f compose.production.yaml config --quiet` прошли; независимый read-only review подтвердил секреты, сеть и зависимость. Корневой local Compose отдельно не запускался: он подключается к существующей пользовательской PostgreSQL. Сам migration job проверен в изолированном production Compose выше.
- Оба disposable Compose project остановлены, их сети удалены; временные credentials и `.tmp-admin-check` удалены. Named volumes оставлены согласно процедуре без `down -v`; рабочие стеки не менялись.

Контейнеры: Python 3.13.15, PostgreSQL 17.11 arm64; host Docker 29.2.1,
Compose 5.1.3, Ruff 0.12.11, Playwright 1.63.0 / Chromium 153.0.8010.12.
Окончательный `cap-budget:admin-check-20261015`:
`sha256:b295c2a3c3b39bf47c5869893155459d68de4bf9875b6277c68b871ec8bded08`.
Использован кеш зависимостей; изменённые backend/frontend скопированы и
собраны заново. Начальная ошибка macOS sandbox при запуске Chromium решена
разрешённым запуском изолированных браузерных тестов вне sandbox.

Проверена свежая PostgreSQL миграция до `0013`. Обновление исторического
production snapshot отдельно не прогонялось. Публикация в реальный сервис и
рассылка настоящим пользователям не выполнялись. Все следующие разделы
относятся к предыдущим задачам и сохранены как исторические результаты.

## Работающий local budget → аккаунт asimonov: 2026-10-14

Исправлен источник переноса: архив от 6 октября содержал только 22 операции
и 5 переводов; работающая локальная PostgreSQL `budget-planner-postgres-1`,
база `budget`, содержит 54/10. Её согласованный экспорт зарегистрирован
как 0004 (`local-budget-live`, 175202 bytes, SHA256
`74f9400b22be8d158c069ac9bf12789b4ed4b801f893063573e6201ff55acfea`).
Перед выполнением текущие counts/checksums всех таблиц бюджета локальной
базы повторно сопоставлены с 0004 и совпали. Локальный источник — owner ID 1;
получатель — существующий продовый asimonov ID 1. Изменения после 2 октября
не фильтровались: переносилось полное актуальное состояние его бюджета.

Код приложения, схема 0012, версия 0.1.4 и native amd64 image
`sha256:64b85cad2252720c855cde21f016080606cbd8064aa3c3208f799e3623fe3619`
не менялись. Git base `82db3f8e4cc6224a8546e2051857e51b831b6fd9`, прежнее
dirty tree сохранено, новых коммитов нет. Добавлен инфраструктурный сценарий
`deploy/transfer_user_budget.py`. Среда: macOS Python 3.14.5; VM Ubuntu
24.04.5, host Python 3.12, container Python 3.13.15, PostgreSQL 17,
Compose 2.40.3. Локальный экспорт выполнен ранее через закреплённый
`pg_export_snapshot`; зарегистрированная дата UTC — 13 октября,
время снимка — 14 октября 00:04 МСК.

| Проверка | Команда / действие | Результат и границы |
| --- | --- | --- |
| Static check | `budget-planner/backend/.venv/bin/python -m ruff check deploy/transfer_user_budget.py`; `ast.parse` host controller | [x] Прошли. Полные gates приложения повторно не запускались: его code/image/schema неизменны; актуальные PostgreSQL/API проверки ниже выполнены на том же 0.1.4. |
| Исходный дамп | `python3 /private/tmp/cap-account-transfer-20261014/control.py upload`, затем `stage` | [x] SHA256 0004 на VM совпал; restore в отдельную базу и migration job текущего image прошли. Counts/MD5 всех 28 таблиц совпали с source proof до и после миграций. Изолированный smoke двух новых пользователей прошёл. |
| Checkpoint | Тот же controller: `pause`, `download` | [x] Во время обслуживания сохранён полный прод 0005, SHA256 `0e3b34aaafb04fa684cfbb4c4b34d6536a48f5f21b57ae8108bb9a525f4caa55`; скачан и проверен локально до изменения бюджета. |
| Проверка копирования | `python3 /private/tmp/cap-account-transfer-20261014/finish.py`: phase `probe` host helper | [x] На отдельной базе из checkpoint 0005 выполнен перенос 23 таблиц только user_id=1. Counts/MD5 совпали с local source; все глобальные auth/notification таблицы и строки других пользователей сохранились. Неверный логин owner отклонён без изменения строк; повторный перенос дал те же данные без дублей. |
| Авторизованный API probe | Тот же phase probe запускает изолированный budget-app на localhost:18316 | [x] Вход именно asimonov ID 1: accounts=8, transactions=54, transfers=10. Другой временный пользователь не видит его счета; logout первого не завершает сессию второго. Для этого пароль изменён исключительно в disposable probe, production пароль не менялся. Probe container и БД удалены. |
| Продовый перенос | Phase `apply`: `transfer_user_budget.py --source-database cap_candidate_r20261014_114645_4994 --target-database budget --source-user-id 1 --target-user-id 1 --target-username asimonov` через admin maintenance container | [x] Одна SERIALIZABLE transaction; зависимости удалены child-first/добавлены parent-first, source IDs сохранены, чужие PK защищены проверкой коллизий. 23 таблицы бюджета совпали по counts/MD5. Пользователи, пароли, сессии, уведомления, release notes и другие владельцы не изменились; проверены до commit и после запуска приложения. |
| Реальная production RLS | Read-only SQL через работающий budget-app с runtime role и `app.current_user_id=1`, затем отдельной транзакцией ID 4 | [x] Аккаунт asimonov ID 1 active/admin: 8 счетов, 54 операции, 10 переводов, 10 категорий, 6 плановых статей; 32 операции датированы после 2026-10-02. Другому пользователю ID 4 доступны 0/0/0. Настоящий пользователь паролем в HTTP-прод не входил; это PostgreSQL RLS проверка без записи в продовые данные. |
| Публичная доступность | `urllib` GET доверенного HTTPS `/`, `/budget/login`, `/api/v1/health/ready`, `/api/v1/accounts`, `/photo/`; `db_dump_registry.py verify 0004` / `0005` | [x] 200/200/200/401/404; оба дампа проходят SHA256. Фото остаётся закрытым. |

Receipt:
`backups-external/db-registry/restore-events/4d3822d71a8a4aaa8a797392b48fbdbd.json`.
Обновлялись данные пользователя, поэтому новый application release и повторная
публикация release note не выполнялись. Все предыдущие результаты ниже —
исторические и не являются утверждением, что текущий бюджет равен архиву 0001.

## Локальный реестр и восстановление 0001: 2026-10-13

Приложение осталось на 0.1.4, образ
`sha256:64b85cad2252720c855cde21f016080606cbd8064aa3c3208f799e3623fe3619`.
Git commit `82db3f8e4cc6224a8546e2051857e51b831b6fd9` и прежнее dirty tree
сохранены; новых коммитов нет. Изменены только инфраструктурные сценарии,
ignore и документация. Код приложения и схема 0012 не менялись.
Среда: локальный Python 3.14.5; VM Ubuntu 24.04.5, host Python 3.12,
Compose 2.40.3, PostgreSQL 17; приложение использует Python 3.13.15.

| Проверка | Команда / действие | Результат и границы |
| --- | --- | --- |
| Локальный каталог | `python3 -m unittest discover -s deploy -p 'test_db_dump_registry.py' -v` | [x] 7 passed, 0 failed/skipped: приватные права, независимая копия, повторный импорт, повреждение, неправильный формат/SHA, путь вне каталога, orphan и receipt без checkpoint. Fixtures проверяют каталог; они не изображают успешный PostgreSQL restore. |
| Статическая проверка | `budget-planner/backend/.venv/bin/python -m ruff check deploy/db_dump_registry.py deploy/test_db_dump_registry.py deploy/restore_db.py`; `ast.parse` обоих сценариев | [x] Прошли. Gates приложения повторно не запускались: его дерево, image и схема не менялись с прогона 0.1.4 выше. |
| Первый дамп | `python3 deploy/db_dump_registry.py add superapp/.local-recovery-20261008/recovery/budget.dump --origin local-recovery-20261008 --snapshot-date 2026-10-06 --proof /private/tmp/cap-db-registry-20261013/local-proof.json --expected-sha256 860fbe41a44f60e6b7e363d01702308348f68841873904f3bdb94d9817960c68`; `verify` | [x] Зарегистрирован 0001: 169260 bytes, исходный SHA256 совпал. Дамп не содержит изменений после 6 октября. |
| Пробное восстановление | `python3 /private/tmp/cap-db-registry-20261013/control.py upload`, затем `stage`; на VM `python3 /opt/cap/deploy/restore_db.py stage /opt/cap/recovery/db-registry/r20261013_200132_2b60` | [x] `pg_restore --no-owner --no-acl --single-transaction --exit-on-error` в отдельную базу, migration job текущего image, совпадение counts/MD5 всех 28 таблиц до и после миграций. В отдельном клоне зарегистрированы два временных пользователя: вход/выход, создание счёта и RLS — второй не видит счёт первого или восемь исходных счетов; после выхода первого второй сохраняет сессию. Тестовый контейнер и только его probe БД удалены. Двухшаговый rename в одной транзакции отдельно выполнен в probe БД. |
| Checkpoint и переключение | `python3 /private/tmp/cap-db-registry-20261013/control.py switch` вызывает `pause`, `download`, `activate` | [x] Во время обслуживания сохранён полный дамп прежнего прода 0002: 170098 bytes, SHA256 `b9b9bce56ad97248d3c355a3d9b88fec9bb82a115821128cc190805ec4cf1b08`. Он скачан и проверен локально до переключения. Подготовленная база атомарно переименована в `budget`, прежняя сохранена с запрещёнными подключениями. Операция завершилась в 20:08:24 UTC. |
| Сохранность и версия | `restore_db.py activate` проверяет текущий image, данные и health после запуска; отдельно `python -c 'import app; print(app.__version__)'` в production container | [x] 0.1.4, та же image. Данные исходного дампа совпали по всем таблицам, кроме намеренно сохранённых `release_notes`/`notifications`: 1 опубликованная запись и 3 прежних уведомления, checksum опубликованной записи не изменился. 3 пользователя, 8 счетов, 22 операции. Пароли пользователей не сбрасывались. |
| Публичный прод | Python `urllib` GET `/`, `/budget/login`, `/api/v1/health/ready`, `/api/v1/accounts`, `/apps.json`, `/photo/`, `/photo-api/auth/me` по доверенному HTTPS | [x] Главная/вход/ready — 200; guest accounts — 401; flags 1/0; фото — 404. Это проверка доступности после переключения; реальный пользователь продовой сессией не входил. |
| Реестр и receipt | `python3 deploy/db_dump_registry.py verify`; `record-restore 0001 --rollback-id 0002 --receipt ...` | [x] Обе копии проходят SHA256. Receipt: `backups-external/db-registry/restore-events/1e11ced53709463181a7aaaf80243be3.json`. Дампы и receipt приватны, исключены из Git; облачное хранилище и расписание не создавались. |

Автоматическая ветка rollback подготовлена, но её отказ после успешного
переключения намеренно не провоцировался на рабочем проде. Прежняя база и
локальный checkpoint сохранены для восстановления при необходимости.

## Выкладка 0.1.4 в Timeweb: 2026-10-13

Рабочее дерево поверх `82db3f8e4cc6224a8546e2051857e51b831b6fd9` остаётся
незакоммиченным; прежние правки пользователя сохранены. Корневой `cap`
не имеет коммитов. В этой задаче добавлен отдельный production Compose,
изменена версия пакетов на 0.1.4 и подготовлен release note. Схема БД и
логика приложения не менялись. Архив исходников 0.1.4 имеет SHA256
`582d37e034003e50c4cce869a16fefc54354187dde6219f48bb1698f8b5fe7f8`.

Локальная среда: macOS arm64, Node.js 26.4.0, npm 12.1.0,
backend Python 3.13.13; вспомогательные сценарии выполнялись Python 3.14.5.
VM: Ubuntu 24.04.5, linux/amd64, Docker 29.1.3, Compose 2.40.3.
Образ `cap-budget:0.1.4` собран непосредственно на VM с закреплёнными
Node 22.19.0 и Python 3.13.15; digest
`sha256:64b85cad2252720c855cde21f016080606cbd8064aa3c3208f799e3623fe3619`.

| Проверка | Команда / действие | Результат и границы |
| --- | --- | --- |
| Gates версии 0.1.4 | `make lint test build` из `budget-planner/` | [x] Ruff, TypeScript, 128 pytest и 89 Vitest прошли, 0 skipped; SPA build и Compose config прошли. В pytest остаётся предупреждение Starlette/AnyIO, в Vite — большой chunk и внешний `/contour.css`. Backend fixtures используют SQLite. |
| Изолированная приёмка | `python3 /private/tmp/cap-vk-20261013/run-acceptance-014.py`, внутри `make -o lint -o test -o build acceptance SMOKE_PROJECT=cap-budget-acceptance-20261013-014-c SMOKE_PORT=18314` | [~] Новая PostgreSQL, текущие миграции и ready прошли. Временный владелец задан через `E2E_USERNAME`/`E2E_PASSWORD`; production БД не использовалась. Gates уже прошли на том же дереве и исключены из повторного запуска через `-o`. Playwright: 4 passed, 1 failed, 0 skipped: сценарий PDF-скилла застал загрузочный экран и превысил 30 секунд в параллельном прогоне. Первые попытки были заблокированы отсутствующим browser path и sandbox MachPort; успешный запуск Chromium потребовал разрешения вне sandbox. |
| Отдельная проверка PDF-скилла | `python3 /private/tmp/cap-vk-20261013/run-skill-e2e-014.py`, внутри `BASE_URL=http://127.0.0.1:18314 npm --prefix e2e test -- --workers=1 --grep 'bank PDF skill'` с временными credentials | [x] 1 passed, 0 failed, 0 skipped на отдельной PostgreSQL `cap-budget-acceptance-20261013-014-d`: popup открыт, скачанный Markdown совпадает с исходником. Это не отменяет сбой параллельной приёмки; см. TD-011. Временные Compose projects остановлены без удаления томов. |
| Восстановление на VM | `pg_restore --no-owner --no-acl --single-transaction --exit-on-error` в пустой `budget`; `python3 /opt/cap/recovery/verify-restored.py` до публикации | [x] Проверены 28 таблиц по одобренной копии от 6 октября; количества и MD5 отсортированных `row_to_json` совпали, кроме ожидаемого нового draft в `release_notes`. 3 пользователя, 8 счетов, 22 операции; схема 0012. Черновик сначала сохранён, затем опубликован после проверки работающей версии. Новые release note и 3 уведомления являются ожидаемыми изменениями служебных таблиц. |
| Production stack | `/opt/cap/deploy/run-production.sh --progress plain up -d --no-build --wait`; `ps -a` | [x] Native amd64 image 0.1.4; postgres и budget-app healthy, gateway работает, migrate exited 0. Запущены только postgres/budget-app/gateway. Порты PostgreSQL и приложения наружу не опубликованы; gateway слушает `127.0.0.1:8083`. |
| Публичные маршруты | Python `urllib` GET к `https://asimonov.space`: `/`, `/settings/`, `/budget/login`, `/apps.json`, `/api/v1/health/ready`, `/api/v1/auth/me`, `/api/v1/accounts`, `/photo`, `/photo/`, `/photo-api/health`, `/photo-api/auth/me`; отдельно `https://www.asimonov.space/` | [x] Обе HTTPS-версии главной отвечают 200 с проверкой доверенного сертификата; ready=ok; flags budget=1/photo=0; гостевой доступ к auth/accounts — 401; все фото-маршруты — 404. |
| Публичный браузер | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SUPERAPP_URL=https://asimonov.space EXPECT_BUDGET_ENABLED=1 EXPECT_PHOTO_ENABLED=0 node superapp/flags-browser-smoke.mjs`; отдельно Codex Browser | [x] Карточка бюджета видна, фото скрыто; оформление, сохранение настроек, меню при 320 px и переход ко входу прошли. В smoke добавлено ожидание инициализации radio и главной после переходов; прежние мгновенные проверки срабатывали до загрузки JS по сети. Реальный пользователь production не входил; рабочие финансовые данные этот прогон не изменяет. |
| SSL | `certbot certonly --webroot -w /var/www/letsencrypt -d asimonov.space -d www.asimonov.space --non-interactive --agree-tos --register-unsafely-without-email`; `nginx -t`; `systemctl is-active certbot.timer` | [x] Доверенный ECDSA сертификат до 2027-01-11, HTTP перенаправляется на HTTPS, timer активен, deploy hook проверяет и reload Nginx. HTTP-01 webroot доступен на 80 и 443. Первый production challenge для www не прошёл; повторный выпуск прошёл. |
| Продление SSL | `certbot renew --dry-run --no-random-sleep-on-renew --run-deploy-hooks` | [x] Exit 0: `all simulated renewals succeeded`; deploy hook выполнил успешный `nginx -t` и reload. Предыдущие тестовые challenges получили сетевые ошибки; перед итоговым прогоном webroot добавлен также на 443. Диагностическая попытка с timeout 150 секунд не дошла до проверки из-за случайной паузы Certbot 451 секунду; эта пауза отключена только флагом итогового теста. Штатный timer сохраняет стандартное поведение. Файлы результата и TCP-диагностики находятся в `/opt/cap/recovery/renewal-test.log` и `acme-network.log`. |
| Release note | Maintenance вызывает штатные обработчики draft/publish из миграционного контейнера | [x] 0.1.4 опубликован один раз, получено `delivered=3`; опубликованные записи не изменялись. Пароли существующих пользователей не сбрасывались, email не отправлялся. |

Ограничения: полной проверки RLS на PostgreSQL с финансовыми действиями двух
пользователей и входа настоящего пользователя на VM этот прогон не даёт.
Копия не содержит изменений после 6 октября. Облачные бэкапы и S3 не созданы.

## Минимальный отдельный стек: 2026-10-13

Проверено рабочее дерево поверх
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`; существующие незакоммиченные
изменения приложения сохранены. Корневой `cap` не имеет коммитов. Добавлены
`compose.production.yaml`, пример env и сценарии запуска/создания секретов;
логика приложения и схема базы в этом локальном прогоне не менялись. Прогон
выполнен до изменения версии пакетов на 0.1.4. Среда: macOS arm64,
локальный Node.js 26.4.0, Python backend 3.13.13, Docker Compose 5.1.3.
Docker-сборка использовала закреплённые Node 22.19.0 и Python 3.13.15.

| Проверка | Команда | Результат и границы |
| --- | --- | --- |
| Repository gates | `make lint test build` из `budget-planner/` | [x] Ruff/TypeScript, 128 backend и 89 frontend тестов, SPA build и Compose config прошли. Backend fixture использует SQLite; локальный Node отличается от закреплённого Docker Node. |
| Синтаксис новой конфигурации | `bash -n deploy/run-production.sh`; `python3 -m py_compile deploy/init-production-secrets.py`; `docker compose -f compose.production.yaml config --quiet` | [x] Прошли. При `PHOTO_ENABLED=0` активны postgres/migrate/budget-app/gateway; профиль `photo` добавляет фотосервисы. |
| Реальный запуск | `DOCKER_HOST=unix:///Users/asimonov05/.colima/default/docker.sock DOCKER_CONFIG=/private/tmp/cap-vk-20261013/docker CAP_ENV_FILE=/private/tmp/cap-vk-20261013/test.env deploy/run-production.sh --progress plain up -d --build --wait`, затем `up -d --no-build --wait` после исправлений конфигурации | [x] Проект `cap-minimal-check-20261013`, порт 18313, новая PostgreSQL. Устранены дублирующая сборка одного image tag и неверное разбиение tmpfs. Migration job завершился с кодом 0, backend и PostgreSQL healthy, шлюз отвечает. Фотосервисы не запущены. |
| Маршруты и авторизация | `python3 /private/tmp/cap-vk-20261013/check_runtime.py` | [x] Главная, настройки, вход и ready доступны; `/apps.json` содержит budget=1/photo=0; фото и его API отвечают 404. Тестовый владелец входит и выходит, второй пользователь сохраняет отдельную действующую сессию. Это API smoke, а не полный browser/E2E или доказательство всех RLS-сценариев. |
| Восстановление | Та же команда: `pg_restore --no-owner --no-acl --single-transaction --exit-on-error` в отдельную базу `cap_restore_*`, затем текущий migrate job | [x] Одобренная копия от 6 октября восстановлена. Количества строк во всех 28 таблицах совпали с `recovery/state.json`; контрольные суммы строк до и после текущих миграций совпали; схема 0012. Пользовательская рабочая база не использовалась. |

Полный `make acceptance`, авторизованные браузерные сценарии новой
production-конфигурации, проверка linux/amd64, HTTPS и фактическая выкладка
на новую облачную VM не подтверждаются этим архивным локальным прогоном;
актуальные результаты 0.1.4 приведены выше.

## Подсказки до выбора счёта: 2026-10-09

Проверено незакоммиченное дерево поверх
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`; ранее начатые правки
интерфейса, API и документации сохранены. Корневой `cap` не имеет коммитов.
Исправлена передача пустого `account_id` из формы подсказок и добавлен
регрессионный тест. API и схема базы не менялись. Среда: macOS arm64,
Python 3.13.13, Node.js 26.4.0, npm 12.1.0, Docker CLI 29.4.3 /
Engine 29.2.1, Compose 5.1.3, Playwright 1.63.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Воспроизведение и регрессия | `npm --prefix frontend test -- src/pages/Resources.test.tsx -t 'suggests operations by title before an account is selected'` до исправления; затем `npm --prefix frontend test -- src/pages/Resources.test.tsx` | [x] До исправления новый тест упал: запрос содержал `account_id=`. После исправления 25/25 тестов прошли: подсказка видна до выбора счёта, её выбор подставляет счёт; существующий тест подтверждает передачу выбранного счёта | DOM-тест использует mock API; общая сериализация пустых значений в `queryString` не менялась |
| Repository gates | `make lint`; `make test`; `make build` из `budget-planner/` | [x] Ruff и TypeScript прошли; 128 backend и 89 frontend тестов прошли; Vite build и Compose config прошли | Backend fixture использует SQLite; Vite предупредил о размере чанка и внешнем `/contour.css` |
| Изолированная приёмка | `DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-no-account-20261009-a SMOKE_PORT=18140 E2E_USERNAME=owner E2E_PASSWORD=<временный тестовый пароль> make acceptance` после `docker compose -p budget-no-account-20261009-a up -d --build --wait` и `docker compose -p budget-no-account-20261009-a exec -T app python -m app.cli init-admin` | [~] Новая PostgreSQL, миграция, `ready`, повторные lint/test/build прошли; Playwright: 3 passed, 2 failed, 0 skipped | Авторизованный мобильный «Обзор» снова вышел за 360 px (365 px, TD-010); тест PDF-скилла в этом прогоне превысил 30 с, ожидая popup. Проект остановлен, том сохранён |
| Браузерный путь подсказки | `docker compose -p budget-no-account-browser-20261009-b up -d --no-build --wait`; `docker compose -p budget-no-account-browser-20261009-b exec -T app python -m app.cli init-admin`; Python `urllib` создал счёт и расход; Playwright Chromium вошёл в `/transactions`, ввёл «Коф» до выбора счёта и выбрал «Кофе тест» | [x] Запрос подсказок без `account_id` ответил 200; подсказка появилась, выбор заполнил название и счёт | Отдельная disposable PostgreSQL и тестовый владелец; проект остановлен без удаления тома |
| Локальный cap space | `DOCKER_CONFIG=/private/tmp/cap-docker docker compose build budget-app`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --no-deps --force-recreate --wait budget-app`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose restart gateway`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Локальный бюджет healthy; `/`, `/budget/`, `/photo/` и оба API ответили 200; гостевой браузерный smoke прошёл | Существующая база и тома не пересоздавались; вход в локальную пользовательскую сессию не проверялся |

## Подсказки операций по названию: 2026-10-08

Проверено незакоммиченное дерево поверх
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`. До задачи уже были
изменения интерфейса и документации; корневой `cap` не имеет коммитов.
Изменены выборка подсказок, её backend-тест и проверка запроса из формы.
Схема базы не менялась. Среда: macOS arm64, Python 3.13.13, pytest 8.4.2,
Node.js 26.4.0, npm 12.1.0, Docker CLI 29.4.3 / Engine 29.2.1,
Compose 5.1.3, Playwright 1.63.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Узкие тесты | `backend/.venv/bin/python -m pytest -q backend/tests/test_transaction_suggestions.py`; `npm --prefix frontend test -- src/pages/Resources.test.tsx` из `budget-planner/` | [x] 5 backend и 24 frontend теста прошли; проверены точное название с другого счёта после 101 новых частичных совпадений и передача названия и счёта из формы | Backend fixture использует SQLite, frontend проверяет DOM и запрос с mock API |
| Repository gates | `make lint`; `make test`; `make build` из `budget-planner/` | [x] Ruff и TypeScript прошли; 128 backend и 88 frontend тестов прошли; Vite build и Compose config прошли | Vite предупредил о размере чанка; `/contour.css` разрешается шлюзом во время выполнения |
| Изолированная приёмка | `DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-title-suggestions-20261008-a SMOKE_PORT=18138 E2E_USERNAME=owner E2E_PASSWORD=<временный тестовый пароль> make acceptance` после `docker compose -p budget-title-suggestions-20261008-a up -d --build --wait` и `docker compose -p budget-title-suggestions-20261008-a exec -T app python -m app.cli init-admin` | [~] Новая PostgreSQL база, миграция, `ready` и повторные lint/test/build прошли; 5 браузерных сценариев не запустились из-за запрета macOS Mach port в песочнице | Это ошибка запуска Chromium до открытия страниц; проект остановлен, тестовый том сохранён |
| Live PostgreSQL API | `docker compose -p budget-title-suggestions-20261008-b up -d --no-build --wait`; `docker compose -p budget-title-suggestions-20261008-b exec -T app python -m app.cli init-admin`; Python `urllib` вызовы `POST /auth/login`, `POST /accounts`, 102 × `POST /transactions`, `GET /transactions/suggestions?query=Кофе&type=expense&account_id=…` | [x] 200/201; старый точный «Кофе» с другого счёта оказался первым после 101 новых «Кофейня …» с выбранного счёта | Использована отдельная одноразовая база и тестовый владелец; другие операции и типы проверены unit-тестами |
| Браузер вне песочницы | `BASE_URL=http://127.0.0.1:18139 E2E_USERNAME=owner E2E_PASSWORD=<временный тестовый пароль> PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 npm --prefix e2e test -- --workers=1` | [~] 4 passed, 1 failed, 0 skipped. Мобильный авторизованный «Обзор» имеет `document.scrollWidth=365` при viewport 360 px (TD-010) | Известный дефект компоновки вне области подсказок; проект остановлен без удаления тома |

## Удаление оформления из настроек бюджета: 2026-10-08

Проверено незакоммиченное дерево поверх
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`. До этой задачи в дереве уже
были изменения оформления cap space, `BankPdfGuide` и E2E; корневой `cap` не
имеет коммитов. Изменены страница настроек бюджета, её тест, CSS и текущая
документация; API и схема базы не менялись. Среда: macOS arm64,
Python 3.13.13 в venv бюджета, Node.js 26.4.0, npm 12.1.0,
Docker 29.4.3, Compose 5.1.3, Playwright 1.63.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Настройки бюджета | `npm --prefix frontend test -- src/pages/Settings.test.tsx` из `budget-planner/` | [x] 1 файл, 7 тестов прошли; пункт и радиокнопки оформления отсутствуют | DOM-тест не проверяет production сборку |
| Repository gates | `make lint`, `make test`, `make build` из `budget-planner/` | [x] Ruff и TypeScript прошли; 127 backend и 88 frontend тестов прошли; Vite build и Compose config прошли | Backend fixture использует SQLite; Vite предупредил о размере JS чанка |
| Сборка и переходы | `VITE_BASE_PATH=/budget/ npm --prefix budget-planner/frontend run build`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/appearance-integration-smoke.mjs` из корня `cap` | [x] Production сборка прошла; браузер с тестовой сессией открыл `/budget/settings` без оформления, общая тема действует в бюджете и фото | Тестовая авторизация подменена; реальные финансовые данные не использовались |
| Изолированная приёмка | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-no-appearance-20261008 SMOKE_PORT=18123 make -o lint -o test -o build acceptance` из `budget-planner/` | [~] Отдельная PostgreSQL, миграция и ready прошли; Playwright: 2 passed, 3 skipped; контейнеры остановлены без удаления тома | Gates пропущены в этом вызове, поскольку прошли отдельно выше. Тестового владельца не создавали; авторизованные сценарии пропущены |
| Локальный стенд | `DOCKER_CONFIG=/private/tmp/cap-docker docker compose build budget-app`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --no-deps --force-recreate --wait budget-app`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` из корня `cap` | [x] Контейнер бюджета healthy, гостевые переходы супераппа прошли | Реальный авторизованный экран после перезапуска не открывали; данные и тома не пересоздавались |

Неиспользуемые стили локального экрана оформления удалены. Ключи
`contour-*` и применение сохранённой темы в бюджете оставлены для работы
общих настроек cap space.

## Переименование интерфейса в cap space: 2026-10-08

Проверено незакоммиченное дерево бюджета поверх
`82db3f8e4cc6224a8546e2051857e51b831b6fd9`. До переименования в нём уже
были незакоммиченные изменения оформления, `BankPdfGuide` и E2E; корневой `cap`
не имеет коммитов. Среда: macOS arm64, Python 3.13.13 в venv бюджета,
Node.js 26.4.0, npm 12.1.0, Docker 29.4.3, Compose 5.1.3,
Playwright 1.63.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Изменённые экраны | `npm --prefix frontend test -- src/pages/Settings.test.tsx src/App.test.tsx src/components/Layout.test.tsx` из `budget-planner/` | [x] 3 файла, 15 тестов прошли | DOM-тесты не показывают компоновку |
| Repository gates | `make lint`, `make test`, `make build` из `budget-planner/` | [x] Ruff и TypeScript прошли; 127 backend и 88 frontend тестов прошли; Vite build и Compose config прошли | Backend fixture использует SQLite; Vite предупредил о размере JS чанка |
| Сборка супераппа | `VITE_BASE_PATH=/budget/ npm --prefix budget-planner/frontend run build` из корня `cap`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/appearance-integration-smoke.mjs` | [x] Сборка прошла; общий бренд и настройки проверены на собранных главной, входе бюджета и фоторазделе | Авторизация в интеграционном браузерном тесте подменена |
| Флаги и узкий экран | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SUPERAPP_SCREENSHOT_DIR=/private/tmp/cap-rename-screens python3 superapp/flags-smoke.py --browser` | [x] 70 HTTP проверок и 4 browser-сценария прошли; снимки 1280 и 320 CSS px просмотрены | Использованы временные шлюзы; реальные данные не менялись |
| Локальный стенд | `DOCKER_CONFIG=/private/tmp/cap-docker docker compose build budget-app`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --no-deps --force-recreate --wait budget-app`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Бюджет healthy; главная, оформление и общий гостевой вход показывают `cap space`; мобильная компоновка прошла | Реальный вход под учётной записью не проверялся; данные и тома не пересоздавались |

Технические ключи `contour-*` и названия CSS-файлов сохранены для совместимости
с выбором темы, сделанным до переименования. Архивную заметку релиза `0.1.3`
не переписывали.

## Общее оформление супераппа: 2026-10-07

Проверено рабочее дерево бюджета поверх `82db3f8e4cc6224a8546e2051857e51b831b6fd9`.
Дерево было грязным до этой задачи и остаётся грязным: кроме изменений оформления
в нём есть ранее начатая правка `BankPdfGuide` и E2E. Корневой `cap` пока не
имеет коммитов. Среда: macOS arm64, Python 3.13.13 в venv бюджета
(хостовый Python 3.14.5), Node.js 26.4.0, npm 12.1.0, Docker 29.4.3,
Compose 5.1.3, Playwright 1.63.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Тема и настройки бюджета | `npm --prefix budget-planner/frontend test -- src/lib/theme.test.tsx src/pages/Settings.test.tsx` | [x] 2 файла, 12 тестов прошли; включая перенос прежних ключей и событие другой вкладки | DOM-тесты не измеряют внешний вид |
| Repository gates | `make lint`, `make test`, `make build` из `budget-planner/` | [x] Ruff и TypeScript прошли; 127 backend и 88 frontend тестов прошли; Vite build и Compose config прошли | Backend fixture использует SQLite; сборка предупреждает о размере чанка |
| Сборки супераппа | `VITE_BASE_PATH=/budget/ npm --prefix frontend run build` из `budget-planner/`; `VITE_BASE_PATH=/photo/ VITE_API_BASE_URL=/photo-api VITE_SUPERAPP=1 npm --prefix frontend run build` из `photo-access/` | [x] Обе production сборки прошли | Общий CSS и JS разрешаются шлюзом во время выполнения; Vite предупреждает, что они отсутствуют внутри отдельных build contexts |
| Флаги и маршруты | `python3 superapp/flags-smoke.py`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SUPERAPP_SCREENSHOT_DIR=/private/tmp/cap-appearance-screens python3 superapp/flags-smoke.py --browser` | [x] 70 HTTP проверок и 4 гостевых browser-сценария прошли для всех сочетаний флагов | Использованы текущие backend контейнеры без изменения данных; временные шлюзы удалены |
| Переходы между приложениями | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/appearance-integration-smoke.mjs` после двух сборок выше | [x] Тёмная и системная темы, акцент и шрифт сохранились на главной, входе бюджета и фоторазделе при 360 CSS px; горизонтального переполнения нет | Авторизация в тесте подменена; реальная сессия и операции с PostgreSQL не проверялись |
| Изолированная приёмка бюджета | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-appearance-20261007-c SMOKE_PORT=18122 make -o lint -o test -o build acceptance` | [~] Отдельные PostgreSQL, миграция и ready прошли; Playwright: 2 passed, 3 skipped; проект остановлен без удаления тома | `lint`, `test`, `build` пропущены в этом вызове, поскольку прошли отдельно на финальном дереве. Тестового владельца не создавали, поэтому авторизованные сценарии пропущены |
| Локальный суперапп | `DOCKER_CONFIG=/private/tmp/cap-docker docker compose build budget-app photo-frontend`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --no-deps --force-recreate --wait budget-app photo-frontend`; `DOCKER_CONFIG=/private/tmp/cap-docker docker compose up -d --no-deps --force-recreate gateway`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Образы собраны, сервисы работают; `/`, `/appearance/`, CSS, JS, общий вход, фото и health отвечают 200; гостевой переход, оформление и 360 CSS px прошли | Локальные данные не пересоздавались. Реальный авторизованный сценарий после перезапуска не проверялся |

Визуально просмотрены снимки главной при 1280 и 320 CSS px и настроек при
320 CSS px. После просмотра исправлены длинные названия шрифтов и отступ
у ссылки оформления; повторный browser-прогон прошёл. Повышенная контрастность,
увеличение текста до 200% и измерение контраста каждой цветовой схемы остаются
непроверенными.

## Открытие и скачивание скилла из супераппа: 2026-10-06

Проверено незакоммиченное дерево поверх `82db3f8e4cc6224a8546e2051857e51b831b6fd9`.
Изменены `frontend/src/components/BankPdfGuide.tsx`, его unit-тесты и
`e2e/tests/budget-planner.spec.ts`. Ссылки используют базовый путь сборки:
`/skills/…` в отдельном бюджете и `/budget/skills/…` в супераппе. Версия
остаётся `0.1.3`, API и схема базы не менялись. Среда: macOS arm64,
Python 3.13.13, Node.js 26.4.0, npm 12.1.0, Docker 29.4.3/29.2.1,
Compose 5.1.3; Docker-сборка использовала закреплённый Node 22.19.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Регрессия ссылок | `npm --prefix frontend test -- src/components/BankPdfGuide.test.tsx` | [x] 4 passed; открытие и скачивание проверены для `/` и `/budget/` | Unit-тест проверяет ссылки и имя файла, а не HTTP |
| Repository gates | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker make lint test build` | [x] Ruff и TypeScript прошли; 127 backend и 86 frontend тестов прошли; production build и Compose config прошли | Backend fixture использует SQLite; Vite предупредил о размере JS чанка |
| Сборка супераппа | `VITE_BASE_PATH=/budget/ npm --prefix frontend run build`; `./e2e/node_modules/.bin/tsc --project e2e/tsconfig.json --noEmit` | [x] Production SPA с `/budget/` и TypeScript E2E прошли | Локальный Node 26 отличается от закреплённого Docker Node 22 |
| Изолированная приёмка | `python3 /private/tmp/cap-skill-links-acceptance.py`: disposable проект `budget-skill-links-20261006`, порт `18104`, отдельный тестовый владелец; `make -o lint -o test -o build acceptance` с уникальным `SMOKE_ENV` | [~] PostgreSQL/migration job/ready прошли; Playwright: 4 passed, 1 failed, 0 skipped. Скилл открылся в новой вкладке; скачанный Markdown побайтно совпал с исходным | Gates пропущены в этом make-вызове, поскольку уже прошли отдельной командой выше. Общая приёмка не зелёная: мобильный Обзор имеет ширину 365 px при viewport 360 px (TD-010). Контейнеры остановлены без удаления тома; пользовательская база не использовалась |

Дополнительно проверена схема сохранённой disposable базы:
`DOCKER_CONFIG=/private/tmp/cap-docker docker compose -p budget-skill-links-20261006 exec -T postgres psql -U budget -d budget -Atqc 'SELECT version_num FROM alembic_version;'`
вернул `0012`. Для чтения поднимался только тестовый PostgreSQL, после чего
проект снова остановлен без удаления тома.

На VM выложен функциональный commit `8d1b1114c0954868d3ee95f963ab56fde4f9fb32`
из `cap-superapp`: `docker compose build budget-app`, затем
`docker compose up -d --no-deps --wait --wait-timeout 90 budget-app` и
проверка/reload Nginx шлюза. Новый образ
`sha256:40509a2171804e4a9a634f9a9a078f4a83250cfd20651d4c4e712f661123bea4`
healthy; исходники и прежний образ сохранены для отката.

Публичная браузерная проверка
`PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node --input-type=module`
на `https://asimonov.space/budget/exchange` подтвердила: обе кнопки ведут на
`/budget/skills/bank-pdf-to-budget-csv/SKILL.md`, открытие показывает Markdown
в новой вкладке, скачивание даёт `bank-pdf-to-budget-csv-SKILL.md`, содержимое
побайтно совпадает с исходным. В браузере подменён только ответ `/auth/me`,
ассеты и Markdown получены с реальной VM; авторизация реальным аккаунтом
и финансовые операции на VM этим прогоном не проверялись. `ready` ответил
200; флаги остались `BUDGET_ENABLED=1`, `PHOTO_ENABLED=0`, фотораздел — 404.
Файл `.env` не изменялся при этой выкладке.

## VM после выкладки `0.1.3`: 2026-10-06

На VM запущен суперапп из приватного дерева `cap-superapp` с бюджетом `0.1.3`
и отдельным фоторазделом. Старая бюджетная установка и её PostgreSQL остались
на месте; публичный Nginx переключён на новый шлюз после сохранения dump,
конфига и откатного образа.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Сервис и схема | `docker compose up -d --no-build --pull never --wait` в новом проекте; `docker compose ps`; `python -c 'import app; print(app.__version__)'` | [x] Все сервисы healthy, budget `0.1.3`; photo migration `20261006000001_add_superapp_identity.sql`; S3 bucket доступен | Новый фотораздел использует пустую отдельную базу |
| Публичные guest-маршруты | GET `/`, `/budget/`, `/photo/`, `/api/v1/health/ready`, `/photo-api/health` и JS assets; `SUPERAPP_URL=http://178.154.244.20 PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node superapp/browser-smoke.mjs` | [x] Все страницы, ассеты и health ответили 200; гостевой браузерный переход и ширина 360 px прошли; API без сессии вернули 401 | Авторизованный вход с реальным аккаунтом на VM не выполнялся |
| Release note | Проверен сохранённый draft `0.1.3` | [~] Черновик создан до выкладки и остаётся `draft` | Публикация уведомления пользователям ожидает отдельного разрешения |


## Подготовка версии `0.1.3`: 2026-10-06

Проверено рабочее дерево поверх commit `664945b` с изменением версии в
`backend/app/__init__.py`, `backend/pyproject.toml`, `backend/uv.lock`,
`frontend/package.json` и `frontend/package-lock.json`. Функциональный код и
схема базы не менялись. Среда: macOS arm64, Python 3.13.13, Node.js 26.4.0,
Docker 29.4.3/29.2.1, Compose 5.1.3; Docker-сборка использовала Node 22.19.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Изолированная приемка | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-v013-20261006 SMOKE_PORT=18110 make acceptance` | [~] Ruff и TypeScript прошли; 127 backend и 84 frontend теста прошли; образ собран, PostgreSQL/migrate/ready прошли; 2 гостевых browser smoke прошли, 2 авторизованных пропущены | В disposable базе не создаётся владелец; контейнеры остановлены без удаления тома. Проверка VM и публикация release note ещё не входят в этот результат |


## Оформление бюджета по правилам Контура: 2026-10-06

Проверено незакоммиченное дерево поверх
`c322d7d844e3d2ea3ae09d80b7be137e42fff6e7`. Изменены интерфейсные файлы
`frontend/src/components/{AuthIntro,Layout,ui}.tsx`, `frontend/src/lib/theme.tsx`,
`frontend/src/pages/{Analytics,Dashboard,Login,Register,Settings}.tsx`, `frontend/src/main.tsx`, их
тесты и этот журнал; добавлены `frontend/src/contour.css` и
`frontend/src/components/ui.test.tsx`. Реестр долга дополнен пунктом TD-009.
Среда: macOS arm64, Python 3.13.13, Node.js 26.4.0, npm 12.1.0,
Docker 29.4.3, Compose 5.1.3, Playwright 1.63.0. Локальный Node отличается
от рекомендуемой версии 22; Docker-сборка использовала Node 22.19.0.

| Уровень | Команда / действие | Результат | Граница доказательства |
| --- | --- | --- | --- |
| Компоненты темы, настроек, меню и диалога | `npm --prefix frontend test -- src/lib/theme.test.tsx src/components/ui.test.tsx src/components/Layout.test.tsx src/pages/Settings.test.tsx` | [x] 4 файла, 14 тестов прошли; проверены новые значения по умолчанию и клавиатурное закрытие диалога с возвратом фокуса | Не измеряет реальные размеры и контраст в браузере |
| Обзор и аналитика | `npm --prefix frontend test -- src/pages/Dashboard.test.tsx src/pages/Analytics.test.tsx src/components/ui.test.tsx src/lib/theme.test.tsx` | [x] 4 файла, 6 тестов прошли после разделения акцентного и смысловых цветов | Цвета проверяются отдельно визуально |
| Repository gates | `make lint`, `make test`, `make build`; затем те же шаги внутри финального `make acceptance` | [x] Ruff и TypeScript прошли; 127 backend и 84 frontend теста прошли; Vite production build и `docker compose config --quiet` прошли на текущем дереве | Backend suite использует SQLite fixture; Vite предупредил о JS чанке 1 059,63 kB |
| Повторная проверка перед push | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-push-20261006 SMOKE_PORT=18101 make acceptance` | [~] 127 backend и 84 frontend теста прошли; сборка и ready в новом Compose-проекте прошли; 2 browser smoke passed, 2 skipped | Изолированный контур не создаёт владельца; контейнеры остановлены без удаления тома |
| Локальная визуальная проверка | `VITE_BASE_PATH=/budget/ npm run dev -- --host 127.0.0.1 --port 5174`; `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 node /private/tmp/budget-visual-check.mjs` | [x] На подменённых API-ответах просмотрены обзор при 1280 и 320 CSS px, тёмная тема, настройки при 320 px и гостевой вход. Горизонтального переполнения и ошибок страницы нет | Временный скрипт и снимки находятся в `/private/tmp`; этот прогон не проверяет реальные финансовые данные, увеличение текста, повышенный контраст и все страницы |
| Изолированная приёмка | `PATH=/private/tmp/cap-bin:$PATH DOCKER_CONFIG=/private/tmp/cap-docker PLAYWRIGHT_BROWSERS_PATH=/private/tmp/budget-planner-playwright-012 SMOKE_PROJECT=budget-contour-design-20261006-c SMOKE_PORT=18090 make acceptance` | [~] Docker-образ текущего дерева собран, отдельные PostgreSQL и migration job запущены, ready ответил; 2 гостевых Playwright-сценария прошли, 2 authenticated-сценария пропущены. Контейнеры остановлены без удаления тома | Тестовый владелец в отдельном проекте не создавался; `/private/tmp/cap-bin/curl` заменял отсутствующий системный `curl` |

Для закрытия визуальной приёмки остаются ручная или автоматизированная проверка
всех финансовых разделов с тестовым владельцем, увеличение текста до 200%,
режим повышенной контрастности и проверка согласованного выбора темы после
перехода в фотораздел.

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
