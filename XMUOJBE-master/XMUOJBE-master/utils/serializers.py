from rest_framework import serializers

from options.options import SysOptions


class InvalidLanguage(serializers.ValidationError):
    def __init__(self, name):
        super().__init__(detail=f"{name} is not a valid language")


class LanguageNameChoiceField(serializers.CharField):
    def __init__(self, **kwargs):
        self.visible_only = kwargs.pop("visible_only", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        names = SysOptions.visible_language_names if self.visible_only else SysOptions.language_names
        if data and data not in names:
            raise InvalidLanguage(data)
        return data


class SPJLanguageNameChoiceField(serializers.CharField):
    def __init__(self, **kwargs):
        self.visible_only = kwargs.pop("visible_only", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        names = SysOptions.visible_spj_language_names if self.visible_only else SysOptions.spj_language_names
        if data and data not in names:
            raise InvalidLanguage(data)
        return data


class LanguageNameMultiChoiceField(serializers.ListField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        for item in data:
            if item not in SysOptions.language_names:
                raise InvalidLanguage(item)
        return data


class SPJLanguageNameMultiChoiceField(serializers.ListField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        for item in data:
            if item not in SysOptions.spj_language_names:
                raise InvalidLanguage(item)
        return data
