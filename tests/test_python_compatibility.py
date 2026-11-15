"""Check production Python syntax even when development runs newer Python."""
import shutil,subprocess,unittest
from pathlib import Path
class ProductionPythonCompatibilityTests(unittest.TestCase):
    def test_production_sources_compile_on_python311(self):
        python=shutil.which('python3.11')
        if not python:self.skipTest('Python 3.11 not installed in this environment')
        root=Path(__file__).resolve().parents[1]
        script="""import pathlib,subprocess
paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],text=True).splitlines()
for path in paths:
    p=pathlib.Path(path)
    if p.suffix=='.py' and p.is_file() and not any(part.startswith('.') for part in p.parts):
        compile(p.read_bytes(),str(p),'exec')
"""
        result=subprocess.run([python,'-c',script],cwd=root,capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
