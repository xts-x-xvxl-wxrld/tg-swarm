def create_virtual_assistant():
    from .virtual_assistant import create_virtual_assistant as _create_virtual_assistant

    return _create_virtual_assistant()


__all__ = ["create_virtual_assistant"]
