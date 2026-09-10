# Сервис аналитики

Отчёты и воронка. Подписан на весь поток событий по `#`, поэтому видит
систему целиком и ни от кого не зависит синхронно.

## Зависимости

| Пакет | Роль |
|---|---|
| [`mirea-contracts`](https://github.com/mireacrm/contracts-py) | сообщения и стабы gRPC |
| [`mireacrm-common`](https://github.com/mireacrm/py-common) | настройки, метрики, трасса, ошибки, база, события, gRPC |

Оба приезжают из своих репозиториев по версии из `pyproject.toml`.
Версию контрактов называет сервис, а не обвяз: два прямых URL одного
пакета pip считает конфликтом.

## Локально

```
pip install -e ".[dev]"
python -m pytest tests/unit -q
python -m pytest tests/integration -q   # нужен Postgres
docker build -t analytics-service .
```

Систему целиком поднимает [`mireacrm/deploy`](https://github.com/mireacrm/deploy).
