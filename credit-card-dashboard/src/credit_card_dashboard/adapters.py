from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IssuerAdapter:
    issuer_key: str
    issuer_name: str
    portal_label: str
    statement_mode: str
    payment_mode: str
    supports_statement_credentials: bool
    supports_payment_credentials: bool
    statement_notes: str
    payment_notes: str


ADAPTERS: dict[str, IssuerAdapter] = {
    "american-express": IssuerAdapter(
        issuer_key="american-express",
        issuer_name="American Express",
        portal_label="Amex Online Services",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Statements can be requested and tracked, then uploaded after local portal download.",
        payment_notes="Payment approvals are staged for manual confirmation against the issuer portal.",
    ),
    "chase": IssuerAdapter(
        issuer_key="chase",
        issuer_name="Chase",
        portal_label="Chase Credit Journey",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Connector-ready credentials can be stored locally, but statement files remain manually imported.",
        payment_notes="Approvals queue a payment task and retain masked credentials for later local execution.",
    ),
    "citi": IssuerAdapter(
        issuer_key="citi",
        issuer_name="Citi",
        portal_label="Citi Cards",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Citi requests are tracked as local tasks until the statement PDF is uploaded.",
        payment_notes="Payment requests move through approval and manual-confirmation states.",
    ),
    "capital-one": IssuerAdapter(
        issuer_key="capital-one",
        issuer_name="Capital One",
        portal_label="Capital One Cards",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Capital One statements are managed as upload-backed lifecycle records.",
        payment_notes="Capital One payment approvals create ready-to-pay tasks for a local operator.",
    ),
    "discover": IssuerAdapter(
        issuer_key="discover",
        issuer_name="Discover",
        portal_label="Discover Card Services",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Discover requests rely on local credential hints and statement upload completion.",
        payment_notes="Discover payment requests require approval before local confirmation.",
    ),
    "bank-of-america": IssuerAdapter(
        issuer_key="bank-of-america",
        issuer_name="Bank of America",
        portal_label="Bank of America Cards",
        statement_mode="manual-upload",
        payment_mode="manual-confirmation",
        supports_statement_credentials=True,
        supports_payment_credentials=True,
        statement_notes="Bank of America statements are imported as local artifacts after portal download.",
        payment_notes="Payments are approved inside the app and confirmed locally against the bank site.",
    ),
}

DEFAULT_ADAPTER = IssuerAdapter(
    issuer_key="generic-bank",
    issuer_name="Generic Bank",
    portal_label="Issuer Portal",
    statement_mode="manual-upload",
    payment_mode="manual-confirmation",
    supports_statement_credentials=True,
    supports_payment_credentials=True,
    statement_notes="This issuer uses the generic manual statement lifecycle.",
    payment_notes="This issuer uses the generic manual payment lifecycle.",
)


def normalize_issuer_key(issuer_name: str) -> str:
    lowered = issuer_name.strip().lower()
    aliases = {
        "american express": "american-express",
        "amex": "american-express",
        "chase": "chase",
        "citi": "citi",
        "citibank": "citi",
        "capital one": "capital-one",
        "discover": "discover",
        "bank of america": "bank-of-america",
        "boa": "bank-of-america",
    }
    return aliases.get(lowered, lowered.replace(" ", "-"))


def get_adapter(issuer_name: str) -> IssuerAdapter:
    return ADAPTERS.get(normalize_issuer_key(issuer_name), DEFAULT_ADAPTER)
