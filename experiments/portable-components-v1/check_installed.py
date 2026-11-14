# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Run pinned public assertions against installed code, with per-method records."""
import argparse,hashlib,importlib,importlib.metadata,json,os,sys,traceback,unittest
from pathlib import Path

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--group',required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(a.suite.read_text());spec=cfg['groups'][a.group]
    report={'status':'running','group':a.group,'commit':cfg['commit'],'scope':spec['scope'],'expected_methods':spec['count'],'checks':[],'origins':{},'failures':[]}
    def save():(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    save()
    try:
        if Path.cwd().resolve().is_relative_to(source):raise AssertionError('run must be outside checkout')
        for name,sha in cfg['files'].items():
            if digest(source/name)!=sha:raise AssertionError('pinned source mismatch: '+name)
        report['source_files_checked']=len(cfg['files'])
        assert importlib.metadata.version('teleion-fabric')==cfg['version']
        import teleion_fabric,stepkit,numpy,scipy
        dist=importlib.metadata.distribution('teleion-fabric')
        for name,sha in cfg['files'].items():
            if name.startswith('src/'):
                installed=Path(dist.locate_file(name[4:])).resolve()
                assert installed.is_relative_to(Path(sys.prefix).resolve()),str(installed)
                assert not installed.is_relative_to(source),str(installed)
                assert digest(installed)==sha,'installed bytes mismatch: '+name
        report['distribution']={'version':dist.version,'direct_url':json.loads(dist.read_text('direct_url.json')),'python':sys.version,'prefix':sys.prefix,'numpy':numpy.__version__,'scipy':scipy.__version__,'dependency_origins':{m.__name__:m.__file__ for m in [numpy,scipy]}}
        from teleion_fabric.context import packet
        context,manifest=packet(spec['scope']);(out/'context.txt').write_text(context);(out/'context-manifest.json').write_text(json.dumps(manifest,indent=2))
        def deny_network(event,args):
            if event in {'socket.connect','socket.getaddrinfo'}:raise RuntimeError('network disabled during behavioral checks')
        sys.addaudithook(deny_network)
        sys.path[:0]=[str(source/'tests'),str(source/'experiments/composition-recovery-v1')]
        loader=unittest.TestLoader();suite=unittest.TestSuite()
        for module,names in spec['tests'].items():
            imported=importlib.import_module(module)
            suite.addTests(loader.loadTestsFromModule(imported) if names is None else loader.loadTestsFromNames(names,imported))
        assert not loader.errors,loader.errors
        report['discovered_methods']=suite.countTestCases()
        assert suite.countTestCases()==spec['count'],report
        class Result(unittest.TextTestResult):
            def addSuccess(self,t):super().addSuccess(t);report['checks'].append({'id':t.id(),'status':'pass'});save()
            def addFailure(self,t,err):super().addFailure(t,err);report['checks'].append({'id':t.id(),'status':'fail','error':self._exc_info_to_string(err,t)});save()
            def addError(self,t,err):super().addError(t,err);report['checks'].append({'id':t.id(),'status':'error','error':self._exc_info_to_string(err,t)});save()
            def addSkip(self,t,reason):super().addSkip(t,reason);report['checks'].append({'id':t.id(),'status':'blocked','reason':reason});save()
            def addSubTest(self,t,sub,err):
                super().addSubTest(t,sub,err)
                if err:report['failures'].append({'id':sub.id(),'error':self._exc_info_to_string(err,t)});save()
        with (out/'unittest.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
        report.update(tests_run=result.testsRun,errors=len(result.errors),assertion_failures=len(result.failures),skipped=len(result.skipped),expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses))
        for name,module in sorted(sys.modules.items()):
            if name.split('.')[0] in {'stepkit','teleion_fabric'} and getattr(module,'__file__',None):
                origin=Path(module.__file__).resolve();assert origin.is_relative_to(Path(sys.prefix).resolve()) and not origin.is_relative_to(source),str(origin)
                report['origins'][name]={'path':str(origin),'sha256':digest(origin)}
        assert result.wasSuccessful() and result.testsRun==spec['count'] and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses,'behavior/count/skip gate failed'
        report['status']='pass_scoped'
    except BaseException:
        report['status']='fail';report['failures'].append({'error':traceback.format_exc()});raise
    finally:
        save();print(json.dumps(report,indent=2))
if __name__=='__main__':main()
