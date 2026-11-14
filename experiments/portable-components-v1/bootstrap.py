# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""CPU bootstrap adapted from public-github-install-v1/run_clean_install.py.

Network is setup-only when no explicit local source/wheel is supplied. No engines.
"""
import datetime,hashlib,json,os,subprocess,sys,tempfile,uuid
from pathlib import Path

def bootstrap(group,suite,checker):
    pin=suite['commit'];base=Path(os.environ.get('TELEION_NOTEBOOK_ROOT','/kaggle/working/teleion-components' if Path('/kaggle/working').exists() else './teleion-components')).resolve()
    base.mkdir(parents=True,exist_ok=True);root=base/(group+'-'+uuid.uuid4().hex[:12]);root.mkdir()
    if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    if hasattr(os,'nice') and os.nice(0)<10:os.nice(10-os.nice(0))
    env={k:v for k,v in os.environ.items() if k in ['PATH','LANG','LC_ALL','SYSTEMROOT','SSL_CERT_FILE','LD_LIBRARY_PATH']}
    env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',PIP_CONFIG_FILE='/dev/null',PIP_DISABLE_PIP_VERSION_CHECK='1',GIT_TERMINAL_PROMPT='0',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='credential.helper',GIT_CONFIG_VALUE_0='')
    report={'status':'running','group':group,'expected_commit':pin,'stages':[],'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'bootstrap_reused_from':'experiments/public-github-install-v1/run_clean_install.py','scope':'Local installed-wheel CPU tests; host numpy/scipy dependencies may be reused. Not all components or live providers.'}
    def save():(root/'BOOTSTRAP.json').write_text(json.dumps(report,indent=2)+'\n')
    def command(label,args,timeout=60):
        rec={'stage':label,'command':list(map(str,args))};report['stages'].append(rec);save()
        try:
            result=subprocess.run(list(map(str,args)),cwd=root,env=env,capture_output=True,text=True,timeout=timeout)
            (root/(label+'.stdout')).write_text(result.stdout);(root/(label+'.stderr')).write_text(result.stderr);rec['exit_code']=result.returncode;save()
            if result.returncode:raise RuntimeError(label+' failed; see '+str(root))
            return result.stdout
        except subprocess.TimeoutExpired as exc:
            rec['status']='timeout';(root/(label+'.stdout')).write_bytes(exc.stdout or b'');(root/(label+'.stderr')).write_bytes(exc.stderr or b'');save();raise
    try:
        local=os.environ.get('TELEION_LOCAL_SOURCE');wheel_path=os.environ.get('TELEION_LOCAL_WHEEL')
        if bool(local)!=bool(wheel_path):raise ValueError('local source and wheel must both be supplied')
        report['setup_route']='offline_local_source_and_wheel' if local else 'public_github_commit_build'
        source=Path(local).resolve() if local else root/'checkout'
        if not local:
            command('clone',['git','clone','--no-checkout','https://github.com/aidonerightcorp/teleion-fabric-python.git',source],300)
            command('checkout',['git','-C',source,'checkout','--detach',pin])
        assert command('commit',['git','-C',source,'rev-parse','HEAD']).strip()==pin,'wrong source commit'
        for name,sha in suite['files'].items():
            assert hashlib.sha256((source/name).read_bytes()).hexdigest()==sha,'wrong source bytes: '+name
        command('source_context',[sys.executable,'-I',source/'tools/sync_context.py','--check'])
        if not local:
            wheel_dir=root/'wheels';wheel_dir.mkdir()
            command('build_wheel',[sys.executable,'-I','-m','pip','wheel','--no-deps','--no-build-isolation',source,'-w',wheel_dir],300)
            wheels=list(wheel_dir.glob('teleion_fabric-*.whl'));assert len(wheels)==1;wheel=wheels[0]
        else:wheel=Path(wheel_path).resolve()
        report['wheel']={'path':str(wheel),'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()}
        venv=root/'venv';command('venv',[sys.executable,'-I','-m','venv','--without-pip','--system-site-packages',venv])
        python=venv/'bin/python'
        dependency_root=os.environ.get('TELEION_LOCAL_DEPENDENCIES')
        if dependency_root:
            if not local:raise ValueError('dependency path override is local-only')
            dependency_root=Path(dependency_root).resolve()
            if not dependency_root.is_dir():raise ValueError('missing dependency path')
            site=Path(command('site_path',[python,'-I','-c','import sysconfig;print(sysconfig.get_path("purelib"))']).strip())
            (site/'offline-dependencies.pth').write_text(str(dependency_root)+'\n')
            report['local_dependency_path']=str(dependency_root)

        command('install',[sys.executable,'-I','-m','pip','--python',python,'install','--no-index','--no-deps','--ignore-installed',wheel],300)
        (root/'suite.json').write_text(json.dumps(suite,indent=2));(root/'check_installed.py').write_text(checker)
        report['checker_sha256']=hashlib.sha256(checker.encode()).hexdigest();save()
        command('behavior',[python,'-I',root/'check_installed.py','--source',source,'--suite',root/'suite.json','--group',group,'--out',root/'behavior'])
        result=json.loads((root/'behavior/RESULT.json').read_text());assert result['status']=='pass_scoped'
        report['status']='pass_scoped';save()
        print(json.dumps({'artifact_directory':str(root),'status':result['status'],'tests_run':result['tests_run'],'scope':result['scope'],'checks':result['checks'],'origins':result['origins']},indent=2))
        return root
    except BaseException as exc:
        report.update(status='fail',error_type=type(exc).__name__,error=str(exc));save();raise
