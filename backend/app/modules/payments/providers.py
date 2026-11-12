from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import ApplicationError

SIMULATION_NOTICE = "SIMULAÇÃO — NÃO REALIZA PAGAMENTO"
SIMULATED_PROVIDER = "simulated_pix"


@dataclass(frozen=True)
class ChargeRequest:
    charge_id: str
    monthly_fee_id: str
    amount_cents: int
    currency: str
    expires_at: datetime


@dataclass(frozen=True)
class ProviderCharge:
    reference: str
    expires_at: datetime


class PixProvider(Protocol):
    name: str
    is_simulated: bool

    def create_charge(self, request: ChargeRequest) -> ProviderCharge: ...


class SimulatedPixProvider:
    """Local, deterministic test adapter. Does not generate EMV/QR or contact a bank."""

    name = SIMULATED_PROVIDER
    is_simulated = True

    def create_charge(self, request: ChargeRequest) -> ProviderCharge:
        return ProviderCharge(
            reference=f"TEST-PIX-{request.charge_id}",
            expires_at=request.expires_at,
        )


def get_pix_provider() -> PixProvider:
    settings = get_settings()
    if settings.app_env == "production" or not settings.pix_simulator_enabled:
        raise ApplicationError("pix_simulator_disabled", "Simulador Pix desativado.", 404)
    return SimulatedPixProvider()
