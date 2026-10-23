import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/director_pipeline.py'
SAMPLE=ROOT/'examples/hall-shot-09/director-contract.json'
class OutputSafetyTests(unittest.TestCase):
    def run_cli(self,*args):
        return subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True)
    def test_no_cut_cannot_overwrite_contract(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'contract.json';p.write_bytes(SAMPLE.read_bytes());before=p.read_bytes()
            r=self.run_cli('group',p,'--pagination','no-cut','--out',p,'--overwrite')
            self.assertEqual(r.returncode,2);self.assertIn('overwrite an input',r.stderr);self.assertEqual(p.read_bytes(),before)
    def test_no_cut_cannot_overwrite_window_input(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'windows.json';p.write_text('[]');before=p.read_bytes()
            r=self.run_cli('group',SAMPLE,'--pagination','no-cut','--windows',p,'--out',p,'--overwrite')
            self.assertEqual(r.returncode,2);self.assertIn('overwrite an input',r.stderr);self.assertEqual(p.read_bytes(),before)
    def test_hardlink_input_alias_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'contract.json';p.write_bytes(SAMPLE.read_bytes());q=Path(td)/'alias.json'
            try:os.link(p,q)
            except OSError:self.skipTest('hardlinks unavailable')
            r=self.run_cli('validate',p,'--out',q,'--overwrite')
            self.assertEqual(r.returncode,2);self.assertIn('overwrite an input',r.stderr);self.assertEqual(p.read_bytes(),SAMPLE.read_bytes())
