"""One catalog for public checkout; old adapters are settlement-only."""
PAYMENT_AGENTS = ("yookassa", "rollypay", "platega", "cryptobot", "freekassa", "cloudpayments", "lava", "pal24", "mulenpay")

PROVIDER_CAPABILITIES = {
    "yookassa": {"cards": True, "recurring": True, "refunds": True},
    "rollypay": {"cards": True, "recurring": False, "refunds": True},
    "platega": {"cards": True, "recurring": False, "refunds": True},
    "cryptobot": {"cards": False, "recurring": False, "refunds": False},
    "freekassa": {"cards": True, "recurring": False, "refunds": False},
    "cloudpayments": {"cards": True, "recurring": False, "refunds": False},
    "lava": {"cards": True, "recurring": False, "refunds": False},
    "pal24": {"cards": True, "recurring": False, "refunds": False},
    "mulenpay": {"cards": True, "recurring": False, "refunds": False},
}


def routing_names(sandbox_allowed: bool) -> set[str]:
    return set(PAYMENT_AGENTS) | ({"sandbox"} if sandbox_allowed else set())
