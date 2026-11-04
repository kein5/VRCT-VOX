"""Request-local history with its in-memory destination generation."""


class TranslationHistory(list):
    def __init__(self, items, generation):
        super().__init__(items)
        self.generation = generation
