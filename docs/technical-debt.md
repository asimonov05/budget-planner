# Реестр технического долга

Этот реестр хранит расхождения между принятыми ADR и текущей реализацией.
Каждая запись должна обновляться после проверки кода, тестов и документации.

## TD-007: мультивалютные цели, кредиты, лимиты и зарплата

**Статус:** open

**Проверено:** 2026-10-02

**Решение:** [ADR-009](adr/business/ADR-009-multicurrency.md)

### Текущее состояние — подтверждено

- `backend/app/models.py` хранит валюту у счёта и плановой статьи, обе суммы
  перевода и валюту/сумму покупки у факта. `backend/app/core/calculations.py`
  фильтрует прогноз по валюте счёта и плана.
- `backend/app/api/finance.py` допускает цель, связанный с кредитом план,
  лимит и кредитный платёж только в основной валюте бюджета;
  `backend/app/api/salary.py` ограничивает зарплатный счёт той же валютой.
  `backend/tests/test_multicurrency.py` проверяет отдельные остатки и прогноз
  для RUB/USD, межвалютный перевод и покупку; round-trip канонического ZIP с
  этими данными проверен в `backend/tests/test_api.py`.
- Интерфейс по умолчанию выводит валюты отдельно; настройка бюджета может
  включить ориентировочный общий итог по вручную сохранённым курсам.
  Будущие курсы не прогнозируются: во всех месяцах общего прогноза используется
  последний заданный курс, а фактические суммы сохраняются в валюте счёта.

### Целевое состояние

Цели, кредиты, лимиты и зарплата могут иметь явно заданную валюту, а все
связанные движения и прогнозы остаются согласованными внутри неё.

### Критерии закрытия

- Валюта явно сохранена у каждой перечисленной сущности и перенесена из
  основной валюты без изменения исторических сумм.
- Все связанные факты, графики, резервы и проверки лимитов используют одну
  валюту или явное конверсионное движение с сохранённым курсом.
- Тесты покрывают CRUD, прогноз, импорт/экспорт и изоляцию пользователей для
  каждой расширенной функции; ER-диаграмма и ADR актуализированы.

## TD-001: убрать backup/restore физической БД из приложения

**Статус:** resolved

**Проверено:** 2026-09-30

**Решение:** [ADR-003](adr/tech/ADR-003-backup-and-transfer.md)

### Текущее состояние — подтверждено

API `/backups`, UI-вкладка резервных копий и CLI-команды `backup`/`restore`
удалены. `BACKUP_DIR`, `/backups` и соответствующий Compose volume удалены.
Физический `pg_dump` выполняется снаружи backend по
[runbook](backup-restore.md). Канонический ZIP сохранён: 97 backend тестов
прошли, а импорт в пустой контур другого пользователя проверен на PostgreSQL
с переназначением ID. Пред- и постмиграционные дампы успешно восстановлены в
изолированные базы. Архивный
[acceptance-status](acceptance-status.md) описывает прежний runtime и не
является обещанием текущей функции backup в приложении.

### Целевое состояние

Приложение поддерживает только экспорт и импорт канонического ZIP финансовой
модели. Физический backup и восстановление PostgreSQL выполняются внешней
инфраструктурой и не управляются API, UI или CLI приложения.

### Критерии закрытия

- В приложении нет API, UI или CLI-команд для создания, скачивания и
  восстановления `.dump`/`.sqlite3` backup.
- Из конфигурации, контейнера и Compose удалены `BACKUP_DIR`, `/backups` и
  связанный volume, если они не используются другой функцией.
- README, архитектурные документы, acceptance-проверки и тесты не обещают и
  не проверяют application-managed backup/restore.
- ZIP export/import остаётся доступным; его существующий round-trip проверен
  после удаления legacy-механизма.

## TD-002: завершить готовность backend к нескольким экземплярам

**Статус:** in progress

**Проверено:** 2026-09-30

**Решение:** [ADR-002](adr/tech/ADR-002-single-app-database.md)

### Текущее состояние — подтверждено

- Compose теперь запускает одноразовый `migrate` job до API;
  `backend/app/start.py` проверяет текущую ревизию и обязательные свойства БД.
- В `backend/app/security.py` попытки входа и новой открытой регистрации
  ограничиваются process-local словарём `login_attempts`; лимит можно обойти
  переключением на другой экземпляр. Для регистрации успешная попытка также
  остаётся в минутном окне, но общий лимит на reverse proxy ещё не настроен.
