class BaseProcessor:
    def process(self, value: int) -> int:
        return value


class ChildProcessor(BaseProcessor):
    def process(self, value: int) -> int:
        return super().process(value) + 1
