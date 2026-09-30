# Резервное копирование PostgreSQL

Все пользователи, сессии и бюджеты находятся в одной базе `budget`. Физический backup выполняется через PostgreSQL вне приложения. Канонический ZIP в интерфейсе переносит финансовые данные одного пользователя и не содержит учётных записей.

## Создание копии

```bash
mkdir -m 700 -p backups-external
docker compose exec -T postgres pg_dump -U budget -d budget -Fc --no-owner --no-acl > backups-external/budget.dump
docker compose exec -T postgres pg_restore --list < backups-external/budget.dump > /dev/null
```

`.dump` содержит финансовые данные, пароли в виде хешей и активные сессии. Храните его на другом носителе с ограниченным доступом и шифрованием. Каталог `backups-external` находится на хосте, а не в Compose volume приложения. Проверка списка объектов подтверждает читаемость файла, но не заменяет пробное восстановление.

## Проверка восстановления

Создайте отдельную пустую тестовую базу в PostgreSQL и восстановите копию туда:

```bash
docker compose exec -T postgres createdb -U budget budget_restore_test
docker compose exec -T postgres pg_restore -U budget --no-owner --no-acl --exit-on-error -d budget_restore_test < backups-external/budget.dump
docker compose exec -T postgres psql -U budget -d budget_restore_test -Atc 'SELECT version_num FROM alembic_version; SELECT count(*) FROM users; SELECT count(*) FROM accounts;'
```

Перед окончательным выводом об успешном восстановлении сравните контрольные суммы/количество строк по всем таблицам и выполните на тестовой базе авторизованный API smoke. Тестовую базу удаляйте только после проверки.

## Восстановление рабочей базы

Остановите API и миграционный job, сохраните свежую копию текущего состояния, затем восстановите совместимый dump. Для уже существующей базы:

```bash
docker compose stop app
docker compose exec -T postgres pg_restore -U budget --no-owner --no-acl --clean --if-exists --single-transaction --exit-on-error -d budget < backups-external/budget.dump
docker compose up -d --force-recreate migrate
docker compose up -d app
```

Убедитесь, что migration job завершился успешно, `health/ready` отвечает 200, а данные каждого пользователя доступны только ему. Старый образ нельзя запускать на более новой схеме без совместимого dump. Для расписания, ротации и удалённого хранения backup используйте инфраструктуру хоста.
