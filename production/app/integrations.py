"""Real-provider integration entry points (production wiring)."""

from dataclasses import dataclass


@dataclass
class EmailProvider:
    api_key: str

    def send(self, to: str, subject: str, body: str) -> dict:
        # Replace with SendGrid/Mailgun implementation.
        return {"status": "queued", "to": to, "provider": "sendgrid_stub"}


@dataclass
class CRMProvider:
    api_key: str

    def upsert_contact(self, email: str, props: dict) -> dict:
        # Replace with HubSpot/Salesforce integration.
        return {"status": "ok", "email": email, "provider": "hubspot_stub"}


@dataclass
class CalendarProvider:
    provider: str

    def create_event(self, summary: str, when_iso: str) -> dict:
        # Replace with Google/Microsoft calendar integration.
        return {"status": "created", "summary": summary, "when": when_iso}


@dataclass
class BillingProvider:
    api_key: str

    def create_subscription(self, customer_email: str, plan: str) -> dict:
        # Replace with Stripe API call.
        return {"status": "active", "plan": plan, "email": customer_email, "provider": "stripe_stub"}
