"""Smoke HTTP para a stack de validação já migrada e semeada."""

import json
import os
from pathlib import Path

import httpx


def main():
    if os.getenv("VALIDATION_ONLY") != "1":
        raise SystemExit("Use apenas o projeto isolado de validação.")
    data = json.loads(Path("/app/data/e2e-credentials.json").read_text())
    with httpx.Client(base_url="http://backend:8000", timeout=10) as client:
        response = client.post(
            "/auth/login",
            json={
                "email": data["email"],
                "password": data["password"],
            },
        )
        assert response.status_code == 200, "Login HTTP falhou"
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.get("/auth/me", headers=headers).status_code == 200
        assert client.get("/auth/admin", headers=headers).status_code == 200
        assert client.post("/auth/logout", headers=headers).status_code == 204
        assert client.get("/auth/me", headers=headers).status_code == 401
    print("PASSOU: HTTP real de login, perfil, permissão e revogação de logout.")


if __name__ == "__main__":
    main()
