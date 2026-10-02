# Architecture Decision Records

ADR разделены на два слоя, чтобы бизнес-правила не смешивались с деталями
реализации.

## Бизнес-решения

- [ADR-001: исходное ограничение одновалютной реализации](adr/business/ADR-001-currency.md)
- [ADR-009: отдельные валютные остатки и фактический курс операции](adr/business/ADR-009-multicurrency.md)
- [ADR-004: неопределённость не превращается в ложную точность](adr/business/ADR-004-uncertainty.md)
- [ADR-005: совпадение не равно дублю](adr/business/ADR-005-duplicate-matching.md)
- [ADR-006: закрытый месяц содержит факт](adr/business/ADR-006-closed-month.md)
- [ADR-007: soft delete важнее физического удаления](adr/business/ADR-007-soft-delete.md)

## Технические решения

- [ADR-002: монолитный backend и отдельная БД](adr/tech/ADR-002-single-app-database.md)
- [ADR-003: ZIP — перенос данных; backup PostgreSQL — внешняя ответственность](adr/tech/ADR-003-backup-and-transfer.md)
- [ADR-008: тема — локальное предпочтение браузера](adr/tech/ADR-008-local-theme.md)