- Сессии хранятся в общей БД. Advisory transaction lock использует стабильный
  namespace и `user_id`; проверено, что ключ одного владельца блокируется,
  а ключ другого доступен. Проверка двух API-реплик ещё не проведена.

### Целевое состояние

Backend можно запустить в нескольких экземплярах за reverse proxy без потери
авторизации, обхода rate limit и гонок миграций. PostgreSQL остаётся общим
production-хранилищем и источником общего состояния.

### Критерии закрытия

- Alembic выполняется отдельным одноразовым migration job до запуска backend,
  а реплики API не запускают миграции самостоятельно.
- Login и registration rate limit обеспечены reverse proxy с одинаковой
  политикой для всех экземпляров; process-local limiter удалён из backend.
- Production-конфигурация и runbook описывают readiness, rolling rollout и
  безопасное масштабирование backend.
- Интеграционная проверка подтверждает, что две реплики работают с одной БД:
  сессия и финансовая мутация корректны при попадании запросов в разные
  экземпляры.

## TD-003: удалить поддержку SQLite

**Статус:** in progress

**Проверено:** 2026-09-30

**Решение:** [ADR-002](adr/tech/ADR-002-single-app-database.md)

### Текущее состояние — подтверждено

- Docker entrypoint требует PostgreSQL URL и секрет; приложение в Compose
  использует только PostgreSQL. Физический SQLite backup/restore и старые
  `tenancy.py`/`migrate_sqlite_to_postgres.py` удалены.
- `backend/app/db.py`, `config.py` и `api/io.py` ещё содержат SQLite fallback
  для локального backend test suite.
- Alembic и модели содержат SQLite-специфичные условия и типы.
- Backend suite и benchmark по-прежнему используют SQLite fixture; целевые
  disposable PostgreSQL fixtures с изоляцией parallel worker ещё не введены.

### Целевое состояние

PostgreSQL — единственное поддерживаемое хранилище для runtime, разработки и
тестов. SQLite не является ни fallback, ни форматом backup/restore, ни
поддерживаемым источником миграции внутри приложения.

### Критерии закрытия

- Для запуска обязательны PostgreSQL `DATABASE_URL` и необходимые секреты;
  SQLite fallback и связанные переменные конфигурации удалены.
- Удалены SQLite-ветки runtime, CLI, Alembic, моделей и import/export,
  включая `migrate_sqlite_to_postgres.py`.
- Docker image, Compose, тесты и benchmark используют PostgreSQL; в
  поддерживаемой документации нет инструкций для SQLite.
- Test suite запускается на disposable PostgreSQL с изоляцией БД или схемы для
  каждого parallel worker; SQLite-fixtures отсутствуют.
- Полный backend test suite и миграции пройдены на изолированном PostgreSQL.

## TD-004: перейти от private budget databases к общей БД с `user_id`

**Статус:** resolved

**Проверено:** 2026-09-30

**Решение:** [ADR-002](adr/tech/ADR-002-single-app-database.md)

### Текущее состояние — подтверждено

- Рабочая установка перешла с `budget` + `budget_auth` на единственную базу
  `budget`: 30 сентября 2026 года migration job скопировал одного owner и
  сессии, применил Alembic `0007` и `0008`, после проверки старая БД удалена.
- Все 23 финансовые и user-scoped служебные таблицы имеют обязательный
  `user_id`, `FORCE RLS`, индексы и составные tenant FK. Ревизия `0008`
  добавила `FORCE RLS` для `sessions`: до аутентификации разрешён только поиск
  по hash текущего токена, после неё — операции текущего владельца; owner
  может отзывать сессии пользователей при управлении учётными записями.
  `users` остаётся глобальной таблицей identity для поиска логина.
- HTTP-процесс использует роль `budget_runtime` без DDL и `BYPASSRLS`;
  migration job — отдельную DDL-роль. Роль `debug_admin` имеет только
  диагностический `SELECT` и явную RLS-политику, панель скрыта для гостей и
  не-владельцев.
- `users.budget_database`, dynamic engines и provisioning private БД удалены.
  Канонический ZIP переназначает внутренние ID при импорте другому владельцу;
  self-service reset сохраняет identity и текущую сессию.
- На disposable PostgreSQL проверены свежая миграция, `0006 → 0007 → 0008`,
  совпадение schema metadata, RLS без scope/с чужим scope/после rollback и
  pool reuse, RLS сессий, составной FK между двумя пользователями и ZIP transfer.
  Контрольные количества строк до/после production cutover совпали; post-cutover
  dump восстановлен в отдельную БД. Backend suite: 97 passed; frontend: 59 passed.

### Целевое состояние

