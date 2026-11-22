"""Conservative source policy. OS isolation remains the security boundary."""
from __future__ import annotations

import ast

SAFE_BUILTINS = {
    'abs', 'all', 'any', 'bool', 'bytes', 'dict', 'enumerate', 'float', 'int',
    'isinstance', 'len', 'list', 'max', 'min', 'range', 'repr', 'reversed', 'round',
    'set', 'sorted', 'str', 'sum', 'tuple', 'zip', 'ValueError', 'TypeError',
    'KeyError', 'IndexError', 'RuntimeError', 'AssertionError', 'Exception',
}
ASSERTIONS = {
    'assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse', 'assertIs',
    'assertIsNot', 'assertIsNone', 'assertIsNotNone', 'assertIn', 'assertNotIn',
    'assertIsInstance', 'assertNotIsInstance', 'assertRaises', 'assertRaisesRegex',
    'assertAlmostEqual', 'assertNotAlmostEqual', 'assertGreater', 'assertGreaterEqual',
    'assertLess', 'assertLessEqual', 'assertCountEqual', 'assertRegex', 'assertNotRegex',
    'assertDictEqual', 'assertListEqual', 'assertTupleEqual', 'assertSetEqual', 'fail',
}
UNSAFE_NAMES = {'eval', 'exec', 'compile', 'open', 'input', 'breakpoint', 'getattr', 'setattr',
                'delattr', 'vars', 'globals', 'locals', '__import__', 'type', 'object', 'super',
                'help', 'dir', 'exit', 'quit', 'classmethod', 'staticmethod', 'property'}
MODULE_ATTRIBUTES = {
    'sqlite3': {'connect', 'Error', 'IntegrityError', 'OperationalError'},
    'pathlib': {'PurePosixPath', 'PurePath', 'PureWindowsPath'},
    'json': {'loads', 'dumps', 'JSONDecodeError'},
    'collections': {'Counter', 'defaultdict', 'deque', 'namedtuple', 'OrderedDict'},
    'datetime': {'date', 'datetime', 'timedelta', 'timezone'},
    're': {'compile', 'match', 'fullmatch', 'search', 'sub', 'split', 'findall', 'escape',
           'IGNORECASE', 'MULTILINE', 'DOTALL'},
    'functools': {'reduce', 'partial', 'lru_cache', 'cache', 'wraps'},
    'itertools': {'permutations', 'combinations', 'product', 'chain', 'islice', 'repeat',
                  'count', 'cycle', 'accumulate', 'zip_longest'},
    'decimal': {'Decimal', 'Context', 'localcontext', 'getcontext'},
    'enum': {'Enum', 'IntEnum', 'auto'},
    'dataclasses': {'dataclass', 'field', 'asdict', 'replace'},
    'typing': {'Any', 'Optional', 'Union', 'List', 'Dict', 'Tuple', 'Set', 'Callable',
               'Iterable', 'Iterator', 'Mapping', 'Sequence', 'TypeVar'},
    'string': {'ascii_letters', 'ascii_lowercase', 'ascii_uppercase', 'digits', 'hexdigits',
               'punctuation', 'whitespace'},
}
OBJECT_ATTRIBUTES = {
    'execute', 'executemany', 'fetchone', 'fetchall', 'close', 'commit', 'rollback',
    'is_absolute', 'parts', 'name', 'suffix', 'stem', 'parent', 'as_posix',
    'add', 'clear', 'discard', 'get', 'items', 'keys', 'values', 'update', 'pop',
    'append', 'extend', 'insert', 'count', 'index', 'sort', 'reverse', 'copy',
    'strip', 'lstrip', 'rstrip', 'split', 'rsplit', 'splitlines', 'join', 'lower',
    'upper', 'casefold', 'startswith', 'endswith', 'isalnum', 'isdigit', 'encode',
    'decode', 'format', 'match', 'search', 'fullmatch', 'group', 'groups',
}
SAFE_IMPORTS = {
    'sqlite3', 'pathlib', 'math', 're', 'json', 'typing', 'collections', 'datetime',
    'functools', 'itertools', 'decimal', 'statistics', 'enum', 'dataclasses', 'string',
}
TEST_NODES = {
    ast.Module, ast.Import, ast.alias, ast.ClassDef, ast.FunctionDef, ast.arguments,
    ast.arg, ast.Expr, ast.Call, ast.Attribute, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.Assign, ast.AnnAssign, ast.Return, ast.Pass, ast.Assert,
    ast.With, ast.withitem, ast.If, ast.For, ast.Break, ast.Continue,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Subscript, ast.Slice,
    ast.UnaryOp, ast.BinOp, ast.BoolOp, ast.Compare, ast.keyword,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt,
    ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
}


def parse(source: str) -> ast.Module:
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > 200000:
        raise ValueError('source must be a nonempty string of at most 200000 bytes')
    tree = ast.parse(source)
    if sum(1 for _ in ast.walk(tree)) > 20000:
        raise ValueError('source is too complex')
    return tree


def public_functions(source: str) -> set[str]:
    return {node.name for node in parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith('_')}


def module_imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
    return names


