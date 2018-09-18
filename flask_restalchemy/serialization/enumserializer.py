from .serializer import Serializer


class EnumSerializer(Serializer):

    def __init__(self, column):
        self.column = column

    def dump(self, value):
        if not value:
            return None
        return value.value

    def load(self, serialized):
        enum = getattr(self.column.type, 'enum_class')
        return enum(serialized)


def is_enum_field(col):
    return hasattr(col.type, 'enum_class') and getattr(col.type, 'enum_class')