Все пользователи, сессии и финансовые данные находятся в одной PostgreSQL БД.
Каждая финансовая и user-scoped служебная запись содержит обязательный
`user_id`; backend получает владельца только из аутентифицированной сессии и
применяет его ко всем операциям.

### Критерии закрытия

- Alembic-миграция добавляет, backfill-ит и делает обязательным `user_id` у
  всех user-scoped таблиц; естественные и внешние уникальные ключи scoped по
  пользователю, например `(user_id, name)` для справочников и
  `(user_id, key)` для idempotency records.
- Доступ к данным всегда добавляет server-side `user_id` scope; входной
  `user_id` клиента не может расширять права. PostgreSQL RLS дублирует этот
  scope для финансовых и user-scoped служебных таблиц; роль приложения не
  может обходить политики. Backend устанавливает scope через `SET LOCAL` в
  каждой транзакции до первого user-scoped запроса.
- DDL выполняется отдельной migration-ролью. Runtime-роль не владеет
  user-scoped таблицами, не имеет `BYPASSRLS`, а таблицы используют `FORCE
  ROW LEVEL SECURITY`.
- Финансовая advisory lock вычисляется из стабильного namespace и server-side
  `user_id`, поэтому конкурентные операции разных пользователей не
  сериализуются между собой.
- Удалены `budget_database`, dynamic engines, provisioning и миграции private
  databases; исторические данные перенесены в общую БД.
- Тесты с двумя пользователями подтверждают изоляцию CRUD, агрегатов,
  импортов/экспортов и доступ по чужому числовому ID, включая отказ RLS для
  запроса без установленного user scope или с чужим scope, а также сброс scope
  после rollback и возврата соединения в пул.
- Канонический ZIP экспортирует только данные текущего пользователя; импорт
  требует пустоты только его финансового контура. Self-service reset удаляет
  только данные владельца, сохраняет его учётную запись и не затрагивает
  другого пользователя.
- Reset требует текущий пароль и фразу `RESET`, выполняется одной транзакцией
  и записывает audit-событие. Проверки покрывают успешный reset → ZIP import,
  неверное подтверждение и rollback без частично удалённых данных; все прочие
  сессии отозваны, а текущая может выполнить import.
- Проверка прав подтверждает, что runtime-роль не может обойти RLS, а
  migration-роль не используется HTTP-процессом.
- Debug-admin остаётся доступна только owner при включённом
  `DEBUG_ADMIN_ENABLED`, не видна другим пользователям и использует отдельный
  PostgreSQL `debug_admin`-роль с явной RLS-политикой, не расширяя права
  обычного runtime API и не используя `BYPASSRLS`.
- Конкурентная проверка подтверждает, что мутации одного пользователя
  сериализуются, а независимые мутации разных пользователей не ждут общий
  глобальный lock.
- После реализации обновлены `docs/database-schema.excalidraw`, документация
  миграции и тестовые сценарии.

## TD-005: декомпозировать backend на слои

**Статус:** open

**Проверено:** 2026-09-30

**Решение:** [ADR-002](adr/tech/ADR-002-single-app-database.md)

### Текущее состояние — подтверждено

- Роутеры `backend/app/api/finance.py`, `catalog.py`, `io.py` и `salary.py`
  одновременно обрабатывают HTTP, выполняют SQLAlchemy-запросы, изменяют
  транзакции и содержат прикладные правила.
- Новый `/budget/reset` вынесен в `presentation/reset_budget.py`, чистый
  `application/reset_budget.py` и SQLAlchemy-адаптер
  `infrastructure/reset_budget.py`; use case задаёт commit/rollback и
  проверен изолированными unit-тестами. Остальные критичные пути пока legacy.
- Регистрация размещена в `presentation/registration.py`,
  `application/register_user.py` и `infrastructure/register_user.py`:
  создание пользователя и сессии проходит одной транзакцией, новый
  пользователь всегда получает обычную роль. Legacy login остаётся в `api/auth.py`.
- `backend/app/core/calculations.py` и часть других `core`-модулей получают
  `Session` и SQLAlchemy-модели, поэтому не являются чистым domain-слоем.
- Общая композиция остальных application use cases, repository ports и
  Unit of Work providers пока не введена; критичные пути ещё не перенесены.

### Целевое состояние

Presentation, application и infrastructure разделены по ADR-002. Финансовые
правила тестируются в application без HTTP и БД; application use cases получают
owner context и порты репозиториев; SQLAlchemy остаётся infrastructure.

### Критерии закрытия

- Новые use cases размещаются в application-слое, а роутеры остаются тонкими:
  без финансовых правил, SQLAlchemy-запросов и `commit`.
