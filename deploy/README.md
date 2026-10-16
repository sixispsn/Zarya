# Размещение Zarya на VPS

> Рабочий сервер обновлён 14.10.2026 отдельным проверенным снимком ВУ.
> Актуальная конфигурация: `/opt/zarya-releases/current`;
> журнал последней выкладки и откат: `docs/deployment_2026-10-14_metering_nodes.md`;
> предыдущая публикация воды и К1: `docs/deployment_2026-10-07_vk_delivery.md`.
> Теперь один вход по персональному ключу, приглашения через `/access/admin`.
> Общий Basic Auth снят; инструкции о нём ниже — исторические для отката.
> Перед новым запуском создайте владельца по `docs/closed_pilot_access_2026-09-27.md`
> и включите `ZARYA_PILOT_ENABLED=1`; без него Compose закрывает доступ (503).
> Старый checkout `/opt/Zarya` оставлен для отката — не обновлять из него
> контейнер командой ниже, пока снимок не перенесён в Git-релиз.

Схема: домен → Caddy (HTTPS) → FastAPI (персональный вход). Проекты, загруженные планы АР
и подтверждённые привязки К1/К2 хранятся в именованном Docker-томе
`zarya_projects` и не пропадают при обновлении контейнера.

## 1. Подготовить домен

В DNS домена создать A-запись:

```text
Имя: zarya (или @ для основного домена)
Значение: публичный IPv4 сервера
TTL: 300
```

Открыть на сервере входящие TCP-порты 22, 80 и 443, а также UDP-порт 443.
Порт 8000 наружу открывать не нужно.

## 2. Подготовить сервер

Подключиться по SSH под созданным провайдером пользователем и установить
Docker Engine с Compose Plugin по официальной инструкции Docker для Ubuntu.
Затем клонировать репозиторий:

```bash
git clone https://github.com/sixispsn/Zarya.git
cd Zarya
cp .env.example .env
chmod 600 .env
```

## 3. Создать пароль

Сначала придумать или сгенерировать пароль и сразу сохранить его в менеджере
паролей как запись `Zarya — <домен>`. Сам пароль в `.env` и Git не записывается.

Получить bcrypt-хеш интерактивно — ввод не отображается:

```bash
docker run --rm -it caddy:2-alpine caddy hash-password --algorithm bcrypt
```

Открыть `.env`:

```bash
nano .env
```

Заполнить домен, логин и вставить полученный хеш в одинарных кавычках:

```dotenv
ZARYA_DOMAIN=zarya.example.ru
ZARYA_USERNAME=zarya
ZARYA_PASSWORD_HASH='$2a$14$...'
ZARYA_HARD_QUALITY_GATES=0
```

## 4. Запустить

```bash
export ZARYA_BUILD_COMMIT=$(git rev-parse HEAD)
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

Когда DNS-запись начнёт указывать на сервер, Caddy автоматически получит
TLS-сертификат. Сайт откроется по `https://<домен>` и запросит логин с
паролем.

## Обновление

```bash
git pull --ff-only
export ZARYA_BUILD_COMMIT=$(git rev-parse HEAD)
docker compose up -d --build
docker image prune -f
```

`ZARYA_BUILD_COMMIT` встраивается в образ и попадает в цифровой паспорт
выпуска. После запуска значение можно проверить командой:

```bash
docker compose exec app printenv ZARYA_BUILD_COMMIT
```

`ZARYA_HARD_QUALITY_GATES=0` оставляет пострасчётные ворота в контрольном
режиме: красные замечания видны, но комплект можно исследовать. Значение `1`
запрещает публикацию цифрового паспорта при любом красном результате. Его
следует включать после того, как контрольный проект проходит все семь ворот.

## Резервная копия проектов

Создать архив в текущей папке:

```bash
docker run --rm \
  -v zarya_zarya_projects:/data:ro \
  -v "$PWD":/backup \
  alpine tar -czf /backup/zarya-projects-$(date +%F).tar.gz -C /data .
```

Имя тома может отличаться, если папка проекта на сервере называется не
`Zarya`. Точное имя показывает команда:

```bash
docker volume ls
```

Папку с кодом можно удалить и клонировать заново, но том проектов и том
сертификатов Caddy удалять нельзя. Не выполнять `docker compose down -v`,
если не требуется намеренно удалить все данные.
