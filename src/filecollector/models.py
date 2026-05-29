class ItemData:
    def __init__(self, type_, path=None, content=None, force_absolute=False):
        self.type = type_
        self.path = path
        self.force_absolute = force_absolute
        self.content = content
