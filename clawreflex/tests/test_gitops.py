import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from clawreflex.gitops import commit_proposal, git


class GitCommitTests(unittest.TestCase):
    def test_branch_commit_preserves_head_index_and_working_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            subprocess.run(['git','init','-q',str(root)],check=True)
            git(root,'config','user.name','Test');git(root,'config','user.email','test@example.invalid')
            target=root/'ordinary.py';target.write_text('def double(x): return x\n')
            git(root,'add','ordinary.py');git(root,'commit','-qm','baseline')
            head=git(root,'rev-parse','HEAD');index=git(root,'ls-files','-s');status=git(root,'status','--porcelain')
            raw=target.read_bytes();candidate='def double(x): return x*2\n'
            result=commit_proposal(root,'ordinary.py',candidate,hashlib.sha256(raw).hexdigest(),'run1','Verified repair')
            self.assertTrue(result['ok']);self.assertEqual(git(root,'rev-parse','HEAD'),head)
            self.assertEqual(git(root,'ls-files','-s'),index);self.assertEqual(git(root,'status','--porcelain'),status)
            self.assertEqual(target.read_bytes(),raw)
            self.assertEqual(git(root,'show',result['branch']+':ordinary.py').decode(),candidate)
            with self.assertRaises(ValueError):
                commit_proposal(root,'ordinary.py',candidate,hashlib.sha256(raw).hexdigest(),'run1','again')
            target.write_text('newer save')
            with self.assertRaises(ValueError):
                commit_proposal(root,'ordinary.py',candidate,hashlib.sha256(raw).hexdigest(),'run2','repair')

    def test_invalid_paths_and_secret_source_fail_before_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();target=root/'x.py';target.write_text('x=1')
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            for path,source in (('../escape.py','x=2'),('x.py','API_KEY="sk-abcdefghijklmnopqrstuv"')):
                with self.subTest(path=path),self.assertRaises(ValueError):
                    commit_proposal(root,path,source,digest,'run1','repair')


if __name__=='__main__':unittest.main()
