"""Owned vulnerable fixtures; reference repairs are withheld from the model."""
def fixture(name, nonce):
    if name == 'sql':
        identifier = nonce.replace('-', '_')
        code = f'''import sqlite3

def authenticate(username, password):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users_{identifier} (name TEXT, password TEXT)")
    db.executemany("INSERT INTO users_{identifier} VALUES (?, ?)", [("alice", "alice-pass"), ("o'brien", "quote-pass")])
    query = f"SELECT name FROM users_{identifier} WHERE name = '{{username}}' AND password = '{{password}}'"
    result = db.execute(query).fetchone()
    db.close()
    return result is not None
'''
        fixed = code.replace('query = f"SELECT name FROM users_' + identifier + ' WHERE name = \'{username}\' AND password = \'{password}\'"', 'query = "SELECT name FROM users_' + identifier + ' WHERE name = ? AND password = ?"').replace('db.execute(query).fetchone()', 'db.execute(query, (username, password)).fetchone()')
        regression = '''import unittest, app
class Regression(unittest.TestCase):
    def test_valid_login(self): self.assertTrue(app.authenticate("alice", "alice-pass"))
    def test_wrong_password(self): self.assertFalse(app.authenticate("alice", "wrong"))
    def test_unknown_user(self): self.assertFalse(app.authenticate("missing", "alice-pass"))
'''
        heldout = '''import unittest, app
class Hidden(unittest.TestCase):
    def test_quote_name(self): self.assertTrue(app.authenticate("o'brien", "quote-pass"))
    def test_password_injection(self): self.assertFalse(app.authenticate("missing", "' OR 1=1 --"))
    def test_username_injection(self): self.assertFalse(app.authenticate("' OR 1=1 --", "wrong"))
    def test_empty(self): self.assertFalse(app.authenticate("", ""))
'''
        return dict(title='SQL injection', file='auth.py', code=code, reference=fixed, regression=regression, heldout=heldout, contract='authenticate(username, password) returns True only for an exact valid credential pair. No SQL injection. Generate a unittest asserting an injection login is denied.')
    if name == 'path':
        code = '''from pathlib import PurePosixPath

def report_path(name):
    return str(PurePosixPath("/srv/reports") / name)
'''
        fixed = '''from pathlib import PurePosixPath

def report_path(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\\\" in name:
        raise ValueError("unsafe report path")
    return str(PurePosixPath("/srv/reports") / p)
'''
        regression = '''import unittest, app
class Regression(unittest.TestCase):
    def test_report(self): self.assertEqual(app.report_path("sales.csv"), "/srv/reports/sales.csv")
    def test_nested(self): self.assertEqual(app.report_path("2026/sales.csv"), "/srv/reports/2026/sales.csv")
'''
        heldout = '''import unittest, app
class Hidden(unittest.TestCase):
    def test_parent(self):
        with self.assertRaises(ValueError): app.report_path("../private.txt")
    def test_absolute(self):
        with self.assertRaises(ValueError): app.report_path("/etc/passwd")
    def test_deep_parent(self):
        with self.assertRaises(ValueError): app.report_path("2026/../../private")
    def test_empty(self):
        with self.assertRaises(ValueError): app.report_path("")
    def test_backslash(self):
        with self.assertRaises(ValueError): app.report_path("..\\\\private")
'''
        return dict(title='Path traversal', file='reports.py', code=code, reference=fixed, regression=regression, heldout=heldout, contract='report_path(name) returns a POSIX path inside /srv/reports. Reject empty, absolute, parent traversal and backslash paths with ValueError. Generate a unittest proving parent traversal is rejected.')
    if name == 'ledger':
        code = '''BALANCE = 100
SEEN = set()

def reset():
    global BALANCE
    BALANCE = 100
    SEEN.clear()

def charge(request_id, amount):
    global BALANCE
    if amount <= 0 or amount > BALANCE:
        raise ValueError("invalid amount")
    BALANCE -= amount
    SEEN.add(request_id)
    return {"charged": True, "balance": BALANCE}
'''
        fixed = code.replace('    if amount <= 0 or amount > BALANCE:', '    if request_id in SEEN:\n        return {"charged": False, "balance": BALANCE}\n    if amount <= 0 or amount > BALANCE:')
        regression = '''import unittest, app
class Regression(unittest.TestCase):
    def setUp(self): app.reset()
    def test_charge(self): self.assertEqual(app.charge("a", 20), {"charged":True,"balance":80})
    def test_overdraft(self):
        with self.assertRaises(ValueError): app.charge("b", 200)
    def test_negative(self):
        with self.assertRaises(ValueError): app.charge("c", -5)
'''
        heldout = '''import unittest, app
class Hidden(unittest.TestCase):
    def setUp(self): app.reset()
    def test_retry(self):
        app.charge("a",20)
        self.assertEqual(app.charge("a",20), {"charged":False,"balance":80})
    def test_full_retry(self):
        app.charge("a",100)
        self.assertEqual(app.charge("a",100), {"charged":False,"balance":0})
    def test_distinct(self):
        app.charge("a",20)
        self.assertEqual(app.charge("b",30), {"charged":True,"balance":50})
'''
        return dict(title='Duplicate charge', file='ledger.py', code=code, reference=fixed, regression=regression, heldout=heldout, contract='charge(request_id, amount) must be idempotent. Repeated request_id returns charged=False and unchanged balance even if the original emptied it. Keep amount validation. Generate a unittest proving retry does not debit twice; call app.reset() first.')
    raise ValueError('unknown fixture')
