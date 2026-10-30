"""Load application code with local OS dependencies, without spoofing the host.

These doubles verify application logic, not the native Windows ABI. The real
module and process-wide sys/os/ctypes objects are never patched or reloaded.
"""

import builtins
from pathlib import Path
import sys
from types import ModuleType


def load_with_imports(source_module, imports):
    name = f"_platform_test_{source_module.__name__.replace('.', '_')}"
    module = ModuleType(name)
    module.__file__ = source_module.__file__
    module.__package__ = source_module.__package__

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name in imports:
            return imports[name] if fromlist else imports[name.split('.')[0]]
        return builtins.__import__(name, globals, locals, fromlist, level)

    module.__dict__["__builtins__"] = dict(vars(builtins), __import__=local_import)
    # typing resolves annotations through sys.modules while creating NamedTuple.
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(Path(module.__file__).read_bytes(), module.__file__, "exec"), module.__dict__)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module