def _dunders(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and (node.id.startswith('__') or node.id in UNSAFE_NAMES):
            raise ValueError('dunder names are forbidden')
        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
            raise ValueError('private and dunder attributes are forbidden')
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and '__' in node.value:
            raise ValueError('dunder strings are forbidden')


def validate_test_source(source: str, app_symbols: set[str] | None = None) -> None:
    tree = parse(source)
    _dunders(tree)
    assertion = False
    tests = 0
    for node in ast.walk(tree):
        if type(node) not in TEST_NODES:
            raise ValueError(f'test syntax is not allowed: {type(node).__name__}')
        if isinstance(node, ast.Import):
            if any(a.name not in {'unittest', 'app'} or a.asname for a in node.names):
                raise ValueError('imports are limited to: app, unittest, without aliases')
        if isinstance(node, ast.ClassDef):
            if (node.decorator_list or node.keywords or len(node.bases) != 1
                    or ast.unparse(node.bases[0]) != 'unittest.TestCase'):
                raise ValueError('only plain unittest.TestCase classes are allowed')
        if isinstance(node, ast.FunctionDef):
            if (node.decorator_list or node.returns or node.args.defaults or node.args.kw_defaults
                    or node.args.vararg or node.args.kwarg or node.args.kwonlyargs
                    or node.args.posonlyargs or len(node.args.args) != 1
                    or node.args.args[0].arg != 'self'
                    or not (node.name.startswith('test_') or node.name in {'setUp', 'tearDown'})):
                raise ValueError('only undecorated test methods with a self argument are allowed')
            tests += node.name.startswith('test_')
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for part in ast.walk(target):
                    if isinstance(part, (ast.Attribute, ast.Subscript)):
                        raise ValueError('test assignment must use local names')
                    if isinstance(part, ast.Name) and part.id in {'app', 'unittest', 'self'} | SAFE_BUILTINS:
                        raise ValueError('cannot rebind trusted names')
        if isinstance(node, ast.For):
            if not isinstance(node.target, ast.Name) or node.target.id in {'app', 'unittest', 'self'} | SAFE_BUILTINS:
                raise ValueError('loop target must be an unreserved local name')
        if isinstance(node, ast.withitem) and node.optional_vars is not None:
            raise ValueError('context manager aliases are outside the test policy')
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name):
                raise ValueError('chained attribute access is forbidden in tests')
            owner = node.value.id
            if owner == 'unittest' and node.attr != 'TestCase':
                raise ValueError('unittest internals are forbidden')
            if owner == 'self' and node.attr not in ASSERTIONS:
                raise ValueError('only assertion methods may be accessed on self')
            if owner == 'app' and (node.attr.startswith('_') or
                                      (app_symbols is not None and node.attr not in app_symbols)):
                raise ValueError('only target public functions may be called')
            if owner not in {'unittest', 'app', 'self'}:
                raise ValueError('unknown attribute owner')
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in SAFE_BUILTINS:
                    raise ValueError('unknown or unsafe builtin call')
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                owner = func.value.id
                if owner == 'self' and func.attr in ASSERTIONS:
                    assertion = True
                elif owner != 'app':
                    raise ValueError('unknown test call')
            else:
                raise ValueError('indirect calls are forbidden')
        if isinstance(node, ast.Assert):
            assertion = True
    if not assertion or not tests:
        raise ValueError('test needs a test method and an assertion')
    # Executable module/class bodies can otherwise alter names before discovery.
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ClassDef)):
            raise ValueError('test module body may only import and define classes')
        if isinstance(node, ast.ClassDef):
            if not all(isinstance(child, (ast.FunctionDef, ast.Pass)) for child in node.body):
                raise ValueError('test class body may only define methods')


def validate_patch_source(source: str, allowed_imports: set[str]) -> None:
    tree = parse(source)
    _dunders(tree)
    allowed = allowed_imports & SAFE_IMPORTS
    imported: set[str] = set()
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed:
                    raise ValueError('patch contains a forbidden import')
                imported.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split('.')[0] not in allowed:
                raise ValueError('patch contains a forbidden import')
            for alias in node.names:
                if (alias.name == '*' or alias.name.startswith('_')
                        or (node.module != 'math' and alias.name not in MODULE_ATTRIBUTES.get(node.module, set()))):
                    raise ValueError('wildcard/private imports are forbidden')
                imported.add(alias.asname or alias.name)
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda)):
            raise ValueError('dynamic or async code is outside the beta source policy')
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.decorator_list:
            raise ValueError('decorators are outside the beta source policy')
    module_aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_aliases.update({alias.asname or alias.name: alias.name for alias in node.names})
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in module_aliases:
                module = module_aliases[node.value.id]
                if module != 'math' and node.attr not in MODULE_ATTRIBUTES.get(module, set()):
                    raise ValueError('unknown module attribute')
            elif node.attr not in OBJECT_ATTRIBUTES:
                raise ValueError('unknown object attribute')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in SAFE_BUILTINS | imported | defined:
                raise ValueError(f'unknown or unsafe patch call: {node.func.id}')
        if isinstance(node, ast.Call) and not isinstance(node.func, (ast.Name, ast.Attribute)):
            raise ValueError('indirect calls are forbidden')
        if isinstance(node, ast.Attribute) and node.attr in {
            'system', 'popen', 'write_text', 'write_bytes', 'unlink', 'remove', 'rmdir',
            'rmtree', 'chmod', 'touch', 'mkdir', 'rename', 'replace', 'open', 'read_text', 'read_bytes',
        }:
            raise ValueError('filesystem/process operations are outside the beta source policy')
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in imported:
                    raise ValueError('cannot modify imported modules')
