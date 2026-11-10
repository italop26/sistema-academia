import argparse
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.core.errors import ApplicationError
from app.modules.users.repositories import UserRepository
from app.modules.users.schemas import AdminCreate
from app.modules.users.services import UserService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cadastrar o administrador inicial")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Use um terminal interativo para digitar a senha com segurança.", file=sys.stderr)
        return 1
    try:
        password = getpass.getpass("Senha (12 a 128 caracteres): ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            print("As senhas não coincidem.", file=sys.stderr)
            return 1
        data = AdminCreate(name=args.name, email=args.email, password=password)
        with Session(get_engine()) as session:
            UserService(UserRepository(session)).bootstrap_admin(data)
    except ValidationError:
        print("Dados inválidos: confira nome, e-mail e tamanho da senha.", file=sys.stderr)
        return 1
    except ApplicationError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Falha ao acessar o banco. Verifique a conexão e execute as migrações.", file=sys.stderr
        )
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCadastro cancelado.", file=sys.stderr)
        return 1
    print("Administrador inicial cadastrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
