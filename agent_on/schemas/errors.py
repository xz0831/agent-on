RULES: dict[str, str] = {}


class SchemaError(ValueError):
    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule, self.detail = rule, detail
