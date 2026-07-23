# Размещение Zarya на VPS

Схема: домен → Caddy (HTTPS и пароль) → FastAPI. Проекты хранятся в
именованном Docker-томе `zarya_projects` и не пропадают при обновлении
контейнера.

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
```

## 4. Запустить

```bash
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
docker compose up -d --build
docker image prune -f
```

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
