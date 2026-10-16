# Подпись «альфа 0.02»

27.09.2026 опубликована подпись версии серым шрифтом возле главного и компактного
логотипов. Единый текст — `app/web/templates/site_version.html`. В инженерные PDF
подпись не добавляется. Конфигурация исходных данных пока только обсуждается:
в этом выпуске поля, расчёты, данные проектов и API не менялись.

Проверки: 16 тестов навигации/оболочки; Ruff; git diff --check; визуально главная
и компактная шапка. Изолированный контейнер и production возвращают новый HTML
и версии CSS. App healthy; публичный HTTPS без пароля — 401.

Выпуск `/opt/zarya-releases/20260927-alpha002`, образ
`zarya-release:20260927-alpha002`, build id `ui-alpha002-20260927`.
База образа — предыдущий рабочий `zarya-release:20260926-408a8cfb8d69`;
зависимости сохранены. Обновлены только 7 файлов шаблонов/CSS.
SHA-256 source.tar.gz:
`4f2047c1e5473644610fe7900b5933bdd79d82725ada14a3b07828c274d3f488`.
Резервная копия `backup/projects.tar.gz`, SHA-256:
`f4104c00043771551b09022a4bf0d7a0340798ac9ac46eeb4e258dd86df960bf`.

Откат приложения (данные не откатывать):

```sh
previous=/opt/zarya-releases/20260926-studio-navigation
docker compose --env-file "$previous/.env" -p zarya \
  -f "$previous/compose.yaml" -f "$previous/release.override.yaml" \
  up -d --no-deps --no-build --wait --wait-timeout 90 app
ln -sfn "$previous" /opt/zarya-releases/current
```

Git-коммит/push не выполнялись.
