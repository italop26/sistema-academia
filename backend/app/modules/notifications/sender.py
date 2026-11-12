from dataclasses import dataclass
from datetime import date

SIMULATION_NOTICE = "SIMULAÇÃO — NENHUMA MENSAGEM REAL FOI ENVIADA"


@dataclass(frozen=True)
class ReminderMessage:
    reminder_id: str
    monthly_fee_id: str
    amount_cents: int
    due_on: date


@dataclass(frozen=True)
class Delivery:
    receipt: str
    message: str


class SimulatedReminderSender:
    """No network, email address or messaging SDK. Output is committed locally by the service."""

    def send(self, data: ReminderMessage) -> Delivery:
        return Delivery(
            receipt=f"TEST-REMINDER-{data.reminder_id}",
            message=f"{SIMULATION_NOTICE}. Mensalidade {data.monthly_fee_id}, "
            f"valor {data.amount_cents} centavos, vencimento {data.due_on.isoformat()}.",
        )