- Прямые entity handlers также находятся в application, получают зависимости
  через DI и не обходят финансовые правила, owner scope или транзакционные
  инварианты use cases. Они применяются только к простым операциям одной
  сущности; межсущностные и финансово значимые сценарии оформлены use cases.
- Application-операции разделены на CQS commands и queries: query не меняет
  состояние, command возвращает минимальный результат. Отдельные read/write
  БД и event sourcing не вводятся.
- Application и infrastructure используют framework-neutral прикладные ошибки;
  HTTP-статусы и `HTTPException` создаются только в presentation.
- Application использует command/query/result DTO. Presentation переиспользует
  такой DTO при полном совпадении HTTP-контракта и создаёт отдельную
  transport-схему/адаптер только при реальном различии полей или семантики.
- Application DTO — immutable `dataclass`/typing-объекты без Pydantic;
  Pydantic остаётся в presentation.
- Критичные пути — финансовые мутации, forecast и ZIP import/export —
  перенесены постепенно, без big-bang переписывания.
- Введены пакеты `app/presentation`, `app/application` и
  `app/infrastructure`; новые возможности размещаются в них, а legacy-модули
  переносятся инкрементально с сохранением публичных контрактов.
- Финансовые правила в application не импортируют FastAPI, SQLAlchemy или
  инфраструктурную конфигурацию и имеют изолированные unit-тесты.
- Application определяет repository ports, а PostgreSQL/SQLAlchemy реализует
  их в infrastructure; owner context и Unit of Work передаются через DI.
- Presentation использует FastAPI `Depends` providers/stubs для сборки любого
  application- или infrastructure-класса; HTTP-тесты подменяют их через
  `dependency_overrides`, а application не импортирует FastAPI.
- `AsyncEngine`/pool создаются один раз на процесс, а `AsyncSession` и Unit of
  Work scoped на одну бизнес-транзакцию, закрываются после awaited
  commit/rollback и не переиспользуются между запросами.
- Repository ports предметные и узкие; `GenericRepository` и передача
  SQLAlchemy-моделей через application-контракты не допускаются.
- Бизнес-логика application явно определяет транзакционную границу: связанные
  изменения проходят одной транзакцией, а presentation не вызывает
  `commit`/`rollback` и не управляет `Session` напрямую.
- Полный backend test suite и архитектурные проверки подтверждают отсутствие
  запрещённых зависимостей в новых и перенесённых модулях.

## TD-006: перевести backend с sync на async I/O

**Статус:** open

**Проверено:** 2026-09-30

**Решение:** [ADR-002](adr/tech/ADR-002-single-app-database.md)

### Текущее состояние — подтверждено

- `backend/app/db.py` создаёт sync SQLAlchemy `Engine` и `SessionLocal`;
  HTTP API и security используют sync `Session`. Обработчики FastAPI с `def`
  исполняются в threadpool, а admin middleware явно выносит sync проверку в
  threadpool. Целевой `AsyncEngine`/`AsyncSession` ещё не введён.
- Отдельный `backend/app/migrate_job.py` использует sync `psycopg` 3 и
  Alembic вне API-процесса, как требует ADR.
- ZIP import/export остаётся sync кодом; его перенос в async infrastructure
  adapter и PostgreSQL-only test runtime ещё не выполнен.

### Целевое состояние

Backend runtime использует SQLAlchemy `AsyncEngine`/`AsyncSession` с async
dialect `psycopg` 3; HTTP dependencies, репозитории, use cases с I/O и внешние
адаптеры не блокируют event loop. Отдельный Alembic migration job использует
sync API того же `psycopg` 3 вне HTTP event loop.
Чистые финансовые расчёты без I/O остаются синхронными application-функциями.

### Критерии закрытия

- Production и test runtime используют async PostgreSQL stack `psycopg` 3;
  sync `Session` в runtime API отсутствует. Отдельный Alembic migration job
  использует sync API того же драйвера и не запускается в API-репликах.
- Unit of Work, RLS `SET LOCAL`, advisory lock, commit и rollback корректно
  awaited и покрыты интеграционными тестами.
- Роутеры и DI providers async там, где используют I/O; sync и async сессии не
  смешиваются в одном execution path.
- Blocking I/O вынесен в выделенные адаптеры или заменён async API; чистые
  CPU-расчёты не получают искусственный async wrapper.
- Полный backend test suite проходит на async PostgreSQL-конфигурации.
- Test runtime использует disposable PostgreSQL с изоляцией БД или схемы для
  parallel worker и прогоном Alembic до тестов.
