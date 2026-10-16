"""Run: python -m scripts.pilot_access --help. Never pass keys on a command line."""
import argparse
import json
import os
from pathlib import Path

from app.intake.pilot_access import AccessStore


def main():
    parser = argparse.ArgumentParser(description="Персональные ключи закрытой альфы ЗАРИ")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="Создать участника или заменить его ключ")
    issue.add_argument("--name", required=True)
    issue.add_argument("--role", choices=["tester", "admin"], default="tester")
    issue.add_argument("--days", type=int, default=30)
    issue.add_argument("--user-id", help="Сохранить проекты существующего участника, отозвать прежний ключ/сессии")
    issue.add_argument("--output", type=Path, required=True, help="Новый закрытый файл для ключа, не stdout")
    sub.add_parser("list", help="Список участников без секретов")
    revoke = sub.add_parser("revoke", help="Отозвать ключ и все сессии; проекты не удаляются")
    revoke.add_argument("user_id")
    args = parser.parse_args()
    access = AccessStore()
    if args.command == "list":
        print(json.dumps(access.list_users(), ensure_ascii=False, indent=2))
    elif args.command == "revoke":
        access.revoke(args.user_id)
        print("Доступ отозван. Проекты сохранены.")
    else:
        # O_EXCL prevents accidental overwrite; secrets never enter shell history,
        # argv, request URLs, CLI stdout or server logs.
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as output:
            uid, key = access.issue(args.name, role=args.role, days=args.days, user_id=args.user_id)
            output.write(key + "\n")
        print(f"Участник: {uid}. Ключ сохранён в закрытом файле {args.output}.")


if __name__ == "__main__":
    main()
