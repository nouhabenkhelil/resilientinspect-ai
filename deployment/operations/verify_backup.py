"""Authenticate existing backups without repeating acquisition or modifying their sources."""
import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from backup import LOCAL,staging,unpack,event


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('archive'); args=parser.parse_args()
    config=json.loads((LOCAL/'backup-config.json').read_text())
    with staging(config) as stage:
        manifest=unpack(config,args.archive,stage)
        result={'archive':Path(args.archive).name,'authenticated':True,'sha256_files_verified':len(manifest['files']),'kind':manifest['kind']}
        if manifest['kind']=='mlops':
            with closing(sqlite3.connect(f'file:{(stage/"tracking.db").as_posix()}?mode=ro',uri=True)) as db:
                result['sqlite_integrity']=db.execute('PRAGMA quick_check').fetchone()[0]
                result['mlflow_registered_models']=db.execute('SELECT count(*) FROM registered_models').fetchone()[0]
            for label in ['dvc-store','mlflow-artifacts']:
                result[label+'_files']=len(json.loads((stage/(label+'-files.json')).read_text()))
    (LOCAL/('verified-'+manifest['kind']+'.json')).write_text(json.dumps(result,indent=2))
    event(config,'backup.verified',**result)
    print(json.dumps(result))


if __name__=='__main__': main()
